#!/usr/bin/env python3
"""PulseFinancials - Orquestrador Central de Execução (Run All).

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
logger = logging.getLogger("pulsefinancials.orchestrator")


def parse_args() -> argparse.Namespace:
    current_year = datetime.datetime.now().year
    parser = argparse.ArgumentParser(description="PulseFinancials - ETL Pipeline CVM")
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
        "# 🚀 PulseFinancials - Sumário de Execução ETL CVM",
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
    logger.info("Iniciando PulseFinancials ETL - Ano: %s | Tipo: %s", args.year, args.doc_type)

    extractor = CVMExtractor()
    if args.force:
        extractor._cache.clear()

    doc_types = ["DFP", "ITR"] if args.doc_type == "ALL" else [args.doc_type]
    summaries = []

    for dt in doc_types:
        summary = extractor.process_financial_year(doc_type=dt, year=args.year)
        summaries.append(summary)

    # Gera sumário de execução
    generate_step_summary(summaries, Path("data/etl_summary.md"))

    logger.info("Execução finalizada com sucesso.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
