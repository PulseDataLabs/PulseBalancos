#!/usr/bin/env python3
"""PulseBalanços - Gerador do Catálogo de Conglomerados Prudenciais do BACEN.

Extrai e consolida a base mais recente de Conglomerados Prudenciais (BACEN):
- Mapeia Líderes e Participantes
- Índice rápido por CNPJ base (8 dígitos)
- Estatísticas de classes, líderes e jurisdição
- Exporta para data/conglomerados.json
"""

from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.scrapers.bacen_conglomerados import BacenConglomeradosScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pulsebalancos.conglomerados")


def build_conglomerados_catalog(year: int = 2026, month: int = 10, output_path: Path | None = None) -> Path:
    scraper = BacenConglomeradosScraper()
    logger.info("Extraindo conglomerados do BACEN para %02d/%d...", month, year)
    records = scraper.extract_conglomerados(year, month)

    by_conglomerado: Dict[str, Dict[str, Any]] = {}
    by_cnpj_base: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    stats_classes: Dict[str, int] = defaultdict(int)

    for r in records:
        c_name = r.nome_conglomerado
        if c_name not in by_conglomerado:
            by_conglomerado[c_name] = {
                "nome_conglomerado": c_name,
                "classe_conglomerado": r.classe_conglomerado,
                "lider": None,
                "participantes": [],
                "total_participantes": 0,
            }
            stats_classes[r.classe_conglomerado] += 1

        entidade = {
            "cnpj_base": r.cnpj_base,
            "nome_participante": r.nome_participante,
            "tipo_participacao": r.tipo_participacao,
            "is_lider": r.is_lider,
            "data_inicio": r.data_inicio,
            "uf": r.uf,
        }

        if r.is_lider and not by_conglomerado[c_name]["lider"]:
            by_conglomerado[c_name]["lider"] = entidade

        by_conglomerado[c_name]["participantes"].append(entidade)
        by_conglomerado[c_name]["total_participantes"] += 1

        if r.cnpj_base:
            by_cnpj_base[r.cnpj_base].append({
                "nome_conglomerado": c_name,
                "classe_conglomerado": r.classe_conglomerado,
                "is_lider": r.is_lider,
                "tipo_participacao": r.tipo_participacao,
            })

    output_data = {
        "metadata": {
            "fonte": "Banco Central do Brasil - DESIG/DIACO",
            "regulamentacao": "Resolução CMN nº 4.950/2021 (Conglomerados Prudenciais)",
            "ano_referencia": year,
            "mes_referencia": month,
            "data_extracao": datetime.now().isoformat(),
            "total_conglomerados": len(by_conglomerado),
            "total_entidades": len(records),
            "distribuicao_classes": dict(stats_classes),
        },
        "conglomerados": list(by_conglomerado.values()),
        "indice_cnpj_base": dict(by_cnpj_base),
    }

    if output_path is None:
        output_path = PROJECT_ROOT / "data" / "conglomerados.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(
        "Catálogo de Conglomerados gerado com sucesso em %s (%d conglomerados, %d participantes).",
        output_path,
        len(by_conglomerado),
        len(records),
    )
    return output_path


if __name__ == "__main__":
    current_year = datetime.now().year
    current_month = 10 if current_year == 2026 else datetime.now().month
    build_conglomerados_catalog(year=current_year, month=current_month)
