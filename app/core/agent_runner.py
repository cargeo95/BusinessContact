from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.config import AppConfig
from app.core.limits import DailyProcessingLimits
from app.core.pipeline import CompanyPipeline
from app.extractor.email_extractor import EmailExtractor
from app.extractor.email_ranker import EmailRanker
from app.storage.crm_manager import CRMManager
from app.storage.state_manager import StateManager
from app.utils.logger import ProjectLogger
from app.website.website_crawler import WebsiteCrawler


@dataclass
class AgentRunSummary:
    search_ready: bool = False
    companies_seen: int = 0
    companies_processed: int = 0
    companies_skipped: int = 0
    messages: list[str] = field(default_factory=list)


class AgentRunner:
    def __init__(
        self,
        config: AppConfig,
        crm_manager: CRMManager | None = None,
        state_manager: StateManager | None = None,
        linkedin_agent: Any = None,
        website_crawler: WebsiteCrawler | None = None,
        email_extractor: EmailExtractor | None = None,
        email_ranker: EmailRanker | None = None,
        logger: ProjectLogger | None = None,
        limits: DailyProcessingLimits | None = None,
        pipeline: CompanyPipeline | None = None,
    ) -> None:
        self.config = config
        self.crm_manager = crm_manager or CRMManager(config.crm_path)
        self.state_manager = state_manager or StateManager(config.state_path)
        self.logger = logger or ProjectLogger(config.logs_path)
        self.linkedin_agent = linkedin_agent
        self.website_crawler = website_crawler or WebsiteCrawler(
            max_pages=config.max_internal_pages,
            timeout_seconds=config.company_timeout_seconds,
        )
        self.email_extractor = email_extractor or EmailExtractor()
        self.email_ranker = email_ranker or EmailRanker()
        self.limits = limits or DailyProcessingLimits(config.daily_company_goal, self.state_manager)
        self.pipeline = pipeline or CompanyPipeline(
            config=config,
            crm_manager=self.crm_manager,
            state_manager=self.state_manager,
            website_crawler=self.website_crawler,
            email_extractor=self.email_extractor,
            email_ranker=self.email_ranker,
            logger=self.logger,
        )

    def run(self) -> AgentRunSummary:
        summary = AgentRunSummary(search_ready=self.linkedin_agent.open_search())

        if not summary.search_ready:
            if self.linkedin_agent.last_status.message:
                summary.messages.append(self.linkedin_agent.last_status.message)
            return summary

        try:
            self.crm_manager.ensure_workbook_exists()
        except RuntimeError as exc:
            summary.messages.append(f"No se pudo preparar crm.xlsx ({exc}).")
            return summary

        print("Consultando Google Maps...", flush=True)

        for company in self.linkedin_agent.iter_company_candidates(
            limit=None,
            company_filter=lambda current_company: not (
                self.crm_manager.attempt_exists(current_company.linkedin_url)
                or self.state_manager.has_attempt_for_company(
                    current_company.linkedin_url,
                    current_company.company_name,
                )
            ),
        ):
            summary.companies_seen += 1
            print(
                f"{summary.companies_seen} | {company.company_name}",
                flush=True,
            )
            try:
                result = self.pipeline.process(company)
                if result.attempt_status != "save_failed":
                    self.state_manager.record_attempt(
                        linkedin_url=result.linkedin_url or company.linkedin_url,
                        company_name=result.company_name or company.company_name,
                        status=result.attempt_status,
                        domain=result.domain,
                        message=result.message,
                        count_in_daily_limit=result.count_in_daily_limit,
                    )
                if result.processed:
                    summary.companies_processed += 1
                else:
                    summary.companies_skipped += 1
                if result.message:
                    summary.messages.append(result.message)
            except Exception as exc:
                self.logger.error(
                    "Excepcion inesperada fuera del pipeline al procesar empresa.",
                    company=company.company_name,
                    linkedin_url=company.linkedin_url,
                    detail=str(exc),
                )
                summary.companies_skipped += 1
                failure_message = f"{company.company_name}: error inesperado controlado ({exc})."
                summary.messages.append(failure_message)
                try:
                    self.state_manager.record_attempt(
                        linkedin_url=company.linkedin_url,
                        company_name=company.company_name,
                        status="unexpected_error",
                        message=failure_message,
                    )
                except Exception:
                    pass
                continue

        last_message = self.linkedin_agent.last_status.message
        if summary.companies_seen == 0:
            summary.messages.append(
                last_message or "No se encontraron resultados para esta busqueda."
            )
        elif last_message and last_message not in summary.messages:
            summary.messages.append(last_message)

        return summary
