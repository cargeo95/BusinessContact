from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import json
import re

from app.utils.domain_utils import normalize_domain
from app.utils.url_utils import canonicalize_linkedin_company_url, normalize_url


class StateManager:
    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def is_domain_processed(self, domain: str) -> bool:
        normalized_domain = normalize_domain(domain)
        state = self._load_state()
        return normalized_domain in state["processed_domains"]

    def mark_domain_processed(
        self,
        domain: str,
        company_name: str,
        processed_at: datetime | None = None,
    ) -> None:
        normalized_domain = normalize_domain(domain)
        if not normalized_domain:
            return

        current_time = processed_at or datetime.now()
        state = self._load_state()

        if normalized_domain in state["processed_domains"]:
            return

        state["processed_domains"][normalized_domain] = {
            "company_name": company_name,
            "processed_at": current_time.isoformat(),
        }
        self._save_state(state)

    def processed_count_for(self, target_date: date | None = None) -> int:
        current_date = (target_date or date.today()).isoformat()
        state = self._load_state()
        return int(state["daily_counts"].get(current_date, 0))

    def processed_domains(self) -> set[str]:
        state = self._load_state()
        return set(state["processed_domains"].keys())

    def has_attempt_for_company(self, linkedin_url: str, company_name: str = "") -> bool:
        state = self._load_state()
        return self._build_company_key(linkedin_url, company_name) in state["attempts"]

    def get_attempt_for_company(self, linkedin_url: str, company_name: str = "") -> dict[str, str] | None:
        state = self._load_state()
        attempt = state["attempts"].get(self._build_company_key(linkedin_url, company_name))
        return dict(attempt) if isinstance(attempt, dict) else None

    def record_attempt(
        self,
        linkedin_url: str,
        company_name: str,
        status: str,
        domain: str = "",
        message: str = "",
        attempted_at: datetime | None = None,
        count_in_daily_limit: bool = True,
    ) -> None:
        current_time = attempted_at or datetime.now()
        current_date = current_time.date().isoformat()
        state = self._load_state()
        company_key = self._build_company_key(linkedin_url, company_name)
        if not company_key:
            return

        is_new_attempt = company_key not in state["attempts"]
        state["attempts"][company_key] = {
            "linkedin_url": canonicalize_linkedin_company_url(linkedin_url) or normalize_url(linkedin_url),
            "company_name": company_name,
            "status": status,
            "domain": normalize_domain(domain),
            "message": message,
            "attempted_at": current_time.isoformat(),
        }

        if count_in_daily_limit and is_new_attempt:
            state["daily_counts"][current_date] = state["daily_counts"].get(current_date, 0) + 1

        self._save_state(state)

    def reset(self) -> None:
        self._save_state(self._default_state())

    def _load_state(self) -> dict[str, dict]:
        if not self.state_path.exists():
            return self._default_state()

        raw_text = self.state_path.read_text(encoding="utf-8").strip()
        if not raw_text:
            return self._default_state()

        try:
            loaded_state = json.loads(raw_text)
        except json.JSONDecodeError:
            return self._default_state()

        processed_domains = loaded_state.get("processed_domains", {})
        daily_counts = loaded_state.get("daily_counts", {})
        attempts = loaded_state.get("attempts", {})
        normalized_attempts: dict[str, dict] = {}

        if isinstance(attempts, dict):
            for raw_key, raw_attempt in attempts.items():
                if not isinstance(raw_attempt, dict):
                    continue

                linkedin_url = canonicalize_linkedin_company_url(
                    str(raw_attempt.get("linkedin_url") or raw_key or "")
                ) or normalize_url(str(raw_attempt.get("linkedin_url") or raw_key or ""))
                company_name = str(raw_attempt.get("company_name") or "")
                attempt_key = self._build_company_key(linkedin_url, company_name)
                if not attempt_key:
                    continue

                normalized_attempt = dict(raw_attempt)
                normalized_attempt["linkedin_url"] = linkedin_url
                normalized_attempts[attempt_key] = normalized_attempt

        return {
            "processed_domains": processed_domains if isinstance(processed_domains, dict) else {},
            "daily_counts": daily_counts if isinstance(daily_counts, dict) else {},
            "attempts": normalized_attempts,
        }

    def _save_state(self, state: dict[str, dict]) -> None:
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _default_state() -> dict[str, dict]:
        return {"processed_domains": {}, "daily_counts": {}, "attempts": {}}

    @staticmethod
    def _build_company_key(linkedin_url: str, company_name: str = "") -> str:
        normalized_url = canonicalize_linkedin_company_url(linkedin_url) or normalize_url(linkedin_url)
        if normalized_url:
            return normalized_url

        normalized_name = re.sub(r"[^a-z0-9]+", "-", company_name.strip().lower()).strip("-")
        return f"company::{normalized_name}" if normalized_name else ""
