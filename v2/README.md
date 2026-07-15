# LinkedIn Scraper v2

**Employment-focused LinkedIn scraper** using multi-method scraping with OCR validation.

## Promesa del proyecto

Encontrar empleo/oprofesiones laborales en LinkedIn usando inteligencia artificial y scraping multi-método, maximizando la cantidad de resultados válidos (solo ofertas reales de trabajo) y minimizando el ruido (noticias, tips, consejos).

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────┐
│                   SEARCH LAYER (4 métodos paralelo)              │
│                                                                   │
│  Guest API (jobs) ──→ 6 keywords × ~1,000 each = ~6,000 jobs   │
│  MCP (people/feed) ──→ 23 keywords + feed + companies           │
│  Playwright (scroll) ──→ infinite scroll para más resultados     │
│  Scrapling (bypass) ──→ company profiles, anti-detection         │
└───────────────────────────┬─────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│                  CONTENT LAYER (OCR)                              │
│  Screenshot → EasyOCR → texto de cada job/post                   │
└───────────────────────────┬─────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│                 VALIDATION LAYER                                  │
│  keyword_principal + (keyword_secundaria OR hashtag) = VÁLIDO    │
└───────────────────────────┬─────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│                    DEDUP LAYER                                    │
│  URL dedup → Name fuzzy → Cross-source merge                     │
│  Output: all_results.json unificado                              │
└─────────────────────────────────────────────────────────────────┘
```

## Métodos de scraping

### 1. Guest API (jobs)
- Endpoint: `/jobs-guest/jobs/api/seeMoreJobPostings/search`
- Paginación: `start=0,25,50...975` (40 páginas × 25 = 1,000 por keyword)
- Filtro temporal: `f_TPR=r2592000` (último mes)
- **No requiere login**

### 2. MCP (people, feed, companies)
- `search_people` → profiles de reclutadores/HR
- `get_feed` → posts del feed
- `search_companies` → company slugs
- `get_company_posts` → posts por empresa
- `get_company_employees` → empleados por empresa
- **Requiere sesión MCP activa**

### 3. Playwright (scroll infinito)
- Scroll para cargar más resultados
- Screenshots para OCR
- Sesiones de 5-7 min con pausas

### 4. Scrapling (bypass + company profiles)
- `StealthyFetcher` → bypass Cloudflare Turnstile
- TLS fingerprint impersonation
- Proxy rotation integrada
- **No requiere login para páginas públicas**

## IP Rotation

### Scrapling ProxyRotator (recomendado)
```python
from scrapling.spiders import Spider
# Proxy rotation automática integrada
```

### swiftshadow (para Guest API)
```python
from swiftshadow import ProxyRotator
rotator = ProxyRotator()
proxy = rotator.get()
# {'http': 'http://ip:port', 'https': 'http://ip:port'}
```

### Opciones de proxy

| Opción | Tipo | Costo | Uso |
|---|---|---|---|
| Scrapling ProxyRotator | Built-in | Gratis | Scrapling fetches |
| swiftshadow | PyPI | Gratis | Guest API requests |
| Webshare | Paid | $0.01/GB | Escalar |
| ScrapeOps | Paid | $4.9/GB | Escalar |

## Validación

Cada resultado se valida contra:
1. **keyword_principal** en el texto OCR → si no está, se descarta
2. **(keyword_secundaria OR hashtag)** en el texto OCR → si no está, se descarta

Ejemplo:
```
"Estamos buscando WordPress developer..."
  keyword_principal "wordpress" → SÍ ✓
  secundaria "estamos buscando" → SÍ ✓
  = VÁLIDO ✓

"5 tips para mejorar tu SEO"
  keyword_principal "wordpress" → NO ✗
  = DESCARTAR ✗
```

## Instalación

```bash
# Instalar dependencias
pip install scrapling easyocr swiftshadow requests beautifulsoup4 playwright

# Instalar browsers de Playwright
playwright install chromium

# Instalar MCP server LinkedIn
uv tool install mcp-server-linkedin
```

## Uso

```bash
# Ejecutar todo
python -m scripts.social_media_manager.linkedin.v2.linkedin_scraper_v2

# Sin Guest API
python -m scripts.social_media_manager.linkedin.v2.linkedin_scraper_v2 --no-guest-api

# Solo MCP
python -m scripts.social_media_manager.linkedin.v2.linkedin_scraper_v2 --no-guest-api --no-playwright --no-scrapling
```

## Output

```json
{
  "metadata": {
    "timestamp": "2026-07-14T22:00:00",
    "location": "Buenos Aires, Argentina",
    "keywords": ["web", "SEO", "wordpress", "full-stack", "full stack", "PHP"]
  },
  "results": {
    "people": [...],
    "jobs": [...],
    "posts": [...],
    "company_profiles": [...]
  }
}
```

## Configuración

Edit `config.py` para cambiar:
- `PRIMARY_KEYWORDS` — keywords de búsqueda (long-tail)
- `SECONDARY_KEYWORDS` — keywords de validación (empleo)
- `HASHTAGS` — hashtags de validación
- `LOCATION` — ubicación de búsqueda
- `TEMPORAL_FILTER` — filtro temporal (`r2592000` = último mes)

## Resultados estimados

| Fuente | Método | Total |
|---|---|---|
| Jobs | Guest API paginado | 3,000-5,000 |
| People | MCP | 150-250 |
| Feed | MCP + Playwright | 30-50 |
| Company posts | MCP + Playwright | 40-80 |
| Company employees | MCP + Playwright | 80-120 |
| Company profiles | Scrapling | 4 |
| **TOTAL** | | **~3,300-5,500** |

Si expandimos a 10 keywords × 3 ubicaciones: **~10,000-20,500**

## License

MIT
