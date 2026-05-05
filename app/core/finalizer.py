from __future__ import annotations

from app.core.agent_runner import AgentRunSummary
from app.core.browser_manager import BrowserManager
from app.utils.logger import ProjectLogger


class Finalizer:
    def __init__(
        self,
        browser_manager: BrowserManager | None = None,
        logger: ProjectLogger | None = None,
    ) -> None:
        self.browser_manager = browser_manager
        self.logger = logger

    def finalize(
        self,
        summary: AgentRunSummary | None = None,
        error: Exception | None = None,
    ) -> int:
        shutdown_error: Exception | None = None

        if self.browser_manager is not None:
            try:
                self.browser_manager.stop()
            except Exception as exc:  # pragma: no cover - defensive shutdown path
                shutdown_error = exc
                if self.logger is not None:
                    self.logger.error(
                        "No se pudo cerrar el navegador de forma limpia.",
                        detail=str(exc),
                    )

            if summary is not None:
                summary.browser_active = self.browser_manager.is_active()

        if error is not None and self.logger is not None:
            self.logger.error(
                "Ejecucion interrumpida por una excepcion no controlada.",
                detail=str(error),
            )

        return 1 if error is not None or shutdown_error is not None else 0
