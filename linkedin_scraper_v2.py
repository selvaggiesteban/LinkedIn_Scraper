"""
linkedin_scraper_v2.py — Main Orchestrator
Multi-method LinkedIn scraper: Guest API + MCP + Playwright + Scrapling
with OCR validation and cross-source dedup.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from typing import Any

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .config import (
    COMPANY_SEARCHES,
    LOCATIONS,
    PEOPLE_KEYWORDS,
    PRIMARY_KEYWORDS,
    OUTPUT_DIR,
)
from .guest_api import scrape_all_keywords
from .mcp_client import scrape_mcp
from .ocr_extractor import OCRExtractor
from .validator import validate_results
from .deduplicator import dedup_all, print_dedup_stats


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _save_json(data: Any, name: str) -> str:
    path = OUTPUT_DIR / f"{name}_{_ts()}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return str(path)


async def run_all(
    use_guest_api: bool = True,
    use_mcp: bool = True,
    use_playwright: bool = True,
    use_scrapling: bool = True,
    use_ocr: bool = True,
    validate: bool = True,
):
    """Main entry point: run all scraping methods in sequence."""
    print(f"\n{'#' * 60}")
    print(f"  LinkedIn Scraper v2 — {_ts()}")
    print(f"  Locations: {LOCATIONS}")
    print(f"  Keywords: {PRIMARY_KEYWORDS}")
    print(f"{'#' * 60}")

    all_raw: dict[str, list] = {
        "people": [], "jobs": [], "posts_feed": [],
        "posts_companies": [], "company_employees": [],
        "company_profiles": [], "authors": [],
    }

    # ── 1. GUEST API (jobs with pagination) ──
    if use_guest_api:
        try:
            from .ip_rotation import ProxyRotator
            rotator = ProxyRotator()
            proxy = rotator.get_proxy()
            jobs = scrape_all_keywords(proxies=proxy)
            all_raw["jobs"] = jobs
        except Exception as e:
            print(f"[ERROR] Guest API failed: {e}")

    # ── 2. MCP (people, feed, companies) ──
    if use_mcp:
        try:
            mcp_results = await scrape_mcp(
                people_keywords=PEOPLE_KEYWORDS,
                company_searches=COMPANY_SEARCHES,
                location=LOCATION,
            )
            for cat in mcp_results:
                all_raw[cat].extend(mcp_results[cat])
        except Exception as e:
            print(f"[ERROR] MCP failed: {e}")

    # ── 3. SCRAPLING (company profiles) ──
    if use_scrapling:
        try:
            from scrapling.fetchers import Fetcher
            print(f"\n{'=' * 60}")
            print("[SCRAPLING] COMPANY PROFILES")
            print(f"{'=' * 60}")
            for ck in COMPANY_SEARCHES:
                try:
                    page = Fetcher.fetch(
                        f"https://www.linkedin.com/company/{ck.split()[0].lower()}/about",
                        timeout=15,
                    )
                    if page.status == 200:
                        all_raw["company_profiles"].append({
                            "type": "company_profile",
                            "source": "scrapling",
                            "company_name": ck,
                            "url": page.url,
                            "scraped_at": datetime.now().isoformat(),
                        })
                        print(f"  ✓ {ck}")
                except Exception as e:
                    print(f"  ✗ {ck}: {e}")
        except ImportError:
            print("[SCRAPLING] Not installed, skipping company profiles")

    # ── 4. OCR EXTRACTION ──
    if use_ocr:
        ocr = OCRExtractor()
        if ocr.available:
            print(f"\n{'=' * 60}")
            print("[OCR] Extracting text from results")
            print(f"{'=' * 60}")
            urls_to_ocr = []
            for job in all_raw["jobs"][:100]:  # Limit for initial run
                urls_to_ocr.append(job.get("job_url", ""))

            if urls_to_ocr:
                try:
                    from playwright.async_api import async_playwright
                    async with async_playwright() as p:
                        browser = await p.chromium.launch(headless=True)
                        page = await browser.new_page()

                        for job in all_raw["jobs"][:100]:
                            url = job.get("job_url", "")
                            if not url:
                                continue
                            result = await ocr.extract_from_url(url, page)
                            job["text_ocr"] = result.get("text", "")
                            if result.get("screenshot"):
                                job["screenshot"] = result["screenshot"]

                        await browser.close()
                        print(f"  OCR applied to {min(100, len(all_raw['jobs']))} jobs")
                except Exception as e:
                    print(f"  [ERROR] Playwright OCR failed: {e}")

    # ── 5. DEDUP ──
    print(f"\n{'=' * 60}")
    print("DEDUPLICATION")
    print(f"{'=' * 60}")
    before = {k: len(v) for k, v in all_raw.items()}
    deduped = dedup_all(all_raw)
    after = {k: len(v) for k, v in deduped.items()}
    print_dedup_stats(
        {k: v for k, v in all_raw.items()},
        deduped,
    )

    # ── 6. VALIDATION ──
    if validate:
        print(f"\n{'=' * 60}")
        print("VALIDATION (employment intent)")
        print(f"{'=' * 60}")
        for cat in deduped:
            if cat in ("people", "company_profiles"):
                continue
            before_val = len(deduped[cat])
            deduped[cat] = validate_results(deduped[cat])
            after_val = len(deduped[cat])
            removed = before_val - after_val
            print(f"  {cat}: {before_val} → {after_val} (removed {removed} without employment context)")

    # ── 7. SAVE ──
    print(f"\n{'=' * 60}")
    print("SAVING RESULTS")
    print(f"{'=' * 60}")

    for cat, items in deduped.items():
        if items:
            path = _save_json(items, cat)
            print(f"  {cat}: {len(items)} items → {path}")

    combined = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "locations": LOCATIONS,
            "keywords": PRIMARY_KEYWORDS,
        },
        "results": deduped,
    }
    combined_path = _save_json(combined, "all_results")
    print(f"  combined → {combined_path}")

    # ── SUMMARY ──
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    total = 0
    for cat, items in deduped.items():
        print(f"  {cat}: {len(items)}")
        total += len(items)
    print(f"  TOTAL: {total}")
    print(f"{'=' * 60}")

    return combined


def main():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="LinkedIn Scraper v2")
    parser.add_argument("--no-guest-api", action="store_true", help="Skip Guest API")
    parser.add_argument("--no-mcp", action="store_true", help="Skip MCP")
    parser.add_argument("--no-playwright", action="store_true", help="Skip Playwright")
    parser.add_argument("--no-scrapling", action="store_true", help="Skip Scrapling")
    parser.add_argument("--no-ocr", action="store_true", help="Skip OCR")
    parser.add_argument("--no-validate", action="store_true", help="Skip validation")
    args = parser.parse_args()

    asyncio.run(run_all(
        use_guest_api=not args.no_guest_api,
        use_mcp=not args.no_mcp,
        use_playwright=not args.no_playwright,
        use_scrapling=not args.no_scrapling,
        use_ocr=not args.no_ocr,
        validate=not args.no_validate,
    ))


if __name__ == "__main__":
    main()
