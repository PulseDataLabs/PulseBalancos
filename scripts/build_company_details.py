#!/usr/bin/env python3
"""PulseBalanços - Gerador de Arquivos Detalhados por Companhia (DRE, BPA, BPP, Docs, Acionistas).

Para cada companhia com dados financeiros disponíveis, gera:
    data/companies/{cnpj}.json
Contendo:
- Metadados cadastrais e auditoria
- Demonstração do Resultado (DRE) linha a linha IFRS
- Balanço Patrimonial Ativo (BPA) e Passivo (BPP)
- Posição acionária e governança (FRE)
- Fatos Relevantes e documentos protocolados na CVM (IPE) com links diretos
"""

from __future__ import annotations

import io
import json
import logging
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import polars as pl
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.scrapers.cvm_ipe_documents import CVMIPEDocumentsScraper
from src.scrapers.cvm_shareholders import CVMShareholdersScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pulsebalancos.company_details")

URL_DFP_2023 = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_2023.zip"


def download_bytes(url: str) -> bytes:
    logger.info("Baixando: %s", url)
    resp = requests.get(url, timeout=90, headers={"User-Agent": "PulseDataLabs-PulseBalancos/1.0"})
    resp.raise_for_status()
    return resp.content


def parse_statement_csv(zf: zipfile.ZipFile, csv_filename: str) -> pl.DataFrame:
    with zf.open(csv_filename) as f:
        df = pl.read_csv(io.BytesIO(f.read()), separator=";", encoding="iso-8859-1", ignore_errors=True)
    df = df.rename({c: c.strip().upper() for c in df.columns})
    if "ORDEM_EXERC" in df.columns:
        df = df.filter(pl.col("ORDEM_EXERC").str.strip_chars().str.to_uppercase() == "ÚLTIMO")

    is_num = df["VL_CONTA"].dtype.is_numeric()
    val_expr = (
        pl.col("VL_CONTA").cast(pl.Float64)
        if is_num
        else pl.col("VL_CONTA").cast(pl.Utf8).str.replace(",", ".").cast(pl.Float64, strict=False)
    )
    escala = pl.col("ESCALA_MOEDA").str.strip_chars().str.to_uppercase()
    val_ajustado = pl.when(escala == "MIL").then(val_expr * 1000.0).otherwise(val_expr)

    return df.with_columns(
        [
            pl.col("CNPJ_CIA").str.replace_all(r"\D", "").str.zfill(14).alias("cnpj"),
            val_ajustado.alias("vl_ajustado"),
        ]
    )


def build_company_details(output_dir: Optional[Path] = None, year: int = 2023) -> int:
    output_dir = Path(output_dir or Path("data/companies"))
    output_dir.mkdir(parents=True, exist_ok=True)

    catalog_path = Path("data/companies_catalog.json")
    if not catalog_path.exists():
        logger.error("Catálogo companies_catalog.json não encontrado!")
        return 0

    with open(catalog_path, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    catalog_by_cnpj = {c["cnpj"]: c for c in catalog}
    logger.info("Carregadas %d companhias do catálogo mestre.", len(catalog_by_cnpj))

    # 1. Download do DFP 2023
    dfp_bytes = download_bytes(URL_DFP_2023)
    with zipfile.ZipFile(io.BytesIO(dfp_bytes)) as zf:
        logger.info("Processando DRE...")
        df_dre = parse_statement_csv(zf, "dfp_cia_aberta_DRE_con_2023.csv")
        logger.info("Processando BPA...")
        df_bpa = parse_statement_csv(zf, "dfp_cia_aberta_BPA_con_2023.csv")
        logger.info("Processando BPP...")
        df_bpp = parse_statement_csv(zf, "dfp_cia_aberta_BPP_con_2023.csv")

    # Agrupa demonstrações por CNPJ
    dre_by_cnpj = defaultdict(list)
    for row in df_dre.iter_rows(named=True):
        cnpj = row["cnpj"]
        cd = str(row.get("CD_CONTA") or "").strip()
        ds = str(row.get("DS_CONTA") or "").strip()
        vl = float(row.get("vl_ajustado") or 0.0)
        nivel = cd.count(".") + 1
        dre_by_cnpj[cnpj].append({"cd_conta": cd, "ds_conta": ds, "nivel": nivel, "valor": vl})

    bpa_by_cnpj = defaultdict(list)
    for row in df_bpa.iter_rows(named=True):
        cnpj = row["cnpj"]
        cd = str(row.get("CD_CONTA") or "").strip()
        ds = str(row.get("DS_CONTA") or "").strip()
        vl = float(row.get("vl_ajustado") or 0.0)
        nivel = cd.count(".") + 1
        bpa_by_cnpj[cnpj].append({"cd_conta": cd, "ds_conta": ds, "nivel": nivel, "valor": vl})

    bpp_by_cnpj = defaultdict(list)
    for row in df_bpp.iter_rows(named=True):
        cnpj = row["cnpj"]
        cd = str(row.get("CD_CONTA") or "").strip()
        ds = str(row.get("DS_CONTA") or "").strip()
        vl = float(row.get("vl_ajustado") or 0.0)
        nivel = cd.count(".") + 1
        bpp_by_cnpj[cnpj].append({"cd_conta": cd, "ds_conta": ds, "nivel": nivel, "valor": vl})

    # 2. Extrai acionistas e documentos do cache ou scrapers
    logger.info("Carregando acionistas FRE...")
    shareholders_by_cnpj = defaultdict(list)
    seen_sh = defaultdict(set)
    try:
        fre = CVMShareholdersScraper()
        for s in fre.extract_shareholders(2024):
            if s.acionista and s.acionista.upper() not in ["OUTROS", "AÇÕES TESOURARIA", "ACOES EM TESOURARIA"]:
                if s.acionista not in seen_sh[s.cnpj_companhia]:
                    seen_sh[s.cnpj_companhia].add(s.acionista)
                    shareholders_by_cnpj[s.cnpj_companhia].append({
                        "nome": s.acionista,
                        "percentual": round(s.percentual_total_acoes, 2),
                        "controlador": s.is_controlador,
                    })
    except Exception as e:
        logger.warning("Falha ao carregar acionistas: %s", e)

    logger.info("Carregando documentos IPE...")
    docs_by_cnpj = defaultdict(list)
    try:
        ipe = CVMIPEDocumentsScraper()
        for d in ipe.extract_year(2024):
            docs_by_cnpj[d.cnpj].append({
                "data": d.data_entrega,
                "categoria": d.categoria,
                "tipo": d.tipo,
                "assunto": (d.assunto or d.especie or d.tipo)[:140],
                "url": d.url_download,
            })
    except Exception as e:
        logger.warning("Falha ao carregar documentos IPE: %s", e)

    # 3. Exporta arquivo JSON individual para cada companhia com DRE ou dados cadastrais
    count = 0
    cnpjs_to_process = set(dre_by_cnpj.keys()).union(
        c["cnpj"] for c in catalog if c.get("ticker_principal") or c.get("is_active")
    )

    logger.info("Gerando arquivos detalhados para %d companhias...", len(cnpjs_to_process))

    for cnpj in cnpjs_to_process:
        cad = catalog_by_cnpj.get(cnpj, {})
        if not cad:
            continue

        dre_accounts = dre_by_cnpj.get(cnpj, [])
        bpa_accounts = bpa_by_cnpj.get(cnpj, [])
        bpp_accounts = bpp_by_cnpj.get(cnpj, [])

        # Calcula Análise Vertical para DRE (% da Receita Líquida 3.01)
        rec_liq = next((a["valor"] for a in dre_accounts if a["cd_conta"] == "3.01"), 0.0)
        for a in dre_accounts:
            a["analise_vertical"] = round((a["valor"] / rec_liq) * 100, 2) if rec_liq > 0 else None

        # Calcula Análise Vertical para BPA (% do Ativo Total 1)
        ativo_tot = next((a["valor"] for a in bpa_accounts if a["cd_conta"] == "1"), 0.0)
        for a in bpa_accounts:
            a["analise_vertical"] = round((a["valor"] / ativo_tot) * 100, 2) if ativo_tot > 0 else None

        # Calcula Análise Vertical para BPP (% do Passivo Total 2)
        passivo_tot = next((a["valor"] for a in bpp_accounts if a["cd_conta"] == "2"), 0.0)
        for a in bpp_accounts:
            a["analise_vertical"] = round((a["valor"] / passivo_tot) * 100, 2) if passivo_tot > 0 else None

        company_doc = {
            "cnpj": cnpj,
            "razao_social": cad.get("razao_social"),
            "nome_fantasia": cad.get("nome_fantasia"),
            "ticker_principal": cad.get("ticker_principal"),
            "tickers_list": cad.get("tickers_list", []),
            "slug": cad.get("slug"),
            "cd_cvm": cad.get("cd_cvm"),
            "setor_cvm": cad.get("setor_cvm"),
            "categoria_registro": cad.get("categoria_registro"),
            "situacao_cvm": cad.get("situacao_cvm"),
            "is_active": cad.get("is_active", True),
            "cidade": cad.get("cidade"),
            "uf": cad.get("uf"),
            "auditor": cad.get("auditor"),
            "ano_balanco_recente": year,
            "resumo_financeiro": {
                "ativo_total": cad.get("ativo_total"),
                "patrimonio_liquido": cad.get("patrimonio_liquido"),
                "receita_liquida": cad.get("receita_liquida"),
                "lucro_liquido": cad.get("lucro_liquido"),
            },
            "dre": dre_accounts,
            "bpa": bpa_accounts,
            "bpp": bpp_accounts,
            "acionistas": sorted(shareholders_by_cnpj.get(cnpj, []), key=lambda x: x["percentual"], reverse=True),
            "documentos": docs_by_cnpj.get(cnpj, [])[:15],
            "url_cvm": f"https://rad.cvm.gov.br/ENET/consultaExterna/default.aspx?codigoCVM={cad.get('cd_cvm')}"
            if cad.get("cd_cvm")
            else "https://dados.cvm.gov.br",
        }

        file_path = output_dir / f"{cnpj}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(company_doc, f, ensure_ascii=False, indent=2)

        count += 1

    logger.info("Concluído! %d arquivos detalhados gerados em %s.", count, output_dir)
    return count


def main() -> int:
    build_company_details()
    return 0


if __name__ == "__main__":
    sys.exit(main())
