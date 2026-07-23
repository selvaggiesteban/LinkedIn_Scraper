"""
ocr_extractor.py — OCR Content Extraction
Uses Playwright for screenshots + EasyOCR for text extraction.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from typing import Any

from ..config import OCR_LANGUAGES, OUTPUT_DIR


class OCRExtractor:
    """Extract text from LinkedIn pages via screenshot + OCR."""

    def __init__(self, languages: list[str] | None = None):
        self._languages = languages or OCR_LANGUAGES
        self._reader = None
        self._init_ocr()

    def _init_ocr(self):
        try:
            import easyocr
            self._reader = easyocr.Reader(self._languages, gpu=False, verbose=False)
            print(f"[OCR] EasyOCR initialized: {self._languages}")
        except ImportError:
            print("[OCR] EasyOCR not installed, OCR extraction disabled")
        except Exception as e:
            print(f"[OCR] EasyOCR init failed: {e}")

    @property
    def available(self) -> bool:
        return self._reader is not None

    def extract_from_screenshot(self, screenshot_path: str) -> str:
        """Extract text from a screenshot file."""
        if not self._reader:
            return ""
        try:
            results = self._reader.readtext(screenshot_path, detail=0)
            return " ".join(results).strip()
        except Exception:
            return ""

    async def extract_from_url(
        self,
        url: str,
        playwright_page=None,
        save_screenshot: bool = False,
    ) -> dict[str, Any]:
        """Navigate to URL, screenshot, OCR."""
        if not playwright_page:
            return {"url": url, "text": "", "screenshot": ""}

        screenshot_path = ""
        try:
            await playwright_page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await playwright_page.wait_for_timeout(500)

            if save_screenshot:
                screenshot_path = os.path.join(
                    str(OUTPUT_DIR), "screenshots",
                    f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hash(url) & 0xFFFF:04x}.png"
                )
                os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
                await playwright_page.screenshot(path=screenshot_path, full_page=True)
            else:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    screenshot_path = tmp.name
                    await playwright_page.screenshot(path=screenshot_path, full_page=True)

            text = self.extract_from_screenshot(screenshot_path)

            if not save_screenshot and os.path.exists(screenshot_path):
                os.unlink(screenshot_path)

            return {"url": url, "text": text, "screenshot": screenshot_path if save_screenshot else ""}

        except Exception as e:
            return {"url": url, "text": "", "screenshot": "", "error": str(e)}

    async def extract_batch(
        self,
        urls: list[str],
        playwright_page=None,
        max_concurrent: int = 1,
        save_screenshots: bool = False,
    ) -> list[dict[str, Any]]:
        """Extract text from multiple URLs."""
        results = []
        for url in urls:
            result = await self.extract_from_url(
                url, playwright_page, save_screenshots
            )
            results.append(result)
        return results
