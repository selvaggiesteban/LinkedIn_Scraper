# LinkedIn Scraper

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![es-AR](https://img.shields.io/badge/README-También%20en%20Español%20(Argentina)-blue?style=flat-square)](README.es-AR.md)

> Multi-method employment-focused LinkedIn scraper (Guest API + MCP + Scrapling + OCR) with employment-intent validation, cross-source deduplication, and unified Excel export.

🇦🇷 **[Versión en español (Argentina)](README.es-AR.md)** — README completo en español rioplatense.

---

## Coverage Inventory

The 4 scraping methods ("vías") cover **all 10 LinkedIn search categories** at maximum capacity. Categories requiring login are covered via the authenticated MCP session, shared with Scrapling and OCR via cookies.

| Category | Vía 1 Guest API<br>(HTTP, no login) | Vía 2 MCP<br>(auth ✅) | Vía 3 Scrapling<br>(auth ✅) | Vía 4 OCR<br>(auth ✅) |
|---|:---:|:---:|:---:|:---:|
| `jobs` | ✅ `seeMoreJobPostings` (public) | ✅ `search_jobs` | ✅ `/jobs/view/<id>` with login | ✅ enriches |
| `job_details` | ❌ login required | ✅ `get_job_details` | ✅ `/jobs/view/<id>` full text | ✅ enriches |
| `people` | ❌ auth needed | ✅ `search_people` | ✅ `/in/<username>` with login | ✅ enriches |
| `person_profiles` | ❌ | ✅ `get_person_profile` | ✅ `/in/<username>` full text | ✅ enriches |
| `posts_feed` | ❌ private feed | ✅ `get_feed` | ✅ feed with login | ✅ enriches |
| `posts_companies` | ❌ | ✅ `get_company_posts` | ✅ `/company/<slug>/posts` with login | ✅ enriches |
| `company_search` | ❌ | ✅ `search_companies` (persisted) | ❌ | ❌ N/A |
| `company_profiles` | ✅ `/company/<slug>/about` (public) | ✅ `get_company_profile` | ✅ `/company/<slug>/about` with login | ✅ enriches |
| `company_employees` | ❌ auth | ✅ `get_company_employees` | ✅ `/company/<slug>/people` with login | ❌ N/A |
| `authors` | ❌ | ✅ derived from feed/posts | ✅ derivable | ❌ N/A |
| **Totals** | **2/10** | **10/10** | **10/10** | **10/10** |

**Combined coverage:** all 10 categories have 1-4 producing sources for cross-source deduplication.

## Features

- 🚀 **4 scraping methods** working in concert: Guest API (no-login), MCP server (auth), Scrapling (anti-bot), OCR (text enrichment)
- 🎯 **10 categories** with full coverage (jobs, job_details, people, person_profiles, posts_feed, posts_companies, company_search, company_profiles, company_employees, authors)
- 🛡️ **Anti-ban measures**: 8-UA rotation, optional proxy rotation (swiftshadow free / Webshare paid), randomized delays 0.5-1.5s, MCP call caps
- ✅ **Employment-intent validation**: primary keyword AND (secondary keyword OR hashtag) must appear in text
- 🧹 **Cross-source deduplication**: URL dedup + fuzzy name matching (`difflib.SequenceMatcher`)
- 📊 **Unified Excel export**: 1 workbook / 11 sheets (1 README + 10 categories) + flat CSV fallback
- 🔐 **One-time interactive auth assistant** (`python auth_assistant.py` or `./setup.ps1`)
- 🌐 **Bilingual README** (English + español argentino variant)

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt
playwright install chromium
uv tool install mcp-server-linkedin

# 2. One-time login (interactive)
python auth_assistant.py
# or on Windows:
./setup.ps1

# 3. Run the scraper (all 4 methods, full coverage)
python linkedin_scraper.py

# 4. Deliverables in output/
#    - LinkedIn_Scraper_<ts>.xlsx   (Excel with 11 sheets)
#    - LinkedIn_Scraper_<ts>.csv    (flat CSV, all categories)
#    - all_results_<ts>.json       (raw JSON with stats)
```

## Authentication Guide

Two authentication worlds:

| Mechanism | Used by | Requirement |
|---|---|---|
| **No login** (Guest API) | Vía 1: `/jobs-guest/...`, `/company/<slug>/about` (public) | None |
| **With login** (persistent session) | Vías 2, 3, 4 | One-time interactive authentication via the auth assistant |

### One session — three channels sharing it

The `mcp-server-linkedin` maintains a single browser session internally. Vías 2, 3, and 4 connect to that same session without re-authenticating:

```
User (1 time) → opens Chrome → signs in to linkedin.com → manual login
                                            │
                            mcp-server-linkedin stores cookies in its own storage
                                            │
                ┌───────────────────────────┼──────────────┐
                │                           │              │
            Vía 2 MCP               Vía 3 Scrapling    Vía 4 OCR
            (JSON-RPC)              (reuses cookies)   (reuses cookies)
```

### Auth flow (one time)

`auth_assistant.py` runs this sequence:

1. **Preflight** — checks Python≥3.11, `uv`, `mcp-server-linkedin` are on PATH; auto-installs the MCP server if missing
2. **Probe session** — tries `MCPClient.connect()` + `get_feed`; if it returns content, the session is already alive → exit 0
3. **Login** — prints "Opening Chrome for LinkedIn login", waits for Enter, spawns `uvx --from mcp-server-linkedin mcp-server-linkedin --login` (browser opens, user logs in manually, server persists the session after success marker within 180s)
4. **Verify** — retries `get_feed` 3× with 5s delays to confirm
5. **Persist status** — writes `output/auth_status.json` with timestamp + status + expiry hint (~30 days)
6. **Exit** — 0 on success, 1 on failure (with troubleshooting hints logged to `output/auth_assistant.log`)

### Re-login (only when needed — every ~30 days)

LinkedIn cookies expire after ~30 days. Symptoms:

- Vía 2 returns empty or `"login is still in progress"`
- Vía 3 Scrapling fetch returns login-wall HTML
- Vía 4 Playwright receives redirects to `/login`

Recovery recipe:
```bash
python auth_assistant.py        # closes old session and re-opens Chrome
# or
python linkedin_tools.py login  # explicit close_session via MCP
```

### Security best practices

- **Never commit cookies or credentials** — the MCP server manages its own storage outside this repo
- **No env-var secrets** — `mcp_client.py` only sends `UV_HTTP_TIMEOUT=300` to the subprocess
- **Programmatic logout** for long sessions: `python linkedin_tools.py login` (calls `close_session`)
- If LinkedIn starts rate-limiting aggressively, lower `config.py:MCP_DELAY_BETWEEN_CALLS` (1.5 → 3.0) and skip Vía 3

## Query Configuration / Search Inputs

Three input tiers (all in `config.py`):

| Input | Where | Default | Example |
|---|---|---|---|
| **Job keywords** (primary) | `config.py:25` `PRIMARY_KEYWORDS` | 8 | `["desarrollador", "web", "SEO", "wordpress", "full-stack", "full stack", "PHP", "developer"]` |
| **People keywords** (recruiters) | `config.py:42-52` `PEOPLE_KEYWORDS` | 23 | `["IT Recruiter", "Technical Sourcer", ...]` |
| **Company searches** | `config.py:55-58` `COMPANY_SEARCHES` | 4 | `["reclutamiento IT", "recursos humanos Buenos Aires", ...]` |
| **Locations** | `config.py:16-20` `LOCATIONS` | 3 | `["Buenos Aires, Argentina", "Argentina", "Latam"]` |

### Derivation rules

| Bucket | Query source | How it's derived |
|---|---|---|
| `jobs` | `PRIMARY_KEYWORDS` × `LOCATIONS` | config — used by Vía 1 Guest API + Vía 2 `search_jobs` |
| `job_details` | URLs in `jobs` | derived — Vía 1 public + Vía 2 `get_job_details` + Vía 3 Scrapling |
| `people` | `PEOPLE_KEYWORDS` × `LOCATIONS[0]` | config — Vía 2 `search_people` |
| `person_profiles` | URLs in `people` | derived — Vía 2 `get_person_profile` + Vía 3 Scrapling |
| `posts_feed` | (no query) | N/A — feed of the authenticated user (Vía 2 `get_feed`) |
| `posts_companies` | Slugs from `company_search` | derived — Vía 2 `get_company_posts` + Vía 3 `/company/<slug>/posts` |
| `company_search` | `COMPANY_SEARCHES` | config — Vía 2 `search_companies` |
| `company_profiles` | Slugs from `company_search` | derived — Vía 1 public + Vía 2 `get_company_profile` + Vía 3 Scrapling |
| `company_employees` | Slugs from `company_search` | derived — Vía 2 `get_company_employees` |
| `authors` | Regex `/in/<username>` in post text | derived — extracted from `posts_feed` + `posts_companies` |

**Principle:** you only define keywords in `config.py`. Slugs, IDs, usernames are derived by the orchestrator from prior buckets. **No hardcoded URLs scattered around.**

### Tuning parameters

| Parameter | Default | Where | Notes |
|---|---|---|---|
| `TEMPORAL_FILTER` | `r2592000` (30 days) | `config.py:21` | Guest API only |
| `GUEST_API_MAX_START` | 100 | `config.py:63` | 4 pages × 25 jobs |
| `MCP_DELAY_BETWEEN_CALLS` | 1.5 s | `config.py:81` | raise to 3.0 if rate-limited |
| `MCP_CAPS_JOB_DETAILS` | 50 | `config.py:84` | top-N jobs to enrich |
| `MCP_CAPS_PERSON_PROFILES` | 30 | `config.py:85` | top-N people to enrich |
| `MCP_CAPS_COMPANY_PROFILES` | 20 | `config.py:86` | top-N companies to enrich |
| `SCRAPLING_CAPS_JOBS` | 30 | `config.py:91` | top-N job IDs via Scrapling |
| `SCRAPLING_CAPS_PROFILES` | 20 | `config.py:92` | top-N usernames via Scrapling |
| `SCRAPLING_CAPS_COMPANIES` | 10 | `config.py:93` | top-N slugs via Scrapling |
| `NAME_FUZZY_THRESHOLD` | 0.85 | `config.py:98` | `difflib.SequenceMatcher` ratio for people dedup |

### CLI flags

```bash
# Full run (all 4 methods + dedup + validation + Excel export)
python linkedin_scraper.py

# Skip individual methods
python linkedin_scraper.py --no-guest-api
python linkedin_scraper.py --no-mcp
python linkedin_scraper.py --no-scrapling
python linkedin_scraper.py --no-ocr
python linkedin_scraper.py --no-playwright    # implicitly gates OCR

# Skip validation (keep all items, no employment-intent filter)
python linkedin_scraper.py --no-validate

# Combine
python linkedin_scraper.py --no-mcp --no-scrapling   # Guest API + OCR if easyocr present
```

## Deliverables

Each run produces three timestamped deliverables in `output/`:

### 1. `output/LinkedIn_Scraper_<ts>.xlsx` (preferred)

Unified workbook with 11 sheets:

| # | Sheet | Contents | Key columns |
|---|---|---|---|
| 0 | `README` | Workbook guide + legend + generation timestamp | — |
| 1 | `jobs` | Job listings from Guest API + MCP `search_jobs` | type, source, title, company, location, url, external_id, posted_date, text_ocr, is_valid |
| 2 | `job_details` | Full descriptions (MCP `get_job_details` + Scrapling) | + description |
| 3 | `people` | Recruiter / HR profiles (MCP `search_people`) | name, headline, location, url, external_id |
| 4 | `person_profiles` | Detailed person profiles | + experience, education, about |
| 5 | `posts_feed` | Personal feed posts (MCP `get_feed`) | author, text, url, posted_date |
| 6 | `posts_companies` | Company page posts | + company_name |
| 7 | `company_search` | Companies discovered (MCP `search_companies`) | name, url, external_id |
| 8 | `company_profiles` | Company /about pages (all 3 sources) | + tagline, industry, size |
| 9 | `company_employees` | Employees of discovered companies | + role, connection_degree |
| 10 | `authors` | Authors deduced from `posts_feed` + `posts_companies` | name, url, post_count |

### 2. `output/LinkedIn_Scraper_<ts>.csv` (flat fallback)

Single CSV with `category` column + standardized columns (`type, source, title, company, location, url, external_id, posted_date, scraped_at, text_ocr, is_valid`). UTF-8 with BOM (for Excel compatibility).

### 3. `output/all_results_<ts>.json` (raw)

Full JSON with metadata + all buckets + stats:
```json
{
  "metadata": {
    "timestamp": "2026-07-22T14:30:00",
    "locations": ["Buenos Aires, Argentina", "Argentina", "Latam"],
    "keywords": ["desarrollador", "web", "SEO", ...]
  },
  "results": {
    "jobs": [...], "job_details": [...], "people": [...],
    "person_profiles": [...], "posts_feed": [...], "posts_companies": [...],
    "company_search": [...], "company_profiles": [...],
    "company_employees": [...], "authors": [...]
  }
}
```

### Unified item schema

Every item, regardless of source, follows the unified schema:
```json
{
  "type": "job|person|job_detail|person_profile|post_feed|post_company|company|company_profile|company_employee|author",
  "source": "guest_api|mcp|scrapling|ocr",
  "search_keyword": "web",
  "title": "SEO Content Specialist",      // or "name" for people
  "company": "Canva",                      // if applicable
  "location": "Buenos Aires, Argentina",
  "url": "https://ar.linkedin.com/jobs/view/...",
  "external_id": "4434143494",             // jobId, username, or slug
  "posted_date": "2026-07-04",
  "scraped_at": "2026-07-22T14:30:00",
  "text_ocr": "...",                       // only if Vía 4 enriched it
  "validation": {                          // only for buckets that pass validation
    "is_valid": true,
    "matched_primary": ["SEO"],
    "matched_secondary": ["we're hiring"]
  }
}
```

## ⚠️ Ban Risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| IP blocked by Guest API | Medium | Lose Vía 1 entirely | Proxy rotation (`USE_SWIFTSHADOW=True`); randomized delays 0.5-1.5s between pages |
| LinkedIn flags MCP session as automation | Low | Session disabled | `MCP_DELAY_BETWEEN_CALLS=1.5s`; caps 50/30/20 |
| Account temporary ban (2FA enforcement) | Low | No auth for 24h | Run at most 1-2 times per day |
| Cloudflare blocking Scrapling | Medium | Lose Vía 3 | Use `StealthyFetcher` with exponential backoff |
| CAPTCHA in Playwright | Low | Vía 4 skipped | `headless=False` to solve manually; or skip OCR and use text from `deduplicator` |

## 🛡️ Anti-Ban Methods

1. **User-Agent rotation** — 8 UAs pool (`config.py:68-77`)
2. **Proxy rotation** — `swiftshadow` (free) or Webshare/ScrapeOps (paid)
3. **Randomized delays** — `random.uniform(0.5, 1.5)` between Guest API page fetches
4. **MCP call delay** — `MCP_DELAY_BETWEEN_CALLS = 1.5s`
5. **MCP enrichment caps** — 50 job_details, 30 person_profiles, 20 company_profiles per run
6. **Scrapling caps** — 30 job IDs, 20 usernames, 10 company slugs per run
7. **OCR cache** — `.ocr_cache/` directory avoids re-screenshotting same URLs across runs
8. **TLS fingerprint impersonation** — `scrapling.StealthyFetcher` bypasses Cloudflare Turnstile
9. **Cookie reuse** — Vía 3 and Vía 4 receive the MCP session cookies, avoiding fresh logins
10. **Session rotation** — re-login every ~30 days (LinkedIn cookie expiry)

## Usage Recommendations

- **Frequency**: 1-2 runs per day max. Each run scrapes from all 4 sources.
- **Best hours**: 6-9am or 8-11pm local time (low LinkedIn traffic in the target region)
- **Volume**: with no proxy, cap at ~2,000 jobs per run; with proxy, ~10,000 is feasible
- **Verify the MCP session first**: `python linkedin_tools.py feed --output feed_test.json` before the full run
- **Backups**: each run produces a timestamped output; delete older outputs manually
- **Anti-spam**: do not use the collected data for mass cold outreach — LinkedIn detects the pattern on the recipient side
- **Keep an eye on `auth_status.json`**: re-run `auth_assistant.py` when you see empty posts or `/login` redirects

## Project Structure

```
LinkedIn_Scraper/
├── .gitignore
├── README.md                          ← this file (English)
├── README.es-AR.md                    ← español argentino
├── requirements.txt
├── pyproject.toml                     (Phase 5)
├── setup.ps1                           ← Windows launcher for auth_assistant
├── auth_assistant.py                  ← one-time interactive auth
├── excel_exporter.py                  ← XLSX + CSV exporter
├── linkedin_scraper.py                ← orchestrator (entry point)
├── linkedin_tools.py                   ← interactive CLI (search/view/connect/message)
├── config.py                          ← single source of truth
├── guest_api.py                       ← Vía 1 (no-login)
├── mcp_client.py                      ← Vía 2 (auth)
├── ocr_extractor.py                   ← Vía 4 (enricher)
├── ip_rotation.py                     ← proxy rotation
├── deduplicator.py                    ← URL + fuzzy name dedup
├── validator.py                       ← employment-intent validation
├── linkedin_parser.py                 ← MCP response parser
├── output/                            ← deliverables (gitignored)
│   ├── all_results_<ts>.json
│   ├── LinkedIn_Scraper_<ts>.xlsx
│   └── LinkedIn_Scraper_<ts>.csv
└── data/outputs/historical/           ← preserved historical runs
```

## Dependencies

### Python libraries (`requirements.txt`)

| Library | Purpose |
|---|---|
| `requests` | HTTP for Vía 1 Guest API |
| `beautifulsoup4` | HTML parsing for Vía 1 |
| `mcp` | JSON-RPC client for the LinkedIn MCP server (Vía 2) |
| `playwright` | Browser automation for screenshots (Vía 4) |
| `easyocr` | OCR text extraction, Spanish + English (Vía 4) |
| `openpyxl` | Excel .xlsx writer |
| `swiftshadow` | Optional free proxy rotation (Vía 1) |
| `scrapling` | Anti-detection fetcher (Vía 3) |
| `pytest` | Test runner (for the smoke test) |

### External services

| Service | How invoked | Purpose |
|---|---|---|
| **`mcp-server-linkedin`** | Spawned as a stdio subprocess via `uvx mcp-server-linkedin@latest` or `mcp-server-linkedin` directly | All authenticated LinkedIn data. The MCP server internally drives a browser session and exposes JSON responses with `sections` (free text) + `references` (structured entities with `kind`/`url`/`text`). |

## License

MIT — see [LICENSE](LICENSE).
