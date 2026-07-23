"""
rate_budget.py — Adaptive rate-limiter for LinkedIn scraping.

Goals:
- Prevent challenge-screen triggers by pacing requests inside a per-minute and
  per-hour budget.
- Never abort the run on rate limiting: when the bucket would be exhausted,
  sleep until a token frees up.
- Expose counters for the orchestrator's `metadata.safety` block.

Design notes:
- Token bucket with two refill rates: a slow burst rate (per minute) and a
  slow average (per hour).
- Two buckets sum total available capacity per request family. Each acquire()
  consumes a token from both buckets (or waits for the slowest).
- Public hooks: `acquire(weight=1)`, `pause_for(seconds)`, `record_error()`,
  `stats()`.

This module is safe to reuse across the whole orchestrator: every call is O(1)
apart from the time.sleep() that actually paces the scraping.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RateBudgetConfig:
    """Tunable knobs. Defaults aim for presupuesto moderado described in plan G."""

    # Per-minute burst rate.
    burst_capacity: int = 8           # tokens per minute
    burst_refill_per_sec: float = 8 / 60.0   # 0.133 token/sec

    # Per-hour long-term average.
    hourly_capacity: int = 100        # baseline tokens in long-term window
    hourly_refill_per_sec: float = 100 / 3600.0  # ~0.0278 token/sec

    # Each `record_error()` reduces available tokens until refilled; helps
    # the budget learn that LinkedIn asked us to slow down.
    error_penalty_tokens: int = 4

    # Optional cool-down mode quadruples acquire delays (trigger via --cool-run).
    cool_run_multiplier: float = 4.0

    # When True, light calls (< 0.2s typ. latency) consume 0.5 tokens; default 1.
    weight_by_latency: bool = True


class RateBudget:
    """Adaptive token bucket for pacing MCP/scraping requests."""

    def __init__(self, cfg: RateBudgetConfig | None = None):
        self.cfg = cfg or RateBudgetConfig()
        self._burst_tokens = float(self.cfg.burst_capacity)
        self._hourly_tokens = float(self.cfg.hourly_capacity)
        self._last_refill = time.monotonic()
        self._total_calls = 0
        self._total_errors = 0
        self._total_pauses = 0
        self._peak_per_minute_rolling: list[float] = []  # timestamp of each call
        self._lock = asyncio.Lock()

    # ── budget accounting ─────────────────────────────────────────────────

    def _refill_locked(self, now: float) -> None:
        """Increment token counts since last update."""
        elapsed = now - self._last_refill
        if elapsed <= 0:
            return
        self._burst_tokens = min(
            float(self.cfg.burst_capacity),
            self._burst_tokens + elapsed * self.cfg.burst_refill_per_sec,
        )
        self._hourly_tokens = min(
            float(self.cfg.hourly_capacity),
            self._hourly_tokens + elapsed * self.cfg.hourly_refill_per_sec,
        )
        self._last_refill = now

    def _consume_locked(self, weight: float = 1.0) -> tuple[float, float]:
        """Atomically subtract one weight from both buckets; return wait times."""
        now = time.monotonic()
        self._refill_locked(now)

        # If both buckets have at least `weight` tokens, consume.
        if self._burst_tokens >= weight and self._hourly_tokens >= weight:
            self._burst_tokens -= weight
            self._hourly_tokens -= weight
            return 0.0, 0.0

        # Compute wait time for the slower bucket.
        wait_burst = 0.0
        if self._burst_tokens < weight:
            deficit = weight - self._burst_tokens
            wait_burst = deficit / self.cfg.burst_refill_per_sec
        wait_hourly = 0.0
        if self._hourly_tokens < weight:
            deficit = weight - self._hourly_tokens
            wait_hourly = deficit / self.cfg.hourly_refill_per_sec
        return wait_burst, wait_hourly

    # ── public async API ─────────────────────────────────────────────────

    async def acquire(self, weight: float = 1.0, cool_run: bool = False) -> float:
        """Wait (in seconds, Pacing) until one token is available. Returns slept."""
        multiplier = self.cfg.cool_run_multiplier if cool_run else 1.0
        async with self._lock:
            wait_burst, wait_hourly = self._consume_locked(weight)
            wait_max = max(wait_burst, wait_hourly) * multiplier
        if wait_max > 0:
            self._total_pauses += 1
            await asyncio.sleep(wait_max)
        # Re-acquire the actual token post-sleep.
        async with self._lock:
            self._refill_locked(time.monotonic())
            self._burst_tokens -= weight
            self._hourly_tokens -= weight
            self._total_calls += 1
            now = time.monotonic()
            self._peak_per_minute_rolling.append(now)
            # Drop entries older than 60 s.
            while self._peak_per_minute_rolling and now - self._peak_per_minute_rolling[0] > 60.0:
                self._peak_per_minute_rolling.pop(0)
        return wait_max

    def record_error(self, weight: float | None = None) -> None:
        """Notify budget of an upstream error so the next acquire sleeps longer."""
        penalty = weight or float(self.cfg.error_penalty_tokens)
        self._burst_tokens = max(0.0, self._burst_tokens - penalty)
        self._hourly_tokens = max(0.0, self._hourly_tokens - penalty)
        self._total_errors += 1

    async def pause_for(self, seconds: float, reason: str = "manual") -> None:
        """Sleep unconditionally for `seconds`. Increments total_pauses."""
        self._total_pauses += 1
        if reason:
            print(f"[RateBudget] pause {seconds:.1f}s — {reason}")
        await asyncio.sleep(seconds)

    # ── stats ────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Snapshot of all safety counters for `metadata.safety`."""
        now = time.monotonic()
        # Calls in the last minute.
        calls_recent = len(self._peak_per_minute_rolling)
        calls_per_min = float(calls_recent)
        if calls_recent >= 2:
            span = max(0.0, self._peak_per_minute_rolling[-1] - self._peak_per_minute_rolling[0])
            if span > 0:
                calls_per_min = calls_recent * (60.0 / max(span, 1.0))
        return {
            "total_calls": self._total_calls,
            "total_errors": self._total_errors,
            "total_pauses": self._total_pauses,
            "burst_tokens_left": round(self._burst_tokens, 2),
            "hourly_tokens_left": round(self._hourly_tokens, 2),
            "calls_per_minute_peak": round(calls_per_min, 2),
            "burst_capacity": self.cfg.burst_capacity,
            "hourly_capacity": self.cfg.hourly_capacity,
        }

    def to_json(self) -> str:
        return json.dumps(self.stats(), ensure_ascii=False, indent=2)
