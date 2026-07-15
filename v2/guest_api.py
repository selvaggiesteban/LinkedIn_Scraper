"""
guest_api.py — LinkedIn Guest API Scraper
Paginated job scraping without login using LinkedIn's hidden API.
"""
from __future__ import annotations

import random
import time
from datetime import datetime
from typing import Any

import requests
from bs4 import BeautifulSoup

from .config import (
    GUEST_API_BASE,
    GUEST_API_DELAY_MAX,
    GUEST_API_DELAY_MIN,
    GUEST_API_MAX_START,
    GUEST_API_PAGE_SIZE,
    LOCATION,
    PRIMARY_KEYWORDS,
    TEMPORAL_FILTER,
    USER_AGENTS,
)


def _get_random_ua() -> str:
    return random.choice(USER_AGENTS)


def _get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": _get_random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    })
    return s


def fetch_jobs_page(
    keyword: str,
    location: str = LOCATION,
    start: int = 0,
    temporal: str = TEMPORAL_FILTER,
    session: requests.Session | None = None,
    proxies: dict | None = None,
) -> list[dict[str, Any]]:
    """Fetch a single page of job results from the Guest API."""
    sess = session or _get_session()
    params = {
        "keywords": keyword,
        "location": location,
        "start": start,
        "f_TPR": temporal,
    }
    try:
        resp = sess.get(GUEST_API_BASE, params=params, proxies=proxies, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    [ERROR] Guest API request failed: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    jobs = []
    for li in soup.select("li"):
        card = li.select_one("div.base-search-card")
        if not card:
            continue

        link_el = card.select_one("a.base-card__full-link")
        title_el = card.select_one("h3.base-search-card__title")
        company_el = card.select_one("h4.base-search-card__subtitle")
        location_el = card.select_one("span.job-search-card__location")
        date_el = card.select_one("time.job-search-card__listdate")

        url = link_el["href"].split("?")[0] if link_el and link_el.has_attr("href") else ""
        title = title_el.get_text(strip=True) if title_el else ""
        company = company_el.get_text(strip=True) if company_el else ""
        loc = location_el.get_text(strip=True) if location_el else ""
        posted = date_el.get("datetime", "") if date_el else ""

        if url and title:
            jobs.append({
                "type": "job",
                "source": "guest_api",
                "search_keyword": keyword,
                "title": title,
                "company": company,
                "location": loc,
                "posted_date": posted,
                "job_url": url,
                "scraped_at": datetime.now().isoformat(),
            })
    return jobs


def fetch_all_jobs(
    keyword: str,
    location: str = LOCATION,
    temporal: str = TEMPORAL_FILTER,
    session: requests.Session | None = None,
    proxies: dict | None = None,
) -> list[dict[str, Any]]:
    """Fetch all pages for a single keyword (up to ~1,000 results)."""
    sess = session or _get_session()
    all_jobs = []
    seen_urls: set[str] = set()

    for start in range(0, GUEST_API_MAX_START + 1, GUEST_API_PAGE_SIZE):
        jobs = fetch_jobs_page(
            keyword=keyword,
            location=location,
            start=start,
            temporal=temporal,
            session=sess,
            proxies=proxies,
        )
        if not jobs:
            break

        new_count = 0
        for job in jobs:
            if job["job_url"] not in seen_urls:
                seen_urls.add(job["job_url"])
                all_jobs.append(job)
                new_count += 1

        print(f"    [start={start}] {new_count} new jobs (total: {len(all_jobs)})")

        if new_count == 0:
            break

        delay = random.uniform(GUEST_API_DELAY_MIN, GUEST_API_DELAY_MAX)
        time.sleep(delay)

    return all_jobs


def scrape_all_keywords(
    keywords: list[str] | None = None,
    location: str = LOCATION,
    temporal: str = TEMPORAL_FILTER,
    proxies: dict | None = None,
) -> list[dict[str, Any]]:
    """Scrape jobs for all primary keywords with pagination."""
    kws = keywords or PRIMARY_KEYWORDS
    all_jobs: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    print(f"\n{'=' * 60}")
    print(f"[GUEST API] JOBS — {len(kws)} keywords × up to 1,000 each")
    print(f"{'=' * 60}")

    for i, kw in enumerate(kws, 1):
        print(f"\n  [{i}/{len(kws)}] \"{kw}\" + \"{location}\"")
        sess = _get_session()
        jobs = fetch_all_jobs(
            keyword=kw,
            location=location,
            temporal=temporal,
            session=sess,
            proxies=proxies,
        )
        new = 0
        for job in jobs:
            if job["job_url"] not in seen_urls:
                seen_urls.add(job["job_url"])
                all_jobs.append(job)
                new += 1
        print(f"  → {new} unique jobs from \"{kw}\" (total: {len(all_jobs)})")

    print(f"\n[GUEST API] TOTAL: {len(all_jobs)} unique jobs")
    return all_jobs
