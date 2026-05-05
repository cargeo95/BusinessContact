from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
import re

from app.utils.domain_utils import is_linkedin_domain
from app.utils.url_utils import canonicalize_linkedin_company_url, normalize_url


EMAIL_PATTERN = re.compile(r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", re.IGNORECASE)
URL_PATTERN = re.compile(
    r"(?:(?:https?://|www\.)[^\s<>()]+|(?<!@)\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>()]*)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LinkedInCompany:
    company_name: str
    linkedin_url: str = ""
    website_url: str = ""
    visible_email: str = ""
    country: str = ""


class CompanyParser:
    def __init__(self, default_country: str) -> None:
        self.default_country = default_country

    def parse_search_result(self, payload: Mapping[str, Any]) -> LinkedInCompany:
        company_name = str(
            payload.get("company_name")
            or payload.get("empresa")
            or payload.get("name")
            or ""
        ).strip()
        linkedin_url = self._normalize_url(
            str(payload.get("linkedin_url") or payload.get("company_url") or "")
        )
        raw_text = str(payload.get("text") or payload.get("visible_text") or "")
        raw_website = str(payload.get("website_url") or payload.get("website") or "")
        raw_email = str(payload.get("visible_email") or payload.get("email") or "")
        country = str(payload.get("country") or payload.get("pais") or self.default_country).strip()

        website_url = self._normalize_external_url(raw_website) or self._extract_first_url(raw_website)
        visible_email = self._extract_first_email(raw_email) or self._extract_first_email(raw_text)

        return LinkedInCompany(
            company_name=company_name,
            linkedin_url=linkedin_url,
            website_url=website_url,
            visible_email=visible_email,
            country=country or self.default_country,
        )

    def parse_visible_text(
        self,
        company_name: str,
        visible_text: str,
        linkedin_url: str = "",
    ) -> LinkedInCompany:
        return LinkedInCompany(
            company_name=company_name.strip(),
            linkedin_url=self._normalize_url(linkedin_url),
            website_url=self._extract_first_url(visible_text),
            visible_email=self._extract_first_email(visible_text),
            country=self.default_country,
        )

    def _extract_first_email(self, text: str) -> str:
        match = EMAIL_PATTERN.search(text or "")
        return match.group(1).strip().lower() if match else ""

    def _extract_first_url(self, text: str) -> str:
        for match in URL_PATTERN.finditer(text or ""):
            raw_url = match.group(0).strip().rstrip(".,);]")
            if "@" in raw_url:
                continue
            normalized_url = self._normalize_external_url(raw_url)
            if normalized_url:
                return normalized_url
        return ""

    @staticmethod
    def _normalize_url(raw_url: str) -> str:
        linkedin_url = canonicalize_linkedin_company_url(raw_url)
        return linkedin_url or normalize_url(raw_url)

    @staticmethod
    def _normalize_external_url(raw_url: str) -> str:
        normalized_url = normalize_url(raw_url)
        if not normalized_url or is_linkedin_domain(normalized_url):
            return ""
        return normalized_url
