# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the agent
uv run python main.py

# Lint
uv run ruff check .
uv run ruff format .

# Type check
uv run mypy app/

# Tests
uv run pytest
uv run pytest tests/path/to/test_file.py::test_name  # single test

# Install dependencies
uv sync
```

## Architecture

The agent runs sequentially: one LinkedIn search → one company at a time → website crawl → email extraction → CRM write.

**Entry flow:** `main.py` → `bootstrap.py` (wires all services) → `AgentRunner.run()` → `CompanyPipeline.process()` per company → `Finalizer.finalize()`.

**Key layers:**

- `app/core/bootstrap.py` — Constructs and wires every service. The single place where dependencies are assembled. `BootstrappedApplication` holds `runner` and `finalizer`.
- `app/core/agent_runner.py` — Orchestrates a full run: calls `open_search()` on the discovery agent, checks daily limits, iterates company candidates, delegates each to `CompanyPipeline`, tracks `AgentRunSummary`.
- `app/core/pipeline.py` — Processes a single `LinkedInCompany`: validates website, checks for duplicates via domain, crawls, extracts and ranks emails, writes to CRM, updates state.
- `app/google_maps/places_agent.py` — Discovery source. Calls the Google Maps Places API (New) Text Search endpoint via `urllib`, paginates through results, yields `LinkedInCompany` objects. No browser needed. The `linkedin_url` field on the yielded object holds the Google Maps place URL.
- `app/website/website_crawler.py` — Crawls a company website up to `max_pages` internal pages using plain `urllib` (no Playwright). Returns `WebsiteCrawlResult` with pages and errors.
- `app/extractor/` — `EmailExtractor` uses regex on raw HTML; `EmailRanker` applies heuristics (domain match priority) to select the top N emails.
- `app/storage/crm_manager.py` — Reads/writes `data/exports/crm.xlsx` via openpyxl. `domain` is the deduplication key (`upsert_record`, `domain_exists`, `attempt_exists`).
- `app/storage/state_manager.py` — Persists `data/processed/state.json`. Tracks processed domains, daily company count, and per-company attempt history.
- `app/linkedin/` — Legacy LinkedIn modules kept for reference. `LinkedInCompany` dataclass is still the shared data contract across all pipeline stages.

**Deduplication:** a company is skipped if its domain already appears in `state.json` OR in `crm.xlsx`. Both checks happen before crawling.

**Discovery limits:** Google Maps Text Search returns up to 20 results per page with a `nextPageToken`. Vary `MAPS_SEARCH_QUERY` (e.g. by industry or zone) to get fresh results across daily runs.

## Configuration

All config is read from `.env` (or environment variables). Keys are case-insensitive:

| Key | Default | Notes |
|-----|---------|-------|
| `GOOGLE_MAPS_API_KEY` | `""` | Places API (New) key from Google Cloud Console |
| `MAPS_SEARCH_QUERY` | `"empresas en Bogotá Colombia"` | Text Search query; vary by industry/zone per run |
| `PAIS` | `"Colombia"` | Fallback country when address parsing yields nothing |
| `DAILY_COMPANY_GOAL` | `100` | Max companies processed per day |
| `MAX_INTERNAL_PAGES` | `3` | Max pages crawled per website |
| `MAX_RANKED_EMAILS` | `3` | Max emails saved per company |
| `COMPANY_TIMEOUT_SECONDS` | `8` | HTTP timeout per website page |
| `GROQ_API_KEY` | `""` | Wired in config; email ranking is still heuristic |
| `GROQ_MODEL` | `""` | Reserved for future LLM ranking layer |

## Runtime files (git-ignored)

| Path | Purpose |
|------|---------|
| `data/exports/crm.xlsx` | Main CRM output |
| `data/processed/state.json` | Domain deduplication + daily counter |
| `logs/logs.txt` | Errors, timeouts, website failures |
