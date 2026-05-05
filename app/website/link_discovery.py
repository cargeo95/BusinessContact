from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse

from app.utils.url_utils import join_url, normalize_url, url_domain


KEYWORD_SCORES = {
    "contact": 120,
    "contacto": 120,
    "about": 100,
    "nosotros": 100,
    "empresa": 95,
    "company": 95,
    "team": 90,
    "staff": 90,
    "directorio": 85,
    "directory": 85,
    "legal": 70,
    "privacy": 55,
    "aviso": 55,
    "footer": 40,
}

IGNORED_SUFFIXES = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".pdf",
    ".zip",
    ".rar",
    ".mp4",
    ".mp3",
)


@dataclass(frozen=True)
class LinkCandidate:
    href: str
    label: str


class _AnchorCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[LinkCandidate] = []
        self._current_href = ""
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a":
            return

        href = dict(attrs).get("href", "")
        self._current_href = str(href or "").strip()
        self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._current_href:
            return

        label = " ".join(part.strip() for part in self._current_text if part.strip())
        self.links.append(LinkCandidate(href=self._current_href, label=label))
        self._current_href = ""
        self._current_text = []


class LinkDiscovery:
    def discover_priority_links(self, page_url: str, html: str, limit: int = 20) -> list[str]:
        collector = _AnchorCollector()
        collector.feed(html)

        current_url = self._normalize_url(page_url)
        if not current_url:
            return []

        current_domain = self._domain_key(current_url)
        scored_links: dict[str, int] = {}

        for candidate in collector.links:
            normalized_url = self._normalize_candidate(current_url, candidate.href)
            if not normalized_url or normalized_url == current_url:
                continue
            if self._domain_key(normalized_url) != current_domain:
                continue

            score = self._score_link(normalized_url, candidate.label)
            previous_score = scored_links.get(normalized_url)
            if previous_score is None or score > previous_score:
                scored_links[normalized_url] = score

        ordered_links = sorted(
            scored_links.items(),
            key=lambda item: (-item[1], len(urlparse(item[0]).path), item[0]),
        )
        return [url for url, _ in ordered_links[:limit]]

    def _normalize_candidate(self, page_url: str, raw_href: str) -> str:
        href = str(raw_href or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            return ""

        absolute_url = join_url(page_url, href)
        if not absolute_url:
            return ""

        parsed_url = urlparse(absolute_url)
        if parsed_url.path.lower().endswith(IGNORED_SUFFIXES):
            return ""

        return absolute_url

    @staticmethod
    def _score_link(url: str, label: str) -> int:
        haystack = f"{url.lower()} {label.lower()}".strip()
        score = 10

        for keyword, bonus in KEYWORD_SCORES.items():
            if keyword in haystack:
                score += bonus

        path = urlparse(url).path.strip("/")
        if not path:
            score -= 15

        if "blog" in haystack or "news" in haystack or "career" in haystack:
            score -= 20

        return score

    @staticmethod
    def _normalize_url(raw_url: str) -> str:
        return normalize_url(raw_url)

    @staticmethod
    def _domain_key(url: str) -> str:
        return url_domain(url)
