"""
linkedin_scraper.py — LinkedIn Scraper Orchestrator
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

# Make PROJECT_ROOT importable (for excel_exporter.py which lives at repo root)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from .config import (
    COMPANY_SEARCHES,
    LOCATIONS,
    PEOPLE_KEYWORDS,
    PRIMARY_KEYWORDS,
    OUTPUT_DIR,
    MCP_CAPS_JOB_DETAILS,
    MCP_CAPS_PERSON_PROFILES,
    MCP_CAPS_COMPANY_PROFILES,
    SCRAPLING_CAPS_JOBS,
    SCRAPLING_CAPS_PROFILES,
    SCRAPLING_CAPS_COMPANIES,
)
from .sources.guest_api import scrape_all_keywords, scrape_public_complements
from .sources.mcp_client import scrape_mcp
from .sources.ocr_extractor import OCRExtractor
from .pipeline.validator import validate_results
from .pipeline.deduplicator import dedup_all


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
    print(f"  LinkedIn Scraper — {_ts()}")
    print(f"  Locations: {LOCATIONS}")
    print(f"  Keywords: {PRIMARY_KEYWORDS}")
    print(f"{'#' * 60}")

    all_raw: dict[str, list] = {
        "people": [], "jobs": [], "job_details": [],
        "person_profiles": [], "company_search": [],
        "posts_feed": [], "posts_companies": [],
        "company_employees": [], "company_profiles": [],
        "authors": [],
    }

    # ── 1. GUEST API (jobs + public complements: job_details, person_profiles, company_profiles) ──
    if use_guest_api:
        try:
            proxies = None
            try:
                from .utils.ip_rotation import ProxyRotator
                rotator = ProxyRotator()
                proxies = rotator.get_proxy()
            except Exception:
                pass  # direct connection fallback
            jobs = scrape_all_keywords(proxies=proxies)
            all_raw["jobs"] = jobs
            # Public complements (Vía 1 full coverage): enrich buckets from no-login endpoints
            complement = scrape_public_complements(
                jobs=jobs,
                people=all_raw.get("people", []),
                companies=all_raw.get("company_search", []),
                proxies=proxies,
            )
            for cat in ("job_details", "person_profiles", "company_profiles"):
                all_raw[cat].extend(complement.get(cat, []))
        except Exception as e:
            print(f"[ERROR] Guest API failed: {e}")

    # ── 2. MCP (jobs, people, feed, companies, employees, details — full coverage Vía 2) ──
    mcp_cookies: dict[str, str] = {}
    if use_mcp:
        try:
            mcp_results = await scrape_mcp(
                people_keywords=PEOPLE_KEYWORDS,
                company_searches=COMPANY_SEARCHES,
                location=LOCATIONS[0],
                job_keywords=PRIMARY_KEYWORDS,
                job_details_cap=MCP_CAPS_JOB_DETAILS,
                person_profiles_cap=MCP_CAPS_PERSON_PROFILES,
                company_profiles_cap=MCP_CAPS_COMPANY_PROFILES,
            )
            for cat in mcp_results:
                all_raw.setdefault(cat, [])
                all_raw[cat].extend(mcp_results[cat])
            # Extract cookies from MCP session to share with Scrapling/Playwright
            try:
                from .sources.mcp_client import MCPClient
                mc = MCPClient()
                await mc.connect()
                mcp_cookies = await mc.get_cookies()
                await mc.close()
            except Exception:
                pass  # direct connection for Scrapling/Playwright
        except Exception as e:
            print(f"[ERROR] MCP failed: {e}")

    # ── 3. SCRAPLING (full coverage Vía 3): jobs + people + companies + posts ──
    if use_scrapling:
        try:
            from scrapling.fetchers import Fetcher
            print(f"\n{'=' * 60}")
            print("[SCRAPLING] FULL COVERAGE (jobs + people + companies + posts)")
            print(f"{'=' * 60}")
            # 3a. Company /about (public + login cookie when available)
            print("  Company /about pages:")
            seen_slugs = set()
            for comp in list(all_raw["company_search"])[:SCRAPLING_CAPS_COMPANIES]:
                url = comp.get("url", "")
                slug = url.rstrip("/").split("/")[-1] if url else comp.get("external_id", "")
                if not slug or slug in seen_slugs:
                    continue
                seen_slugs.add(slug)
                about_url = f"https://www.linkedin.com/company/{slug}/about"
                try:
                    page = Fetcher.fetch(about_url, timeout=15, cookies=mcp_cookies or None)
                    if page.status == 200:
                        text = page.get_all_text() if hasattr(page, "get_all_text") else ""
                        all_raw["company_profiles"].append({
                            "type": "company_profile",
                            "source": "scrapling",
                            "name": comp.get("name", slug),
                            "external_id": slug,
                            "url": about_url,
                            "text_ocr": text,
                            "scraped_at": datetime.now().isoformat(),
                        })
                        print(f"    ✓ {slug}")
                except Exception as e:
                    print(f"    ✗ {slug}: {type(e).__name__}")
            # 3b. Company /posts
            print("  Company /posts pages:")
            for slug in list(seen_slugs)[:5]:
                posts_url = f"https://www.linkedin.com/company/{slug}/posts"
                try:
                    page = Fetcher.fetch(posts_url, timeout=15, cookies=mcp_cookies or None)
                    if page.status == 200:
                        text = page.get_all_text() if hasattr(page, "get_all_text") else ""
                        all_raw["posts_companies"].append({
                            "type": "post_company",
                            "source": "scrapling",
                            "company_name": slug,
                            "external_id": slug,
                            "url": posts_url,
                            "text_ocr": text,
                            "scraped_at": datetime.now().isoformat(),
                        })
                        print(f"    ✓ {slug}")
                except Exception as e:
                    print(f"    ✗ {slug}: {type(e).__name__}")
            # 3c. Job detail pages (public)
            print(f"  Job detail pages (top {SCRAPLING_CAPS_JOBS}):")
            seen_job_ids = set()
            for job in list(all_raw["jobs"])[:SCRAPLING_CAPS_JOBS]:
                url = job.get("url") or job.get("job_url") or job.get("applyUrl", "")
                jid = job.get("external_id", "") or url.rstrip("/").split("/")[-1] if url else ""
                if not url or jid in seen_job_ids:
                    continue
                seen_job_ids.add(jid)
                try:
                    page = Fetcher.fetch(url, timeout=15, cookies=mcp_cookies or None)
                    if page.status == 200:
                        text = page.get_all_text() if hasattr(page, "get_all_text") else ""
                        all_raw["job_details"].append({
                            "type": "job_detail",
                            "source": "scrapling",
                            "title": job.get("title", ""),
                            "external_id": jid,
                            "url": url,
                            "text_ocr": text,
                            "scraped_at": datetime.now().isoformat(),
                        })
                        print(f"    ✓ {jid}")
                except Exception as e:
                    print(f"    ✗ {jid}: {type(e).__name__}")
            # 3d. Person profiles (public /in/<username>/)
            print(f"  Person profiles (top {SCRAPLING_CAPS_PROFILES}):")
            seen_usernames = set()
            for person in list(all_raw["people"])[:SCRAPLING_CAPS_PROFILES]:
                url = person.get("url") or person.get("profile_url", "")
                if not url:
                    continue
                username = url.rstrip("/").split("/in/")[-1] if "/in/" in url else ""
                if not username or username in seen_usernames:
                    continue
                seen_usernames.add(username)
                try:
                    page = Fetcher.fetch(url, timeout=15, cookies=mcp_cookies or None)
                    if page.status == 200:
                        text = page.get_all_text() if hasattr(page, "get_all_text") else ""
                        all_raw["person_profiles"].append({
                            "type": "person_profile",
                            "source": "scrapling",
                            "name": person.get("name", ""),
                            "external_id": username,
                            "url": url,
                            "text_ocr": text,
                            "scraped_at": datetime.now().isoformat(),
                        })
                        print(f"    ✓ {username}")
                except Exception as e:
                    print(f"    ✗ {username}: {type(e).__name__}")
        except ImportError:
            print("[SCRAPLING] Not installed, skipping full coverage Vía 3")
        except Exception as e:
            print(f"[SCRAPLING] Error: {e}")

    # ── 4. OCR EXTRACTION (Vía 4 full coverage — 7 categories) ──
    if use_ocr and use_playwright:
        ocr = OCRExtractor()
        if ocr.available:
            print(f"\n{'=' * 60}")
            print("[OCR] Extracting text from 7 categories")
            print(f"{'=' * 60}")
            ocr_categories = [
                "jobs", "job_details", "people",
                "person_profiles", "posts_feed",
                "posts_companies", "company_profiles",
            ]
            try:
                from playwright.async_api import async_playwright
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    context = await browser.new_context()
                    if mcp_cookies:
                        await context.add_cookies([
                            {"name": k, "value": v, "domain": ".linkedin.com", "path": "/"}
                            for k, v in mcp_cookies.items()
                        ])
                    page = await context.new_page()
                    ocr_cap_per_cat = 20  # cap per category to avoid overrun
                    total_enriched = 0
                    for cat in ocr_categories:
                        items = all_raw.get(cat, [])[:ocr_cap_per_cat]
                        if not items:
                            continue
                        print(f"  {cat}: {len(items)} items to OCR")
                        cat_enriched = 0
                        for item in items:
                            url = item.get("url") or item.get("job_url") or item.get("profile_url") or item.get("post_url") or ""
                            if not url:
                                continue
                            result = await ocr.extract_from_url(url, page)
                            item["text_ocr"] = result.get("text", "")
                            if result.get("screenshot"):
                                item["screenshot"] = result["screenshot"]
                            cat_enriched += 1
                        total_enriched += cat_enriched
                        print(f"    → enriched {cat_enriched}")
                    await browser.close()
                    print(f"  OCR total enriched: {total_enriched} items")
            except Exception as e:
                print(f"  [ERROR] Playwright OCR failed: {e}")

    # ── 5. DEDUP ──
    print(f"\n{'=' * 60}")
    print("DEDUPLICATION")
    print(f"{'=' * 60}")
    before_counts = {k: len(v) for k, v in all_raw.items()}
    deduped = dedup_all(all_raw)
    for cat, items in deduped.items():
        b = before_counts.get(cat, 0)
        removed = b - len(items)
        pct = f" ({removed/b*100:.0f}%)" if b > 0 else ""
        print(f"  {cat}: {b} → {len(items)} (removed {removed}{pct})")
    total_before = sum(before_counts.get(c, 0) for c in deduped)
    total_after = sum(len(v) for v in deduped.values())
    print(f"  TOTAL: {total_before} → {total_after} (removed {total_before - total_after})")
    print(f"{'=' * 60}")

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

    # ── 8. EXPORT EXCEL + CSV ──
    try:
        from excel_exporter import export_all
        xlsx_path, csv_path = export_all(combined["results"], OUTPUT_DIR)
        if xlsx_path:
            print(f"  XLSX → {xlsx_path}")
        print(f"  CSV  → {csv_path}")
    except Exception as e:
        print(f"  [ERROR] Excel/CSV export failed: {e}")

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
    parser = argparse.ArgumentParser(description="LinkedIn Scraper")
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
