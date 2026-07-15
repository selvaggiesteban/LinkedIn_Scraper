"""
run_all.py — Execute all scraping methods in parallel (simplified)
Guest API + MCP
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from typing import Any

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    LOCATIONS, PRIMARY_KEYWORDS, PEOPLE_KEYWORDS, COMPANY_SEARCHES, OUTPUT_DIR,
)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _save_json(data: Any, name: str) -> str:
    path = OUTPUT_DIR / f"{name}_{_ts()}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return str(path)


# ═══════════════════════════════════════════════════════════════
# 1. GUEST API — Jobs
# ═══════════════════════════════════════════════════════════════
def run_guest_api() -> list[dict]:
    print("\n[1/2] GUEST API")
    from guest_api import scrape_all_keywords
    jobs = scrape_all_keywords()
    print(f"  -> {len(jobs)} unique jobs")
    return jobs


# ═══════════════════════════════════════════════════════════════
# 2. MCP — People, Feed, Companies
# ═══════════════════════════════════════════════════════════════
async def run_mcp() -> dict[str, list]:
    print("\n[2/2] MCP")
    from mcp_client import MCPClient, _parse_people_refs, _parse_post_refs, _parse_employee_refs

    mcp = MCPClient()
    await mcp.connect()

    results = {"people": [], "posts_feed": [], "posts_companies": [], "company_employees": []}
    seen_profiles = set()

    # People
    print(f"  PEOPLE: {len(PEOPLE_KEYWORDS)} keywords")
    for i, kw in enumerate(PEOPLE_KEYWORDS, 1):
        data = await mcp.call_raw("search_people", {"keywords": kw, "location": "Buenos Aires, Argentina"})
        if data:
            people = _parse_people_refs(data, kw)
            new = 0
            for p in people:
                url = p.get("profile_url", "")
                if url and url not in seen_profiles:
                    seen_profiles.add(url)
                    results["people"].append(p)
                    new += 1
            if new:
                print(f"    [{i}] {kw}: +{new}")
        await asyncio.sleep(1.5)

    # Feed
    print("  FEED")
    try:
        data = await mcp.call_raw("get_feed", {"num_posts": 50}, timeout=45)
        if data:
            results["posts_feed"] = _parse_post_refs(data, "feed")
            print(f"    -> {len(results['posts_feed'])} posts")
    except asyncio.TimeoutError:
        print("    -> TIMEOUT (skipped)")
    except Exception as e:
        print(f"    -> ERROR: {e}")

    # Companies
    print(f"  COMPANIES: {len(COMPANY_SEARCHES)} searches")
    for i, ck in enumerate(COMPANY_SEARCHES, 1):
        cdata = await mcp.call_raw("search_companies", {"keywords": ck})
        if not cdata:
            continue
        comp_refs = cdata.get("references", {}).get("search_results", [])
        slugs = [r["url"].rstrip("/").split("/")[-1] for r in comp_refs
                 if r.get("kind") == "company" and "/company/" in r.get("url", "")]
        print(f"    [{i}] {ck}: {len(slugs)} companies")

        for slug in slugs[:5]:
            # Posts
            try:
                ptext = await mcp.call_text("get_company_posts", {"company_name": slug})
                if ptext:
                    import re
                    urls = re.findall(
                        r'https?://www\.linkedin\.com/feed/update/urn:li:[^\s\)\"\'<>]+|'
                        r'https?://www\.linkedin\.com/posts/[^\s\)\"\'<>]+', ptext)
                    for u in list(dict.fromkeys(u.split("?")[0] for u in urls)):
                        results["posts_companies"].append({
                            "type": "post_company", "source": "mcp",
                            "post_url": u, "company_name": slug,
                            "scraped_at": datetime.now().isoformat(),
                        })
            except (asyncio.TimeoutError, Exception) as e:
                print(f"      {slug} posts: {type(e).__name__}")

            # Employees
            try:
                edata = await mcp.call_raw("get_company_employees", {"company_name": slug}, timeout=20)
                if edata:
                    for emp in _parse_employee_refs(edata, slug):
                        url = emp["profile_url"]
                        if url and url not in seen_profiles:
                            seen_profiles.add(url)
                            results["company_employees"].append(emp)
            except (asyncio.TimeoutError, Exception) as e:
                print(f"      {slug} employees: {type(e).__name__}")
            await asyncio.sleep(1.5)

    await mcp.close()
    total = sum(len(v) for v in results.values())
    print(f"  -> {total} total items")
    return results


# ═══════════════════════════════════════════════════════════════
# DEDUP
# ═══════════════════════════════════════════════════════════════
def dedup_all(data: dict) -> dict:
    from deduplicator import dedup_urls
    result = {}
    for cat, items in data.items():
        result[cat] = dedup_urls(items) if items else []
        print(f"  {cat}: {len(items)} -> {len(result[cat])}")
    return result


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
async def main():
    start = time.time()
    print(f"\n{'#' * 60}")
    print(f"  LinkedIn Scraper v2 — FULL RUN")
    print(f"  Started: {_ts()}")
    print(f"  Keywords: {PRIMARY_KEYWORDS}")
    print(f"  Locations: {LOCATIONS}")
    print(f"{'#' * 60}")

    # Run both layers
    jobs = run_guest_api()
    mcp = await run_mcp()

    # Combine
    all_data = {
        "jobs": jobs,
        "people": mcp["people"],
        "posts_feed": mcp["posts_feed"],
        "posts_companies": mcp["posts_companies"],
        "company_employees": mcp["company_employees"],
    }

    # Dedup
    print("\nDEDUP:")
    deduped = dedup_all(all_data)

    # Save
    print("\nSAVE:")
    combined = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "keywords": PRIMARY_KEYWORDS,
            "locations": LOCATIONS,
            "duration_s": round(time.time() - start),
        },
        "results": deduped,
    }
    path = _save_json(combined, "all_results")
    print(f"  -> {path}")

    # Summary
    elapsed = time.time() - start
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    total = 0
    for cat, items in deduped.items():
        print(f"  {cat}: {len(items)}")
        total += len(items)
    print(f"  TOTAL: {total}")
    print(f"  Duration: {elapsed:.0f}s")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
