"""
Recupera el CRM a partir de los dominios guardados en state.json.
No llama a la API de Google Maps. Solo crawlea websites y extrae correos.
No modifica state.json.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from app.core.config import load_config
from app.extractor.email_extractor import EmailExtractor
from app.extractor.email_ranker import EmailRanker
from app.storage.crm_manager import CRMManager, CRMRecord
from app.website.website_crawler import WebsiteCrawler

_TLD_COUNTRY: dict[str, str] = {
    ".co.cr": "Costa Rica",
    ".com.co": "Colombia",
    ".com.gt": "Guatemala",
    ".com.pa": "Panamá",
    ".com.mx": "México",
    ".com.pe": "Perú",
    ".com.ec": "Ecuador",
    ".com.ve": "Venezuela",
    ".com.ar": "Argentina",
    ".com.cl": "Chile",
    ".co": "Colombia",
    ".cr": "Costa Rica",
    ".gt": "Guatemala",
    ".pa": "Panamá",
    ".mx": "México",
    ".pe": "Perú",
    ".ec": "Ecuador",
    ".ve": "Venezuela",
    ".ar": "Argentina",
    ".cl": "Chile",
}


def _infer_country(domain: str) -> str:
    domain = domain.lower()
    for suffix, country in _TLD_COUNTRY.items():
        if domain.endswith(suffix):
            return country
    return ""


def main() -> None:
    config = load_config()

    state_path = config.state_path
    if not state_path.exists():
        print("ERROR: No se encontró state.json")
        sys.exit(1)

    with open(state_path, encoding="utf-8") as f:
        state = json.load(f)

    saved_attempts = [
        v for v in state.get("attempts", {}).values() if v.get("status") == "saved"
    ]
    total = len(saved_attempts)
    print(f"Empresas a recuperar: {total}")
    print(f"CRM destino: {config.crm_path}")
    print("-" * 60)

    crm = CRMManager(config.crm_path)
    crm.ensure_workbook_exists()

    # Dominios ya presentes en el CRM (para reanudar sin re-crawlear)
    already_done: set[str] = set()
    for row in crm.load_rows():
        if row.dominio:
            already_done.add(row.dominio.strip().lower())
    skipped_already = sum(1 for a in saved_attempts if a.get("domain", "").strip().lower() in already_done)
    print(f"Ya en CRM (se saltarán): {skipped_already}")
    print(f"Pendientes de crawlear : {total - skipped_already}")
    print("-" * 60)

    crawler = WebsiteCrawler(
        max_pages=config.max_internal_pages,
        timeout_seconds=config.company_timeout_seconds,
    )
    extractor = EmailExtractor()
    ranker = EmailRanker()

    recovered = 0
    no_email = 0
    failed = 0

    for i, attempt in enumerate(saved_attempts, 1):
        company_name: str = attempt.get("company_name", "")
        domain: str = attempt.get("domain", "")
        linkedin_url: str = attempt.get("linkedin_url", "")

        if not domain:
            failed += 1
            continue

        if domain.strip().lower() in already_done:
            print(f"[{i}/{total}] SKIP      {company_name[:45]}")
            continue

        website_url = f"https://{domain}"
        crawl_result = crawler.crawl(website_url)

        if not crawl_result.pages:
            website_url = f"http://{domain}"
            crawl_result = crawler.crawl(website_url)

        fecha = datetime.now().date().isoformat()
        pais = _infer_country(domain)

        if not crawl_result.pages:
            crm.upsert_record(CRMRecord(
                empresa=company_name,
                linkedin_url=linkedin_url,
                dominio=domain,
                pais=pais,
                fecha=fecha,
                estado="website_failed",
                detalle=" || ".join(crawl_result.errors) or "Sin HTML útil.",
            ))
            failed += 1
            print(f"[{i}/{total}] FALLO    {company_name[:45]}")
            continue

        emails = extractor.extract_from_pages(crawl_result.pages)
        ranked = ranker.select_top(emails, company_domain=domain, limit=config.max_ranked_emails)

        if not ranked:
            crm.upsert_record(CRMRecord(
                empresa=company_name,
                linkedin_url=linkedin_url,
                dominio=domain,
                pais=pais,
                fecha=fecha,
                estado="no_email",
                detalle="No se encontraron correos en el website.",
            ))
            no_email += 1
            print(f"[{i}/{total}] SIN EMAIL {company_name[:45]}")
            continue

        padded = ranked + [""] * max(0, config.max_ranked_emails - len(ranked))
        crm.upsert_record(CRMRecord(
            empresa=company_name,
            linkedin_url=linkedin_url,
            dominio=domain,
            correo_1=padded[0] if len(padded) > 0 else "",
            correo_2=padded[1] if len(padded) > 1 else "",
            correo_3=padded[2] if len(padded) > 2 else "",
            pais=pais,
            fecha=fecha,
            estado="saved",
            detalle="Correos recuperados.",
        ))
        recovered += 1
        print(f"[{i}/{total}] OK        {company_name[:40]}  →  {ranked[0]}")

    print()
    print("=" * 60)
    print(f"Recuperadas con email : {recovered}")
    print(f"Sin email esta vez    : {no_email}")
    print(f"Website fallido       : {failed}")
    print(f"Total procesadas      : {i}")
    print("CRM listo para continuar desde la fila 635 del plan.")


if __name__ == "__main__":
    main()
