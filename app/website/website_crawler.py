from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from http.client import HTTPException, RemoteDisconnected
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.utils.url_utils import normalize_url, url_domain
from app.website.link_discovery import LinkDiscovery


@dataclass(frozen=True)
class WebsitePage:
    url: str
    html: str
    text: str
    status_code: int | None = None


@dataclass(frozen=True)
class WebsiteCrawlResult:
    root_url: str
    pages: list[WebsitePage] = field(default_factory=list)
    visited_urls: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._ignored_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._ignored_tags.append(tag.lower())

    def handle_endtag(self, tag: str) -> None:
        if self._ignored_tags and tag.lower() == self._ignored_tags[-1]:
            self._ignored_tags.pop()

    def handle_data(self, data: str) -> None:
        if self._ignored_tags:
            return

        cleaned = data.strip()
        if cleaned:
            self.parts.append(cleaned)


class WebsiteCrawler:
    def __init__(
        self,
        link_discovery: LinkDiscovery | None = None,
        max_pages: int = 20,
        timeout_seconds: int = 15,
    ) -> None:
        self.link_discovery = link_discovery or LinkDiscovery()
        self.max_pages = max_pages
        self.timeout_seconds = timeout_seconds

    def crawl(self, start_url: str) -> WebsiteCrawlResult:
        normalized_url = self._normalize_start_url(start_url)
        if not normalized_url:
            return WebsiteCrawlResult(root_url=start_url, errors=["Website invalido o vacio."])

        root_domain = self._domain_key(normalized_url)
        crawl_deadline = monotonic() + self._crawl_budget_seconds()
        frontier = [normalized_url]
        visited: set[str] = set()
        pages: list[WebsitePage] = []
        errors: list[str] = []

        while frontier and len(visited) < self.max_pages:
            if monotonic() >= crawl_deadline:
                errors.append(
                    f"Tiempo maximo total de crawl alcanzado para {normalized_url}."
                )
                break

            current_url = frontier.pop(0)
            if current_url in visited:
                continue
            if self._domain_key(current_url) != root_domain:
                continue

            visited.add(current_url)
            html, status_code, error = self._fetch_html(current_url)
            if error is not None:
                errors.append(error)
                continue

            text = self._html_to_text(html)
            pages.append(
                WebsitePage(
                    url=current_url,
                    html=html,
                    text=text,
                    status_code=status_code,
                )
            )

            for next_url in self.link_discovery.discover_priority_links(
                page_url=current_url,
                html=html,
                limit=self.max_pages,
            ):
                if next_url not in visited and next_url not in frontier:
                    frontier.append(next_url)

        return WebsiteCrawlResult(
            root_url=normalized_url,
            pages=pages,
            visited_urls=list(visited),
            errors=errors,
        )

    def _fetch_html(self, url: str) -> tuple[str, int | None, str | None]:
        request = Request(
            url,
            headers={"User-Agent": "CompanyDiscoveryAgent/0.1 (+lead-research)"},
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                status_code = getattr(response, "status", None)
                content_type = response.headers.get("Content-Type", "")
                if "text/html" not in content_type.lower():
                    return "", status_code, f"Contenido no HTML descartado: {url}"

                payload = response.read()
                encoding = response.headers.get_content_charset() or "utf-8"
                return payload.decode(encoding, errors="replace"), status_code, None
        except HTTPError as exc:
            return "", exc.code, f"HTTP {exc.code} al abrir {url}"
        except URLError as exc:
            return "", None, f"Fallo de red al abrir {url}: {exc.reason}"
        except RemoteDisconnected as exc:
            return "", None, f"Conexion remota cerrada al abrir {url}: {exc}"
        except HTTPException as exc:
            return "", None, f"Fallo HTTP inesperado al abrir {url}: {exc}"
        except ConnectionResetError as exc:
            return "", None, f"Conexion reiniciada al abrir {url}: {exc}"
        except TimeoutError:
            return "", None, f"Timeout al abrir {url}"
        except UnicodeEncodeError:
            return "", None, f"URL invalida descartada: {url}"
        except OSError as exc:
            return "", None, f"Fallo de sistema/red al abrir {url}: {exc}"
        except Exception as exc:  # pragma: no cover - defensive network fallback
            return "", None, f"Fallo inesperado al abrir {url}: {exc}"

    @staticmethod
    def _html_to_text(html: str) -> str:
        parser = _VisibleTextParser()
        parser.feed(html)
        return " ".join(parser.parts)

    @staticmethod
    def _normalize_start_url(raw_url: str) -> str:
        return normalize_url(raw_url)

    @staticmethod
    def _domain_key(url: str) -> str:
        return url_domain(url)

    def _crawl_budget_seconds(self) -> int:
        configured_budget = max(self.max_pages, 1) * max(self.timeout_seconds, 1)
        return max(self.timeout_seconds, min(configured_budget, 30))
