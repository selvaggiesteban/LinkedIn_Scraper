"""
ip_rotation.py — IP Rotation for LinkedIn Scraper v2
Uses swiftshadow for free proxy rotation with Guest API requests.
"""
from __future__ import annotations

import random
import time
from typing import Any


class ProxyRotator:
    """Simple proxy rotator using swiftshadow or fallback to direct."""

    def __init__(self, use_swiftshadow: bool = True, refresh_interval: int = 300):
        self._use_swiftshadow = use_swiftshadow
        self._refresh_interval = refresh_interval
        self._proxy_list: list[dict[str, str]] = []
        self._last_refresh = 0.0
        self._rotator = None

        if use_swiftshadow:
            try:
                from swiftshadow import ProxyRotator as _SWProxyRotator
                self._rotator = _SWProxyRotator()
                self._refresh_proxies()
                print(f"[PROXY] swiftshadow loaded with {len(self._proxy_list)} proxies")
            except ImportError:
                print("[PROXY] swiftshadow not installed, using direct connection")
                self._use_swiftshadow = False
            except Exception as e:
                print(f"[PROXY] swiftshadow init failed: {e}, using direct connection")
                self._use_swiftshadow = False
        else:
            print("[PROXY] disabled, using direct connection")

    def _refresh_proxies(self):
        if not self._rotator:
            return
        try:
            proxy = self._rotator.get()
            if proxy:
                self._proxy_list = [proxy] if isinstance(proxy, dict) else [{"http": str(proxy), "https": str(proxy)}]
                self._last_refresh = time.time()
        except Exception:
            pass

    def get_proxy(self) -> dict[str, str] | None:
        """Get next proxy, refreshing if needed."""
        if not self._use_swiftshadow or not self._proxy_list:
            return None

        if time.time() - self._last_refresh > self._refresh_interval:
            self._refresh_proxies()

        if self._proxy_list:
            return random.choice(self._proxy_list)
        return None

    def get_proxy_for_playwright(self) -> str | None:
        """Get proxy URL string for Playwright browser."""
        proxy = self.get_proxy()
        if proxy:
            return proxy.get("http") or proxy.get("https")
        return None


class DirectConnection:
    """Fallback: no proxy rotation."""

    def get_proxy(self) -> dict[str, str] | None:
        return None

    def get_proxy_for_playwright(self) -> str | None:
        return None
