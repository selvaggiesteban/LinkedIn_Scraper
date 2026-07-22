"""
guest_api.py — LinkedIn Guest API Scraper
Paginated job scraping without login using LinkedIn's hidden API.
"""
from __future__ import annotations

import random
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

import requests
from bs4 import BeautifulSoup

from ..config import (
    GUEST_API_BASE,
    GUEST_API_DELAY_MAX,
    GUEST_API_DELAY_MIN,
    GUEST_API_MAX_START,
    GUEST_API_PAGE_SIZE,
    LOCATIONS,
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
    location: str = "Buenos Aires, Argentina",
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
    location: str = "Buenos Aires, Argentina",
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
    locations: list[str] | None = None,
    temporal: str = TEMPORAL_FILTER,
    proxies: dict | None = None,
) -> list[dict[str, Any]]:
    """Scrape jobs for all primary keywords × locations with pagination."""
    kws = keywords or PRIMARY_KEYWORDS
    locs = locations or LOCATIONS
    all_jobs: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    print(f"\n{'=' * 60}")
    print(f"[GUEST API] JOBS — {len(kws)} keywords × {len(locs)} locations × up to 1,000 each")
    print(f"{'=' * 60}")

    for loc in locs:
        for i, kw in enumerate(kws, 1):
            print(f"\n  [{i}/{len(kws)}] \"{kw}\" + \"{loc}\"")
            sess = _get_session()
            jobs = fetch_all_jobs(
                keyword=kw,
                location=loc,
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


# ═══════════════════════════════════════════════════════════════
# PUBLIC ENDPOINT FETCHERS (no-login Vía 1 full coverage)
# ═══════════════════════════════════════════════════════════════
import re as _re
from ..config import (
    GUEST_API_JOBS_VIEW_BASE as _JOBS_VIEW_BASE,
    GUEST_PUBLIC_PROFILE_BASE as _PROFILE_BASE,
    GUEST_COMPANY_ABOUT_BASE as _COMPANY_BASE,
)


def _extract_job_id(url: str) -> str:
    """Extract LinkedIn job ID from job_url."""
    m = _re.search(r"/jobs/view/(\d+)", url)
    return m.group(1) if m else ""


def _extract_username(url: str) -> str:
    """Extract LinkedIn username from /in/<username>/."""
    m = _re.search(r"/in/([^/?#]+)/?", url)
    return m.group(1) if m else ""


def _extract_slug(url: str) -> str:
    """Extract company slug from /company/<slug>/."""
    m = _re.search(r"/company/([^/?#]+)/?", url)
    return m.group(1) if m else ""


def fetch_job_detail(job_url: str, session: requests.Session | None = None, proxies: dict | None = None) -> dict[str, Any]:
    """Fetch a public /jobs/view/<id> page (no login required). Returns job_detail dict."""
    sess = session or _get_session()
    job_id = _extract_job_id(job_url)
    try:
        resp = sess.get(job_url, proxies=proxies, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    [WARN] fetch_job_detail({job_id}): {e}")
        return {}
    soup = BeautifulSoup(resp.text, "html.parser")
    title_el = soup.select_one("h1.topcard__title, h1.top-card-layout__title, h3.t-24")
    company_el = soup.select_one("a.topcard__org-name-link, span.topcard__flavor")
    location_el = soup.select_one("span.topcard__flavor--bullet, span.topcard__flavor.topcard__flavor--bullet")
    desc_el = soup.select_one("div.description__text, div.show-more-less-html__markup")
    return {
        "type": "job_detail",
        "source": "guest_api",
        "title": title_el.get_text(strip=True) if title_el else "",
        "company": company_el.get_text(strip=True) if company_el else "",
        "location": location_el.get_text(strip=True) if location_el else "",
        "description": desc_el.get_text(separator=" ", strip=True) if desc_el else "",
        "url": job_url,
        "external_id": job_id,
        "scraped_at": datetime.now().isoformat(),
    }


def fetch_public_profile(username: str, session: requests.Session | None = None, proxies: dict | None = None) -> dict[str, Any]:
    """Fetch a public /in/<username> page (no login required). Returns person_profile dict."""
    sess = session or _get_session()
    url = f"{_PROFILE_BASE}{username}/"
    try:
        resp = sess.get(url, proxies=proxies, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    [WARN] fetch_public_profile({username}): {e}")
        return {}
    soup = BeautifulSoup(resp.text, "html.parser")
    name_el = soup.select_one("h1.top-card-layout__title, h1.font-bold")
    headline_el = soup.select_one("div.top-card-layout__second-headline, h2.top-card-layout__headline")
    about_el = soup.select_one("section.summary, div.inline.break-words")
    return {
        "type": "person_profile",
        "source": "guest_api",
        "name": name_el.get_text(strip=True) if name_el else "",
        "headline": headline_el.get_text(strip=True) if headline_el else "",
        "about": about_el.get_text(separator=" ", strip=True) if about_el else "",
        "url": url,
        "external_id": username,
        "scraped_at": datetime.now().isoformat(),
    }


def fetch_company_about(slug: str, session: requests.Session | None = None, proxies: dict | None = None) -> dict[str, Any]:
    """Fetch a public /company/<slug>/about page (no login required). Returns company_profile dict."""
    sess = session or _get_session()
    url = f"{_COMPANY_BASE}{slug}/about/"
    try:
        resp = sess.get(url, proxies=proxies, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    [WARN] fetch_company_about({slug}): {e}")
        return {}
    soup = BeautifulSoup(resp.text, "html.parser")
    name_el = soup.select_one("h1.org-top-card-summary__title, h1.org-page-details__name")
    tagline_el = soup.select_one("p.org-top-card-summary__tagline, h2.org-page-details__tagline")
    industry_el = soup.select_one("dd.org-page-details__definition-text, span.org-top-card-summary__info-item")
    return {
        "type": "company_profile",
        "source": "guest_api",
        "name": name_el.get_text(strip=True) if name_el else slug,
        "tagline": tagline_el.get_text(strip=True) if tagline_el else "",
        "industry": industry_el.get_text(strip=True) if industry_el else "",
        "url": url,
        "external_id": slug,
        "scraped_at": datetime.now().isoformat(),
    }


def scrape_public_complements(
    jobs: list[dict[str, Any]],
    people: list[dict[str, Any]] | None = None,
    companies: list[dict[str, Any]] | None = None,
    proxies: dict | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Vía 1 full coverage: enrich jobs/job_details/people/person_profiles/company_profiles from public endpoints."""
    print(f"\n{'=' * 60}")
    print("[GUEST API] PUBLIC COMPLEMENTS (no-login)")
    print(f"{'=' * 60}")
    sess = _get_session()
    result: dict[str, list] = {"job_details": [], "person_profiles": [], "company_profiles": []}
    seen_jobs = set()
    for i, job in enumerate(jobs[:50], 1):  # cap 50 job details (public endpoints can rate-limit)
        url = job.get("job_url", "")
        if not url or url in seen_jobs:
            continue
        seen_jobs.add(url)
        print(f"  [{i}/50] job_detail: {url[:80]}…")
        detail = fetch_job_detail(url, sess, proxies)
        if detail:
            result["job_details"].append(detail)
        time.sleep(random.uniform(GUEST_API_DELAY_MIN, GUEST_API_DELAY_MAX))
    # People derived: scrape top 15 unique /in/<username>/ URLs from `people` bucket (filled by MCP)
    seen_users = set()
    for person in (people or [])[:15]:
        url = person.get("profile_url", "")
        if not url:
            continue
        username = _extract_username(url)
        if not username or username in seen_users:
            continue
        seen_users.add(username)
        print(f"  person_profile: /in/{username}/")
        profile = fetch_public_profile(username, sess, proxies)
        if profile:
            result["person_profiles"].append(profile)
        time.sleep(random.uniform(GUEST_API_DELAY_MIN, GUEST_API_DELAY_MAX))
    # Companies derived: scrape top 10 unique /company/<slug>/about from `companies` bucket
    seen_slugs = set()
    for comp in (companies or [])[:10]:
        url = comp.get("url", "")
        slug = _extract_slug(url) or comp.get("external_id", "") or comp.get("slug", "")
        if not slug or slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        print(f"  company_about: /company/{slug}/about")
        about = fetch_company_about(slug, sess, proxies)
        if about:
            result["company_profiles"].append(about)
        time.sleep(random.uniform(GUEST_API_DELAY_MIN, GUEST_API_DELAY_MAX))
    print(f"  → job_details: {len(result['job_details'])}, person_profiles: {len(result['person_profiles'])}, company_profiles: {len(result['company_profiles'])}")
    return result
