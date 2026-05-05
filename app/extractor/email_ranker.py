from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable
import re

from app.utils.domain_utils import normalize_domain


HIGH_PRIORITY_PREFIXES = {
    "gerencia",
    "direccion",
    "comercial",
    "negocios",
    "ceo",
    "founder",
    "ventas",
    "alianzas",
}

MEDIUM_PRIORITY_PREFIXES = {
    "contacto",
    "administracion",
    "office",
}

LOW_PRIORITY_PREFIXES = {
    "info",
    "noreply",
    "no-reply",
    "soporte",
    "support",
    "webmaster",
}

PUBLIC_EMAIL_DOMAINS = {
    "gmail.com",
    "hotmail.com",
    "outlook.com",
    "yahoo.com",
}


@dataclass(frozen=True)
class RankedEmail:
    email: str
    score: int
    priority: str


class EmailRanker:
    def rank(
        self,
        emails: Iterable[str],
        company_domain: str = "",
        limit: int = 3,
    ) -> list[RankedEmail]:
        ranked_emails: list[RankedEmail] = []
        seen: set[str] = set()

        for raw_email in emails:
            email = raw_email.strip().lower()
            if not email or email in seen or "@" not in email:
                continue

            seen.add(email)
            score, priority = self._score_email(email, company_domain)
            ranked_emails.append(RankedEmail(email=email, score=score, priority=priority))

        ranked_emails.sort(key=lambda item: (-item.score, item.email))
        return ranked_emails[:limit]

    def select_top(
        self,
        emails: Iterable[str],
        company_domain: str = "",
        limit: int = 3,
    ) -> list[str]:
        return [item.email for item in self.rank(emails, company_domain=company_domain, limit=limit)]

    def _score_email(self, email: str, company_domain: str) -> tuple[int, str]:
        local_part, domain = email.split("@", 1)
        normalized_company_domain = normalize_domain(company_domain)
        normalized_domain = normalize_domain(domain)
        tokens = set(re.split(r"[._+\-]+", local_part))

        priority = "normal"
        score = 180

        if local_part in HIGH_PRIORITY_PREFIXES or tokens.intersection(HIGH_PRIORITY_PREFIXES):
            priority = "alta"
            score = 320
        elif local_part in MEDIUM_PRIORITY_PREFIXES or tokens.intersection(MEDIUM_PRIORITY_PREFIXES):
            priority = "media"
            score = 240
        elif local_part in LOW_PRIORITY_PREFIXES or tokens.intersection(LOW_PRIORITY_PREFIXES):
            priority = "baja"
            score = 120

        if normalized_company_domain:
            if normalized_domain == normalized_company_domain:
                score += 35
            else:
                score -= 20

        if normalized_domain in PUBLIC_EMAIL_DOMAINS:
            score -= 35

        return score, priority
