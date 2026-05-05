from __future__ import annotations

from collections.abc import Iterable
import re

import dns.resolver

from app.website.website_crawler import WebsitePage


EMAIL_PATTERN = re.compile(r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", re.IGNORECASE)

INVALID_DOMAINS = {
    "example.com",
    "yourdomain.com",
    "domain.com",
    "test.com",
}

INVALID_TLDS = {
    "jpg",
    "jpeg",
    "png",
    "gif",
    "svg",
    "webp",
    "avif",
    "bmp",
    "ico",
    "css",
    "js",
    "map",
    "pdf",
    "zip",
}

# Addresses that are guaranteed to bounce or never reach a human
BOUNCE_PREFIXES = {
    "noreply",
    "no-reply",
    "mailer-daemon",
    "postmaster",
    "bounce",
    "bounces",
    "do-not-reply",
    "donotreply",
    "notifications",
    "automated",
    "automailer",
    "daemon",
}

# MX lookup result cache — persists for the lifetime of the process
_MX_CACHE: dict[str, bool] = {}


def _has_valid_mx(domain: str) -> bool:
    """Return True if the domain has at least one MX record."""
    cached = _MX_CACHE.get(domain)
    if cached is not None:
        return cached
    try:
        dns.resolver.resolve(domain, "MX")
        result = True
    except Exception:
        result = False
    _MX_CACHE[domain] = result
    return result


class EmailExtractor:
    def extract_from_text(self, text: str) -> list[str]:
        found_emails: list[str] = []

        for match in EMAIL_PATTERN.finditer(text or ""):
            candidate = match.group(1).strip().lower().rstrip(".,);]")
            if self._is_valid_email(candidate) and candidate not in found_emails:
                found_emails.append(candidate)

        return found_emails

    def extract_from_pages(self, pages: Iterable[WebsitePage]) -> list[str]:
        collected: list[str] = []

        for page in pages:
            for source_text in (page.html, page.text):
                for email in self.extract_from_text(source_text):
                    if email not in collected:
                        collected.append(email)

        return collected

    @staticmethod
    def _is_valid_email(email: str) -> bool:
        if "@" not in email:
            return False

        local_part, domain = email.split("@", 1)
        if not local_part or not domain or "." not in domain:
            return False
        if domain in INVALID_DOMAINS:
            return False
        if ".." in email:
            return False
        tld = domain.rsplit(".", 1)[-1].lower()
        if tld in INVALID_TLDS:
            return False
        if local_part in BOUNCE_PREFIXES:
            return False
        if not _has_valid_mx(domain):
            return False

        return True
