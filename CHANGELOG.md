# Changelog

## [2.0.0] - 2026-07-26

### Added
- Subprocess isolation for MCP calls (`mcp_subprocess.py`) — crash-safe via subprocess.run()
- Save-before-close checkpoint pattern in `mcp_client.py`
- Per-tool timeout configuration (`MCP_TIMEOUT_*` constants in `config.py`)
- HTTP status diagnostics in `guest_api.py` when 0 results are returned
- Structured author extraction via `_parse_author_refs()` with regex fallback
- `duration_s` tracking in orchestrator metadata
- `tools/` directory: `consolidate_data.py` (merges all historical data), `analyze_jobs.py`, `auth_assistant.py`
- `data/outputs/consolidated/` with unified JSON + CSV + Excel (703 jobs + 62 companies = 765 records)
- `tests/conftest.py` — shared pytest fixtures (no duplicate session setup)

### Changed
- Reorganized to proper Python package layout: `src/linkedin_scraper/`
- Moved `excel_exporter.py` → `src/linkedin_scraper/utils/excel_exporter.py`
- Moved `auth_assistant.py` → `tools/auth_assistant.py` (path fix: `.parent.parent`)
- Moved `analyze_jobs.py` → `tools/analyze_jobs.py`
- Updated orchestrator import to `from .utils.excel_exporter import export_all`
- Updated `.gitignore` with `node_modules/`, `data/outputs/consolidated/`, `linkedin_mcp_checkpoint.json`
- Updated `README.md` and `README.es-AR.md` with normalized structure and new features

### Removed
- Entire `linkedin/` directory (legacy Python scripts, JS, node_modules, screenshots) — all functionality consolidated into `src/linkedin_scraper/`
- `linkedin/tools/` (legacy Python scripts: `analyze_jobs.py`, `auth_assistant.py`, `consolidate_data.py`) — moved to `tools/`
- `linkedin/tests/` — kept canonical `tests/` only
- `empresas_encontradas.*` files from root — consolidated into `data/outputs/consolidated/`
- Duplicate files in `data/outputs/historical/` (6 files → 2 unique sources)
- All `__pycache__/`, `.pytest_cache/`, `output/` temp files

## [1.0.0] - 2026-07-15

### Added
- 4-method LinkedIn scraper: Guest API, MCP, Scrapling, OCR
- Employment-intent validation with keyword/hashtag matching
- Cross-source deduplication (URL + fuzzy name matching)
- Unified Excel export (11 sheets) with flat CSV fallback
- One-time interactive auth assistant
- Adaptive rate limiting (RateBudget)
- Proxy rotation (swiftshadow free / Webshare paid)
