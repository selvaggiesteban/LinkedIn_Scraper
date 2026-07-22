"""
test_mcp_single.py — Smoke test for the LinkedIn MCP connection.

Verifies that:
  1. The linkedin_scraper package imports cleanly from the src/ layout.
  2. MCPClient can be instantiated.
  3. If a session is alive, search_people returns parseable results.

Run:
    pytest tests/test_mcp_single.py -v
    python tests/test_mcp_single.py        # direct call (manual smoke)

Note: This test is marked as `mcp` so it can be skipped in CI without a live
session via: pytest -m "not mcp"
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure src/ is on path even when invoked directly (non-pytest)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest


def test_package_imports():
    """The linkedin_scraper package and its MCP-client submodule must import."""
    from linkedin_scraper.sources.mcp_client import MCPClient, _parse_people_refs
    assert MCPClient is not None
    assert callable(_parse_people_refs)


def test_mcp_client_instantiation():
    """MCPClient can be instantiated without connect."""
    from linkedin_scraper.sources.mcp_client import MCPClient
    client = MCPClient()
    assert client is not None


@pytest.mark.mcp
def test_mcp_search_people_smoke():
    """End-to-end smoke against a live MCP server (requires login)."""
    from linkedin_scraper.sources.mcp_client import (
        MCPClient,
        _parse_people_refs,
    )

    async def _run():
        mcp = MCPClient()
        try:
            await mcp.connect()
            data = await mcp.call_raw(
                "search_people",
                {"keywords": "IT Recruiter", "location": "Buenos Aires, Argentina"},
                timeout=30,
            )
            if data is None:
                pytest.skip("MCP session not alive (login required) — run auth_assistant.py first")
            people = _parse_people_refs(data, "IT Recruiter")
            assert isinstance(people, list)
            return people
        finally:
            try:
                await mcp.close()
            except Exception:
                pass

    people = asyncio.run(_run())
    assert isinstance(people, list)


if __name__ == "__main__":
    # Manual smoke fallback (preserves the original behavior of test_mcp_single)
    from linkedin_scraper.sources.mcp_client import MCPClient, _parse_people_refs

    async def main():
        mcp = MCPClient()
        print("Connecting…")
        await mcp.connect()
        print("Connected. Calling search_people…")
        data = await mcp.call_raw(
            "search_people",
            {"keywords": "IT Recruiter", "location": "Buenos Aires, Argentina"},
        )
        if data:
            people = _parse_people_refs(data, "IT Recruiter")
            print(f"Got {len(people)} people")
            for p in people[:3]:
                print(f"  {p.get('name', '?')}")
        else:
            print("No data — session may not be authenticated")
        await mcp.close()
        print("Done")

    asyncio.run(main())
