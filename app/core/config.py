from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    url_procesar: str
    pais: str
    google_maps_api_key: str
    maps_search_query: str
    groq_api_key: str
    groq_model: str
    daily_company_goal: int
    max_internal_pages: int
    max_ranked_emails: int
    company_timeout_seconds: int
    headless_browser: bool
    crm_path: Path
    state_path: Path
    logs_path: Path
    browser_profile_path: Path
    session_state_path: Path


def load_config(env_path: Path | None = None) -> AppConfig:
    project_root = Path(__file__).resolve().parents[2]
    dotenv_path = env_path or project_root / ".env"
    dotenv_values = _read_dotenv(dotenv_path)

    def get_value(key: str, default: str) -> str:
        for candidate_key in (key, key.lower()):
            env_value = os.getenv(candidate_key)
            if env_value is not None:
                return env_value.strip()

        for candidate_key in (key, key.lower()):
            dotenv_value = dotenv_values.get(candidate_key)
            if dotenv_value is not None:
                return dotenv_value.strip()

        return default

    def get_int(key: str, default: int) -> int:
        raw_value = get_value(key, str(default))
        try:
            return int(raw_value)
        except ValueError:
            return default

    def get_bool(key: str, default: bool) -> bool:
        raw_value = get_value(key, "1" if default else "0").lower()
        return raw_value in {"1", "true", "yes", "si", "on"}

    crm_path = project_root / "data" / "exports" / "crm.xlsx"
    state_path = project_root / "data" / "processed" / "state.json"
    logs_path = project_root / "logs" / "logs.txt"
    browser_profile_path = project_root / "data" / "processed" / "browser_profile"
    session_state_path = project_root / "data" / "processed" / "session_state.json"

    return AppConfig(
        project_root=project_root,
        url_procesar=get_value("URL_PROCESAR", ""),
        pais=get_value("PAIS", "Colombia"),
        google_maps_api_key=get_value("GOOGLE_MAPS_API_KEY", ""),
        maps_search_query=get_value("MAPS_SEARCH_QUERY", "empresas en Bogotá Colombia"),
        groq_api_key=get_value("GROQ_API_KEY", ""),
        groq_model=get_value("GROQ_MODEL", ""),
        daily_company_goal=get_int("DAILY_COMPANY_GOAL", 100),
        max_internal_pages=get_int("MAX_INTERNAL_PAGES", 3),
        max_ranked_emails=get_int("MAX_RANKED_EMAILS", 3),
        company_timeout_seconds=get_int("COMPANY_TIMEOUT_SECONDS", 8),
        headless_browser=get_bool("HEADLESS_BROWSER", True),
        crm_path=crm_path,
        state_path=state_path,
        logs_path=logs_path,
        browser_profile_path=browser_profile_path,
        session_state_path=session_state_path,
    )


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')

    return values
