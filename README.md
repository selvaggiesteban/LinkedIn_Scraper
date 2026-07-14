# LinkedIn MCP Scraper

MCP-only LinkedIn scraper (no Playwright, no browser). Uses `mcp-server-linkedin` to scrape profiles, jobs, posts, and company employees via LinkedIn's DOM.

## Requirements

- Python 3.10+
- `mcp-server-linkedin` installed via `uv tool install mcp-server-linkedin`
- LinkedIn session must be active (run `mcp-server-linkedin --login` first)

## Usage

```bash
# Full scrape (people + jobs + posts + companies)
python linkedin_full_scraper.py

# MCP CLI (individual tools)
python linkedin_tools.py people --keywords "wordpress" --location "Buenos Aires"
python linkedin_tools.py jobs --keywords "SEO" --location "Buenos Aires"
python linkedin_tools.py feed
python linkedin_tools.py company --url "mercadolibre"
python linkedin_tools.py company-posts --url "mercadolibre"
python linkedin_tools.py view-profile --username "stickerdaniel"
```

## Output

All results saved to `data/outputs/linkedin/` as JSON + CSV.

## Architecture

- `linkedin_full_scraper.py` — Full scrape pipeline (MCP-only, no Playwright)
- `linkedin_tools.py` — CLI wrapper for individual MCP tools
- `linkedin_parser.py` — Parse MCP responses into structured data
- `linkedin_job_search.py` — Job-specific search and filter logic
