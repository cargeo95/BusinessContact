from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
from typing import Any


@dataclass
class BrowserRuntime:
    profile_dir: Path
    headless: bool
    browser_name: str
    started_at: str
    active: bool = False
    launch_error: str = ""
    playwright: Any = None
    context: Any = None
    page: Any = None


class BrowserManager:
    def __init__(
        self,
        profile_dir: Path,
        headless: bool = True,
        browser_name: str = "persistent-headless-browser",
    ) -> None:
        self.profile_dir = profile_dir
        self.headless = headless
        self.browser_name = browser_name
        self.metadata_path = self.profile_dir / "runtime.json"
        self._runtime: BrowserRuntime | None = None

    def start(self) -> BrowserRuntime:
        if self._runtime and self._runtime.active:
            return self._runtime

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        runtime = BrowserRuntime(
            profile_dir=self.profile_dir,
            headless=self.headless,
            browser_name=self.browser_name,
            started_at=datetime.now().isoformat(timespec="seconds"),
        )

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            runtime.launch_error = (
                "Playwright no esta disponible en este Python. "
                "Usa `uv run python main.py` o instala las dependencias en este entorno."
            )
            self._runtime = runtime
            self._write_metadata(runtime)
            return runtime

        try:
            playwright = sync_playwright().start()
            runtime.playwright = playwright
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=self.headless,
                viewport={"width": 1440, "height": 1024},
                accept_downloads=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--disable-dev-shm-usage",
                ],
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(20_000)
            page.set_default_navigation_timeout(60_000)

            runtime.playwright = playwright
            runtime.context = context
            runtime.page = page
            runtime.active = True
        except Exception as exc:
            runtime.launch_error = self._format_launch_error(exc)
            self._safe_close_runtime(runtime)

        self._runtime = runtime
        self._write_metadata(runtime)
        return runtime

    def stop(self) -> None:
        if self._runtime is None:
            return

        self._safe_close_runtime(self._runtime)
        self._runtime.active = False
        self._write_metadata(self._runtime)

    def is_active(self) -> bool:
        return bool(self._runtime and self._runtime.active)

    def _write_metadata(self, runtime: BrowserRuntime) -> None:
        payload = {
            "browser_name": runtime.browser_name,
            "headless": runtime.headless,
            "profile_dir": str(runtime.profile_dir),
            "started_at": runtime.started_at,
            "active": runtime.active,
            "launch_error": runtime.launch_error,
        }
        self.metadata_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _safe_close_runtime(runtime: BrowserRuntime) -> None:
        context = runtime.context
        playwright = runtime.playwright

        runtime.page = None
        runtime.context = None
        runtime.playwright = None
        runtime.active = False

        try:
            if context is not None:
                context.close()
        except Exception:
            pass

        try:
            if playwright is not None:
                playwright.stop()
        except Exception:
            pass

    @staticmethod
    def _format_launch_error(exc: Exception) -> str:
        raw_message = str(exc).strip()
        lowered = raw_message.lower()

        if "executable doesn't exist" in lowered or "browser has not been found" in lowered:
            return (
                "Playwright esta instalado pero falta el navegador Chromium. "
                "Ejecuta `uv run playwright install chromium` y vuelve a intentar."
            )

        return raw_message or "No se pudo iniciar el navegador persistente."
