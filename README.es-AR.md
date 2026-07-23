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
| LinkedIn detecta la sesión MCP como automatización (`actividad sospechosa en tu cuenta`) | Media → **Baja** con RateBudget | Sesión cancelada; cuenta suspendida temporalmente | RateBudget de doble cubeta (8/min + 100/h) + 8 fases MCP escalonadas + recuperación de `MCPChallengePendingError` (45 s × 2 reintentos) |
| Ban temporal de cuenta (forzado 2FA) | Baja | Sin auth 24 h | Correr máx 1-2 veces por día; `--cool-run` multiplica los delays entre llamadas × 4 |
| Cloudflare bloquea Scrapling | Media | Perder Vía 3 | `stealthy_headers=True` en cada `Fetcher.get` (v3); cool-downs gateados por el budget entre URLs |
| CAPTCHA en Playwright | Baja | Vía 4 se saltea | `headless=False` para resolver a mano; o saltear OCR y usar el texto del `deduplicator` |
| Challenge screen durante la corrida MCP (cookies vencidas) | Media | El bucket vuelve vacío | `_safe_call` devuelve `None` graceful → bucket preservado pero vacío; re-corre `auth_assistant.py` |

## 🛡️ Métodos Anti-Bloqueo

### Nivel 1 — Fundacionales (siempre activos)
1. **Rotación de User-Agent** — pool de 8 UAs (`config.py:USER_AGENTS`)
2. **Rotación de proxies** — `swiftshadow` (gratis) o Webshare/ScrapeOps (pago) para Guest API
3. **Retardos aleatorios** — `random.uniform(0.5, 1.5)` entre fetches del Guest API
4. **Impersonación de fingerprint TLS** — `scrapling.Fetcher(stealthy_headers=True)` esquiva Cloudflare Turnstile
5. **Caché de OCR** — directorio `.ocr_cache/` evita re-screenshot de las mismas URLs entre corridas
6. **Reutilización de cookies** — Vía 3 y Vía 4 reciben las cookies de la sesión MCP, evitando inicios de sesión adicionales
7. **Rotación de sesión** — re-inicio de sesión cada ~30 días (caducidad de cookies de LinkedIn)

### Nivel 2 — Pacing con RateBudget (nuevo en v3.0)
El orquestador ahora comparte **una sola instancia de `RateBudget`** entre MCP y Scrapling para
mantener la tasa acumulada de llamadas por debajo de la ventana anti-abuso de LinkedIn
(~150 perfiles/h, ~5-8/min en ráfagas). Los knobs de tuning viven en
`src/linkedin_scraper/utils/rate_budget.py` + `config.py`:

| Knob | Default | Efecto |
|---|---|---|
| `RateBudgetConfig.burst_capacity` | **8/min** | Techo duro de llamadas por ventana móvil de 60 s |
| `RateBudgetConfig.hourly_capacity` | **100/h** | Techo duro de llamadas acumuladas por ventana de 3600 s |
| `RateBudgetConfig.error_penalty` | **4 tokens** | Cada error de LinkedIn quema 4 tokens de ráfaga → fuerza cool-down más largo |
| `RateBudgetConfig.cool_run_multiplier` | **4.0** | Si activás `--cool-run`, todos los delay entre llamadas × 4 (más lento = menor riesgo de ban) |
| `MCP_CAPS_JOB_DETAILS` | **20** | Top-N empleos a enriquecer con `get_job_details` por corrida |
| `MCP_CAPS_PERSON_PROFILES` | **15** | Top-N personas a enriquecer con `get_person_profile` |
| `MCP_CAPS_COMPANY_PROFILES` | **8** | Top-N empresas a enriquecer con `get_company_profile` |
| `SCRAPLING_CAPS_*` | 30/20/10 | Techos por corrida para fetches de URLs con Scrapling |
| `SCRAPLING_REQUEST_COOLDOWN` | **3.5 s** | Sleep paced entre fetches de Scrapling (jitter ±0.5–1.0 s) |

### Nivel 3 — 8 fases MCP escalonadas (`scrape_mcp`)
Cada fase es gate-gated por `_safe_call` que adquiere un token del budget, llama al tool MCP,
captura `MCPChallengePendingError` (→ espera 45 s, máx 2 reintentos) y registra error penalties:

| Fase | Tool(s) | Delay entre llamadas | Cool-down |
|---|---|---|---|
| A | `search_jobs` × 8 keywords | `jitter(3,5)` s | — |
| B | `search_people` × 23 keywords (lotes de 4) | `jitter(4,6)` s | **60 s** entre lotes |
| C | `get_feed` (×1) | después de 20 s de cool-down | 30 s antes de D |
| D | `search_companies` × 4 keywords | `jitter(4,6)` s | — |
| E | `get_company_posts` + `get_company_employees` (top 3 slugs/búsqueda) | `jitter(5,7)` s | **30 s** por slug |
| F | `get_job_details` × N | `jitter(3,5)` s | — |
| G | `get_person_profile` × N | `jitter(4,6)` s | — |
| H | `get_company_profile` × N | `jitter(5,7)` s | — |

### Nivel 4 — Degradación graceful
- **`MCPChallengePendingError`** → 45 s de espera, máx 2 reintentos, después devuelve `None`. El
  bucket se preserva pero vacío (garantiza que las 10 categorías estén presentes en el Excel aun
  con fallas parciales).
- **Errores de Scrapling** → registrados con `budget.record_error()`, sin crash, sólo devuelve `None`.
- **Playwright OCR** envuelto en `try/finally` con `browser.close()` — nunca fuga un proceso de
  Chromium ni siquiera con `asyncio.CancelledError`.
- **`mcp.close()`** envuelto en `try/except` para tragar el inofensivo `RuntimeError: cancel scope`
  que levanta anyio en el teardown.

### Telemetría
Después de cada corrida, `output/all_results_<ts>.json` ahora incluye un bloque `metadata.safety`:

```json
{
  "metadata": {
    "cool_run": false,
    "safety": {
      "total_calls": 87,
      "total_errors": 2,
      "total_pauses": 14,
      "burst_tokens_left": 3.2,
      "hourly_tokens_left": 73.8,
      "calls_per_minute_peak": 6.4,
      "burst_capacity": 8,
      "hourly_capacity": 100
    }
  }
}
```

Usá estos números para tunear `RateBudgetConfig` entre corridas (p.ej. si `total_errors` > 5 o
`calls_per_minute_peak` > 7 → bajá los caps o corré siempre con `--cool-run`).

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
