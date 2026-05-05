from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.core.config import AppConfig
from app.extractor.email_extractor import EmailExtractor
from app.extractor.email_ranker import EmailRanker
from app.linkedin.company_parser import LinkedInCompany
from app.storage.crm_manager import CRMManager, CRMRecord
from app.storage.state_manager import StateManager
from app.utils.domain_utils import extract_domain_from_url
from app.utils.logger import ProjectLogger
from app.website.website_crawler import WebsiteCrawler


@dataclass(frozen=True)
class PipelineResult:
    status: str
    attempt_status: str
    company_name: str
    linkedin_url: str = ""
    domain: str = ""
    message: str = ""
    ranked_emails: list[str] = field(default_factory=list)
    count_in_daily_limit: bool = True

    @property
    def processed(self) -> bool:
        return self.status == "processed"


class CompanyPipeline:
    def __init__(
        self,
        config: AppConfig,
        crm_manager: CRMManager,
        state_manager: StateManager,
        website_crawler: WebsiteCrawler,
        email_extractor: EmailExtractor,
        email_ranker: EmailRanker,
        logger: ProjectLogger,
    ) -> None:
        self.config = config
        self.crm_manager = crm_manager
        self.state_manager = state_manager
        self.website_crawler = website_crawler
        self.email_extractor = email_extractor
        self.email_ranker = email_ranker
        self.logger = logger

    def process(self, company: LinkedInCompany) -> PipelineResult:
        try:
            if not company.website_url:
                self.crm_manager.upsert_record(
                    self._build_record(
                        company=company,
                        estado="no_website",
                        detalle="No tiene website visible en LinkedIn.",
                    )
                )
                return PipelineResult(
                    status="skipped",
                    attempt_status="no_website",
                    company_name=company.company_name,
                    linkedin_url=company.linkedin_url,
                    message=f"{company.company_name}: omitida por no tener website visible.",
                )

            company_domain = extract_domain_from_url(company.website_url)
            if not company_domain:
                self.crm_manager.upsert_record(
                    self._build_record(
                        company=company,
                        estado="invalid_website",
                        detalle=f"Website invalido detectado: {company.website_url}",
                    )
                )
                return PipelineResult(
                    status="skipped",
                    attempt_status="invalid_website",
                    company_name=company.company_name,
                    linkedin_url=company.linkedin_url,
                    message=f"{company.company_name}: omitida por website invalido.",
                )

            if self.state_manager.is_domain_processed(company_domain) or self.crm_manager.domain_exists(
                company_domain
            ):
                self.crm_manager.upsert_record(
                    self._build_record(
                        company=company,
                        dominio=company_domain,
                        estado="duplicate_domain",
                        detalle=f"Dominio duplicado: {company_domain}",
                    )
                )
                return PipelineResult(
                    status="skipped",
                    attempt_status="duplicate_domain",
                    company_name=company.company_name,
                    linkedin_url=company.linkedin_url,
                    domain=company_domain,
                    message=f"{company.company_name}: omitida por dominio duplicado ({company_domain}).",
                )

            crawl_result = self.website_crawler.crawl(company.website_url)
            if not crawl_result.pages:
                self._log_crawl_failure(company, company_domain, crawl_result.errors)
                self.crm_manager.upsert_record(
                    self._build_record(
                        company=company,
                        dominio=company_domain,
                        estado="website_failed",
                        detalle=" || ".join(crawl_result.errors) or "Website sin HTML util.",
                    )
                )
                return PipelineResult(
                    status="failed",
                    attempt_status="website_failed",
                    company_name=company.company_name,
                    linkedin_url=company.linkedin_url,
                    domain=company_domain,
                    message=f"{company.company_name}: website fallido o sin HTML util.",
                )

            candidate_emails: list[str] = []
            if company.visible_email:
                candidate_emails.append(company.visible_email)
            candidate_emails.extend(self.email_extractor.extract_from_pages(crawl_result.pages))

            ranked_emails = self.email_ranker.select_top(
                candidate_emails,
                company_domain=company_domain,
                limit=self.config.max_ranked_emails,
            )
            if not ranked_emails:
                self.crm_manager.upsert_record(
                    self._build_record(
                        company=company,
                        dominio=company_domain,
                        estado="no_email",
                        detalle="No se encontraron correos visibles en el website.",
                    )
                )
                return PipelineResult(
                    status="skipped",
                    attempt_status="no_email",
                    company_name=company.company_name,
                    linkedin_url=company.linkedin_url,
                    domain=company_domain,
                    message=f"{company.company_name}: omitida por no encontrar correos visibles.",
                )

            top_emails = ranked_emails + [""] * max(0, self.config.max_ranked_emails - len(ranked_emails))
            record = self._build_record(
                company=company,
                dominio=company_domain,
                correo_1=top_emails[0] if len(top_emails) > 0 else "",
                correo_2=top_emails[1] if len(top_emails) > 1 else "",
                correo_3=top_emails[2] if len(top_emails) > 2 else "",
                estado="saved",
                detalle="Correos encontrados y guardados.",
            )

            try:
                self.crm_manager.upsert_record(record)
            except Exception as exc:
                self.logger.error(
                    "No se pudo guardar el CRM.",
                    company=company.company_name,
                    domain=company_domain,
                    detail=str(exc),
                )
                return PipelineResult(
                    status="failed",
                    attempt_status="save_failed",
                    company_name=company.company_name,
                    linkedin_url=company.linkedin_url,
                    domain=company_domain,
                    message=f"{company.company_name}: no se pudo guardar CRM ({exc}).",
                    count_in_daily_limit=False,
                )

            self.state_manager.mark_domain_processed(company_domain, company.company_name)
            return PipelineResult(
                status="processed",
                attempt_status="saved",
                company_name=company.company_name,
                linkedin_url=company.linkedin_url,
                domain=company_domain,
                message=f"{company.company_name}: procesada correctamente.",
                ranked_emails=ranked_emails,
            )
        except Exception as exc:
            self.logger.error(
                "Excepcion inesperada durante el pipeline de empresa.",
                company=company.company_name,
                url=company.website_url,
                detail=str(exc),
            )
            try:
                self.crm_manager.upsert_record(
                    self._build_record(
                        company=company,
                        dominio=extract_domain_from_url(company.website_url),
                        estado="unexpected_error",
                        detalle=str(exc),
                    )
                )
            except Exception:
                pass

            return PipelineResult(
                status="failed",
                attempt_status="unexpected_error",
                company_name=company.company_name,
                linkedin_url=company.linkedin_url,
                domain=extract_domain_from_url(company.website_url),
                message=f"{company.company_name}: error inesperado controlado ({exc}).",
            )

    def _log_crawl_failure(
        self,
        company: LinkedInCompany,
        domain: str,
        errors: list[str],
    ) -> None:
        if not errors:
            self.logger.website_failed(
                "Website sin contenido HTML util.",
                company=company.company_name,
                domain=domain,
                url=company.website_url,
            )
            return

        joined_errors = " || ".join(errors)
        if any("timeout" in error.lower() for error in errors):
            self.logger.timeout(
                "Timeout al procesar website de la empresa.",
                company=company.company_name,
                domain=domain,
                url=company.website_url,
                detail=joined_errors,
            )
            return

        self.logger.website_failed(
            "Website fallido durante el crawl.",
            company=company.company_name,
            domain=domain,
            url=company.website_url,
            detail=joined_errors,
        )

    def _build_record(
        self,
        company: LinkedInCompany,
        dominio: str = "",
        correo_1: str = "",
        correo_2: str = "",
        correo_3: str = "",
        estado: str = "",
        detalle: str = "",
    ) -> CRMRecord:
        return CRMRecord(
            empresa=company.company_name,
            linkedin_url=company.linkedin_url,
            dominio=dominio,
            correo_1=correo_1,
            correo_2=correo_2,
            correo_3=correo_3,
            pais=company.country or self.config.pais,
            fecha=datetime.now().date().isoformat(),
            estado=estado,
            detalle=detalle,
        )
