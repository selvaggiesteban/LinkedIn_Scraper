"""
linkedin_parser.py — LinkedIn MCP response parsing helpers.
Extracted from linkedin_job_search.py and generalized for multiple entity types.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Low-level text extraction
# ---------------------------------------------------------------------------

def _unwrap(obj: Any) -> Any:
    """Traverse SessionMessage/JSONRPCMessage wrappers to get inner Payload."""
    while hasattr(obj, 'message') and obj.message is not None:
        obj = obj.message
    while hasattr(obj, 'root') and obj.root is not None:
        obj = obj.root
    return obj


# ---------------------------------------------------------------------------
# Helpers: noise filtering and line classification
# ---------------------------------------------------------------------------

def _is_noise(line: str) -> bool:
    """Return True if line is UI noise, not real content."""
    noise_patterns = [
        r'^\d+\s*resultados?$',
        r'^Crear alerta',
        r'^Saltar para',
        r'^Ir al resultado',
        r'^Visto$',
        r'^Solicitud sencilla$',
        r'^\d+\s+antiguos?\s+alumnos?',
        r'^\d+\s+contacto\s+trabaja',
        r'^Promocionado$',
        r'^Adelántate',
        r'^(¿)?Estos resultados',
        r'^Tus comentarios',
        r'^(¿)?Encuentras lo',
        r'^Mira empleos donde',
        r'^Reactiv(ar|a) Premium',
        r'^Descartar',
        r'^Hace \d+\s+(minuto|minutos|hora|horas)$',
        r'^En las últimas',
        r'^Descargar la aplicación',
        r'^Obtén acceso',
        r'^Personas con las que',
        r'^Logotipo de',
        r'^Antiguos alumnos',
        r'^Más$',
        r'^with verification$',
        r'^\s*$',
    ]
    stripped = line.strip()
    if not stripped:
        return True
    for pattern in noise_patterns:
        if re.match(pattern, stripped, re.IGNORECASE):
            return True
    return False


def _is_date(line: str) -> bool:
    """Detect LinkedIn relative date like 'Hace 1 semana'."""
    return bool(re.match(r'^Hace\s+\d+\s+(día|días|semana|semanas|mes|meses)', line.strip(), re.IGNORECASE))


def _is_location(line: str) -> bool:
    """Detect location-ish lines."""
    markers = ['Argentina', 'Buenos Aires', 'Provincia', 'Ciudad Autónoma',
               'y alrededores', 'En remoto', 'Presencial', 'Híbrido', 'América Latina']
    return any(marker in line for marker in markers)


# ---------------------------------------------------------------------------
# Line extraction (shared)
# ---------------------------------------------------------------------------

def _extract_listing_lines(text: str) -> list[str]:
    """Extract compact listing lines, stopping before pagination or expanded details."""
    lines = text.split('\n')
    clean: list[str] = []

    stop_markers = {
        'Siguiente', '---', 'Mostrar más opciones', 'Guardar', 'Compartir', 'Seguir',
        'Mira una comparación', 'Accede a información exclusiva', 'Me interesa',
        'Solicitar', 'Empezar', 'Cancelar', 'mostrar más', 'Mostrar todo',
    }

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in stop_markers:
            break
        if re.match(r'^Siguiente$', stripped):
            break
        if len(stripped) > 200:
            break
        if re.match(r'^\d+\s+\d+\s+\d+', stripped):
            break
        if 'LinkedIn Corporation' in stripped:
            break
        clean.append(stripped)

    return clean


# ---------------------------------------------------------------------------
# Jobs parsing
# ---------------------------------------------------------------------------

def parse_sections_to_jobs(text: str) -> list[dict[str, Any]]:
    """Parse sections.search_results text → list of {title, companyName, location, postedDate}."""
    lines = _extract_listing_lines(text)
    clean = [l for l in lines if not _is_noise(l)]

    # Drop LinkedIn header like "software engineer en Buenos Aires... Argentina"
    if clean and (' en ' in clean[0].lower() and 'argentina' in clean[0].lower()):
        clean = clean[1:]

    jobs: list[dict[str, Any]] = []
    i = 0
    while i < len(clean) - 1:
        title = clean[i]
        next_line = clean[i + 1] if i + 1 < len(clean) else ''

        # LinkedIn sometimes repeats title twice
        if next_line == title or next_line.rstrip() == title + ' with verification':
            i += 1
            next_line = clean[i + 1] if i + 1 < len(clean) else ''

        company = next_line if next_line and not _is_location(next_line) and not _is_date(next_line) else ''
        company_idx = i + 1 if company else i
        location = ''
        date = ''

        loc_idx = company_idx + 1
        if company and loc_idx < len(clean):
            candidate = clean[loc_idx]
            if _is_location(candidate):
                location = candidate
                if loc_idx + 1 < len(clean) and _is_date(clean[loc_idx + 1]):
                    date = clean[loc_idx + 1]
                    i = loc_idx + 2
                else:
                    i = loc_idx + 1
            elif _is_date(candidate):
                date = candidate
                i = loc_idx + 1
            else:
                i = company_idx + 1
        elif not company and loc_idx < len(clean):
            if _is_location(clean[i + 1] if i + 1 < len(clean) else ''):
                location = clean[i + 1]
                i += 2
            else:
                i += 1
        else:
            i = company_idx + 1

        if len(title) < 100 and not _is_noise(title):
            jobs.append({'title': title, 'companyName': company, 'location': location, 'postedDate': date})

    return jobs


JUNK_TITLES = {
    'Accesibilidad', 'Centro de ayuda', 'Privacidad y condiciones',
    'Opciones de publicidad', 'Publicidad', 'Servicios empresariales',
    '…', '---', 'LinkedIn Job', 'mostrar más', 'Mostrar todo',
}


def deduplicate_jobs(all_jobs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate by jobId (falls back to title+company). Filter junk."""
    seen: set[Any] = set()
    unique: list[dict[str, Any]] = []
    for job in all_jobs:
        jid = job.get('jobId')
        key = jid if jid else (job.get('title', '') + '|' + job.get('companyName', ''))
        if key in seen:
            continue
        seen.add(key)
        title = job.get('title', '')
        if title in JUNK_TITLES:
            continue
        if not jid and not title:
            continue
        unique.append(job)

    def richness(j: dict[str, Any]) -> int:
        score = 0
        if j.get('jobId'): score += 10
        if j.get('companyName'): score += 5
        if j.get('location'): score += 3
        if j.get('postedDate'): score += 2
        if j.get('applyUrl'): score += 1
        return -score

    unique.sort(key=richness)
    return unique


def parse_single_response(text: str) -> list[dict[str, Any]] | None:
    """Parse one MCP search_jobs response → list of job dicts with full data."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    # Source 1: references (structured title, jobId, URL)
    references = data.get('references', {}).get('search_results', [])
    ref_by_id: dict[int, dict[str, Any]] = {}
    ref_by_title: dict[str, dict[str, Any]] = {}
    for ref in references:
        if ref.get('kind') != 'job':
            continue
        url = ref.get('url', '')
        ref_title = ref.get('text', '')
        if not url:
            continue
        job_id: int | None = None
        parts = url.strip('/').split('/')
        if len(parts) >= 3 and parts[0] == 'jobs' and parts[1] == 'view':
            try:
                job_id = int(parts[2])
            except ValueError:
                pass
        apply_url = f"https://www.linkedin.com{url}"
        entry = {'title': ref_title, 'jobId': job_id, 'applyUrl': apply_url}
        if job_id is not None:
            ref_by_id[job_id] = entry
        norm = re.sub(r'\s+with verification$', '', ref_title.lower().strip())
        ref_by_title[norm] = entry

    # Source 2: text sections (company, location, date)
    section_text = data.get('sections', {}).get('search_results', '')
    text_jobs = parse_sections_to_jobs(section_text) if section_text else []

    # Source 3: job_ids
    job_ids = [int(jid) for jid in data.get('job_ids', []) if str(jid).isdigit()]

    # Merge: text_jobs enriched with reference IDs
    result: list[dict[str, Any]] = []
    used_ids: set[int] = set()

    for tjob in text_jobs:
        ttitle_norm = re.sub(r'\s+with verification$', '', tjob['title'].lower().strip())
        matched = ref_by_title.get(ttitle_norm)
        if not matched:
            # Fuzzy prefix match
            for norm, ref in ref_by_title.items():
                if norm.startswith(ttitle_norm) or ttitle_norm.startswith(norm):
                    if ref['jobId'] and ref['jobId'] not in used_ids:
                        matched = ref
                        break

        job = {
            'title': tjob['title'],
            'companyName': tjob.get('companyName', ''),
            'location': tjob.get('location', ''),
            'postedDate': tjob.get('postedDate', ''),
            'jobId': None,
            'applyUrl': None,
        }

        if matched and matched['jobId'] and matched['jobId'] not in used_ids:
            job['jobId'] = matched['jobId']
            job['applyUrl'] = matched['applyUrl']
            if 'with verification' in job['title'] and 'with verification' not in matched['title']:
                job['title'] = matched['title']
            used_ids.add(matched['jobId'])

        result.append(job)

    # Assign remaining job_ids to unmatched text_jobs
    unmatched = [j for j in result if j['jobId'] is None]
    available = [jid for jid in job_ids if jid not in used_ids]
    for idx, job in enumerate(unmatched):
        if idx < len(available):
            job['jobId'] = available[idx]
            job['applyUrl'] = f"https://www.linkedin.com/jobs/view/{available[idx]}"
            used_ids.add(available[idx])

    # Add orphan job_ids
    known = {j['jobId'] for j in result if j['jobId']}
    for jid in job_ids:
        if jid not in known:
            result.append({
                'title': '', 'companyName': '', 'location': '', 'postedDate': '',
                'jobId': jid, 'applyUrl': f"https://www.linkedin.com/jobs/view/{jid}",
            })

    # Add orphan references
    for norm, ref in ref_by_title.items():
        if ref['jobId'] and ref['jobId'] not in known:
            result.append({
                'title': ref['title'], 'companyName': '', 'location': '', 'postedDate': '',
                'jobId': ref['jobId'], 'applyUrl': ref['applyUrl'],
            })

    return result if result else None
