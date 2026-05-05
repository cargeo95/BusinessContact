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

The agent runs sequentially: one Google Maps Text Search query → one company at a time → website crawl → email extraction → CRM write → advance to next query.

**Entry flow:** `main.py` → `bootstrap.py` (wires all services) → `AgentRunner.run()` → `CompanyPipeline.process()` per company → `Finalizer.finalize()` → `main.py` advances the query plan.

**Key layers:**

- `app/core/bootstrap.py` — Constructs and wires every service. The single place where dependencies are assembled. Returns `BootstrappedApplication(config, runner, finalizer)`.
- `app/core/agent_runner.py` — Orchestrates a full run: calls `open_search()` on the discovery agent, checks daily limits, iterates company candidates, delegates each to `CompanyPipeline`, tracks `AgentRunSummary`.
- `app/core/pipeline.py` — Processes a single `LinkedInCompany`: validates website, checks for duplicates via domain, crawls, extracts and ranks emails, writes to CRM, updates state. Exit statuses: `"processed"`, `"skipped"`, `"failed"`, `"unexpected_error"`.
- `app/google_maps/places_agent.py` — Discovery source. Calls the Google Maps Places API (New) Text Search endpoint via `urllib`, paginates through results, yields `LinkedInCompany` objects. No browser needed. The `linkedin_url` field on the yielded object holds the Google Maps place URL.
- `app/website/website_crawler.py` — BFS crawl of a company website up to `max_pages` internal pages using plain `urllib` (no Playwright). Returns `WebsiteCrawlResult` with pages and errors.
- `app/extractor/email_extractor.py` — Regex extraction + live MX record validation. Filters bounce addresses and fake domains.
- `app/extractor/email_ranker.py` — Scores emails by title heuristics (management > contact > automated) and domain ownership (+35 pts domain match, -35 pts public providers). Returns top N.
- `app/storage/crm_manager.py` — Reads/writes `data/exports/crm.xlsx` via openpyxl. Atomic saves via temp-file rename. Rotating backups (`.bak1`–`.bak3`). `domain` is the deduplication key (`upsert_record`, `domain_exists`, `attempt_exists`).
- `app/storage/state_manager.py` — Persists `data/processed/state.json`. Tracks processed domains, daily company count by date, and per-company attempt history.
- `app/linkedin/` — Legacy LinkedIn modules kept for reference. `LinkedInCompany` dataclass is still the shared data contract across all pipeline stages.

**Query plan (`main.py`):**
- `queries_plan.xlsx` holds the list of search queries; `main.py` reads the first unused row, marks it `used=True` after the run, and writes stats to `queries_log.csv`.
- `_advance_env_query()` rewrites the `MAPS_SEARCH_QUERY` line in `.env` so the next `uv run python main.py` picks up the next query automatically.

**Deduplication:** a company is skipped if its domain already appears in `state.json` OR in `crm.xlsx`. Both checks happen before crawling.

**Discovery limits:** Google Maps Text Search returns up to 20 results per page with a `nextPageToken`. Vary `MAPS_SEARCH_QUERY` (e.g. by industry or zone) to get fresh results across daily runs.

## Utility scripts

- `enrich_phones.py` — Standalone script to enrich phone numbers in an existing `crm.xlsx`. Uses the `phonenumbers` library to parse and normalize entries.
- `recover_crm.py` — Restores `crm.xlsx` from the most recent `.bak` file when the main file is corrupted or missing.

## Configuration

All config is read from `.env` (or environment variables). Keys are case-insensitive.

| Key | Default | Notes |
|-----|---------|-------|
| `GOOGLE_MAPS_API_KEY` | `""` | Places API (New) key from Google Cloud Console |
| `MAPS_SEARCH_QUERY` | `"empresas en Bogotá Colombia"` | Text Search query; auto-advanced by `main.py` after each run |
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
| `data/exports/crm.xlsx` | Main CRM output; `.bak1`–`.bak3` rotate automatically |
| `data/processed/state.json` | Domain deduplication + daily counter |
| `queries_plan.xlsx` | Search query plan with `used` column |
| `queries_log.csv` | Per-run stats (seen, processed, skipped, errors) |
| `logs/logs.txt` | Errors, timeouts, website failures |
