"""
linkedin_full_scraper.py — MCP-only LinkedIn scraper (no Playwright).
  - People: MCP search_people → references with /in/ URLs
  - Jobs: MCP search_jobs → references with job URLs
  - Posts: MCP get_feed + get_company_posts
  - Company employees: MCP get_company_employees
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import csv
import sys
from datetime import datetime
from typing import Any

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

OUTPUT_DIR = os.path.join("data", "outputs", "linkedin")
os.makedirs(OUTPUT_DIR, exist_ok=True)

LOCATION = "Buenos Aires, Argentina"
GEO_URN_PBA = "%5B%22103787309%22%5D"

PRIMARY_KEYWORDS = ["web", "SEO", "wordpress", "full-stack", "full stack", "PHP"]

SECONDARY_KEYWORDS = [
    "búsqueda", "oportunidad", "nueva oportunidad", "nueva oportunidad de empleo",
    "estamos buscando", "estamos buscando talento", "manda tu cv", "enviar cv",
    "send your cv", "we're hiring", "we are looking for a",
    "diseñador", "desarrollador", "programador", "analista de sistemas",
]

HASHTAGS = ["empleo", "trabajo", "hiring", "recruitment", "itrecruitment", "talentacquisition"]

_FILTER_KW = [k.lower() for k in SECONDARY_KEYWORDS]
_FILTER_HT = [h.lower().lstrip("#") for h in HASHTAGS]

PEOPLE_KEYWORDS = [
    "IT Recruiter", "Technical Sourcer", "Talent Acquisition Specialist",
    "People & Talent Specialist", "IT Talent Acquisition & HR",
    "Senior Talent Acquisition Specialist", "Selección de Personal IT",
    "RR.HH", "TALENT ACQUISITION", "Recursos Humanos",
    "Responsable de recursos humanos", "Gestión de talento IT",
    "Administración de personal", "HR Leader", "Talent Hunter",
    "Recruiting Specialist Sr", "Hunting Freelance", "Head of HR",
    "HR & Talent Acquisition", "Recruiting", "Talent Management",
    "Reclutamiento de talentos IT", "Gestión de RRHH",
]

COMPANY_SEARCHES = [
    "reclutamiento IT", "recursos humanos Buenos Aires",
    "consultora IT Argentina", "empresa tecnología Buenos Aires",
]


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _save_json(data: list[dict], name: str) -> str:
    path = os.path.join(OUTPUT_DIR, f"{name}_{_ts()}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def _save_csv(data: list[dict], name: str) -> str:
    if not data:
        return ""
    path = os.path.join(OUTPUT_DIR, f"{name}_{_ts()}.csv")
    keys = list(data[0].keys())
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(data)
    return path


def _matches_filter(text: str, primary_kw: str) -> tuple[bool, list[str]]:
    lower = text.lower()
    if primary_kw.lower() not in lower:
        return False, []
    matched = []
    for kw in _FILTER_KW:
        if kw in lower:
            matched.append(kw)
    for tag in _FILTER_HT:
        if f"#{tag}" in lower or tag in lower:
            matched.append(f"#{tag}")
    return len(matched) > 0, matched


# ---------------------------------------------------------------------------
# MCP client — returns full JSON dict (not just text)
# ---------------------------------------------------------------------------

class MCPClient:
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
        self._read_stream, self._write_stream = await self._cm.__aenter__()

        init = types.JSONRPCRequest(
            jsonrpc="2.0", id=1, method="initialize",
            params=types.InitializeRequestParams(
                protocolVersion=types.LATEST_PROTOCOL_VERSION,
                capabilities=types.ClientCapabilities(),
                clientInfo=types.Implementation(name="scraper", version="2.0"),
            ).model_dump(),
        )
        await self._write_stream.send(SessionMessage(message=init))
        await self._read_stream.receive()

    async def call_raw(self, tool_name: str, arguments: dict) -> dict | None:
        """Call MCP tool and return full parsed JSON dict with sections + references."""
        import mcp.types as types
        from mcp.shared.message import SessionMessage

        self._req_id += 1
        req = types.JSONRPCRequest(
            jsonrpc="2.0", id=self._req_id, method="tools/call",
            params={"name": tool_name, "arguments": arguments},
        )
        await self._write_stream.send(SessionMessage(message=req))
        response = await self._read_stream.receive()

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
        """Call MCP tool and return text content only (fallback)."""
        data = await self.call_raw(tool_name, arguments)
        if not data:
            return None
        sections = data.get("sections", {})
        return "\n".join(str(v) for v in sections.values()) if sections else None

    async def close(self):
        if self._cm:
            await self._cm.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# 1. PEOPLE — from MCP search_people references
# ---------------------------------------------------------------------------

def _parse_people_refs(data: dict, keyword: str) -> list[dict[str, Any]]:
    """Extract people from MCP search_people response references."""
    results = []
    refs = data.get("references", {}).get("search_results", [])
    for ref in refs:
        if ref.get("kind") != "person":
            continue
        url = ref.get("url", "")
        if not url or "/in/" not in url:
            continue
        full_url = f"https://www.linkedin.com{url}" if url.startswith("/") else url
        text = ref.get("text", "")
        results.append({
            "type": "person",
            "search_keyword": keyword,
            "name": text,
            "profile_url": full_url,
            "scraped_at": datetime.now().isoformat(),
        })
    return results


def _parse_people_text(text: str, keyword: str) -> list[dict[str, Any]]:
    """Fallback: extract people from plain text (names only, no URLs)."""
    results = []
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for line in lines:
        if any(skip in line.lower() for skip in ["search", "filter", "result", "relevance"]):
            continue
        if len(line) > 5 and not line.startswith("http"):
            results.append({
                "type": "person",
                "search_keyword": keyword,
                "name": line,
                "profile_url": "",
                "scraped_at": datetime.now().isoformat(),
            })
    return results


# ---------------------------------------------------------------------------
# 2. JOBS — from MCP search_jobs references
# ---------------------------------------------------------------------------

def _parse_job_refs(data: dict, keyword: str) -> list[dict[str, Any]]:
    """Extract jobs from MCP search_jobs response references."""
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
            "search_keyword": keyword,
            "title": ref.get("text", ""),
            "job_url": full_url,
            "scraped_at": datetime.now().isoformat(),
        })
    return results


# ---------------------------------------------------------------------------
# 3. POSTS — from MCP get_feed / get_company_posts references
# ---------------------------------------------------------------------------

def _parse_post_refs(data: dict, source: str, company: str = "") -> list[dict[str, Any]]:
    """Extract posts from MCP feed/company_posts response references."""
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
            "post_url": full_url,
            "title": ref.get("text", ""),
            "company_name": company,
            "scraped_at": datetime.now().isoformat(),
        })
    return results


def _parse_author_refs(data: dict, source: str) -> list[dict[str, Any]]:
    """Extract author profile URLs from feed/company_posts references."""
    results = []
    refs = data.get("references", {}).get("search_results", []) or \
           data.get("references", {}).get("feed", [])
    for ref in refs:
        if ref.get("kind") != "person":
            continue
        url = ref.get("url", "")
        if not url or "/in/" not in url:
            continue
        full_url = f"https://www.linkedin.com{url}" if url.startswith("/") else url
        results.append({
            "profile_url": full_url,
            "name": ref.get("text", ""),
            "source": source,
        })
    return results


# ---------------------------------------------------------------------------
# 4. COMPANY EMPLOYEES — from MCP get_company_employees references
# ---------------------------------------------------------------------------

def _parse_employee_refs(data: dict, company: str) -> list[dict[str, Any]]:
    """Extract employee profile URLs from MCP get_company_employees response."""
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
            "search_keyword": company,
            "name": ref.get("text", ""),
            "profile_url": full_url,
            "source": "company_employees",
            "scraped_at": datetime.now().isoformat(),
        })
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_all():
    all_results: dict[str, list] = {
        "people": [], "jobs": [], "posts_feed": [],
        "posts_companies": [], "authors": [],
    }

    mcp = MCPClient()
    print("[*] Connecting to MCP server...")
    await mcp.connect()
    print("[OK] MCP connected.\n")

    # --- 1. PEOPLE (MCP search_people with references) ---
    print("=" * 60)
    print(f"[1/4] RECRUITER PROFILES — {len(PEOPLE_KEYWORDS)} keywords (MCP)")
    print("=" * 60)
    seen_profiles: set[str] = set()
    for i, kw in enumerate(PEOPLE_KEYWORDS, 1):
        print(f"  [{i}/{len(PEOPLE_KEYWORDS)}] {kw}")
        data = await mcp.call_raw("search_people", {
            "keywords": kw, "location": LOCATION,
        })
        if data:
            people = _parse_people_refs(data, kw)
            # Fallback to text parsing if no references
            if not people:
                sections = data.get("sections", {})
                text = sections.get("search_results", "")
                if text:
                    people = _parse_people_text(text, kw)
            new = 0
            for person in people:
                url = person.get("profile_url", "")
                if url and url not in seen_profiles:
                    seen_profiles.add(url)
                    all_results["people"].append(person)
                    new += 1
                elif not url:
                    all_results["people"].append(person)
            print(f"    -> {new} new profiles (refs: {len(people)})")
        else:
            print("    -> 0 (no data)")
        await asyncio.sleep(1.5)

    # --- 2. JOBS (MCP search_jobs with references) ---
    print(f"\n{'=' * 60}")
    print(f"[2/4] JOBS — {len(PRIMARY_KEYWORDS)} keywords (MCP)")
    print("=" * 60)
    seen_jobs: set[str] = set()
    for i, kw in enumerate(PRIMARY_KEYWORDS, 1):
        print(f"  [{i}/{len(PRIMARY_KEYWORDS)}] {kw}")
        data = await mcp.call_raw("search_jobs", {
            "keywords": kw, "location": LOCATION,
            "date_posted": "past_week", "sort_by": "date",
        })
        if data:
            jobs = _parse_job_refs(data, kw)
            new = 0
            for job in jobs:
                url = job["job_url"]
                if url not in seen_jobs:
                    seen_jobs.add(url)
                    all_results["jobs"].append(job)
                    new += 1
            print(f"    -> {new} new jobs")
        else:
            print("    -> 0")
        await asyncio.sleep(1)

    # --- 3. FEED POSTS (MCP get_feed) ---
    print(f"\n{'=' * 60}")
    print("[3/4] FEED POSTS (MCP)")
    print("=" * 60)
    data = await mcp.call_raw("get_feed", {"num_posts": 50})
    if data:
        posts = _parse_post_refs(data, "feed")
        authors = _parse_author_refs(data, "feed")
        for p in posts:
            all_results["posts_feed"].append(p)
        for a in authors:
            url = a["profile_url"]
            if url not in seen_profiles:
                seen_profiles.add(url)
                all_results["authors"].append(a)
        print(f"  -> {len(posts)} posts, {len(authors)} authors")
    else:
        print("  -> 0")

    # --- 4. COMPANY POSTS + EMPLOYEES (MCP) ---
    print(f"\n{'=' * 60}")
    print(f"[4/4] COMPANY POSTS + EMPLOYEES — {len(COMPANY_SEARCHES)} searches (MCP)")
    print("=" * 60)
    for i, ck in enumerate(COMPANY_SEARCHES, 1):
        print(f"  [{i}/{len(COMPANY_SEARCHES)}] {ck}")
        cdata = await mcp.call_raw("search_companies", {"keywords": ck})
        if not cdata:
            print("    -> 0 companies")
            continue
        comp_refs = cdata.get("references", {}).get("search_results", [])
        comp_names = []
        for ref in comp_refs:
            if ref.get("kind") == "company":
                text = ref.get("text", "")
                if text:
                    comp_names.append(text)
        if not comp_names:
            # Fallback to text extraction
            text = cdata.get("sections", {}).get("search_results", "")
            comp_names = re.findall(r'\*\*([^*]+)\*\*', text)[:5]
        print(f"    -> {len(comp_names)} companies")
        for cname in comp_names[:5]:
            # Company posts
            ptext = await mcp.call_text("get_company_posts", {"company_name": cname})
            if ptext:
                posts = _extract_post_urls_from_text(ptext)
                for u in posts:
                    all_results["posts_companies"].append({
                        "type": "post_company", "post_url": u,
                        "company_name": cname,
                        "scraped_at": datetime.now().isoformat(),
                    })
                print(f"      {cname}: {len(posts)} posts")
            # Company employees
            edata = await mcp.call_raw("get_company_employees", {"company_name": cname})
            if edata:
                employees = _parse_employee_refs(edata, cname)
                for emp in employees:
                    url = emp["profile_url"]
                    if url and url not in seen_profiles:
                        seen_profiles.add(url)
                        all_results["authors"].append({"profile_url": url, "name": emp["name"], "source": "company"})
                print(f"      {cname}: {len(employees)} employees")
            await asyncio.sleep(1)

    await mcp.close()

    # --- Save ---
    print(f"\n{'=' * 60}")
    print("SAVING RESULTS")
    print("=" * 60)

    for cat, items in all_results.items():
        if items:
            p1 = _save_json(items, cat)
            p2 = _save_csv(items, cat)
            print(f"  {cat}: {len(items)} items -> {p1}")

    combined_path = os.path.join(OUTPUT_DIR, f"all_results_{_ts()}.json")
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"  combined -> {combined_path}")

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print("=" * 60)
    total = 0
    for cat, items in all_results.items():
        print(f"  {cat}: {len(items)}")
        total += len(items)
    print(f"  TOTAL: {total}")
    print(f"  Unique profiles: {len(seen_profiles)}")
    print("=" * 60)


def _extract_post_urls_from_text(text: str) -> list[str]:
    urls = re.findall(
        r'https?://www\.linkedin\.com/feed/update/urn:li:[^\s\)\"\'<>]+|'
        r'https?://www\.linkedin\.com/posts/[^\s\)\"\'<>]+',
        text,
    )
    return list(dict.fromkeys(u.split("?")[0] for u in urls))


if __name__ == "__main__":
    asyncio.run(run_all())
