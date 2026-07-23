"""
mcp_client.py — MCP LinkedIn Client (adaptive rate-limited)

Wraps mcp-server-linkedin for jobs, people, feed, company posts, employees,
and details enrichment. Uses RateBudget + jitter to stay under LinkedIn's
challenge-screen threshold (~150 profiles/hr, ~5-8/min bursts).
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
from datetime import datetime
from typing import Any

from ..utils.rate_budget import RateBudget, RateBudgetConfig


# ── typed errors so callers can distinguish transient vs. fatal ──────────────

class MCPServerError(RuntimeError):
    """Generic structured error from the MCP server."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class MCPChallengePendingError(MCPServerError):
    """Server told us the login window is still open / challenge isn't resolved.

    Caller must wait (per the server's own instructions: "call again in ~30s")
    or surface the manual-action hint to the user.
    """



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
        try:
            response = await asyncio.wait_for(self._read_stream.receive(), timeout=timeout)
        except asyncio.TimeoutError:
            raise

        inner = response
        while hasattr(inner, "message") and inner.message is not None:
            inner = inner.message
        while hasattr(inner, "root") and inner.root is not None:
            inner = inner.root

        # Detect structured ToolError / AuthenticationInProgressError / challenge messages.
        # The stdio MCP server surfaces these as `inner.error.code/message = -32002 ...`
        # or as content text containing the literal phrase. We raise a typed
        # exception so scrape_mcp's per-bucket try/except can back off specifically.
        if hasattr(inner, "error") and inner.error is not None:
            err = inner.error
            err_msg = ""
            try:
                err_msg = err.message if hasattr(err, "message") else str(err)
            except Exception:
                err_msg = str(err)
            raise MCPServerError(err_msg, code=getattr(err, "code", None))

        if not hasattr(inner, "result") or inner.result is None:
            return None

        content = inner.result.get("content", [])
        text_blobs = []
        for item in content:
            t = item.get("text", "") if isinstance(item, dict) else getattr(item, "text", "")
            if t:
                text_blobs.append(t)
        merged = "\n".join(text_blobs)
        lower = merged.lower()
        # The server returns the human message directly in content when login is pending.
        if "login is still in progress" in lower or "authentication in progress" in lower or "setup is not complete" in lower:
            raise MCPChallengePendingError(merged.strip())
        if merged:
            try:
                return json.loads(merged)
            except json.JSONDecodeError:
                return {"sections": {"raw": merged}, "references": {}}
        return None

    async def call_text(self, tool_name: str, arguments: dict) -> str | None:
        data = await self.call_raw(tool_name, arguments)
        if not data:
            return None
        sections = data.get("sections", {})
        return "\n".join(str(v) for v in sections.values()) if sections else None

    async def close(self):
        if self._cm:
            try:
                await self._cm.__aexit__(None, None, None)
            except (Exception, BaseException):
                # anyio cancel-scope mismatch is harmless at exit
                pass

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
    budget: RateBudget | None = None,
    cool_run: bool = False,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:


    """Run all MCP searches with full coverage, using RateBudget pacing.

    Returns ``(results, cookies)``: ``results`` is the bucket dict, and
    ``cookies`` are the active session cookies captured before teardown (used
    downstream by Scrapling / Playwright).

    The pipeline is broken into 8 staggered phases (T8 plan) to dodge the
    LinkedIn "actividad sospechosa en tu cuenta" modal:

      Fase A: search_jobs × N keywords            (delay 3.0–5.0 s)
      Fase B: search_people × M keywords (5-batch) (delay 4.0–6.0 s, 60 s cool-down / 5 keywords)
      Fase C: get_feed                              (delay 8 s cool-down)
      Fase D: search_companies × K keywords         (delay 4.0–6.0 s)
      Fase E: get_company_posts + employees (top 3) (delay 5.0–7.0 s, 30 s cool-down)
      Fase F: get_job_details                       (delay 3.0–5.0 s)
      Fase G: get_person_profile                    (delay 4.0–6.0 s)
      Fase H: get_company_profile                   (delay 5.0–7.0 s)

    The RateBudget pacing is shared with the caller via the ``budget``
    attribute on the returned ``results`` dict (a private side-channel since
    the public tuple is fixed). Callers that want stats after the run can
    fetch ``scrape_mcp.last_budget`` or build a fresh snapshot from the
    helper class instance before invoking this function.
    """
    budget = budget or RateBudget()
    results: dict[str, list] = {
        "people": [], "jobs": [], "job_details": [],
        "posts_feed": [], "posts_companies": [],
        "authors": [], "company_employees": [],
        "company_search": [], "company_profiles": [],
        "person_profiles": [],
    }
    seen_profiles: set[str] = set()
    seen_job_ids: set[str] = set()

    def _jitter(low: float, high: float) -> float:
        return random.uniform(low, high) * (4.0 if cool_run else 1.0)

    async def _safe_call(tool_name: str, args: dict, *, timeout: float = 30,
                         weight: float = 1.0) -> dict | None:
        """Wrapper that paces via the budget and recovers challenge-pending."""
        attempt = 0
        last_exc = None
        while attempt < 2:
            await budget.acquire(weight=weight, cool_run=cool_run)
            try:
                return await mcp.call_raw(tool_name, args, timeout=timeout)
            except MCPChallengePendingError as e:
                print(f"  [challenge-pending] {tool_name}: {str(e)[:120]}")
                budget.record_error()
                await budget.pause_for(45.0, reason=f"challenge pending after {tool_name}")
                attempt += 1
            except (MCPServerError, asyncio.TimeoutError) as e:
                print(f"  [WARN] {tool_name} transient {type(e).__name__}")
                budget.record_error(weight=2.0)
                await budget.pause_for(15.0, reason=f"{tool_name} transient")
                attempt += 1
            except Exception as e:
                print(f"  [WARN] {tool_name} unexpected {type(e).__name__}")
                budget.record_error(weight=2.0)
                return None
        return None

    mcp = MCPClient()
    print(f"\n{'=' * 60}")
    print(f"[MCP] Connecting...")
    try:
        await mcp.connect()
    except Exception as e:
        print(f"[MCP] connect failed: {type(e).__name__}")
        return results, {}
    print("[MCP] Connected.\n")

    # ── Fase A — search_jobs (low-risk; no profile view yet) ────────────
    if job_keywords:
        print(f"[MCP/Fase A] JOBS — {len(job_keywords)} keywords")
        for i, kw in enumerate(job_keywords, 1):
            print(f"  [{i}/{len(job_keywords)}] {kw}")
            args = {"keywords": kw, "max_pages": 1, "date_posted": "past_week",
                    "sort_by": "date", "work_type": "remote,on_site"}
            if location:
                args["location"] = location
            data = await _safe_call("search_jobs", args, timeout=45, weight=1.0)
            if not data:
                print("    -> 0")
                await asyncio.sleep(_jitter(3.0, 5.0))
                continue
            try:
                from ..parsers.linkedin_parser import parse_single_response
                jobs_data = parse_single_response(_to_text(data)) or []
            except Exception:
                jobs_data = _parse_job_refs(data, kw)
            new = 0
            for job in jobs_data:
                job_id = str(job.get("jobId", "")) or _extract_job_id_from_item(job)
                if job_id and job_id in seen_job_ids:
                    continue
                seen_job_ids.add(job_id)
                job["url"] = job.get("applyUrl") or job.get("url") or job.get("job_url", "")
                job["source"] = "mcp"
                job["type"] = "job"
                job["search_keyword"] = kw
                job["external_id"] = job_id
                job.setdefault("scraped_at", datetime.now().isoformat())
                results["jobs"].append(job)
                new += 1
            print(f"    -> {new} new jobs")
            await asyncio.sleep(_jitter(3.0, 5.0))

    # ── Fase B — search_people (highest risk; batched) ───────────────────
    print(f"[MCP/Fase B] PEOPLE — {len(people_keywords)} keywords")
    batch_size = 4                       # 5 → 4 buckets per batch for cooler pacing
    for batch_start in range(0, len(people_keywords), batch_size):
        batch = people_keywords[batch_start:batch_start + batch_size]
        for i, kw in enumerate(batch, batch_start + 1):
            print(f"  [{i}/{len(people_keywords)}] {kw}")
            data = await _safe_call(
                "search_people",
                {"keywords": kw, "location": location},
                weight=1.0,
            )
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
            await asyncio.sleep(_jitter(4.0, 6.0))
        # Cool-down between batches (B batches → ~60s extra)
        if batch_start + batch_size < len(people_keywords):
            await budget.pause_for(60.0, reason="between-people-batches")

    # ── Fase C — feed (single call, low cardinality) ─────────────────────
    print(f"\n[MCP/Fase C] FEED (after Fase B cool-down)")
    await budget.pause_for(20.0, reason="pre-feed cool-down")
    data = await _safe_call("get_feed", {"num_posts": 50}, timeout=30, weight=1.0)
    if data:
        posts = _parse_post_refs(data, "feed")
        results["posts_feed"] = [_normalize_post(p) for p in posts]
        print(f"  -> {len(posts)} posts")
        for p in posts:
            text = (p.get("title", "") or "") + " " + (p.get("text", "") or "")
            urls = re.findall(r'https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+/?', text)
            for au in urls:
                authors = _parse_authors_from_text(au, "mcp")
                for a in authors:
                    if a["url"] not in {x.get("url") for x in results["authors"]}:
                        results["authors"].append(a)
    await asyncio.sleep(_jitter(8.0, 12.0))

    # ── Fase D — search_companies (full coverage) ───────────────────────
    print(f"\n[MCP/Fase D] COMPANIES — {len(company_searches)} searches")
    comp_slugs_by_search: list[list[str]] = []
    for i, ck in enumerate(company_searches, 1):
        print(f"  [{i}/{len(company_searches)}] {ck}")
        cdata = await _safe_call(
            "search_companies", {"keywords": ck}, timeout=30, weight=1.0,
        )
        if not cdata:
            print("    -> 0 companies")
            comp_slugs_by_search.append([])
            await asyncio.sleep(_jitter(4.0, 6.0))
            continue

        comp_refs = cdata.get("references", {}).get("search_results", [])
        comp_slugs: list[str] = []
        for ref in comp_refs:
            if ref.get("kind") == "company":
                url = ref.get("url", "")
                if url and "/company/" in url:
                    slug = url.rstrip("/").split("/")[-1]
                    if slug not in comp_slugs:
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

        comp_slugs_by_search.append(comp_slugs)
        print(f"    -> {len(comp_slugs)} company slugs")
        await asyncio.sleep(_jitter(4.0, 6.0))

    # ── Fase E — posts + employees per top-3 slug (per search) ─────────
    print(f"\n[MCP/Fase E] COMPANY POSTS + EMPLOYEES")
    for ck, comp_slugs in zip(company_searches, comp_slugs_by_search):
        top_slugs = comp_slugs[:3] if comp_slugs else []
        if not top_slugs:
            continue
        print(f"  search={ck!r}: {len(top_slugs)} slugs")
        for j, slug in enumerate(top_slugs, 1):
            # Company posts
            pdata = await _safe_call(
                "get_company_posts", {"company_name": slug}, timeout=30, weight=1.0,
            )
            ptext = ""
            if pdata:
                sections = pdata.get("sections", {})
                ptext = "\n".join(str(v) for v in sections.values()) if isinstance(sections, dict) else ""
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
                print(f"    [{j}/{len(top_slugs)}] {slug}: {len(unique_urls)} posts")
                for au in _parse_authors_from_text(ptext, "mcp_company"):
                    if au["url"] not in {x.get("url") for x in results["authors"]}:
                        results["authors"].append(au)

            # Company employees
            edata = await _safe_call(
                "get_company_employees", {"company_name": slug}, timeout=30, weight=1.0,
            )
            if edata:
                employees = _parse_employee_refs(edata, slug)
                new_emp = 0
                for emp in employees:
                    emp = _normalize_person(emp)
                    url = emp.get("url") or emp.get("profile_url", "")
                    if url and url not in seen_profiles:
                        seen_profiles.add(url)
                        results["company_employees"].append(emp)
                        new_emp += 1
                print(f"    [{j}/{len(top_slugs)}] {slug}: {new_emp} new employees")
            await asyncio.sleep(_jitter(5.0, 7.0))
        # Cool-down between company searches
        if top_slugs:
            await budget.pause_for(30.0, reason="between-company-slugs")

    # ── Fase F — job_details (top-N jobId enrichment) ────────────────
    if results["jobs"]:
        print(f"\n[MCP/Fase F] JOB_DETAILS — top {min(job_details_cap, len(results['jobs']))}")
        for i, job in enumerate(results["jobs"][:job_details_cap], 1):
            job_id = _extract_job_id_from_item(job)
            if not job_id:
                continue
            print(f"  [{i}/{job_details_cap}] job_id={job_id}")
            detail_data = await _safe_call(
                "get_job_details", {"job_id": job_id}, timeout=30, weight=1.0,
            )
            if detail_data:
                detail = _parse_job_details(detail_data, job_id)
                if detail:
                    detail["search_keyword"] = job.get("search_keyword", "")
                    results["job_details"].append(detail)
            await asyncio.sleep(_jitter(3.0, 5.0))

    # ── Fase G — person_profile (top-N username enrichment) ──────────
    if results["people"]:
        print(f"\n[MCP/Fase G] PERSON_PROFILES — top {min(person_profiles_cap, len(results['people']))}")
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
            pdata = await _safe_call(
                "get_person_profile", {"linkedin_username": username},
                timeout=30, weight=1.0,
            )
            if pdata:
                profile = _parse_person_profile(pdata, username)
                if profile:
                    profile["search_keyword"] = person.get("search_keyword", "")
                    results["person_profiles"].append(profile)
            await asyncio.sleep(_jitter(4.0, 6.0))

    # ── Fase H — company_profile (top-N slug enrichment) ─────────────
    seen_slugs: set[str] = set()
    candidates = list(results["company_search"])[:company_profiles_cap]
    if candidates:
        print(f"\n[MCP/Fase H] COMPANY_PROFILES — top {len(candidates)}")
        for i, comp in enumerate(candidates, 1):
            slug = comp.get("external_id", "")
            if not slug or slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            print(f"  [{i}/{len(candidates)}] slug={slug}")
            cpdata = await _safe_call(
                "get_company_profile", {"company_name": slug}, timeout=30, weight=1.0,
            )
            if cpdata:
                profile = _parse_company_profile(cpdata, slug)
                if profile:
                    results["company_profiles"].append(profile)
            await asyncio.sleep(_jitter(5.0, 7.0))

    cookies: dict[str, str] = {}
    try:
        # Capture cookies before closing — share with Scrapling/Playwright
        try:
            cookies = await asyncio.wait_for(mcp.get_cookies(), timeout=20)
        except Exception:
            cookies = {}
        await mcp.close()
    except Exception:
        pass  # asyncio cancel scope mismatch is harmless at exit

    total = sum(len(v) for v in results.values())
    stats = budget.stats()
    print(f"\n[MCP] TOTAL: {total} items across {len(results)} buckets")
    print(f"[MCP] budget: calls={stats['total_calls']} errors={stats['total_errors']} "
          f"pauses={stats['total_pauses']} peak/min={stats['calls_per_minute_peak']:.1f} "
          f"burst_left={stats['burst_tokens_left']:.1f}/{stats['burst_capacity']} "
          f"hour_left={stats['hourly_tokens_left']:.1f}/{stats['hourly_capacity']}")
    # Side-channel: orchestrator can grab budget via scrape_mcp.last_budget without
    # changing the public tuple signature.
    scrape_mcp.last_budget = budget  # type: ignore[attr-defined]
    return results, cookies


def _to_text(data: dict) -> str:
    """Re-encode a dict response to JSON text for parsers expecting string input."""
    try:
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return str(data)
