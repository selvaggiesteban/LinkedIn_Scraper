"""
auth_assistant.py — One-time interactive LinkedIn authentication assistant.

Flow:
  1. Preflight checks (Python≥3.11, uv, mcp-server-linkedin, requests)
  2. Auto-install mcp-server-linkedin if missing
  3. Probe existing session via MCP get_feed
  4. If session missing: open Chrome for manual login
  5. Verify session works
  6. Persist status to output/auth_status.json

Usage:
  python auth_assistant.py                 # interactive mode (default)
  python auth_assistant.py --interactive    # explicit interactive
  python auth_assistant.py --non-interactive  # CI mode (no prompts)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = OUTPUT_DIR / "auth_assistant.log"
STATUS_PATH = OUTPUT_DIR / "auth_status.json"


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _check_command(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _preflight() -> bool:
    """Check Python, uv, mcp-server-linkedin availability."""
    _log("Preflight checks…")
    if not _check_command("python"):
        _log("  [FAIL] python not on PATH")
        return False
    if not _check_command("uv"):
        _log("  [FAIL] uv not on PATH — install with: pip install uv")
        return False
    if not _check_command("mcp-server-linkedin"):
        _log("  mcp-server-linkedin not installed — installing via: uv tool install mcp-server-linkedin")
        try:
            subprocess.run(["uv", "tool", "install", "mcp-server-linkedin"], check=True)
            _log("  [OK] mcp-server-linkedin installed")
        except subprocess.CalledProcessError as e:
            _log(f"  [FAIL] install failed: {e}")
            return False
    else:
        _log("  [OK] mcp-server-linkedin on PATH")
    _log("  [OK] Preflight passed")
    return True


async def _probe_session() -> bool:
    """Try connecting to MCP and calling get_feed — returns True if session alive."""
    try:
        from linkedin_scraper.sources.mcp_client import MCPClient
        mcp = MCPClient()
        await mcp.connect()
        data = await mcp.call_raw("get_feed", {"num_posts": 1}, timeout=20)
        await mcp.close()
        if data and (data.get("references") or data.get("sections")):
            _log("  [OK] Existing session is alive")
            return True
        _log("  [WARN] MCP responded but session looks empty — login needed")
        return False
    except Exception as e:
        _log(f"  [INFO] No active session: {type(e).__name__}: {e}")
        return False


def _open_login_interactive() -> bool:
    """Launch the manual login browser and wait for completion."""
    _log("Starting manual LinkedIn login flow…")
    _log("A Chrome window will open. Sign in with your LinkedIn account (email + password + 2FA if enabled).")
    _log("The MCP server will save the session; you only need to do this once (~every 30 days).")
    try:
        input("Press Enter to open the browser and login manually…")
    except EOFError:
        _log("Non-interactive mode — launching browser without prompt")

    cmd = ["uvx", "--from", "mcp-server-linkedin", "mcp-server-linkedin", "--login"]
    _log(f"Running: {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as e:
        _log(f"[FAIL] could not launch login subprocess: {e}")
        return False

    _log("Waiting for login to complete (timeout 180s)…")
    deadline = time.time() + 180
    success_markers = ("login successful", "session saved", "ready to serve", "mcp server", "fastmcp")
    saw_marker = False
    while time.time() < deadline:
        if proc.poll() is not None:
            _log(f"Login process exited with code {proc.returncode}")
            break
        try:
            line = proc.stdout.readline() if proc.stdout else ""
        except Exception:
            line = ""
        if line:
            stripped = line.strip().lower()
            if any(m in stripped for m in success_markers):
                _log(f"  [login output] {line.strip()}")
                saw_marker = True
                # Give the server an extra few seconds to finalize session persistence
                time.sleep(3)
                break
        time.sleep(2)

    if not saw_marker and proc.poll() is None:
        _log("Login timed out — try again and complete within 180 seconds")
        try:
            proc.terminate()
        except Exception:
            pass
        return False

    _log("Login flow completed")
    return True


async def _verify() -> bool:
    """Verify session by calling get_feed with retries."""
    _log("Verifying session (3 retries)…")
    for attempt in range(1, 4):
        _log(f"  attempt {attempt}/3")
        if await _probe_session():
            return True
        if attempt < 3:
            await asyncio.sleep(5)
    return False


def _persist_status(status: str, mcp_version: str = "") -> None:
    data: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "status": status,
        "mcp_version": mcp_version or "unknown",
        "expires_hint": "30 days (LinkedIn cookie expiry)",
        "next_steps": (
            "Re-run auth_assistant.py when posts/feed come back empty "
            "or when Vía 2/3/4 receive redirects to /login"
        ),
    }
    with open(STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _log(f"Status persisted → {STATUS_PATH}")


async def _run() -> int:
    _log("=" * 60)
    _log("LinkedIn Scraper — Auth Assistant")
    _log("=" * 60)

    if not _preflight():
        _persist_status("failed", "preflight")
        return 1

    _log("")
    _log("Step 1: Probe existing session…")
    if await _probe_session():
        _log("Session already active — no login needed")
        _persist_status("active")
        return 0

    _log("")
    _log("Step 2: Launch interactive login…")
    if not _open_login_interactive():
        _log("[FAIL] Login could not be completed")
        _persist_status("failed", "login_timeout")
        return 1

    _log("")
    _log("Step 3: Verify new session…")
    if await _verify():
        _log("[SUCCESS] Session is active — you can now run: python linkedin_scraper.py")
        _persist_status("active")
        return 0

    _log("[FAIL] Session verification failed")
    _log("Troubleshooting:")
    _log("  1. Make sure you completed the LinkedIn sign-in inside the Chrome window")
    _log("  2. Disable any ad-blockers on linkedin.com during login")
    _log("  3. Try again: python auth_assistant.py")
    _log("  4. If captchas appear, solve them manually in the browser")
    _persist_status("failed", "verify_failed")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="LinkedIn Scraper — Auth Assistant")
    parser.add_argument("--non-interactive", action="store_true", help="CI mode (no prompts)")
    parser.add_argument("--interactive", action="store_true", help="Explicit interactive mode (default)")
    args = parser.parse_args()
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
