from __future__ import annotations

import json
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from app.linkedin.company_parser import LinkedInCompany


PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = "places.id,places.displayName,places.websiteUri,places.formattedAddress"
PAGE_SIZE = 20


@dataclass(frozen=True)
class MapsCollectionStatus:
    ready: bool = False
    login_required: bool = False
    captcha_pending: bool = False
    message: str = ""


class GoogleMapsAgent:
    def __init__(
        self,
        api_key: str,
        search_query: str,
        default_country: str = "Colombia",
    ) -> None:
        self.api_key = api_key.strip()
        self.search_query = search_query.strip()
        self.default_country = default_country
        self.last_status = MapsCollectionStatus(ready=bool(self.api_key and self.search_query))

    def open_search(self) -> bool:
        if not self.api_key:
            self.last_status = MapsCollectionStatus(
                ready=False,
                message="Falta configurar GOOGLE_MAPS_API_KEY en el .env.",
            )
            return False
        if not self.search_query:
            self.last_status = MapsCollectionStatus(
                ready=False,
                message="Falta configurar MAPS_SEARCH_QUERY en el .env.",
            )
            return False
        self.last_status = MapsCollectionStatus(ready=True)
        return True

    def iter_company_candidates(
        self,
        limit: int | None = None,
        browser_runtime: Any = None,
        company_filter: Callable[[LinkedInCompany], bool] | None = None,
    ) -> Iterator[LinkedInCompany]:
        if not self.open_search():
            return

        yielded = 0
        page_token = ""
        seen_place_ids: set[str] = set()

        while True:
            try:
                places, next_token = self._fetch_page(page_token)
            except urllib.error.HTTPError as exc:
                self.last_status = MapsCollectionStatus(
                    ready=False,
                    message=f"Error HTTP {exc.code} al consultar Places API: {exc.reason}",
                )
                return
            except Exception as exc:
                self.last_status = MapsCollectionStatus(
                    ready=False,
                    message=f"Error al consultar Places API: {exc}",
                )
                return

            if not places:
                break

            for place in places:
                if limit is not None and yielded >= limit:
                    self.last_status = MapsCollectionStatus(ready=True)
                    return

                place_id = str(place.get("id") or "")
                if not place_id or place_id in seen_place_ids:
                    continue
                seen_place_ids.add(place_id)

                company = self._parse_place(place)
                if not company.company_name or not company.website_url:
                    continue

                if company_filter is not None and not company_filter(company):
                    continue

                yielded += 1
                yield company

            if not next_token:
                break
            page_token = next_token

        if limit is not None and yielded < limit:
            self.last_status = MapsCollectionStatus(
                ready=True,
                message=f"Se agotaron los resultados de Google Maps ({yielded}/{limit}).",
            )
        else:
            self.last_status = MapsCollectionStatus(ready=True)

    def _fetch_page(self, page_token: str = "") -> tuple[list[dict], str]:
        body: dict[str, Any] = {
            "textQuery": self.search_query,
            "pageSize": PAGE_SIZE,
            "languageCode": "es",
        }
        if page_token:
            body["pageToken"] = page_token

        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            PLACES_SEARCH_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": FIELD_MASK,
            },
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))

        return data.get("places", []), data.get("nextPageToken", "")

    @staticmethod
    def _sanitize(text: str) -> str:
        return "".join(c for c in text if unicodedata.category(c) != "Cf").strip()

    def _parse_place(self, place: dict) -> LinkedInCompany:
        place_id = str(place.get("id") or "")
        name = self._sanitize(str((place.get("displayName") or {}).get("text") or ""))
        website = str(place.get("websiteUri") or "").strip().rstrip("/")
        address = str(place.get("formattedAddress") or "").strip()
        country = self._extract_country(address)
        maps_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}" if place_id else ""

        return LinkedInCompany(
            company_name=name,
            linkedin_url=maps_url,
            website_url=website,
            visible_email="",
            country=country or self.default_country,
        )

    @staticmethod
    def _extract_country(address: str) -> str:
        if not address:
            return ""
        parts = [p.strip() for p in address.split(",")]
        return parts[-1] if parts else ""
