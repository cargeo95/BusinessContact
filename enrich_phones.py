"""
Enriches existing CRM records with phone numbers scraped from company websites.
Resumable: companies that already have a phone number are skipped automatically.

Usage:
    uv run python enrich_phones.py
"""
from __future__ import annotations

from app.core.config import load_config
from app.extractor.phone_extractor import PhoneExtractor
from app.storage.crm_manager import CRMManager
from app.website.link_discovery import LinkDiscovery
from app.website.website_crawler import WebsiteCrawler


def main() -> None:
    config = load_config()
    crm = CRMManager(config.crm_path)
    crm.ensure_workbook_exists()  # migrates schema → adds telefono_1, telefono_2 columns

    all_rows = crm.load_rows()
    candidates = [r for r in all_rows if r.dominio and not r.telefono_1]

    total = len(candidates)
    already_done = sum(1 for r in all_rows if r.telefono_1)
    print(f"CRM: {len(all_rows)} registros  |  ya con teléfono: {already_done}  |  pendientes: {total}")

    if not total:
        print("Todas las empresas con dominio ya tienen teléfono.")
        return

    crawler = WebsiteCrawler(
        link_discovery=LinkDiscovery(),
        max_pages=config.max_internal_pages,
        timeout_seconds=config.company_timeout_seconds,
    )
    extractor = PhoneExtractor()
    found_count = 0

    for idx, record in enumerate(candidates, start=1):
        print(f"[{idx}/{total}] {record.empresa} ({record.dominio})", end=" ... ", flush=True)

        try:
            result = crawler.crawl(record.dominio)
            phones = extractor.extract_from_pages(result.pages, country_hint=record.pais)

            if not phones:
                print("sin teléfono")
                continue

            t1 = phones[0]
            t2 = phones[1] if len(phones) >= 2 else ""

            crm.update_phones_by_domain(record.dominio, t1, t2)
            found_count += 1
            display = "  |  ".join(p for p in [t1, t2] if p)
            print(display)

        except Exception as exc:
            print(f"ERROR: {exc}")

    print(f"\nResultado: {found_count} de {total} empresas con al menos un teléfono.")


if __name__ == "__main__":
    main()
