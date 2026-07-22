# LinkedIn Scraper

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![en](https://img.shields.io/badge/README-Also%20in%20English-blue?style=flat-square)](README.md)

> Scraper de LinkedIn enfocado en empleo (Guest API + MCP + Scrapling + OCR) con validación de intención de empleo, deduplicación cruzada entre fuentes y exportación unificada a Excel.

🇬🇧 **[English version](README.md)** — README also available in English.

---

## Inventario de Cobertura

Las 4 vías de scraping cubren **las 10 categorías de búsqueda de LinkedIn** al máximo. Las categorías que requieren inicio de sesión se cubren vía la sesión MCP autenticada, compartida con Scrapling y OCR por cookies.

| Categoría | Vía 1 Guest API<br>(HTTP, sin inicio de sesión) | Vía 2 MCP<br>(auth ✅) | Vía 3 Scrapling<br>(auth ✅) | Vía 4 OCR<br>(auth ✅) |
|---|:---:|:---:|:---:|:---:|
| `jobs` (empleos) | ✅ `seeMoreJobPostings` (público) | ✅ `search_jobs` | ✅ `/jobs/view/<id>` con sesión | ✅ enriquece |
| `job_details` (detalle de empleos) | ❌ requiere inicio de sesión | ✅ `get_job_details` | ✅ `/jobs/view/<id>` texto completo | ✅ enriquece |
| `people` (personas) | ❌ requiere auth | ✅ `search_people` | ✅ `/in/<username>` con sesión | ✅ enriquece |
| `person_profiles` (perfiles de personas) | ❌ | ✅ `get_person_profile` | ✅ `/in/<username>` texto completo | ✅ enriquece |
| `posts_feed` (publicaciones) | ❌ feed privado | ✅ `get_feed` | ✅ feed con sesión | ✅ enriquece |
| `posts_companies` (publicaciones de empresas) | ❌ | ✅ `get_company_posts` | ✅ `/company/<slug>/posts` con sesión | ✅ enriquece |
| `company_search` (búsqueda de empresas) | ❌ | ✅ `search_companies` (se persiste) | ❌ | ❌ N/A |
| `company_profiles` (perfiles de empresas) | ✅ `/company/<slug>/about` (público) | ✅ `get_company_profile` | ✅ `/company/<slug>/about` con sesión | ✅ enriquece |
| `company_employees` (empleados de empresas) | ❌ auth | ✅ `get_company_employees` | ✅ `/company/<slug>/people` con sesión | ❌ N/A |
| `authors` (autores) | ❌ | ✅ derivado de feed/publicaciones | ✅ derivable | ❌ N/A |
| **Totales** | **2/10** | **10/10** | **10/10** | **10/10** |

**Cobertura combinada:** las 10 categorías tienen 1-4 fuentes productoras para deduplicación cruzada entre fuentes.

## Características

- 🚀 **4 métodos de scraping** trabajando en conjunto: Guest API (sin inicio de sesión), MCP server (autenticado), Scrapling (anti-bot), OCR (enriquecimiento de texto)
- 🎯 **10 categorías** con cobertura total (jobs, job_details, people, person_profiles, posts_feed, posts_companies, company_search, company_profiles, company_employees, authors)
- 🛡️ **Medidas anti-bloqueo**: rotación de 8 User-Agents, rotación opcional de proxies (swiftshadow gratis / Webshare pago), retardos aleatorios de 0.5-1.5 s, topes en llamadas MCP
- ✅ **Validación de intención de empleo**: debe aparecer palabra clave primaria Y (palabra clave secundaria O hashtag) en el texto
- 🧹 **Deduplicación cruzada entre fuentes**: por URL + coincidencia difusa de nombres (`difflib.SequenceMatcher`)
- 📊 **Exportación unificada a Excel**: 1 libro / 11 hojas (1 README + 10 categorías) + CSV plano como alternativa
- 🔐 **Asistente de autenticación interactivo** una sola vez (`python auth_assistant.py` o `./setup.ps1`)
- 🌐 **README bilingüe** (inglés + español argentino)

## Inicio Rápido

```bash
# 1. Instalar dependencias
pip install -r requirements.txt
playwright install chromium
uv tool install mcp-server-linkedin

# 2. Inicio de sesión por única vez (interactivo)
python auth_assistant.py
# o en Windows:
./setup.ps1

# 3. Correr el scraper (las 4 vías, cobertura total)
python linkedin_scraper.py

# 4. Entregables en output/
#    - LinkedIn_Scraper_<ts>.xlsx   (Excel con 11 hojas)
#    - LinkedIn_Scraper_<ts>.csv    (CSV plano, todas las categorías)
#    - all_results_<ts>.json        (JSON crudo con estadísticas)
```

## Guía de Autenticación

Dos mundos de autenticación:

| Mecanismo | Usado por | Requisito |
|---|---|---|
| **Sin inicio de sesión** (Guest API) | Vía 1: `/jobs-guest/...`, `/company/<slug>/about` (público) | Ninguno |
| **Con inicio de sesión** (sesión persistente) | Vías 2, 3, 4 | Una sola autenticación interactiva vía el asistente |

### Una sesión — tres canales que la comparten

El `mcp-server-linkedin` mantiene internamente una única sesión de navegador. Las Vías 2, 3 y 4 se conectan a esa misma sesión sin volver a autenticarse:

```
Usuario (1 vez) → abre Chrome → entra a linkedin.com → inicio de sesión manual
                                            │
                            mcp-server-linkedin guarda las cookies en su propio storage
                                            │
                ┌───────────────────────────┼──────────────┐
                │                           │              │
            Vía 2 MCP               Vía 3 Scrapling    Vía 4 OCR
            (JSON-RPC)              (reutiliza cookies) (reutiliza cookies)
```

### Flujo de autenticación (una sola vez)

`auth_assistant.py` corre esta secuencia:

1. **Preflight** — comprueba que Python≥3.11, `uv`, `mcp-server-linkedin` estén en el PATH; autoinstala el MCP server si falta
2. **Prueba de sesión** — intenta `MCPClient.connect()` + `get_feed`; si devuelve contenido, la sesión ya está activa → sale con código 0
3. **Inicio de sesión** — imprime "Se va a abrir Chrome para iniciar sesión en LinkedIn", espera Enter, lanza `uvx --from mcp-server-linkedin mcp-server-linkedin --login` (se abre el navegador, el usuario se loguea a mano, el server persiste la sesión cuando detecta un marcador de éxito dentro de 180 s)
4. **Verifica** — reintenta `get_feed` 3× con esperas de 5 s para confirmar
5. **Persiste el estado** — escribe `output/auth_status.json` con timestamp + estado + indicación de caducidad (~30 días)
6. **Sale** — 0 si todo OK, 1 si falla (con pistas de troubleshooting en `output/auth_assistant.log`)

### Re-inicio de sesión (solo si hace falta — cada ~30 días)

Las cookies de LinkedIn caducan pasados ~30 días. Síntomas:

- Vía 2 devuelve vacío o `"login is still in progress"`
- Vía 3 Scrapling recibe HTML de la página de inicio de sesión
- Vía 4 Playwright recibe redirects a `/login`

Receta de recuperación:
```bash
python auth_assistant.py        # cierra la sesión vieja y reabre Chrome
# o
python linkedin_tools.py login  # close_session explícito vía MCP
```

### Buenas prácticas de seguridad

- **Nunca commitear cookies ni credenciales** — el MCP server maneja su propio storage fuera de este repo
- **Nada de secretos en variables de entorno** — `mcp_client.py` solo envía `UV_HTTP_TIMEOUT=300` al subprocess
- **Cierre de sesión programático** para sesiones largas: `python linkedin_tools.py login` (llama a `close_session`)
- Si LinkedIn empieza a rate-limitiar agresivamente, bajá `config.py:MCP_DELAY_BETWEEN_CALLS` (1.5 → 3.0) y salteá Vía 3

## Configuración de Búsquedas / Entrada de Datos

Tres niveles de input (todos en `config.py`):

| Input | Dónde | Default | Ejemplo |
|---|---|---|---|
| **Palabras clave de empleos** (primarias) | `config.py:25` `PRIMARY_KEYWORDS` | 8 | `["desarrollador", "web", "SEO", "wordpress", "full-stack", "full stack", "PHP", "developer"]` |
| **Palabras clave de reclutadores** | `config.py:42-52` `PEOPLE_KEYWORDS` | 23 | `["IT Recruiter", "Technical Sourcer", ...]` |
| **Búsquedas de empresas** | `config.py:55-58` `COMPANY_SEARCHES` | 4 | `["reclutamiento IT", "recursos humanos Buenos Aires", ...]` |
| **Ubicaciones** | `config.py:16-20` `LOCATIONS` | 3 | `["Buenos Aires, Argentina", "Argentina", "Latam"]` |

### Reglas de derivación

| Bucket | Origen de la query | Cómo se deriva |
|---|---|---|
| `jobs` | `PRIMARY_KEYWORDS` × `LOCATIONS` | config — usado por Vía 1 Guest API + Vía 2 `search_jobs` |
| `job_details` | URLs en `jobs` | derivado — Vía 1 público + Vía 2 `get_job_details` + Vía 3 Scrapling |
| `people` | `PEOPLE_KEYWORDS` × `LOCATIONS[0]` | config — Vía 2 `search_people` |
| `person_profiles` | URLs en `people` | derivado — Vía 2 `get_person_profile` + Vía 3 Scrapling |
| `posts_feed` | (sin query) | N/A — feed del usuario autenticado (Vía 2 `get_feed`) |
| `posts_companies` | Slugs de `company_search` | derivado — Vía 2 `get_company_posts` + Vía 3 `/company/<slug>/posts` |
| `company_search` | `COMPANY_SEARCHES` | config — Vía 2 `search_companies` |
| `company_profiles` | Slugs de `company_search` | derivado — Vía 1 público + Vía 2 `get_company_profile` + Vía 3 Scrapling |
| `company_employees` | Slugs de `company_search` | derivado — Vía 2 `get_company_employees` |
| `authors` | Regex `/in/<username>` en texto de publicaciones | derivado — extraído de `posts_feed` + `posts_companies` |

**Principio:** solo definís palabras clave en `config.py`. Los slugs, IDs y usernames los deriva el orquestador a partir de buckets previos. **No hay URLs hardcodeadas dispersas.**

### Parámetros de tuning

| Parámetro | Default | Dónde | Notas |
|---|---|---|---|
| `TEMPORAL_FILTER` | `r2592000` (30 días) | `config.py:21` | Solo Guest API |
| `GUEST_API_MAX_START` | 100 | `config.py:63` | 4 páginas × 25 empleos |
| `MCP_DELAY_BETWEEN_CALLS` | 1.5 s | `config.py:81` | subir a 3.0 si hay rate-limit |
| `MCP_CAPS_JOB_DETAILS` | 50 | `config.py:84` | top-N empleos a enriquecer |
| `MCP_CAPS_PERSON_PROFILES` | 30 | `config.py:85` | top-N personas a enriquecer |
| `MCP_CAPS_COMPANY_PROFILES` | 20 | `config.py:86` | top-N empresas a enriquecer |
| `SCRAPLING_CAPS_JOBS` | 30 | `config.py:91` | top-N IDs de empleos vía Scrapling |
| `SCRAPLING_CAPS_PROFILES` | 20 | `config.py:92` | top-N usernames vía Scrapling |
| `SCRAPLING_CAPS_COMPANIES` | 10 | `config.py:93` | top-N slugs de empresas vía Scrapling |
| `NAME_FUZZY_THRESHOLD` | 0.85 | `config.py:98` | ratio `difflib.SequenceMatcher` para dedup de personas |

### Flags de CLI

```bash
# Corrida completa (4 vías + dedup + validación + export Excel)
python linkedin_scraper.py

# Saltear vías individuales
python linkedin_scraper.py --no-guest-api
python linkedin_scraper.py --no-mcp
python linkedin_scraper.py --no-scrapling
python linkedin_scraper.py --no-ocr
python linkedin_scraper.py --no-playwright    # implícitamente saltea OCR

# Saltear validación (conserva todo, sin filtro de intención de empleo)
python linkedin_scraper.py --no-validate

# Combinar
python linkedin_scraper.py --no-mcp --no-scrapling   # Guest API + OCR si easyocr está
```

## Entregables

Cada corrida produce tres entregables con timestamp en `output/`:

### 1. `output/LinkedIn_Scraper_<ts>.xlsx` (preferido)

Libro unificado con 11 hojas:

| # | Hoja | Contenido | Columnas clave |
|---|---|---|---|
| 0 | `README` | Guía del libro + leyenda + fecha de generación | — |
| 1 | `jobs` | Empleos de Guest API + MCP `search_jobs` | type, source, title, company, location, url, external_id, posted_date, text_ocr, is_valid |
| 2 | `job_details` | Descripciones completas (MCP `get_job_details` + Scrapling) | + description |
| 3 | `people` | Perfiles de reclutadores / RR.HH. (MCP `search_people`) | name, headline, location, url, external_id |
| 4 | `person_profiles` | Perfiles detallados de personas | + experience, education, about |
| 5 | `posts_feed` | Publicaciones del feed personal (MCP `get_feed`) | author, text, url, posted_date |
| 6 | `posts_companies` | Publicaciones de páginas de empresas | + company_name |
| 7 | `company_search` | Empresas descubiertas (MCP `search_companies`) | name, url, external_id |
| 8 | `company_profiles` | Páginas /about de empresas (las 3 fuentes) | + tagline, industry, size |
| 9 | `company_employees` | Empleados de las empresas descubiertas | + role, connection_degree |
| 10 | `authors` | Autores deducidos de `posts_feed` + `posts_companies` | name, url, post_count |

### 2. `output/LinkedIn_Scraper_<ts>.csv` (alternativa plana)

CSV único con columna `category` + columnas estandarizadas (`type, source, title, company, location, url, external_id, posted_date, scraped_at, text_ocr, is_valid`). UTF-8 con BOM (para compatibilidad con Excel).

### 3. `output/all_results_<ts>.json` (crudo)

JSON completo con metadata + todos los buckets + estadísticas:
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

### Schema unificado de items

Cada item, sin importar la fuente, sigue el schema unificado:
```json
{
  "type": "job|person|job_detail|person_profile|post_feed|post_company|company|company_profile|company_employee|author",
  "source": "guest_api|mcp|scrapling|ocr",
  "search_keyword": "web",
  "title": "SEO Content Specialist",      // o "name" para personas
  "company": "Canva",                      // si aplica
  "location": "Buenos Aires, Argentina",
  "url": "https://ar.linkedin.com/jobs/view/...",
  "external_id": "4434143494",             // jobId, username, o slug
  "posted_date": "2026-07-04",
  "scraped_at": "2026-07-22T14:30:00",
  "text_ocr": "...",                       // solo si Vía 4 lo enriqueció
  "validation": {                          // solo para buckets que pasan validación
    "is_valid": true,
    "matched_primary": ["SEO"],
    "matched_secondary": ["we're hiring"]
  }
}
```

## ⚠️ Riesgos de Bloqueo

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| IP bloqueada por Guest API | Media | Perder Vía 1 entera | Rotación de proxies (`USE_SWIFTSHADOW=True`); retardos aleatorios 0.5-1.5 s entre páginas |
| LinkedIn detecta la sesión MCP como automatización | Baja | Sesión cancelada | `MCP_DELAY_BETWEEN_CALLS=1.5s`; topes 50/30/20 |
| Ban temporal de cuenta (forzado 2FA) | Baja | Sin auth 24 h | Correr máx 1-2 veces por día |
| Cloudflare bloquea Scrapling | Media | Perder Vía 3 | Usar `StealthyFetcher` con backoff exponencial |
| CAPTCHA en Playwright | Baja | Vía 4 se saltea | `headless=False` para resolver a mano; o saltear OCR y usar el texto del `deduplicator` |

## 🛡️ Métodos Anti-Bloqueo

1. **Rotación de User-Agent** — pool de 8 UAs (`config.py:68-77`)
2. **Rotación de proxies** — `swiftshadow` (gratis) o Webshare/ScrapeOps (pago)
3. **Retardos aleatorios** — `random.uniform(0.5, 1.5)` entre fetches del Guest API
4. **Delay entre llamadas MCP** — `MCP_DELAY_BETWEEN_CALLS = 1.5s`
5. **Topes de enriquecimiento MCP** — 50 job_details, 30 person_profiles, 20 company_profiles por corrida
6. **Topes de Scrapling** — 30 IDs de empleos, 20 usernames, 10 slugs de empresas por corrida
7. **Caché de OCR** — directorio `.ocr_cache/` evita re-screenshot de las mismas URLs entre corridas
8. **Impersonación de fingerprint TLS** — `scrapling.StealthyFetcher` esquiva Cloudflare Turnstile
9. **Reutilización de cookies** — Vía 3 y Vía 4 reciben las cookies de la sesión MCP, evitando inicios de sesión adicionales
10. **Rotación de sesión** — re-inicio de sesión cada ~30 días (caducidad de cookies de LinkedIn)

## Recomendaciones de Uso

- **Frecuencia**: 1-2 corridas por día como máximo. Cada corrida scrapea desde las 4 fuentes.
- **Mejores horarios**: 6-9am o 8-11pm hora local (tráfico bajo de LinkedIn en la región objetivo)
- **Volumen**: sin proxy, tope de ~2.000 empleos por corrida; con proxy, ~10.000 es factible
- **Verificar la sesión MCP primero**: `python linkedin_tools.py feed --output feed_test.json` antes de la corrida completa
- **Backups**: cada corrida genera un output con timestamp; eliminar outputs viejos a mano
- **Anti-spam**: no usar los datos recolectados para cold outreach masivo — LinkedIn detecta el patrón del lado del destinatario
- **Ojo con `auth_status.json`**: re-corre `auth_assistant.py` cuando veas publicaciones vacías o redirects a `/login`

## Estructura del Proyecto

```
LinkedIn_Scraper/
├── .gitignore
├── README.md                          ← versión inglés
├── README.es-AR.md                    ← este archivo (español argentino)
├── requirements.txt
├── pyproject.toml                     (Fase 5)
├── setup.ps1                          ← launcher Windows para auth_assistant
├── auth_assistant.py                  ← inicio de sesión interactivo una vez
├── excel_exporter.py                  ← exportador XLSX + CSV
├── linkedin_scraper.py                ← orquestador (entry point)
├── linkedin_tools.py                   ← CLI interactivo (search/view/connect/message)
├── config.py                          ← única fuente de verdad
├── guest_api.py                       ← Vía 1 (sin inicio de sesión)
├── mcp_client.py                      ← Vía 2 (autenticado)
├── ocr_extractor.py                   ← Vía 4 (enriquecedor)
├── ip_rotation.py                     ← rotación de proxy
├── deduplicator.py                    ← dedup por URL + fuzzy name
├── validator.py                       ← validación de intención de empleo
├── linkedin_parser.py                 ← parser de respuesta MCP
├── output/                            ← entregables (gitignored)
│   ├── all_results_<ts>.json
│   ├── LinkedIn_Scraper_<ts>.xlsx
│   └── LinkedIn_Scraper_<ts>.csv
└── data/outputs/historical/           ← corridas históricas preservadas
```

## Dependencias

### Librerías Python (`requirements.txt`)

| Librería | Propósito |
|---|---|
| `requests` | HTTP para Vía 1 Guest API |
| `beautifulsoup4` | Parseo HTML para Vía 1 |
| `mcp` | Cliente JSON-RPC para el server MCP de LinkedIn (Vía 2) |
| `playwright` | Automatización de browser para screenshots (Vía 4) |
| `easyocr` | Extracción de texto vía OCR, español + inglés (Vía 4) |
| `openpyxl` | Escritor de Excel .xlsx |
| `swiftshadow` | Rotación opcional de proxies gratis (Vía 1) |
| `scrapling` | Fetcher anti-detección (Vía 3) |
| `pytest` | Runner de tests (para el smoke test) |

### Servicios externos

| Servicio | Cómo se invoca | Propósito |
|---|---|---|
| **`mcp-server-linkedin`** | Spawnado como subprocess stdio vía `uvx mcp-server-linkedin@latest` o `mcp-server-linkedin` directo | Todos los datos autenticados de LinkedIn. El MCP server maneja internamente una sesión de browser y expone respuestas JSON con `sections` (texto libre) + `references` (entidades estructuradas con `kind`/`url`/`text`). |

## Licencia

MIT — ver [LICENSE](LICENSE).
