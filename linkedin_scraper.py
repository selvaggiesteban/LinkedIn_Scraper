"""
linkedin_scraper.py — CLI wrapper for LinkedIn Scraper.

This thin entry point loads the orchestrator from the src/ package layout
so the user-facing invocation remains:

    python linkedin_scraper.py [--no-guest-api] [--no-mcp] ...

Project layout:
    linkedin_scraper.py            ← this wrapper (repo root)
    src/linkedin_scraper/orchestrator.py  ← actual orchestrator
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from linkedin_scraper.orchestrator import main


if __name__ == "__main__":
    sys.exit(main())
