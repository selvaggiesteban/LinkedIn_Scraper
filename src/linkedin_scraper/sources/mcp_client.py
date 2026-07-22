"""
mcp_client.py — MCP LinkedIn Client (fixed initialization)
Wraps mcp-server-linkedin for people, feed, company posts, employees.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from typing import Any


class MCPClient:
    """Async MCP client for LinkedIn server via stdio transport."""

    def __init__(self):
        self._read_stream = None
        self._write_stream = None
        self._req_id = 0
        self._cm = None

    async def connect(self):
        from mcp.client.stdio import stdio_client
        from mcp import StdioServerParameters
        import mcp.types as types
        from mcp.shared.message import SessionMessage

        server_params = StdioServerParameters(
            command="mcp-server-linkedin", args=[],
            env={"UV_HTTP_TIMEOUT": "300"},
        )
        self._cm = stdio_client(server_params)
        streams = await self._cm.__aenter__()
        self._read_stream = streams[0]
        self._write_stream = streams[1]

        # Initialize
        init = types.JSONRPCRequest(
            jsonrpc="2.0", id=1, method="initialize",
            params=types.InitializeRequestParams(
                protocolVersion=types.LATEST_PROTOCOL_VERSION,
                capabilities=types.ClientCapabilities(),
                clientInfo=types.Implementation(name="linkedin-scraper", version="2.0"),
            ).model_dump(),
        )
        await self._write_stream.send(SessionMessage(message=init))
        resp = await asyncio.wait_for(self._read_stream.receive(), timeout=15)
        print("[MCP] Initialized OK")

    async def call_raw(self, tool_name: str, arguments: dict, timeout: float = 30) -> dict | None:
        import mcp.types as types
        from mcp.shared.message import SessionMessage

        self._req_id += 1
        req = types.JSONRPCRequest(
            jsonrpc="2.0", id=self._req_id, method="tools/call",
            params={"name": tool_name, "arguments": arguments},
        )
        await self._write_stream.send(SessionMessage(message=req))
        response = await asyncio.wait_for(self._read_stream.receive(), timeout=timeout)

        inner = response
        while hasattr(inner, "message") and inner.message is not None:
            inner = inner.message
        while hasattr(inner, "root") and inner.root is not None:
            inner = inner.root

        if not hasattr(inner, "result") or inner.result is None:
            return None

        content = inner.result.get("content", [])
        for item in content:
            t = item.get("text", "") if isinstance(item, dict) else getattr(item, "text", "")
            if t:
                try:
                    return json.loads(t)
                except json.JSONDecodeError:
                    return {"sections": {"raw": t}, "references": {}}
        return None

    async def call_text(self, tool_name: str, arguments: dict) -> str | None:
        data = await self.call_raw(tool_name, arguments)
        if not data:
            return None
        sections = data.get("sections", {})
        return "\n".join(str(v) for v in sections.values()) if sections else None

    async def close(self):
        if self._cm:
            await self._cm.__aexit__(None, None, None)

    async def get_cookies(self) -> dict[str, str]:
        """Return the active session cookies (for Scrapling/Playwright to reuse the MCP login)."""
        try:
            data = await self.call_raw("get_feed", {"num_posts": 1}, timeout=20)
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        # mcp-server-linkedin sometimes surfaces session cookies inside metadata
        cookies = data.get("cookies") or data.get("session", {}).get("cookies") or {}
        if isinstance(cookies, dict):
            return cookies
        # Fallback: if it's a list of {name, value}, flatten it
        if isinstance(cookies, list):
            return {c.get("name", ""): c.get("value", "") for c in cookies if isinstance(c, dict)}
        return {}


def _parse_people_refs(data: dict, keyword: str) -> list[dict[str, Any]]:
    results = []
    refs = data.get("references", {}).get("search_results", [])
    for ref in refs:
        if ref.get("kind") != "person":
            continue
        url = ref.get("url", "")
        if not url or "/in/" not in url:
            continue
        full_url = f"https://www.linkedin.com{url}" if url.startswith("/") else url
        results.append({
            "type": "person",
            "source": "mcp",
            "search_keyword": keyword,
            "name": ref.get("text", ""),
            "profile_url": full_url,
            "scraped_at": datetime.now().isoformat(),
        })
    return results


def _parse_people_text(text: str, keyword: str) -> list[dict[str, Any]]:
    results = []
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for line in lines:
        if any(skip in line.lower() for skip in ["search", "filter", "result", "relevance"]):
            continue
        if len(line) > 5 and not line.startswith("http"):
            results.append({
                "type": "person",
                "source": "mcp",
                "search_keyword": keyword,
                "name": line,
                "profile_url": "",
                "scraped_at": datetime.now().isoformat(),
            })
    return results


def _parse_job_refs(data: dict, keyword: str) -> list[dict[str, Any]]:
    results = []
    refs = data.get("references", {}).get("search_results", [])
    for ref in refs:
        if ref.get("kind") != "job":
            continue
        url = ref.get("url", "")
        if not url:
            continue
        full_url = f"https://www.linkedin.com{url}" if url.startswith("/") else url
        results.append({
            "type": "job",
            "source": "mcp",
            "search_keyword": keyword,
            "title": ref.get("text", ""),
            "job_url": full_url,
            "scraped_at": datetime.now().isoformat(),
        })
    return results


def _parse_post_refs(data: dict, source: str, company: str = "") -> list[dict[str, Any]]:
    results = []
    refs = data.get("references", {}).get("search_results", []) or \
           data.get("references", {}).get("feed", [])
    for ref in refs:
        kind = ref.get("kind", "")
        if kind not in ("feed_post", "article"):
            continue
        url = ref.get("url", "")
        if not url:
            continue
        full_url = f"https://www.linkedin.com{url}" if url.startswith("/") else url
        results.append({
            "type": f"post_{source}",
            "source": "mcp",
            "post_url": full_url,
            "title": ref.get("text", ""),
            "company_name": company,
            "scraped_at": datetime.now().isoformat(),
        })
    return results


def _parse_employee_refs(data: dict, company: str) -> list[dict[str, Any]]:
    results = []
    refs = data.get("references", {}).get("employees", [])
    for ref in refs:
        if ref.get("kind") != "person":
            continue
        url = ref.get("url", "")
        if not url or "/in/" not in url:
            continue
        full_url = f"https://www.linkedin.com{url}" if url.startswith("/") else url
        results.append({
            "type": "person",
            "source": "mcp_company",
            "search_keyword": company,
            "name": ref.get("text", ""),
            "profile_url": full_url,
            "url": full_url,
            "external_id": url.rstrip("/").split("/in/")[-1],
            "scraped_at": datetime.now().isoformat(),
        })
    return results


def _parse_job_details(data: dict, job_id: str = "") -> dict[str, Any]:
    """Parse get_job_details response into a job_detail dict."""
    if not isinstance(data, dict):
        return {}
    sections = data.get("sections", {}) or {}
    description = sections.get("description") or sections.get("details") or ""
    title = sections.get("title", "")
    company = sections.get("company", "")
    location = sections.get("location", "")
    url = sections.get("url") or (f"https://www.linkedin.com/jobs/view/{job_id}/" if job_id else "")
    return {
        "type": "job_detail",
        "source": "mcp",
        "title": title,
        "company": company,
        "location": location,
        "description": description if isinstance(description, str) else str(description),
        "url": url,
        "external_id": str(job_id),
        "scraped_at": datetime.now().isoformat(),
    }


def _parse_person_profile(data: dict, username: str = "") -> dict[str, Any]:
    """Parse get_person_profile response into person_profile dict."""
    if not isinstance(data, dict):
        return {}
    sections = data.get("sections", {}) or {}
    name = sections.get("name", "")
    headline = sections.get("headline", "")
    about = sections.get("about", "") or sections.get("summary", "")
    experience = sections.get("experience", "")
    education = sections.get("education", "")
    url = sections.get("url") or (f"https://www.linkedin.com/in/{username}/" if username else "")
    return {
        "type": "person_profile",
        "source": "mcp",
        "name": name,
        "headline": headline,
        "about": about if isinstance(about, str) else str(about),
        "experience": experience if isinstance(experience, str) else str(experience),
        "education": education if isinstance(education, str) else str(education),
        "url": url,
        "external_id": username,
        "scraped_at": datetime.now().isoformat(),
    }


def _parse_company_profile(data: dict, slug: str = "") -> dict[str, Any]:
    """Parse get_company_profile response into company_profile dict."""
    if not isinstance(data, dict):
        return {}
    sections = data.get("sections", {}) or {}
    name = sections.get("name", "") or slug
    tagline = sections.get("tagline", "") or sections.get("slogan", "")
    industry = sections.get("industry", "")
    size = sections.get("company_size", "") or sections.get("size", "")
    about = sections.get("about", "") or sections.get("description", "")
    url = sections.get("url") or (f"https://www.linkedin.com/company/{slug}/about/" if slug else "")
    return {
        "type": "company_profile",
        "source": "mcp",
        "name": name,
        "tagline": tagline if isinstance(tagline, str) else str(tagline),
        "industry": industry if isinstance(industry, str) else str(industry),
        "size": size if isinstance(size, str) else str(size),
        "about": about if isinstance(about, str) else str(about),
        "url": url,
        "external_id": slug,
        "scraped_at": datetime.now().isoformat(),
    }


def _parse_authors_from_text(text: str, source: str = "mcp") -> list[dict[str, Any]]:
    """Regex-extract author /in/<username>/ URLs from a post/feed text block."""
    if not text:
        return []
    urls = re.findall(r'https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+/?', text)
    seen = set()
    authors = []
    for u in urls:
        norm = u.split("?")[0].rstrip("/")
        if norm in seen:
            continue
        seen.add(norm)
        username = norm.rstrip("/").split("/in/")[-1]
        authors.append({
            "type": "author",
            "source": source,
            "name": "",
            "url": norm,
            "external_id": username,
            "scraped_at": datetime.now().isoformat(),
        })
    return authors


def _normalize_person(p: dict[str, Any]) -> dict[str, Any]:
    """Ensure every person dict has a `url` field for dedup compatibility."""
    url = p.get("profile_url") or p.get("url", "")
    p["url"] = url
    if url and "external_id" not in p:
        m = re.search(r"/in/([^/?#]+)/?", url)
        if m:
            p["external_id"] = m.group(1)
    return p


def _normalize_post(p: dict[str, Any]) -> dict[str, Any]:
    """Ensure every post dict has a `url` field for dedup compatibility."""
    p["url"] = p.get("post_url") or p.get("url", "")
    return p


def _extract_job_id_from_item(item: dict[str, Any]) -> str:
    """Extract job ID from a normalized job item (jobId field or URL pattern)."""
    jid = item.get("jobId") or item.get("external_id")
    if jid:
        return str(jid)
    url = item.get("url") or item.get("job_url") or item.get("applyUrl", "")
    m = re.search(r"/jobs/view/(\d+)", url)
    return m.group(1) if m else ""


async def scrape_mcp(
    people_keywords: list[str],
    company_searches: list[str],
    location: str,
    delay: float = 1.5,
    job_keywords: list[str] | None = None,
    job_details_cap: int = 50,
    person_profiles_cap: int = 30,
    company_profiles_cap: int = 20,
) -> dict[str, list[dict[str, Any]]]:
    """Run all MCP searches with full coverage: jobs, people, feed, companies, employees + details enrichment."""
    results: dict[str, list] = {
        "people": [], "jobs": [], "job_details": [],
        "posts_feed": [], "posts_companies": [],
        "authors": [], "company_employees": [],
        "company_search": [], "company_profiles": [],
        "person_profiles": [],
    }
    seen_profiles: set[str] = set()
    seen_job_ids: set[str] = set()

    mcp = MCPClient()
    print(f"\n{'=' * 60}")
    print(f"[MCP] Connecting...")
    await mcp.connect()
    print("[MCP] Connected.\n")

    # --- JOBS (search_jobs) — Vía 2 full coverage ---
    if job_keywords:
        print(f"[MCP] JOBS — {len(job_keywords)} keywords")
        for i, kw in enumerate(job_keywords, 1):
            print(f"  [{i}/{len(job_keywords)}] {kw}")
            args = {"keywords": kw, "max_pages": 1, "date_posted": "past_week", "sort_by": "date", "work_type": "remote,on_site"}
            if location:
                args["location"] = location
            data = await mcp.call_raw("search_jobs", args, timeout=45)
            if not data:
                print("    -> 0")
                await asyncio.sleep(delay)
                continue
            try:
                from ..parsers.linkedin_parser import parse_single_response
                # parser expects a text string; MCP call_raw returns dict already
                # Re-encode to text so parser can consume it (fallback path)
                jobs_data = parse_single_response(_to_text(data)) or []
            except Exception:
                jobs_data = _parse_job_refs(data, kw)
            new = 0
            for job in jobs_data:
                job_id = str(job.get("jobId", "")) or _extract_job_id_from_item(job)
                if job_id and job_id in seen_job_ids:
                    continue
                seen_job_ids.add(job_id)
                # Normalize: ensure `url` field exists for dedup
                job["url"] = job.get("applyUrl") or job.get("url") or job.get("job_url", "")
                job["source"] = "mcp"
                job["type"] = "job"
                job["search_keyword"] = kw
                job["external_id"] = job_id
                if "scraped_at" not in job:
                    job["scraped_at"] = datetime.now().isoformat()
                results["jobs"].append(job)
                new += 1
            print(f"    -> {new} new jobs")
            await asyncio.sleep(delay)

    # --- PEOPLE ---
    print(f"[MCP] PEOPLE — {len(people_keywords)} keywords")
    for i, kw in enumerate(people_keywords, 1):
        print(f"  [{i}/{len(people_keywords)}] {kw}")
        data = await mcp.call_raw("search_people", {"keywords": kw, "location": location})
        if data:
            people = _parse_people_refs(data, kw)
            if not people:
                sections = data.get("sections", {})
                text = sections.get("search_results", "")
                if text:
                    people = _parse_people_text(text, kw)
            new = 0
            for person in people:
                person = _normalize_person(person)
                url = person.get("url") or person.get("profile_url", "")
                if url and url not in seen_profiles:
                    seen_profiles.add(url)
                    results["people"].append(person)
                    new += 1
                elif not url:
                    results["people"].append(person)
            print(f"    -> {new} new profiles")
        else:
            print("    -> 0")
        await asyncio.sleep(delay)

    # --- FEED ---
    print(f"\n[MCP] FEED")
    data = await mcp.call_raw("get_feed", {"num_posts": 50})
    if data:
        posts = _parse_post_refs(data, "feed")
        results["posts_feed"] = [_normalize_post(p) for p in posts]
        print(f"  -> {len(posts)} posts")
        # Authors: extract /in/<username>/ from raw feed text
        for p in posts:
            text = p.get("title", "") + " " + p.get("text", "")
            urls = re.findall(r'https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+/?', text)
            for au in urls:
                authors = _parse_authors_from_text(au, "mcp")
                for a in authors:
                    if a["url"] not in {x.get("url") for x in results["authors"]}:
                        results["authors"].append(a)

    # --- COMPANY POSTS + EMPLOYEES + SEARCH + PROFILE ---
    print(f"\n[MCP] COMPANIES — {len(company_searches)} searches")
    for i, ck in enumerate(company_searches, 1):
        print(f"  [{i}/{len(company_searches)}] {ck}")
        cdata = await mcp.call_raw("search_companies", {"keywords": ck})
        if not cdata:
            print("    -> 0 companies")
            continue

        comp_refs = cdata.get("references", {}).get("search_results", [])
        comp_slugs = []
        for ref in comp_refs:
            if ref.get("kind") == "company":
                url = ref.get("url", "")
                if url and "/company/" in url:
                    slug = url.rstrip("/").split("/")[-1]
                    comp_slugs.append(slug)
                # Persist ALL company entries to company_search bucket (full coverage)
                results["company_search"].append({
                    "type": "company",
                    "source": "mcp",
                    "name": ref.get("text", ""),
                    "url": f"https://www.linkedin.com{url}" if url.startswith("/") else url,
                    "external_id": url.rstrip("/").split("/")[-1] if url else "",
                    "scraped_at": datetime.now().isoformat(),
                })

        print(f"    -> {len(comp_slugs)} company slugs")
        for slug in comp_slugs[:5]:
            # Company posts
            ptext = await mcp.call_text("get_company_posts", {"company_name": slug})
            if ptext:
                urls = re.findall(
                    r'https?://www\.linkedin\.com/feed/update/urn:li:[^\s\)\"\'<>]+|'
                    r'https?://www\.linkedin\.com/posts/[^\s\)\"\'<>]+',
                    ptext,
                )
                unique_urls = list(dict.fromkeys(u.split("?")[0] for u in urls))
                for u in unique_urls:
                    results["posts_companies"].append(_normalize_post({
                        "type": "post_company",
                        "source": "mcp",
                        "post_url": u,
                        "url": u,
                        "company_name": slug,
                        "scraped_at": datetime.now().isoformat(),
                    }))
                print(f"      {slug}: {len(unique_urls)} posts")
                # Authors of company posts
                for au in _parse_authors_from_text(ptext, "mcp_company"):
                    if au["url"] not in {x.get("url") for x in results["authors"]}:
                        results["authors"].append(au)

            # Company employees
            edata = await mcp.call_raw("get_company_employees", {"company_name": slug})
            if edata:
                employees = _parse_employee_refs(edata, slug)
                for emp in employees:
                    emp = _normalize_person(emp)
                    url = emp.get("url") or emp.get("profile_url", "")
                    if url and url not in seen_profiles:
                        seen_profiles.add(url)
                        results["company_employees"].append(emp)
                print(f"      {slug}: {len(employees)} employees")
            await asyncio.sleep(delay)

    # --- JOB DETAILS (get_job_details) — top-N jobId enrichment ---
    if results["jobs"]:
        print(f"\n[MCP] JOB_DETAILS — top {min(job_details_cap, len(results['jobs']))}")
        for i, job in enumerate(results["jobs"][:job_details_cap], 1):
            job_id = _extract_job_id_from_item(job)
            if not job_id:
                continue
            print(f"  [{i}/{job_details_cap}] job_id={job_id}")
            try:
                detail_data = await mcp.call_raw("get_job_details", {"job_id": job_id}, timeout=30)
                detail = _parse_job_details(detail_data, job_id)
                if detail:
                    # carry over original metadata
                    detail["search_keyword"] = job.get("search_keyword", "")
                    results["job_details"].append(detail)
            except Exception as e:
                print(f"    [ERR] get_job_details({job_id}): {type(e).__name__}")
            await asyncio.sleep(delay)

    # --- PERSON PROFILES (get_person_profile) — top-N username enrichment ---
    if results["people"]:
        print(f"\n[MCP] PERSON_PROFILES — top {min(person_profiles_cap, len(results['people']))}")
        for i, person in enumerate(results["people"][:person_profiles_cap], 1):
            username = person.get("external_id", "")
            if not username:
                url = person.get("url") or person.get("profile_url", "")
                m = re.search(r"/in/([^/?#]+)/?", url)
                if m:
                    username = m.group(1)
            if not username:
                continue
            print(f"  [{i}/{person_profiles_cap}] username={username}")
            try:
                pdata = await mcp.call_raw("get_person_profile", {"username": username}, timeout=30)
                profile = _parse_person_profile(pdata, username)
                if profile:
                    profile["search_keyword"] = person.get("search_keyword", "")
                    results["person_profiles"].append(profile)
            except Exception as e:
                print(f"    [ERR] get_person_profile({username}): {type(e).__name__}")
            await asyncio.sleep(delay)

    # --- COMPANY PROFILES (get_company_profile) — top-N slug enrichment ---
    seen_slugs = set()
    candidates = list(results["company_search"])[:company_profiles_cap]
    if candidates:
        print(f"\n[MCP] COMPANY_PROFILES — top {len(candidates)}")
        for i, comp in enumerate(candidates, 1):
            slug = comp.get("external_id", "")
            if not slug or slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            print(f"  [{i}/{len(candidates)}] slug={slug}")
            try:
                company_url = comp.get("url", "") or f"https://www.linkedin.com/company/{slug}/about/"
                cpdata = await mcp.call_raw("get_company_profile", {"url": company_url}, timeout=30)
                profile = _parse_company_profile(cpdata, slug)
                if profile:
                    results["company_profiles"].append(profile)
            except Exception as e:
                print(f"    [ERR] get_company_profile({slug}): {type(e).__name__}")
            await asyncio.sleep(delay)

    await mcp.close()

    total = sum(len(v) for v in results.values())
    print(f"\n[MCP] TOTAL: {total} items across {len(results)} buckets")
    return results


def _to_text(data: dict) -> str:
    """Re-encode a dict response to JSON text for parsers expecting string input."""
    try:
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return str(data)
