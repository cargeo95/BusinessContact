from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.agent_runner import AgentRunner
from app.core.config import AppConfig, load_config
from app.core.finalizer import Finalizer
from app.core.limits import DailyProcessingLimits
from app.core.pipeline import CompanyPipeline
from app.extractor.email_extractor import EmailExtractor
from app.extractor.email_ranker import EmailRanker
from app.google_maps.places_agent import GoogleMapsAgent
from app.storage.crm_manager import CRMManager
from app.storage.state_manager import StateManager
from app.utils.logger import ProjectLogger
from app.website.website_crawler import WebsiteCrawler


@dataclass(frozen=True)
class BootstrappedApplication:
    config: AppConfig
    runner: AgentRunner
    finalizer: Finalizer


def bootstrap_application(env_path: Path | None = None) -> BootstrappedApplication:
    config = load_config(env_path)
    _prepare_runtime_layout(config)

    logger = ProjectLogger(config.logs_path)
    crm_manager = CRMManager(config.crm_path)
    crm_manager.ensure_workbook_exists()

    state_manager = StateManager(config.state_path)
    maps_agent = GoogleMapsAgent(
        api_key=config.google_maps_api_key,
        search_query=config.maps_search_query,
        default_country=config.pais,
    )
    website_crawler = WebsiteCrawler(
        max_pages=config.max_internal_pages,
        timeout_seconds=config.company_timeout_seconds,
    )
    email_extractor = EmailExtractor()
    email_ranker = EmailRanker()
    limits = DailyProcessingLimits(config.daily_company_goal, state_manager)
    pipeline = CompanyPipeline(
        config=config,
        crm_manager=crm_manager,
        state_manager=state_manager,
        website_crawler=website_crawler,
        email_extractor=email_extractor,
        email_ranker=email_ranker,
        logger=logger,
    )
    runner = AgentRunner(
        config=config,
        crm_manager=crm_manager,
        state_manager=state_manager,
        linkedin_agent=maps_agent,
        website_crawler=website_crawler,
        email_extractor=email_extractor,
        email_ranker=email_ranker,
        logger=logger,
        limits=limits,
        pipeline=pipeline,
    )
    finalizer = Finalizer(logger=logger)

    return BootstrappedApplication(
        config=config,
        runner=runner,
        finalizer=finalizer,
    )


def _prepare_runtime_layout(config: AppConfig) -> None:
    (config.project_root / "data" / "raw").mkdir(parents=True, exist_ok=True)
    config.crm_path.parent.mkdir(parents=True, exist_ok=True)
    config.state_path.parent.mkdir(parents=True, exist_ok=True)
    config.logs_path.parent.mkdir(parents=True, exist_ok=True)
    config.logs_path.touch(exist_ok=True)
