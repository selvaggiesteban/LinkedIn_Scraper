"""
mcp_subprocess.py — Subprocess-isolated MCP calls.

Each MCP call runs in a fresh Python process, providing:
  - Process-level crash isolation (one bad call doesn't kill the session)
  - Hard OS-level timeout enforcement (asyncio.wait_for can be circumvented)
  - Memory leak isolation (each call gets a fresh process)

Use as a fallback when the persistent MCPClient proves unstable.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any


def run_mcp_call(
    tool_name: str,
    arguments: dict,
    timeout: float = 30,
) -> dict | None:
    """Run a single MCP tool call in an isolated subprocess.

    Returns the parsed JSON response, or None on failure.
    """
    script = f'''
import sys, os, json, asyncio
os.environ["PYTHONIOENCODING"] = "utf-8"
from mcp.client.stdio import stdio_client
from mcp import StdioServerParameters
import mcp.types as types
from mcp.shared.message import SessionMessage

async def main():
    server_params = StdioServerParameters(
        command="mcp-server-linkedin", args=[],
        env={{"UV_HTTP_TIMEOUT": "300"}},
    )
    async with stdio_client(server_params) as (read_stream, write_stream):
        # Initialize
        init = types.JSONRPCRequest(
            jsonrpc="2.0", id=1, method="initialize",
            params=types.InitializeRequestParams(
                protocolVersion=types.LATEST_PROTOCOL_VERSION,
                capabilities=types.ClientCapabilities(),
                clientInfo=types.Implementation(name="scraper-subprocess", version="1.0"),
            ).model_dump(),
        )
        await write_stream.send(SessionMessage(message=init))
        await asyncio.wait_for(read_stream.receive(), timeout=15)

        # Call tool
        req = types.JSONRPCRequest(
            jsonrpc="2.0", id=2, method="tools/call",
            params={{"name": "{tool_name}", "arguments": {json.dumps(arguments)}}},
        )
        await write_stream.send(SessionMessage(message=req))
        response = await asyncio.wait_for(read_stream.receive(), timeout={timeout})

        inner = response
        while hasattr(inner, "message") and inner.message is not None:
            inner = inner.message
        while hasattr(inner, "root") and inner.root is not None:
            inner = inner.root

        if hasattr(inner, "error") and inner.error is not None:
            err_msg = inner.error.message if hasattr(inner.error, "message") else str(inner.error)
            sys.exit(1)

        if hasattr(inner, "result") and inner.result is not None:
            content = inner.result.get("content", [])
            for item in content:
                t = item.get("text", "") if isinstance(item, dict) else getattr(item, "text", "")
                if t:
                    print(t)
                    return

asyncio.run(main())
'''
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=timeout + 10,  # extra buffer for process startup
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None

    if result.returncode != 0:
        return None

    # Parse JSON from stdout (scan line-by-line for valid JSON)
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if line.startswith("{") or line.startswith("["):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None
