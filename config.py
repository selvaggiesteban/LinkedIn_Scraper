"""
config.py — LinkedIn Scraper v2 Configuration
All keywords, location, temporal filters, and scraping parameters.
"""
from __future__ import annotations

import os
from pathlib import Path

# === PROJECT PATHS ===
PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# === SEARCH CONFIGURATION ===
LOCATIONS = [
    "Buenos Aires, Argentina",
    "Argentina",
    "Latam",
]
TEMPORAL_FILTER = "r2592000"  # último mes
EXPERIENCE_LEVEL = "5"  # Senior

# Primary keywords = long-tail (what we search for)
PRIMARY_KEYWORDS = ["web", "SEO", "wordpress", "full-stack", "full stack", "PHP", "developer"]

# Secondary keywords = employment context (validated in OCR text)
SECONDARY_KEYWORDS = [
    "búsqueda", "oportunidad", "nueva oportunidad", "nueva oportunidad de empleo",
    "estamos buscando", "estamos buscando talento", "manda tu cv", "enviar cv",
    "send your cv", "we're hiring", "we are looking for a",
    "diseñador", "desarrollador", "programador", "analista de sistemas",
]

# Hashtags = employment context (validated in OCR text)
HASHTAGS = [
    "#empleo", "#trabajo", "#hiring", "#recruitment",
    "#itrecruitment", "#talentacquisition",
]

# People search keywords (recruiters, HR)
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

# Company search keywords
COMPANY_SEARCHES = [
    "reclutamiento IT", "recursos humanos Buenos Aires",
    "consultora IT Argentina", "empresa tecnología Buenos Aires",
]

# === GUEST API CONFIGURATION ===
GUEST_API_BASE = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
GUEST_API_PAGE_SIZE = 25
GUEST_API_MAX_START = 100  # LinkedIn caps at ~40 jobs per keyword, 4 pages is enough
GUEST_API_DELAY_MIN = 0.5
GUEST_API_DELAY_MAX = 1.5

# User-Agent rotation pool
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
]

# === MCP CONFIGURATION ===
MCP_COMMAND = "mcp-server-linkedin"
MCP_DELAY_BETWEEN_CALLS = 1.5

# === PLAYWRIGHT CONFIGURATION ===
PLAYWRIGHT_SCROLL_DELAY = 1.0
PLAYWRIGHT_SESSION_MAX_MINUTES = 5
PLAYWRIGHT_PAUSE_MINUTES = 2

# === OCR CONFIGURATION ===
OCR_LANGUAGES = ["es", "en"]
OCR_MODELStorage = str(OUTPUT_DIR / ".ocr_cache")

# === VALIDATION CONFIGURATION ===
# Minimum secondary keyword matches to consider valid
MIN_SECONDARY_MATCHES = 1

# === DEDUP CONFIGURATION ===
# Levenshtein distance threshold for name matching
NAME_FUZZY_THRESHOLD = 0.85

# === PROXY CONFIGURATION ===
# Scrapling ProxyRotator uses free proxies by default
# Set to True to use swiftshadow for Guest API requests
USE_SWIFTSHADOW = True
PROXY_REFRESH_INTERVAL = 300  # seconds
