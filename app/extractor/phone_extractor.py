from __future__ import annotations

import re
from collections.abc import Iterable

try:
    import phonenumbers
    from phonenumbers import NumberParseException, PhoneNumberFormat, PhoneNumberType

    _PHONENUMBERS_AVAILABLE = True
except ImportError:
    _PHONENUMBERS_AVAILABLE = False

from app.website.website_crawler import WebsitePage


_COUNTRY_REGION: dict[str, str] = {
    "colombia": "CO",
    "méxico": "MX",
    "mexico": "MX",
    "argentina": "AR",
    "chile": "CL",
    "perú": "PE",
    "peru": "PE",
    "ecuador": "EC",
    "venezuela": "VE",
    "españa": "ES",
    "spain": "ES",
    "estados unidos": "US",
    "united states": "US",
    "usa": "US",
    "brasil": "BR",
    "brazil": "BR",
    "panamá": "PA",
    "panama": "PA",
    "costa rica": "CR",
    "guatemala": "GT",
    "honduras": "HN",
    "el salvador": "SV",
    "nicaragua": "NI",
    "paraguay": "PY",
    "uruguay": "UY",
    "bolivia": "BO",
    "cuba": "CU",
    "república dominicana": "DO",
    "republica dominicana": "DO",
}

# Country calling code prefix per region (for ranking)
_REGION_CC: dict[str, str] = {
    "CO": "+57", "MX": "+52", "AR": "+54", "CL": "+56",
    "PE": "+51", "EC": "+593", "VE": "+58", "ES": "+34",
    "US": "+1",  "BR": "+55", "PA": "+507", "CR": "+506",
    "GT": "+502", "HN": "+504", "SV": "+503", "NI": "+505",
    "PY": "+595", "UY": "+598", "BO": "+591", "CU": "+53", "DO": "+1809",
}

# tel: href values, e.g. href="tel:+573001234567"
_TEL_HREF_RE = re.compile(r'href=["\']tel:([+\d\s\-\.\(\)]+)["\']', re.IGNORECASE)

# +XX international numbers in visible text
_INTL_RE = re.compile(r'\+\s*\d[\d\s\-\.\(\)]{7,18}')

# Local 10-digit: 3XX or 6XX prefix with optional separators (Colombian style)
_LOCAL_10_RE = re.compile(r'(?<!\d)([36]\d{2})[\s\-\.]?(\d{3})[\s\-\.]?(\d{4})(?!\d)')

# (XXX) XXXXXXX — parenthesized area code
_PAREN_RE = re.compile(r'\((\d{2,4})\)\s*(\d[\d\s\-\.]{5,11}\d)')

_NON_DIGITS_RE = re.compile(r'\D')


def _region_for(country: str) -> str:
    return _COUNTRY_REGION.get(country.strip().lower(), "CO")


def _parse_phone(raw: str, region: str) -> str | None:
    if not _PHONENUMBERS_AVAILABLE:
        return None
    try:
        number = phonenumbers.parse(raw.strip(), region)
        if phonenumbers.is_valid_number(number):
            return phonenumbers.format_number(number, PhoneNumberFormat.INTERNATIONAL)
    except NumberParseException:
        pass
    return None


def _rank_phones(phones: list[str], region: str) -> list[str]:
    """
    Sort so that the best WhatsApp candidates come first:
      1. Same country + mobile  (ideal for WhatsApp)
      2. Same country + landline
      3. Foreign numbers        (last resort)
    """
    cc = _REGION_CC.get(region, "")

    def _score(phone: str) -> tuple[int, int]:
        same_country = 1 if (cc and phone.startswith(cc)) else 0
        is_mobile = 0
        if _PHONENUMBERS_AVAILABLE:
            try:
                n = phonenumbers.parse(phone)
                is_mobile = 1 if phonenumbers.number_type(n) == PhoneNumberType.MOBILE else 0
            except Exception:
                pass
        # Lower tuple = higher priority
        return (1 - same_country, 1 - is_mobile)

    return sorted(phones, key=_score)


class PhoneExtractor:
    def extract_from_pages(self, pages: Iterable[WebsitePage], country_hint: str = "") -> list[str]:
        region = _region_for(country_hint)
        collected: list[str] = []
        seen_digits: set[str] = set()

        for page in pages:
            for phone in self._from_page(page, region):
                digits = _NON_DIGITS_RE.sub("", phone)
                if digits not in seen_digits:
                    seen_digits.add(digits)
                    collected.append(phone)

        # Rank: same-country mobile first, then same-country landline, foreign last
        return _rank_phones(collected, region)

    def _from_page(self, page: WebsitePage, region: str) -> list[str]:
        found: list[str] = []

        # tel: links are the most reliable signal
        for m in _TEL_HREF_RE.finditer(page.html):
            result = _parse_phone(m.group(1), region)
            if result:
                found.append(result)

        # +XX international format in visible text
        for m in _INTL_RE.finditer(page.text):
            result = _parse_phone(m.group(0), region)
            if result:
                found.append(result)

        # Local 10-digit (3XX / 6XX prefix)
        for m in _LOCAL_10_RE.finditer(page.text):
            raw = m.group(1) + m.group(2) + m.group(3)
            result = _parse_phone(raw, region)
            if result:
                found.append(result)

        # (XXX) XXXXXXXX patterns
        for m in _PAREN_RE.finditer(page.text):
            raw = m.group(1) + _NON_DIGITS_RE.sub("", m.group(2))
            result = _parse_phone(raw, region)
            if result:
                found.append(result)

        return found
