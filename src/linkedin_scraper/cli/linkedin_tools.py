"""
linkedin_tools.py — Unified CLI for stickerdaniel/linkedin-mcp-server.
Sub-comandos: people, search-companies, company, company-posts, jobs, jobs-detail,
              feed, view-profile, connect, message, inbox
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Sequence

if sys.platform == 'win32':
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# (legacy site-packages path removed; install mcp via requirements.txt)

from mcp.client.stdio import stdio_client
from mcp import StdioServerParameters
import mcp.types as types
from mcp.shared.message import SessionMessage

from ..parsers import linkedin_parser as lp

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OUTPUT_DIR = os.path.join("data", "outputs", "linkedin")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# MCP helpers
# ---------------------------------------------------------------------------

def _init_mcp() -> tuple[Any, Any]:
    """Return (read_stream, write_stream) via stdio_client."""
    server_params = StdioServerParameters(
        command="uvx",
        args=["mcp-server-linkedin@latest"],
        env={"UV_HTTP_TIMEOUT": "300"}
    )
    return stdio_client(server_params)


async def _send_init(read_stream, write_stream) -> bool:
    init = types.JSONRPCRequest(
        jsonrpc="2.0", id=1, method="initialize",
        params=types.InitializeRequestParams(
            protocolVersion=types.LATEST_PROTOCOL_VERSION,
            capabilities=types.ClientCapabilities(),
            clientInfo=types.Implementation(name="linkedin_tools", version="0.1.0"),
        ).model_dump()
    )
    await write_stream.send(SessionMessage(message=init))
    resp = await read_stream.receive()
    return not isinstance(resp, Exception)


async def _call_tool(read_stream, write_stream, request_id: int, name: str, arguments: dict[str, Any], *, retries: int = 3):
    """Generic tool caller with retry."""
    req = types.JSONRPCRequest(
        jsonrpc="2.0", id=request_id, method="tools/call",
        params={"name": name, "arguments": arguments}
    )
    last_err = "Unknown error"
    for attempt in range(1, retries + 1):
        await write_stream.send(SessionMessage(message=req))
        response = await read_stream.receive()

        if isinstance(response, Exception):
            last_err = str(response)
            time.sleep(2 * attempt)
            continue

        inner = lp._unwrap(response)
        if hasattr(inner, 'error') and inner.error is not None:
            last_err = str(inner.error)
            time.sleep(2 * attempt)
            continue

        if not hasattr(inner, 'result') or inner.result is None:
            last_err = "No result in response"
            time.sleep(2 * attempt)
            continue

        result = inner.result
        if not isinstance(result, dict) or 'content' not in result:
            last_err = f"Unexpected result format: {type(result)}"
            time.sleep(2 * attempt)
            continue

        content = result['content']
        if not content:
            last_err = "Empty content"
            time.sleep(2 * attempt)
            continue

        for item in content:
            text = item.get('text', '') if isinstance(item, dict) else getattr(item, 'text', '')
            if not text:
                continue
            lower = text.lower()
            if "setup is not complete yet" in lower or "downloading" in lower:
                last_err = "SETUP_PENDING"
                break
            if "login is still in progress" in lower or "authenticationinprogresserror" in lower:
                last_err = "LOGIN_REQUIRED"
                break
            return text, None

        if last_err in ("SETUP_PENDING", "LOGIN_REQUIRED"):
            if last_err == "SETUP_PENDING":
                wait = 15 * attempt
                print(f"  Server setting up… waiting {wait}s")
                await asyncio.sleep(wait)
            else:
                return None, "LOGIN_REQUIRED"
        else:
            time.sleep(2 * attempt)

    return None, last_err


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _save_output(data: Sequence[dict[str, Any]], sub: str, ext: str = "json") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(OUTPUT_DIR, f"{sub}_{ts}.{ext}")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


# ---------------------------------------------------------------------------
# Sub-command handlers
# ---------------------------------------------------------------------------

async def cmd_people(args: argparse.Namespace) -> int:
    async with _init_mcp() as (read_stream, write_stream):
        if not await _send_init(read_stream, write_stream):
            print("[ERR] MCP init failed")
            return 1

        arguments = {"keywords": args.keywords}
        if args.location:
            arguments["location"] = args.location
        if args.connection_degree:
            arguments["connection_degree"] = args.connection_degree
        if args.max_pages:
            arguments["max_pages"] = args.max_pages

        text, err = await _call_tool(read_stream, write_stream, 2, "search_people", arguments)
        if err:
            print(f"[ERR] search_people: {err}")
            return 1

        # Basic parse from text sections
        try:
            data = json.loads(text or '{}')
        except json.JSONDecodeError:
            data = {}
        search_text = data.get('sections', {}).get('search_results', text or '')
        lines = lp._extract_listing_lines(search_text)
        clean = [l for l in lines if not lp._is_noise(l)]
        people: list[dict[str, Any]] = []
        i = 0
        while i < len(clean):
            # very heuristic: name | headline | location on consecutive lines
            if i + 1 < len(clean) and (clean[i + 1].startswith('Ingenier') or clean[i + 1].startswith('Software') or clean[i + 1].startswith('Developer')):
                people.append({"name": clean[i], "headline": clean[i+1], "location": clean[i+2] if i+2 < len(clean) and lp._is_location(clean[i+2]) else ""})
                i += 2
            else:
                people.append({"name": clean[i], "headline": "", "location": ""})
                i += 1

        # Also use references if present
        refs = data.get('references', {}).get('search_results', [])
        for ref in refs:
            if ref.get('kind') == 'person':
                url = ref.get('url', '')
                text_r = ref.get('text', '')
                # Try to match/add
                found = False
                for p in people:
                    if p['name'] in text_r or text_r in p['name']:
                        found = True
                        break
                if not found:
                    people.append({"name": text_r, "headline": "", "location": "", "url": url})

        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(people, f, ensure_ascii=False, indent=2)
            path = args.output
        else:
            path = os.path.join(OUTPUT_DIR, f"people_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(people, f, ensure_ascii=False, indent=2)

        print(f"[OK] {len(people)} personas encontradas → {path}")
        for p in people[:10]:
            print(f"  • {p['name']} — {p['headline']} — {p['location']}")
        return 0


async def cmd_search_companies(args: argparse.Namespace) -> int:
    async with _init_mcp() as (read_stream, write_stream):
        if not await _send_init(read_stream, write_stream):
            print("[ERR] MCP init failed")
            return 1

        text, err = await _call_tool(read_stream, write_stream, 2, "search_companies", {"keywords": args.keywords})
        if err:
            print(f"[ERR] search_companies: {err}")
            return 1

        try:
            data = json.loads(text or '{}')
        except json.JSONDecodeError:
            data = {}

        companies: list[dict[str, Any]] = []
        for ref in data.get('references', {}).get('search_results', []):
            if ref.get('kind') == 'company':
                companies.append({"name": ref.get('text', ''), "url": ref.get('url', '')})

        path = _save_output(companies, "companies")
        print(f"[OK] {len(companies)} empresas → {path}")
        for c in companies[:10]:
            print(f"  • {c['name']}")
        return 0


async def cmd_company_profile(args: argparse.Namespace) -> int:
    async with _init_mcp() as (read_stream, write_stream):
        if not await _send_init(read_stream, write_stream):
            print("[ERR] MCP init failed")
            return 1

        text, err = await _call_tool(read_stream, write_stream, 2, "get_company_profile", {"url": args.url})
        if err:
            print(f"[ERR] get_company_profile: {err}")
            return 1

        # Save raw for now
        data = json.loads(text or '{}')
        path = _save_output([data], "company")
        print(f"[OK] perfil empresa → {path}")
        return 0


async def cmd_company_posts(args: argparse.Namespace) -> int:
    async with _init_mcp() as (read_stream, write_stream):
        if not await _send_init(read_stream, write_stream):
            print("[ERR] MCP init failed")
            return 1

        text, err = await _call_tool(read_stream, write_stream, 2, "get_company_posts", {"url": args.url})
        if err:
            print(f"[ERR] get_company_posts: {err}")
            return 1

        data = json.loads(text or '{}')
        path = _save_output([data], "company_posts")
        print(f"[OK] publicaciones empresa → {path}")
        return 0


async def cmd_jobs(args: argparse.Namespace) -> int:
    keyword_groups = [k.strip() for k in args.keywords.split(',')] if ',' in args.keywords else [args.keywords]
    all_jobs: list[dict[str, Any]] = []

    async with _init_mcp() as (read_stream, write_stream):
        if not await _send_init(read_stream, write_stream):
            print("[ERR] MCP init failed")
            return 1

        req_id = 2
        for kw in keyword_groups:
            print(f"[SEARCH] {kw}")
            arguments: dict[str, Any] = {
                "keywords": kw,
                "work_type": "remote,on_site",
                "max_pages": 1,
                "date_posted": args.date_posted or "past_week",
                "sort_by": args.sort_by or "date",
            }
            if args.location:
                arguments["location"] = args.location

            text, err = await _call_tool(read_stream, write_stream, req_id, "search_jobs", arguments)
            req_id += 1
            if err:
                print(f"  [ERR] {err}")
                continue

            jobs = lp.parse_single_response(text or '')
            if jobs:
                print(f"  [OK] {len(jobs)} jobs")
                all_jobs.extend(jobs)
            else:
                print(f"  [WARN] No parseable jobs")

    unique = lp.deduplicate_jobs(all_jobs)
    if args.output:
        path = args.output
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(unique, f, ensure_ascii=False, indent=2)
    else:
        path = _save_output(unique, "jobs")

    print(f"\n[OK] {len(unique)} unique jobs saved → {path}")
    for j in unique[:10]:
        print(f"  • {j['title']} | {j['companyName']} | {j['location']}")
    return 0


async def cmd_jobs_detail(args: argparse.Namespace) -> int:
    async with _init_mcp() as (read_stream, write_stream):
        if not await _send_init(read_stream, write_stream):
            print("[ERR] MCP init failed")
            return 1

        text, err = await _call_tool(read_stream, write_stream, 2, "get_job_details", {"job_id": args.job_id})
        if err:
            print(f"[ERR] get_job_details: {err}")
            return 1

        data = json.loads(text or '{}')
        path = os.path.join(OUTPUT_DIR, f"job_{args.job_id}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[OK] Detalle job {args.job_id} → {path}")
        return 0


async def cmd_feed(args: argparse.Namespace) -> int:
    async with _init_mcp() as (read_stream, write_stream):
        if not await _send_init(read_stream, write_stream):
            print("[ERR] MCP init failed")
            return 1

        text, err = await _call_tool(read_stream, write_stream, 2, "get_feed", {})
        if err:
            print(f"[ERR] get_feed: {err}")
            return 1

        data = json.loads(text or '{}')
        path = _save_output([data], "feed")
        print(f"[OK] Feed guardado → {path}")
        return 0


async def cmd_view_profile(args: argparse.Namespace) -> int:
    async with _init_mcp() as (read_stream, write_stream):
        if not await _send_init(read_stream, write_stream):
            print("[ERR] MCP init failed")
            return 1

        text, err = await _call_tool(read_stream, write_stream, 2, "get_person_profile", {"username": args.username})
        if err:
            print(f"[ERR] get_person_profile: {err}")
            return 1

        data = json.loads(text or '{}')
        path = os.path.join(OUTPUT_DIR, f"profile_{args.username}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[OK] Perfil @{args.username} → {path}")
        return 0


async def cmd_connect(args: argparse.Namespace) -> int:
    print(f"You are about to send a connection request to @{args.username}.")
    print(f"Note: {args.note[:80]}...")
    confirm = input("Confirm? [y/N]: ").strip().lower()
    if confirm not in ('y', 'yes', 's', 'si'):
        print("Cancelled")
        return 0

    async with _init_mcp() as (read_stream, write_stream):
        if not await _send_init(read_stream, write_stream):
            print("[ERR] MCP init failed")
            return 1

        text, err = await _call_tool(read_stream, write_stream, 2, "connect_with_person", {
            "username": args.username,
            "note": args.note,
        })
        if err:
            print(f"[ERR] connect_with_person: {err}")
            return 1

        print(f"[OK] Connection request sent to @{args.username}")
        return 0


async def cmd_message(args: argparse.Namespace) -> int:
    print(f"You are about to send a message to @{args.username}.")
    print(f"Body: {args.body[:80]}...")
    confirm = input("Confirm? [y/N]: ").strip().lower()
    if confirm not in ('y', 'yes', 's', 'si'):
        print("Cancelled")
        return 0

    async with _init_mcp() as (read_stream, write_stream):
        if not await _send_init(read_stream, write_stream):
            print("[ERR] MCP init failed")
            return 1

        text, err = await _call_tool(read_stream, write_stream, 2, "send_message", {
            "username": args.username,
            "body": args.body,
        })
        if err:
            print(f"[ERR] send_message: {err}")
            return 1

        print(f"[OK] Message sent to @{args.username}")
        return 0


async def cmd_inbox(args: argparse.Namespace) -> int:
    async with _init_mcp() as (read_stream, write_stream):
        if not await _send_init(read_stream, write_stream):
            print("[ERR] MCP init failed")
            return 1

        text, err = await _call_tool(read_stream, write_stream, 2, "get_inbox", {})
        if err:
            print(f"[ERR] get_inbox: {err}")
            return 1

        data = json.loads(text or '{}')
        path = _save_output([data], "inbox")
        print(f"[OK] Inbox → {path}")
        return 0


async def cmd_login(args: argparse.Namespace) -> int:
    print("[INFO] Triggering LinkedIn login flow...")
    print("If a browser doesn't open, run manually:")
    print("  uvx --from mcp-server-linkedin mcp-server-linkedin --login")
    # Try to trigger close_session to force re-auth
    try:
        async with _init_mcp() as (read_stream, write_stream):
            await _send_init(read_stream, write_stream)
            text, err = await _call_tool(read_stream, write_stream, 2, "close_session", {})
            if err:
                print(f"[INFO] close_session: {err}")
            else:
                print("[OK] Session closed. Re-run to authenticate.")
    except Exception as e:
        print(f"[ERR] {e}")
    return 0


# ---------------------------------------------------------------------------
# CLI setup
# ---------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="linkedin_tools.py", description="LinkedIn MCP CLI — stickerdaniel/linkedin-mcp-server")
    sub = parser.add_subparsers(dest="command", required=True)

    # people
    p_people = sub.add_parser("people", help="Buscar perfiles de personas")
    p_people.add_argument("--keywords", required=True, help="Palabras clave")
    p_people.add_argument("--location", default="", help="Ubicación")
    p_people.add_argument("--connection-degree", default="", help="Grado de conexión")
    p_people.add_argument("--max-pages", type=int, default=1, help="Max páginas")
    p_people.add_argument("--output", default="", help="Archivo de salida")

    # search-companies
    p_sc = sub.add_parser("search-companies", help="Buscar empresas")
    p_sc.add_argument("--keywords", required=True, help="Palabras clave")

    # company
    p_co = sub.add_parser("company", help="Ver perfil de empresa")
    p_co.add_argument("--url", required=True, help="LinkedIn company URL")

    # company-posts
    p_cp = sub.add_parser("company-posts", help="Ver publicaciones de empresa")
    p_cp.add_argument("--url", required=True, help="LinkedIn company URL")

    # jobs
    p_jobs = sub.add_parser("jobs", help="Buscar empleos")
    p_jobs.add_argument("--keywords", required=True, help="Palabras clave (coma-separated for multiples)")
    p_jobs.add_argument("--location", default="", help="Ubicación")
    p_jobs.add_argument("--date-posted", default="past_week", help="Filtro fecha")
    p_jobs.add_argument("--sort-by", default="date", help="Ordenamiento")
    p_jobs.add_argument("--output", default="", help="Archivo JSON de salida")

    # jobs-detail
    p_jd = sub.add_parser("jobs-detail", help="Detalle de un empleo")
    p_jd.add_argument("--job-id", required=True, help="LinkedIn Job ID")

    # feed
    sub.add_parser("feed", help="Ver feed personal")

    # view-profile
    p_vp = sub.add_parser("view-profile", help="Ver perfil de persona")
    p_vp.add_argument("--username", required=True, help="LinkedIn username (e.g. vanesapaz)")

    # connect
    p_con = sub.add_parser("connect", help="Enviar solicitud de conexión")
    p_con.add_argument("--username", required=True, help="LinkedIn username")
    p_con.add_argument("--note", default="", help="Nota personalizada")

    # message
    p_msg = sub.add_parser("message", help="Enviar mensaje directo")
    p_msg.add_argument("--username", required=True, help="LinkedIn username")
    p_msg.add_argument("--body", required=True, help="Contenido del mensaje")

    # inbox
    sub.add_parser("inbox", help="Ver inbox/conversaciones")

    # login
    sub.add_parser("login", help="Forzar re-login manual en LinkedIn")

    args = parser.parse_args(argv)

    # Dispatch
    handlers: dict[str, Any] = {
        "people": cmd_people,
        "search-companies": cmd_search_companies,
        "company": cmd_company_profile,
        "company-posts": cmd_company_posts,
        "jobs": cmd_jobs,
        "jobs-detail": cmd_jobs_detail,
        "feed": cmd_feed,
        "view-profile": cmd_view_profile,
        "connect": cmd_connect,
        "message": cmd_message,
        "inbox": cmd_inbox,
        "login": cmd_login,
    }

    if args.command not in handlers:
        parser.print_help()
        return 1

    return asyncio.run(handlers[args.command](args))


if __name__ == "__main__":
    sys.exit(main())
