uv run python recover_crm.py

# CompanyDiscoveryAgent

## Objetivo

Construir un agente secuencial de descubrimiento comercial B2B para encontrar correos empresariales utiles y guardarlos en un CRM vivo.

Flujo objetivo:

```text
Empresa -> Website -> Correos -> CRM
```

## Estado actual

La base del proyecto ya esta armada en los modulos principales:

```text
main.py
  -> bootstrap.py
  -> agent_runner.py
  -> pipeline.py
  -> linkedin/
  -> website/
  -> extractor/
  -> storage/
  -> finalizer.py
```

## Estructura

```text
app/
  core/
    agent_runner.py
    bootstrap.py
    browser_manager.py
    config.py
    finalizer.py
    limits.py
    pipeline.py
    session_manager.py
  linkedin/
    company_parser.py
    linkedin_agent.py
  website/
    link_discovery.py
    website_crawler.py
  extractor/
    email_extractor.py
    email_ranker.py
  storage/
    crm_manager.py
    state_manager.py
  utils/
    domain_utils.py
    logger.py
    url_utils.py
data/
  raw/
  processed/
  exports/
logs/
main.py
pyproject.toml
.env
```

## Responsabilidades

`main.py`
Inicia la aplicacion y delega el arranque a `bootstrap.py`.

`bootstrap.py`
Carga configuracion, prepara carpetas, construye servicios y devuelve la aplicacion lista para ejecutar.

`agent_runner.py`
Orquesta una corrida completa del agente.

`pipeline.py`
Ejecuta el flujo de una empresa: website, crawl, extraccion, ranking, guardado y estado.

`finalizer.py`
Cierra navegador y deja la ejecucion en estado limpio aunque ocurra un error.

## Archivos vivos

`data/exports/crm.xlsx`
CRM principal. Se escribe empresa por empresa.

`data/processed/state.json`
Estado de dominios procesados y conteo diario.

`logs/logs.txt`
Registro de errores, timeouts, captcha y websites fallidos.

## Variables de entorno

El proyecto lee `.env` con estas claves:

```text
url_procesar
pais
daily_company_goal
max_internal_pages
max_ranked_emails
company_timeout_seconds
headless_browser
groq_api_key
groq_model
```

Notas:

- `url_procesar` es la busqueda de LinkedIn a procesar.
- `pais` se escribe en el CRM cuando la empresa no trae un pais especifico.
- `groq_api_key` ya queda soportada por configuracion.
- Groq queda listo en entorno, pero el ranking actual sigue siendo heuristico hasta agregar un cliente dedicado.

## Ejecucion

Con `uv`:

```bash
uv sync
uv run python main.py
```

Con Python local:

```bash
python main.py
```

## Reglas operativas

- Procesamiento secuencial: una empresa a la vez.
- Meta diaria por defecto: `100`.
- Maximo por website: `20` paginas internas.
- Maximo de guardado: `3` correos por empresa.
- Identificador unico: `dominio`.
- Si LinkedIn requiere captcha, la corrida se detiene y queda registrada en logs.

## Dependencias principales

- `openpyxl` para `crm.xlsx`
- `playwright` para el navegador persistente
- `groq` para la futura capa LLM de ranking

## Siguiente paso natural

Con esta base ya cerrada, el siguiente trabajo recomendable es conectar `LinkedInAgent` y `BrowserManager` con navegacion real en LinkedIn usando una sesion persistente.
