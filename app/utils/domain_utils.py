from __future__ import annotations

from urllib.parse import urlparse


def normalize_domain(value: str) -> str:
    candidate = str(value or "").strip().lower()
    if not candidate:
        return ""

    if "@" in candidate and "://" not in candidate:
        candidate = candidate.split("@", 1)[1]

    if "://" not in candidate:
        parsed = urlparse(f"https://{candidate}")
    else:
        parsed = urlparse(candidate)

    hostname = parsed.netloc or parsed.path.split("/", 1)[0]
    hostname = hostname.split(":", 1)[0].strip().strip("/")

    if hostname.startswith("www."):
        hostname = hostname[4:]

    return hostname


def extract_domain_from_url(url: str) -> str:
    return normalize_domain(url)


def extract_domain_from_email(email: str) -> str:
    value = str(email or "").strip().lower()
    if "@" not in value:
        return ""
    return normalize_domain(value.split("@", 1)[1])


def domains_match(left: str, right: str) -> bool:
    normalized_left = normalize_domain(left)
    normalized_right = normalize_domain(right)
    return bool(normalized_left and normalized_left == normalized_right)


def is_subdomain_of(domain: str, root_domain: str) -> bool:
    normalized_domain = normalize_domain(domain)
    normalized_root = normalize_domain(root_domain)
    if not normalized_domain or not normalized_root:
        return False
    return normalized_domain == normalized_root or normalized_domain.endswith(f".{normalized_root}")


def is_linkedin_domain(value: str) -> bool:
    return is_subdomain_of(value, "linkedin.com")
