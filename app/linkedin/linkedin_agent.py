from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterator, Sequence
from time import monotonic
import re
from typing import Callable
from typing import Any, Mapping
from urllib.parse import parse_qs, urlencode, urlparse, urlsplit, urlunsplit
import unicodedata

from app.core.browser_manager import BrowserRuntime
from app.linkedin.company_parser import CompanyParser, LinkedInCompany
from app.utils.domain_utils import is_linkedin_domain, is_subdomain_of, normalize_domain
from app.utils.url_utils import canonicalize_linkedin_company_url, normalize_url


VISIBLE_URL_PATTERN = re.compile(
    r"(?:(?:https?://|www\.)[^\s<>()]+|(?<!@)\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>()]*)?)",
    re.IGNORECASE,
)

WEBSITE_HINTS = (
    "website",
    "sitio web",
    "pagina web",
    "página web",
    "web oficial",
    "visit website",
    "visitar sitio",
    "pagina oficial",
    "página oficial",
)

BLOCKED_EXTERNAL_DOMAINS = {
    "lnkd.in",
    "bing.com",
    "google.com",
    "google.com.co",
    "yahoo.com",
    "duckduckgo.com",
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "wa.me",
    "whatsapp.com",
    "linktr.ee",
}

COMPANY_TOKEN_STOPWORDS = {
    "sas",
    "sa",
    "ltda",
    "sucursal",
    "grupo",
    "company",
    "empresa",
    "empresarial",
    "consultoria",
    "consultorias",
    "consulting",
    "auditoria",
    "auditorias",
    "asesoria",
    "asesorias",
    "servicio",
    "servicios",
    "solutions",
    "soluciones",
    "colombia",
}

SEARCH_NAVIGATION_TIMEOUT_MS = 8_000
SEARCH_RETRY_TIMEOUT_MS = 4_000
PROFILE_NAVIGATION_TIMEOUT_MS = 4_000
ABOUT_NAVIGATION_TIMEOUT_MS = 3_000
SETTLE_LOAD_TIMEOUT_MS = 1_500
SETTLE_WAIT_MS = 400
SEARCH_RESULTS_WAIT_MS = 4_000
SEARCH_RESULTS_POLL_MS = 500
ABOUT_DETAILS_WAIT_MS = 2_500
NEXT_PAGE_EMPTY_RETRIES = 2
NEXT_PAGE_RETRY_WAIT_MS = 1_200


@dataclass(frozen=True)
class LinkedInCollectionStatus:
    ready: bool = False
    login_required: bool = False
    captcha_pending: bool = False
    message: str = ""


class LinkedInAgent:
    def __init__(
        self,
        search_url: str,
        parser: CompanyParser,
        seed_results: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self.search_url = search_url.strip()
        self.parser = parser
        self._seed_results = list(seed_results or [])
        self.last_status = LinkedInCollectionStatus(ready=bool(self.search_url))

    def open_search(self) -> bool:
        return bool(self.search_url)

    def set_seed_results(self, seed_results: Sequence[Mapping[str, Any]]) -> None:
        self._seed_results = list(seed_results)

    def iter_company_candidates(
        self,
        limit: int | None = None,
        browser_runtime: BrowserRuntime | None = None,
        company_filter: Callable[[LinkedInCompany], bool] | None = None,
    ) -> Iterator[LinkedInCompany]:
        self.last_status = LinkedInCollectionStatus(ready=self.open_search())
        if not self.open_search():
            self.last_status = LinkedInCollectionStatus(
                ready=False,
                message="Falta configurar la URL de busqueda de LinkedIn.",
            )
            return

        if browser_runtime is None or not browser_runtime.active or browser_runtime.page is None:
            yield from self._iter_seed_candidates(limit)
            return

        yield from self._iter_live_company_candidates(browser_runtime, limit, company_filter)

    def _iter_seed_candidates(self, limit: int | None = None) -> Iterator[LinkedInCompany]:
        yielded = 0
        for payload in self._seed_results:
            if limit is not None and yielded >= limit:
                break

            company = self.parser.parse_search_result(payload)
            if not company.company_name:
                continue

            yielded += 1
            yield company

    def _iter_live_company_candidates(
        self,
        browser_runtime: BrowserRuntime,
        limit: int | None = None,
        company_filter: Callable[[LinkedInCompany], bool] | None = None,
    ) -> Iterator[LinkedInCompany]:
        page = browser_runtime.page
        if page is None:
            self.last_status = LinkedInCollectionStatus(
                ready=False,
                message="No hay una pagina activa de navegador para LinkedIn.",
            )
            return

        initial_search_results, search_warning = self._open_search_page(page)
        if self._is_captcha_page(page):
            self.last_status = LinkedInCollectionStatus(
                ready=False,
                captcha_pending=True,
                message="LinkedIn mostro captcha; resuelvelo manualmente y vuelve a correr.",
            )
            return

        if self._is_login_page(page):
            if not browser_runtime.headless and self._wait_for_manual_login(page):
                self._settle_page(page)
                initial_search_results = self._collect_search_results(page)
            else:
                login_message = (
                    "LinkedIn requiere login. Cambia `headless_browser=false`, "
                    "ejecuta `uv run python main.py`, inicia sesion una vez y luego vuelve a `true`."
                    if browser_runtime.headless
                    else "LinkedIn requiere login. Inicia sesion en la ventana del navegador y espera unos segundos."
                )
                self.last_status = LinkedInCollectionStatus(
                    ready=False,
                    login_required=True,
                    message=login_message,
                )
                return

        if self._is_login_page(page):
            self.last_status = LinkedInCollectionStatus(
                ready=False,
                login_required=True,
                message=(
                    "LinkedIn requiere login. Cambia `headless_browser=false`, "
                    "ejecuta `uv run python main.py`, inicia sesion una vez y luego vuelve a `true`."
                    if browser_runtime.headless
                    else "LinkedIn requiere login. Inicia sesion en la ventana del navegador y espera unos segundos."
                ),
            )
            return

        if not initial_search_results and not self._is_empty_search_page(page):
            self.last_status = LinkedInCollectionStatus(
                ready=False,
                message=search_warning or "No se pudo cargar la busqueda de LinkedIn de forma util.",
            )
            return

        yielded = 0
        seen_company_urls: set[str] = set()
        seen_search_pages: set[tuple[str, tuple[str, ...]]] = set()
        use_initial_search_results = True

        while True:
            self._settle_page(page)
            if use_initial_search_results:
                search_results = initial_search_results
                initial_search_results = []
                use_initial_search_results = False
            else:
                search_results = self._collect_search_results(page)
            if not search_results:
                break

            page_marker = self._build_search_page_marker(page, search_results)
            if page_marker in seen_search_pages:
                break
            seen_search_pages.add(page_marker)

            for payload in search_results:
                linkedin_url = canonicalize_linkedin_company_url(str(payload.get("linkedin_url") or ""))
                if not linkedin_url or linkedin_url in seen_company_urls:
                    continue

                seen_company_urls.add(linkedin_url)
                rough_company = LinkedInCompany(
                    company_name=str(payload.get("company_name") or "").strip(),
                    linkedin_url=linkedin_url,
                    country=self.parser.default_country,
                )
                if company_filter is not None and not company_filter(rough_company):
                    continue

                company = self._load_company_profile(
                    browser_runtime=browser_runtime,
                    linkedin_url=linkedin_url,
                    fallback_name=str(payload.get("company_name") or ""),
                    fallback_text=str(payload.get("text") or ""),
                )
                if self.last_status.login_required or self.last_status.captcha_pending:
                    return
                if company is None or not company.company_name:
                    continue

                yielded += 1
                yield company

                if limit is not None and yielded >= limit:
                    self.last_status = LinkedInCollectionStatus(ready=True)
                    return

            if limit is not None and yielded >= limit:
                break
            current_company_urls = {
                canonicalize_linkedin_company_url(str(item.get("linkedin_url") or ""))
                for item in search_results
                if isinstance(item, dict)
                and canonicalize_linkedin_company_url(str(item.get("linkedin_url") or ""))
            }
            if not self._go_to_next_results_page(page, current_company_urls):
                break

        if limit is not None and yielded < limit:
            status_message = self.last_status.message.strip()
            self.last_status = LinkedInCollectionStatus(
                ready=True,
                message=status_message or (
                    f"Se agotaron los resultados disponibles antes de completar la meta "
                    f"({yielded}/{limit})."
                ),
            )
            return

        self.last_status = LinkedInCollectionStatus(
            ready=True,
            message=search_warning if search_warning else (
                "" if yielded else "No se encontraron empresas nuevas utilizables en la busqueda actual."
            ),
        )

    def _load_company_profile(
        self,
        browser_runtime: BrowserRuntime,
        linkedin_url: str,
        fallback_name: str,
        fallback_text: str,
    ) -> LinkedInCompany | None:
        linkedin_url = canonicalize_linkedin_company_url(linkedin_url)
        if not linkedin_url:
            return None

        context = browser_runtime.context
        if context is None:
            return None

        profile_page = context.new_page()
        profile_page.set_default_timeout(PROFILE_NAVIGATION_TIMEOUT_MS)
        profile_page.set_default_navigation_timeout(PROFILE_NAVIGATION_TIMEOUT_MS)

        try:
            profile_page.goto(
                linkedin_url,
                wait_until="commit",
                timeout=PROFILE_NAVIGATION_TIMEOUT_MS,
            )
            self._settle_page(profile_page)

            if self._is_captcha_page(profile_page):
                self.last_status = LinkedInCollectionStatus(
                    ready=False,
                    captcha_pending=True,
                    message="LinkedIn mostro captcha dentro del perfil de empresa.",
                )
                return None

            if self._is_login_page(profile_page):
                if not browser_runtime.headless and self._wait_for_manual_login(profile_page):
                    self._settle_page(profile_page)
                else:
                    self.last_status = LinkedInCollectionStatus(
                        ready=False,
                        login_required=True,
                        message="LinkedIn redirigio a login al abrir una empresa.",
                    )
                    return None

            if self._is_login_page(profile_page):
                self.last_status = LinkedInCollectionStatus(
                    ready=False,
                    login_required=True,
                    message="LinkedIn redirigio a login al abrir una empresa.",
                )
                return None

            payload = self._extract_company_payload(profile_page, linkedin_url, fallback_name, fallback_text)
            company = self.parser.parse_search_result(
                {
                    **payload,
                    "text": "",
                    "visible_text": "",
                }
            )
            if company.company_name and company.website_url:
                return company

            about_url = self._build_about_url(linkedin_url)
            if about_url:
                profile_page.goto(
                    about_url,
                    wait_until="commit",
                    timeout=ABOUT_NAVIGATION_TIMEOUT_MS,
                )
                self._settle_page(profile_page)
                self._wait_for_about_details(profile_page)
                about_payload = self._extract_company_payload(
                    profile_page,
                    linkedin_url,
                    fallback_name,
                    fallback_text,
                )
                merged_payload = dict(payload)
                if about_payload.get("website_url"):
                    merged_payload["website_url"] = about_payload["website_url"]
                if about_payload.get("visible_email"):
                    merged_payload["visible_email"] = about_payload["visible_email"]
                if about_payload.get("text"):
                    merged_payload["text"] = f"{payload.get('text', '')}\n{about_payload['text']}".strip()
                company = self.parser.parse_search_result(
                    {
                        **merged_payload,
                        "text": "",
                        "visible_text": "",
                    }
                )

            if company.company_name:
                return company
            return None
        except Exception:
            return None
        finally:
            try:
                if not profile_page.is_closed():
                    profile_page.close()
            except Exception:
                pass

    def _extract_search_results(self, page: Any) -> list[dict[str, str]]:
        raw_results = page.evaluate(
            """
            () => {
              const items = [];
              const seen = new Set();
              const anchors = Array.from(document.querySelectorAll("a[href*='/company/']"));
              for (const anchor of anchors) {
                const href = anchor.href || "";
                const pathname = (() => { try { return new URL(href).pathname; } catch { return ""; } })();
                if (!pathname.includes("/company/")) continue;
                if (pathname.includes("/jobs/") || pathname.includes("/posts/")) continue;
                const name = (anchor.innerText || anchor.textContent || "").trim();
                const card = anchor.closest("li, div, article, section");
                const text = (card?.innerText || "").trim();
                const key = `${href}::${name}`;
                if (!name || seen.has(key)) continue;
                seen.add(key);
                items.push({
                  company_name: name,
                  linkedin_url: href,
                  text: text
                });
              }
              return items;
            }
            """
        )
        return [item for item in raw_results if isinstance(item, dict)]

    def _extract_company_payload(
        self,
        page: Any,
        linkedin_url: str,
        fallback_name: str,
        fallback_text: str,
    ) -> dict[str, str]:
        raw_payload = page.evaluate(
            """
            () => {
              const heading = document.querySelector("h1");
              const scope = document.querySelector("main") || document.body;
              const visibleText = (scope?.innerText || "").trim();
              const links = Array.from((scope || document).querySelectorAll("a[href]")).map((anchor) => ({
                href: anchor.href || "",
                text: (anchor.innerText || anchor.textContent || "").trim()
              }));
              const details = Array.from((scope || document).querySelectorAll("dt")).map((dt) => {
                const dd = dt.nextElementSibling;
                if (!dd || (dd.tagName || "").toLowerCase() !== "dd") {
                  return null;
                }
                return {
                  label: (dt.innerText || dt.textContent || "").trim(),
                  text: (dd.innerText || dd.textContent || "").trim(),
                  links: Array.from(dd.querySelectorAll("a[href]")).map((anchor) => ({
                    href: anchor.href || "",
                    text: (anchor.innerText || anchor.textContent || "").trim()
                  }))
                };
              }).filter(Boolean);
              return {
                company_name: (heading?.innerText || "").trim(),
                visible_text: visibleText,
                links: links,
                details: details
              };
            }
            """
        )

        visible_text = ""
        if isinstance(raw_payload, dict):
            visible_text = str(raw_payload.get("visible_text") or "")

        company_name = fallback_name.strip()
        if isinstance(raw_payload, dict) and raw_payload.get("company_name"):
            company_name = str(raw_payload.get("company_name") or "").strip()

        website_candidates: list[tuple[str, str]] = []
        seen_candidates: set[str] = set()

        def add_candidate(raw_candidate_url: str, candidate_label: str) -> None:
            candidate_url = self._clean_external_link(raw_candidate_url)
            if not candidate_url or candidate_url in seen_candidates:
                return
            if not self._looks_like_official_website_candidate(
                candidate_url,
                candidate_label,
                company_name,
            ):
                return

            website_candidates.append((candidate_url, candidate_label))
            seen_candidates.add(candidate_url)

        details = raw_payload.get("details", []) if isinstance(raw_payload, dict) else []
        for detail in details:
            if not isinstance(detail, dict):
                continue

            detail_label = str(detail.get("label") or "").strip()
            if not self._is_website_label(detail_label):
                continue

            for link_item in detail.get("links", []):
                if not isinstance(link_item, dict):
                    continue
                add_candidate(
                    str(link_item.get("href") or ""),
                    f"website_hint {detail_label} {str(link_item.get('text') or '').strip()}",
                )

            detail_text = str(detail.get("text") or "").strip()
            for candidate_url in self._extract_visible_text_candidates(detail_text):
                add_candidate(candidate_url, f"website_hint {detail_label}")

        website_url = self._pick_best_website_candidate(website_candidates, company_name)
        combined_text = "\n".join(part for part in [visible_text, fallback_text] if part).strip()
        return {
            "company_name": company_name,
            "linkedin_url": canonicalize_linkedin_company_url(linkedin_url) or linkedin_url,
            "website_url": website_url,
            "visible_email": "",
            "text": combined_text,
            "country": self.parser.default_country,
        }

    def _go_to_next_results_page(self, page: Any, current_company_urls: set[str]) -> bool:
        current_url = str(getattr(page, "url", "") or "")
        if not current_company_urls:
            return False

        next_url = self._build_next_results_url(current_url or self.search_url)

        selectors = [
            "button[aria-label*='Next']",
            "button[aria-label*='Siguiente']",
            "a[aria-label*='Next']",
            "a[aria-label*='Siguiente']",
            "button:has-text('Next')",
            "button:has-text('Siguiente')",
            "a:has-text('Next')",
            "a:has-text('Siguiente')",
        ]

        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.count() == 0:
                    continue
                if not locator.is_visible():
                    continue

                aria_disabled = locator.get_attribute("aria-disabled")
                disabled = locator.is_disabled()
                if disabled or aria_disabled == "true":
                    continue

                locator.scroll_into_view_if_needed()
                locator.click()
                self._settle_page(page)
                next_results = self._collect_next_page_results_with_retries(page, next_url)
                if not next_results:
                    return False
                if self._search_results_changed(page, current_url, current_company_urls, next_results):
                    return True
            except Exception:
                continue

        if not next_url:
            return False

        try:
            page.goto(
                next_url,
                wait_until="domcontentloaded",
                timeout=SEARCH_NAVIGATION_TIMEOUT_MS,
            )
        except Exception:
            try:
                page.goto(
                    next_url,
                    wait_until="commit",
                    timeout=SEARCH_RETRY_TIMEOUT_MS,
                )
            except Exception:
                pass

        self._settle_page(page)
        next_results = self._collect_next_page_results_with_retries(page, next_url)
        if not next_results:
            return False

        return self._search_results_changed(page, current_url, current_company_urls, next_results)

    @staticmethod
    def _settle_page(page: Any) -> None:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=SETTLE_LOAD_TIMEOUT_MS)
        except Exception:
            pass

        try:
            page.wait_for_timeout(SETTLE_WAIT_MS)
        except Exception:
            pass

    def _collect_search_results(self, page: Any) -> list[dict[str, str]]:
        deadline = monotonic() + (SEARCH_RESULTS_WAIT_MS / 1000)
        best_results: list[dict[str, str]] = []

        while monotonic() <= deadline:
            results = self._extract_search_results(page)
            if results:
                return results
            if self._is_login_page(page) or self._is_captcha_page(page) or self._is_empty_search_page(page):
                return []

            best_results = results
            try:
                page.wait_for_timeout(SEARCH_RESULTS_POLL_MS)
            except Exception:
                break

        return best_results

    def _collect_next_page_results_with_retries(
        self,
        page: Any,
        next_url: str,
    ) -> list[dict[str, str]]:
        for attempt in range(NEXT_PAGE_EMPTY_RETRIES + 1):
            self._settle_page(page)
            next_results = self._collect_search_results(page)
            if next_results:
                return next_results

            if self._is_login_page(page) or self._is_captcha_page(page) or self._is_empty_search_page(page):
                return []

            if attempt >= NEXT_PAGE_EMPTY_RETRIES:
                break

            try:
                page.wait_for_timeout(NEXT_PAGE_RETRY_WAIT_MS)
            except Exception:
                break

            if next_url:
                try:
                    page.goto(
                        next_url,
                        wait_until="commit",
                        timeout=SEARCH_RETRY_TIMEOUT_MS,
                    )
                except Exception:
                    pass

        self.last_status = LinkedInCollectionStatus(
            ready=True,
            message=(
                "LinkedIn devolvio una pagina siguiente vacia repetidas veces; "
                "se detuvo la corrida para evitar un falso fin o una paginacion inestable."
            ),
        )
        return []

    def _open_search_page(self, page: Any) -> tuple[list[dict[str, str]], str]:
        warnings: list[str] = []

        for wait_until, timeout_ms in (
            ("domcontentloaded", SEARCH_NAVIGATION_TIMEOUT_MS),
            ("commit", SEARCH_RETRY_TIMEOUT_MS),
        ):
            try:
                page.goto(
                    self.search_url,
                    wait_until=wait_until,
                    timeout=timeout_ms,
                )
            except Exception as exc:
                warnings.append(self._compact_exception(exc))

            self._settle_page(page)
            search_results = self._collect_search_results(page)
            if search_results or self._is_login_page(page) or self._is_captcha_page(page) or self._is_empty_search_page(page):
                warning_message = ""
                if warnings:
                    warning_message = (
                        "La busqueda de LinkedIn cargo con lentitud, pero se continuo. "
                        f"Detalles: {' || '.join(warnings)}"
                    )
                return search_results, warning_message

        warning_message = ""
        if warnings:
            warning_message = (
                "No se pudo abrir la busqueda de LinkedIn tras reintentos. "
                f"Detalles: {' || '.join(warnings)}"
            )
        return [], warning_message

    @staticmethod
    def _wait_for_about_details(page: Any) -> None:
        selectors = [
            "dt:has-text('Sitio web')",
            "dt:has-text('Website')",
            "dt",
            "main",
        ]

        for selector in selectors:
            try:
                page.locator(selector).first.wait_for(
                    state="visible",
                    timeout=ABOUT_DETAILS_WAIT_MS,
                )
                return
            except Exception:
                continue

    @staticmethod
    def _is_login_page(page: Any) -> bool:
        current_url = str(getattr(page, "url", "") or "").lower()
        if "/login" in current_url or "/checkpoint/lg/login" in current_url:
            return True

        try:
            return bool(
                page.locator("input[name='session_key'], #username, form.login__form").count()
            )
        except Exception:
            return False

    @staticmethod
    def _is_captcha_page(page: Any) -> bool:
        current_url = str(getattr(page, "url", "") or "").lower()
        if "captcha" in current_url or "checkpoint/challenge" in current_url:
            return True

        try:
            body_text = page.locator("body").inner_text(timeout=5_000).lower()
        except Exception:
            return False

        return "captcha" in body_text

    @staticmethod
    def _build_about_url(linkedin_url: str) -> str:
        normalized = canonicalize_linkedin_company_url(linkedin_url)
        if not normalized:
            return ""
        return f"{normalized}/about"

    @classmethod
    def _wait_for_manual_login(cls, page: Any, timeout_ms: int = 300_000) -> bool:
        elapsed = 0
        interval_ms = 2_000

        while elapsed < timeout_ms:
            cls._settle_page(page)
            if not cls._is_login_page(page) and not cls._is_captcha_page(page):
                return True

            try:
                page.wait_for_timeout(interval_ms)
            except Exception:
                return False

            elapsed += interval_ms

        return False

    @staticmethod
    def _clean_external_link(raw_url: str) -> str:
        parsed = urlparse(str(raw_url or "").strip())
        domain = normalize_domain(parsed.netloc)

        if is_linkedin_domain(domain) and "/redir/redirect" in parsed.path:
            target = parse_qs(parsed.query).get("url", [""])[0]
            raw_url = target

        candidate = normalize_url(raw_url)
        if not candidate:
            return ""

        parsed = urlparse(candidate)
        domain = normalize_domain(parsed.netloc)
        if is_linkedin_domain(domain) or LinkedInAgent._is_blocked_external_domain(domain):
            return ""

        return candidate

    @classmethod
    def _extract_visible_text_candidates(cls, text: str) -> list[str]:
        candidates: list[str] = []
        seen: set[str] = set()

        for match in VISIBLE_URL_PATTERN.finditer(text or ""):
            raw_candidate = match.group(0).strip().rstrip(".,);]")
            if "@" in raw_candidate:
                continue

            normalized_candidate = cls._clean_external_link(raw_candidate)
            if not normalized_candidate or normalized_candidate in seen:
                continue

            candidates.append(normalized_candidate)
            seen.add(normalized_candidate)

        return candidates

    def _build_search_page_marker(
        self,
        page: Any,
        search_results: list[dict[str, str]],
    ) -> tuple[str, tuple[str, ...]]:
        current_url = normalize_url(str(getattr(page, "url", "") or ""))
        current_company_urls = tuple(
            sorted(
                canonicalize_linkedin_company_url(str(item.get("linkedin_url") or ""))
                for item in search_results
                if isinstance(item, dict)
                and canonicalize_linkedin_company_url(str(item.get("linkedin_url") or ""))
            )
        )
        return current_url, current_company_urls

    def _search_results_changed(
        self,
        page: Any,
        previous_url: str,
        previous_company_urls: set[str],
        next_results: list[dict[str, str]],
    ) -> bool:
        new_url = str(getattr(page, "url", "") or "")
        new_company_urls = {
            canonicalize_linkedin_company_url(str(item.get("linkedin_url") or ""))
            for item in next_results
            if isinstance(item, dict)
            and canonicalize_linkedin_company_url(str(item.get("linkedin_url") or ""))
        }
        return normalize_url(new_url) != normalize_url(previous_url) or new_company_urls != previous_company_urls

    @staticmethod
    def _is_empty_search_page(page: Any) -> bool:
        try:
            body_text = page.locator("body").inner_text(timeout=2_000).lower()
        except Exception:
            return False

        empty_markers = (
            "no results found",
            "no matching results",
            "no hay resultados",
            "no se encontraron resultados",
            "intenta modificar tu busqueda",
            "try adjusting your search",
        )
        return any(marker in body_text for marker in empty_markers)

    @staticmethod
    def _build_next_results_url(current_url: str) -> str:
        normalized_url = normalize_url(current_url)
        if not normalized_url:
            return ""

        parsed = urlsplit(normalized_url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        current_page = 1
        raw_page = query.get("page", ["1"])[0]
        try:
            current_page = max(int(raw_page), 1)
        except ValueError:
            current_page = 1

        query["page"] = [str(current_page + 1)]
        rebuilt_query = urlencode(query, doseq=True)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, rebuilt_query, ""))

    @staticmethod
    def _compact_exception(exc: Exception) -> str:
        return " ".join(str(exc).split())

    @classmethod
    def _pick_best_website_candidate(
        cls,
        candidates: list[tuple[str, str]],
        company_name: str,
    ) -> str:
        best_url = ""
        best_score = -1

        for candidate_url, candidate_label in candidates:
            score = cls._score_website_candidate(candidate_url, candidate_label, company_name)
            if score > best_score:
                best_score = score
                best_url = candidate_url

        return best_url

    @classmethod
    def _score_website_candidate(
        cls,
        candidate_url: str,
        candidate_label: str,
        company_name: str,
    ) -> int:
        parsed = urlparse(candidate_url)
        domain = normalize_domain(parsed.netloc)
        if not domain or is_linkedin_domain(domain) or cls._is_blocked_external_domain(domain):
            return -1_000

        root_label = cls._normalize_text(f"{candidate_label} {candidate_url}")
        score = 0

        if candidate_label.startswith("website_hint"):
            score += 120

        if any(hint in root_label for hint in WEBSITE_HINTS):
            score += 100

        if cls._domain_matches_company_name(domain, company_name):
            score += 40

        if parsed.scheme == "https":
            score += 5

        if parsed.path in {"", "/"}:
            score += 10
        else:
            score += 2

        if candidate_label == "visible_text":
            score += 20

        return score

    @classmethod
    def _domain_matches_company_name(cls, domain: str, company_name: str) -> bool:
        normalized_company = cls._normalize_text(company_name)
        domain_label = cls._normalize_text(domain.split(".", 1)[0])

        if not normalized_company or not domain_label:
            return False

        tokens = [
            token
            for token in re.findall(r"[a-z0-9]+", normalized_company)
            if len(token) >= 4 and token not in COMPANY_TOKEN_STOPWORDS
        ]
        if not tokens:
            return False

        return any(token in domain_label for token in tokens)

    @staticmethod
    def _normalize_text(value: str) -> str:
        ascii_value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
        return ascii_value.lower()

    @staticmethod
    def _is_website_label(label: str) -> bool:
        normalized_label = LinkedInAgent._normalize_text(label)
        return any(hint in normalized_label for hint in WEBSITE_HINTS)

    @classmethod
    def _looks_like_official_website_candidate(
        cls,
        candidate_url: str,
        candidate_label: str,
        company_name: str,
    ) -> bool:
        parsed = urlparse(candidate_url)
        domain = normalize_domain(parsed.netloc)
        if not domain or is_linkedin_domain(domain) or cls._is_blocked_external_domain(domain):
            return False

        normalized_label = cls._normalize_text(candidate_label)
        if any(hint in normalized_label for hint in WEBSITE_HINTS):
            return True

        return cls._domain_matches_company_name(domain, company_name)

    @staticmethod
    def _is_blocked_external_domain(domain: str) -> bool:
        normalized_domain = normalize_domain(domain)
        if not normalized_domain:
            return True

        return any(
            is_subdomain_of(normalized_domain, blocked_domain)
            for blocked_domain in BLOCKED_EXTERNAL_DOMAINS
        )
