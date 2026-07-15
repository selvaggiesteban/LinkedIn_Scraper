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
                clientInfo=types.Implementation(name="scraper-v2", version="2.0"),
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
            "scraped_at": datetime.now().isoformat(),
        })
    return results


async def scrape_mcp(
    people_keywords: list[str],
    company_searches: list[str],
    location: str,
    delay: float = 1.5,
) -> dict[str, list[dict[str, Any]]]:
    """Run all MCP searches: people, feed, company posts, employees."""
    results: dict[str, list] = {
        "people": [], "posts_feed": [], "posts_companies": [],
        "authors": [], "company_employees": [],
    }

    mcp = MCPClient()
    print(f"\n{'=' * 60}")
    print(f"[MCP] Connecting...")
    await mcp.connect()
    print("[MCP] Connected.\n")

    # --- PEOPLE ---
    print(f"[MCP] PEOPLE — {len(people_keywords)} keywords")
    seen_profiles: set[str] = set()
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
                url = person.get("profile_url", "")
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
        results["posts_feed"] = posts
        print(f"  -> {len(posts)} posts")

    # --- COMPANY POSTS + EMPLOYEES ---
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
                    results["posts_companies"].append({
                        "type": "post_company",
                        "source": "mcp",
                        "post_url": u,
                        "company_name": slug,
                        "scraped_at": datetime.now().isoformat(),
                    })
                print(f"      {slug}: {len(unique_urls)} posts")

            # Company employees
            edata = await mcp.call_raw("get_company_employees", {"company_name": slug})
            if edata:
                employees = _parse_employee_refs(edata, slug)
                for emp in employees:
                    url = emp["profile_url"]
                    if url and url not in seen_profiles:
                        seen_profiles.add(url)
                        results["company_employees"].append(emp)
                print(f"      {slug}: {len(employees)} employees")
            await asyncio.sleep(delay)

    await mcp.close()

    total = sum(len(v) for v in results.values())
    print(f"\n[MCP] TOTAL: {total} items")
    return results
