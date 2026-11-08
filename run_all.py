#!/usr/bin/env python3
"""PulseBalanços - Orquestrador Central de Execução (Run All).

Pipeline unificado para ingestão, saneamento e carga de demonstrações financeiras
da CVM (DFP/ITR) e indicadores fundamentalistas.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sys
from pathlib import Path

from src.extractors.cvm import CVMExtractor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pulsebalancos.orchestrator")


def parse_args() -> argparse.Namespace:
    current_year = datetime.datetime.now().year
    parser = argparse.ArgumentParser(description="PulseBalanços - ETL Pipeline CVM")
    parser.add_argument(
        "--year",
        type=int,
        default=current_year,
        help=f"Ano de referência para processamento (padrão: {current_year})",
    )
    parser.add_argument(
        "--doc-type",
        type=str,
        default="ALL",
        choices=["ALL", "DFP", "ITR"],
        help="Tipo de documento a processar (ALL, DFP, ITR)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignora cabeçalhos de cache HTTP (ETag) e força novo download",
    )
    return parser.parse_args()


def generate_step_summary(summaries: list, output_path: Path) -> None:
    """Gera sumário em Markdown para publicação no GitHub Actions."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 🚀 PulseBalanços - Sumário de Execução ETL CVM",
        f"**Data da Execução:** {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')} (BRT)\n",
        "| Documento | Ano | Status | Cache Hit | Demonstrações Extraídas | Total Registros |",
        "|:---|:---:|:---:|:---:|:---|:---:|",
    ]
    for s in summaries:
        status_icon = "✅" if s.status == "SUCCESS" else ("⏭️" if "SKIPPED" in s.status else "❌")
        lines.append(
            f"| **{s.doc_type}** | {s.year} | {status_icon} `{s.status}` | "
            f"{'Sim' if s.cache_hit else 'Não'} | {', '.join(s.statements_extracted) or '-'} | {s.total_records:,} |"
        )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    logger.info("Sumário salvo em %s", output_path)


def main() -> int:
    args = parse_args()
    logger.info("Iniciando PulseBalanços ETL - Ano: %s | Tipo: %s", args.year, args.doc_type)

    # 1. Atualização do catálogo de companhias abertas e tickers B3
    logger.info("Etapa 1: Atualizando catálogo mestre de companhias CVM e B3...")
    try:
        from scripts.build_companies_catalog import build_companies_catalog
        build_companies_catalog()
    except Exception as e:
        logger.warning("Falha ao atualizar catálogo de companhias: %s", e)

    # 2. Ingestão de Publicações Oficiais e Fatos Relevantes Recentes (CVM IPE)
    logger.info("Etapa 2: Monitorando últimas publicações e fatos relevantes (IPE 2026/2025)...")
    try:
        from scripts.build_latest_publications import build_latest_publications
        build_latest_publications()
    except Exception as e:
        logger.warning("Falha ao atualizar feed de publicações recentes: %s", e)

    # 3. Geração de relatórios e demonstrações detalhadas com histórico multi-ano (2022-2025)
    logger.info("Etapa 3: Gerando relatórios individuais com série histórica multi-ano em data/companies/...")
    try:
        from scripts.build_company_details import build_company_details
        build_company_details(years=[2022, 2023, 2024, 2025])
    except Exception as e:
        logger.warning("Falha ao gerar demonstrações detalhadas por empresa: %s", e)

    # 4. Extração e saneamento de demonstrações contábeis (CVMExtractor)
    logger.info("Etapa 4: Ingestão de demonstrações financeiras (DFP/ITR)...")
    extractor = CVMExtractor()
    if args.force:
        extractor._cache.clear()

    doc_types = ["DFP", "ITR"] if args.doc_type == "ALL" else [args.doc_type]
    summaries = []

    for dt in doc_types:
        summary = extractor.process_financial_year(doc_type=dt, year=args.year)
        summaries.append(summary)

    # 5. Gera sumário de execução
    generate_step_summary(summaries, Path("data/etl_summary.md"))

    logger.info("Execução finalizada com sucesso.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

