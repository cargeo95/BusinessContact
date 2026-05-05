# CompanyDiscoveryAgent

Agente secuencial de descubrimiento comercial B2B. Consulta Google Maps Places API por zona o industria, rastrea sitios web de las empresas encontradas, extrae y valida correos empresariales con MX en tiempo real, y los escribe en un CRM vivo en Excel.

```text
Google Maps API → Website Crawl → Email Extraction → CRM (Excel)
```

## Características

- Descubrimiento sin navegador vía Google Maps Places API (Text Search)
- Crawl de páginas internas con `urllib` (sin dependencias de browser)
- Extracción de correos con regex + validación de registros MX en tiempo real
- Ranking heurístico por cargo (gerencial > contacto > automatizado) y por dominio propio
- CRM en Excel con escritura atómica y rotación automática de backups (`.bak1`–`.bak3`)
- Deduplicación por dominio: doble chequeo contra `state.json` y `crm.xlsx`
- Avance automático de consulta al terminar cada corrida (`queries_plan.xlsx`)
- Límite diario configurable de empresas procesadas

## Instalación

Requiere Python ≥ 3.10 y [`uv`](https://docs.astral.sh/uv/).

```bash
pip install uv
uv sync
cp .env.example .env   # completar con tus claves
```

## Configuración

Todas las claves se leen desde `.env` (o variables de entorno). Son insensibles a mayúsculas.

| Variable | Default | Descripción |
|----------|---------|-------------|
| `GOOGLE_MAPS_API_KEY` | `""` | Clave Places API (New) de Google Cloud Console |
| `MAPS_SEARCH_QUERY` | `"empresas en Bogotá Colombia"` | Consulta de texto; variar por industria o zona en cada corrida |
| `PAIS` | `"Colombia"` | País de reserva cuando la dirección no lo indica |
| `DAILY_COMPANY_GOAL` | `100` | Máximo de empresas procesadas por día |
| `MAX_INTERNAL_PAGES` | `3` | Máximo de páginas internas rastreadas por sitio |
| `MAX_RANKED_EMAILS` | `3` | Máximo de correos guardados por empresa |
| `COMPANY_TIMEOUT_SECONDS` | `8` | Timeout HTTP por página |
| `GROQ_API_KEY` | `""` | Reservado para ranking LLM (futuro) |
| `GROQ_MODEL` | `""` | Reservado para ranking LLM (futuro) |

## Ejecución

```bash
uv run python main.py
```

Al terminar, `main.py` marca la consulta actual como usada en `queries_plan.xlsx`, registra estadísticas en `queries_log.csv` y avanza automáticamente a la siguiente consulta del plan.

## Estructura del proyecto

```text
app/
  core/           # Bootstrap, orquestación, pipeline y configuración
  google_maps/    # Integración con Places API (Text Search)
  website/        # Crawl BFS y descubrimiento de enlaces internos
  extractor/      # Extracción de correos (regex + MX) y ranking heurístico
  storage/        # CRM (openpyxl) y estado de corrida (JSON)
  linkedin/       # Módulos legacy; LinkedInCompany es el contrato de datos compartido
  utils/          # Logger, normalización de dominios y URLs
data/
  exports/        # crm.xlsx — salida principal con backups rotativos
  processed/      # state.json — deduplicación y conteo diario
logs/             # logs.txt — errores, timeouts y fallos de sitios
main.py           # Punto de entrada
enrich_phones.py  # Utilitario: enriquecer teléfonos en el CRM existente
recover_crm.py    # Utilitario: restaurar CRM desde el último backup
```

## Archivos de runtime

Estos archivos son generados en ejecución y están en `.gitignore`.

| Ruta | Propósito |
|------|-----------|
| `data/exports/crm.xlsx` | CRM principal; backups automáticos en `.bak1`–`.bak3` |
| `data/processed/state.json` | Dominios procesados y conteo diario por fecha |
| `queries_plan.xlsx` | Plan de consultas con columna `used` |
| `queries_log.csv` | Estadísticas por corrida (empresas vistas, procesadas, omitidas) |
| `logs/logs.txt` | Errores, timeouts y fallos de sitios web |

## Utilitarios

```bash
# Enriquecer teléfonos en el CRM ya existente
uv run python enrich_phones.py

# Restaurar CRM desde el último backup disponible
uv run python recover_crm.py
```

## Dependencias principales

| Paquete | Uso |
|---------|-----|
| `openpyxl` | Lectura/escritura del CRM en Excel |
| `dnspython` | Validación de registros MX en tiempo real |
| `phonenumbers` | Parseo y normalización de números telefónicos |
| `playwright` | Automatización de navegador (reservado para integración futura) |
| `groq` | Cliente LLM para ranking de correos (reservado para integración futura) |

## Comandos de desarrollo

```bash
uv run ruff check .       # Lint
uv run ruff format .      # Formato
uv run mypy app/          # Verificación de tipos estáticos
uv run pytest             # Tests
```
