from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json

from app.core.browser_manager import BrowserRuntime


@dataclass(frozen=True)
class SessionState:
    session_ready: bool
    login_required: bool
    captcha_pending: bool
    cookies_present: bool
    last_saved_at: str = ""


class SessionManager:
    def __init__(self, session_state_path: Path) -> None:
        self.session_state_path = session_state_path
        self.session_state_path.parent.mkdir(parents=True, exist_ok=True)

    def ensure_session(self, browser_runtime: BrowserRuntime) -> SessionState:
        state = self._load_state()
        if not self.session_state_path.exists():
            self._save_state(state)

        cookies_present = bool(state["cookies_present"])
        if getattr(browser_runtime, "active", False) and getattr(browser_runtime, "context", None) is not None:
            try:
                cookies = browser_runtime.context.cookies()
                cookies_present = any(
                    "linkedin.com" in str(cookie.get("domain", "")).lower()
                    for cookie in cookies
                )
                state["cookies_present"] = cookies_present
                if cookies_present:
                    state["login_required"] = False
                    state["captcha_pending"] = False
                state["last_saved_at"] = datetime.now().isoformat(timespec="seconds")
                self._save_state(state)
            except Exception:
                cookies_present = bool(state["cookies_present"])

        if cookies_present and not state["captcha_pending"]:
            state["login_required"] = False
            self._save_state(state)

        session_ready = bool(browser_runtime.active) and not state["login_required"] and not state["captcha_pending"]
        return SessionState(
            session_ready=session_ready,
            login_required=bool(state["login_required"]),
            captcha_pending=bool(state["captcha_pending"]),
            cookies_present=cookies_present,
            last_saved_at=str(state.get("last_saved_at", "")),
        )

    def mark_login_required(self) -> SessionState:
        state = self._load_state()
        state["login_required"] = True
        state["captcha_pending"] = False
        state["last_saved_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_state(state)
        return self.ensure_session(
            BrowserRuntime(
                profile_dir=self.session_state_path.parent,
                headless=True,
                browser_name="session-only",
                started_at=state["last_saved_at"],
            )
        )

    def mark_login_completed(self, cookie_count: int = 0) -> SessionState:
        state = self._load_state()
        state["login_required"] = False
        state["captcha_pending"] = False
        state["cookies_present"] = cookie_count > 0 or bool(state["cookies_present"])
        state["last_saved_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_state(state)
        return self.ensure_session(
            BrowserRuntime(
                profile_dir=self.session_state_path.parent,
                headless=True,
                browser_name="session-only",
                started_at=state["last_saved_at"],
            )
        )

    def mark_captcha_required(self) -> SessionState:
        state = self._load_state()
        state["login_required"] = True
        state["captcha_pending"] = True
        state["last_saved_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_state(state)
        return self.ensure_session(
            BrowserRuntime(
                profile_dir=self.session_state_path.parent,
                headless=True,
                browser_name="session-only",
                started_at=state["last_saved_at"],
            )
        )

    def record_cookie_snapshot(self, cookie_count: int) -> SessionState:
        state = self._load_state()
        state["cookies_present"] = cookie_count > 0
        state["last_saved_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_state(state)
        return self.ensure_session(
            BrowserRuntime(
                profile_dir=self.session_state_path.parent,
                headless=True,
                browser_name="session-only",
                started_at=state["last_saved_at"],
            )
        )

    def _load_state(self) -> dict[str, object]:
        if not self.session_state_path.exists():
            return self._default_state()

        raw_text = self.session_state_path.read_text(encoding="utf-8").strip()
        if not raw_text:
            return self._default_state()

        try:
            loaded = json.loads(raw_text)
        except json.JSONDecodeError:
            return self._default_state()

        state = self._default_state()
        for key in state:
            if key in loaded:
                state[key] = loaded[key]
        return state

    def _save_state(self, state: dict[str, object]) -> None:
        self.session_state_path.write_text(
            json.dumps(state, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _default_state() -> dict[str, object]:
        return {
            "login_required": False,
            "captcha_pending": False,
            "cookies_present": False,
            "last_saved_at": "",
        }
