from __future__ import annotations

from datetime import datetime
from pathlib import Path


class ProjectLogger:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.touch(exist_ok=True)

    def error(self, message: str, **context: str) -> None:
        self._write("ERROR", message, context)

    def timeout(self, message: str, **context: str) -> None:
        self._write("TIMEOUT", message, context)

    def captcha(self, message: str, **context: str) -> None:
        self._write("CAPTCHA", message, context)

    def website_failed(self, message: str, **context: str) -> None:
        self._write("WEBSITE_FAILED", message, context)

    def _write(self, category: str, message: str, context: dict[str, str]) -> None:
        timestamp = datetime.now().isoformat(timespec="seconds")
        safe_context = {
            key: str(value).strip()
            for key, value in context.items()
            if value is not None and str(value).strip()
        }
        serialized_context = " | ".join(
            f"{key}={value.replace('|', '/').replace(chr(10), ' ')}"
            for key, value in safe_context.items()
        )
        line = f"[{timestamp}] [{category}] {message.strip()}"
        if serialized_context:
            line = f"{line} | {serialized_context}"

        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")
