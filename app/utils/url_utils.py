from __future__ import annotations

import re
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from app.utils.domain_utils import is_linkedin_domain, normalize_domain


DOMAIN_LIKE_PATTERN = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/.*)?$", re.IGNORECASE)
STRIP_EDGE_CHARS = "\"'<> \t\r\n\u201c\u201d\u2018\u2019"


def normalize_url(raw_url: str, default_scheme: str = "https") -> str:
    candidate = _prepare_url_candidate(raw_url, default_scheme=default_scheme)
    if not candidate:
        return ""

    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"}:
        return ""
    if not parsed.netloc:
        return ""

    hostname = parsed.hostname or ""
    if not hostname:
        return ""

    try:
        normalized_host = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return ""

    credentials = ""
    if parsed.username:
        credentials = quote(parsed.username, safe="")
        if parsed.password:
            credentials = f"{credentials}:{quote(parsed.password, safe='')}"
        credentials = f"{credentials}@"

    port = f":{parsed.port}" if parsed.port else ""
    normalized_netloc = f"{credentials}{normalized_host}{port}"
    normalized_path = quote(parsed.path or "/", safe="/%:@+!$,;=-._~")
    normalized_query = quote(parsed.query, safe="=&%:@+!$,;/-._~")
    cleaned = urlunsplit(
        (
            parsed.scheme.lower(),
            normalized_netloc,
            normalized_path,
            normalized_query,
            "",
        )
    )
    return cleaned.rstrip("/")


def canonicalize_linkedin_company_url(raw_url: str, default_scheme: str = "https") -> str:
    candidate = _prepare_url_candidate(
        raw_url,
        default_scheme=default_scheme,
        trim_trailing_punctuation=False,
    )
    if not candidate:
        return ""

    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"}:
        return ""
    if not parsed.netloc:
        return ""

    hostname = parsed.hostname or ""
    if not hostname:
        return ""

    try:
        normalized_host = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return ""

    if not is_linkedin_domain(normalized_host):
        return normalize_url(candidate, default_scheme=default_scheme)

    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 2 or path_parts[0].lower() != "company":
        return normalize_url(candidate, default_scheme=default_scheme)

    slug = unquote(path_parts[1]).strip()
    if not slug:
        return normalize_url(candidate, default_scheme=default_scheme)

    canonical_path = f"/company/{quote(slug, safe='-._~')}"
    credentials = ""
    if parsed.username:
        credentials = quote(parsed.username, safe="")
        if parsed.password:
            credentials = f"{credentials}:{quote(parsed.password, safe='')}"
        credentials = f"{credentials}@"

    port = f":{parsed.port}" if parsed.port else ""
    normalized_netloc = f"{credentials}{normalized_host}{port}"
    return urlunsplit(
        (
            parsed.scheme.lower(),
            normalized_netloc,
            canonical_path,
            "",
            "",
        )
    )


def join_url(base_url: str, href: str) -> str:
    base = normalize_url(base_url)
    if not base:
        return ""
    return normalize_url(urljoin(base, href))


def url_domain(url: str) -> str:
    return normalize_domain(url)


def same_domain_url(url: str, domain: str) -> bool:
    normalized_domain = normalize_domain(domain)
    return bool(normalized_domain and url_domain(url) == normalized_domain)


def _prepare_url_candidate(
    raw_url: str,
    *,
    default_scheme: str,
    trim_trailing_punctuation: bool = True,
) -> str:
    candidate = str(raw_url or "").replace("\u00a0", " ").strip().strip(STRIP_EDGE_CHARS)
    if trim_trailing_punctuation:
        candidate = candidate.rstrip(".,);]")
    else:
        candidate = candidate.rstrip(");]")

    if not candidate:
        return ""

    if candidate.startswith(("mailto:", "tel:", "javascript:", "#")):
        return ""

    if candidate.startswith("//"):
        candidate = f"{default_scheme}:{candidate}"

    if candidate.startswith("www."):
        candidate = f"{default_scheme}://{candidate}"
    elif "://" not in candidate and DOMAIN_LIKE_PATTERN.fullmatch(candidate):
        candidate = f"{default_scheme}://{candidate}"

    return candidate
