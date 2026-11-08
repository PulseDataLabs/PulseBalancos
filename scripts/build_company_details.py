#!/usr/bin/env python3
"""PulseBalanços - Gerador de Arquivos Detalhados por Companhia com Histórico Multi-Ano.

Para cada companhia com dados financeiros disponíveis, gera:
    data/companies/{cnpj}.json
Contendo:
- Metadados cadastrais, auditores e links oficiais CVM
- Série histórica multi-ano (2022 a 2025) da Demonstração do Resultado (DRE) IFRS
- Série histórica do Balanço Patrimonial Ativo (BPA) e Passivo (BPP)
- Variação horizontal anual (% YoY) e Análise Vertical (% AV)
- Posição acionária e governança (FRE)
- Fatos Relevantes e documentos protocolados recentes (IPE 2026/2025)
"""

from __future__ import annotations

import io
import json
import logging
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

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

URL_DFP_TEMPLATE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{year}.zip"


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


def build_company_details(output_dir: Optional[Path] = None, years: Optional[List[int]] = None) -> int:
    if years is None:
        years = [2022, 2023, 2024, 2025]

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

    # Dicionários de histórico por CNPJ e por Conta
    # dre_history[cnpj][cd_conta] = {"ds_conta": ..., "nivel": ..., "valores": {year: val}}
    dre_history: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(lambda: defaultdict(lambda: {"valores": {}}))
    bpa_history: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(lambda: defaultdict(lambda: {"valores": {}}))
    bpp_history: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(lambda: defaultdict(lambda: {"valores": {}}))
    company_years: Dict[str, Set[int]] = defaultdict(set)

    # 1. Ingestão de todos os anos da série histórica DFP
    for y in years:
        url = URL_DFP_TEMPLATE.format(year=y)
        try:
            dfp_bytes = download_bytes(url)
            with zipfile.ZipFile(io.BytesIO(dfp_bytes)) as zf:
                logger.info("Processando DFP %d (DRE, BPA, BPP)...", y)
                df_dre = parse_statement_csv(zf, f"dfp_cia_aberta_DRE_con_{y}.csv")
                df_bpa = parse_statement_csv(zf, f"dfp_cia_aberta_BPA_con_{y}.csv")
                df_bpp = parse_statement_csv(zf, f"dfp_cia_aberta_BPP_con_{y}.csv")

            for row in df_dre.iter_rows(named=True):
                cnpj = row["cnpj"]
                cd = str(row.get("CD_CONTA") or "").strip()
                ds = str(row.get("DS_CONTA") or "").strip()
                vl = float(row.get("vl_ajustado") or 0.0)
                entry = dre_history[cnpj][cd]
                entry["ds_conta"] = ds
                entry["nivel"] = cd.count(".") + 1
                entry["valores"][str(y)] = vl
                company_years[cnpj].add(y)

            for row in df_bpa.iter_rows(named=True):
                cnpj = row["cnpj"]
                cd = str(row.get("CD_CONTA") or "").strip()
                ds = str(row.get("DS_CONTA") or "").strip()
                vl = float(row.get("vl_ajustado") or 0.0)
                entry = bpa_history[cnpj][cd]
                entry["ds_conta"] = ds
                entry["nivel"] = cd.count(".") + 1
                entry["valores"][str(y)] = vl
                company_years[cnpj].add(y)

            for row in df_bpp.iter_rows(named=True):
                cnpj = row["cnpj"]
                cd = str(row.get("CD_CONTA") or "").strip()
                ds = str(row.get("DS_CONTA") or "").strip()
                vl = float(row.get("vl_ajustado") or 0.0)
                entry = bpp_history[cnpj][cd]
                entry["ds_conta"] = ds
                entry["nivel"] = cd.count(".") + 1
                entry["valores"][str(y)] = vl
                company_years[cnpj].add(y)

        except Exception as e:
            logger.warning("Erro ao processar DFP %d: %s", y, e)

    # 2. Extrai acionistas FRE
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

    # 3. Extrai documentos IPE mais recentes (2026 e 2025)
    logger.info("Carregando documentos IPE (2026/2025)...")
    docs_by_cnpj = defaultdict(list)
    try:
        ipe = CVMIPEDocumentsScraper()
        for doc_year in [2026, 2025]:
            for d in ipe.extract_year(doc_year):
                if len(docs_by_cnpj[d.cnpj]) < 20:
                    docs_by_cnpj[d.cnpj].append({
                        "data": d.data_entrega,
                        "categoria": d.categoria,
                        "tipo": d.tipo,
                        "assunto": (d.assunto or d.especie or d.tipo)[:140],
                        "url": d.url_download,
                    })
    except Exception as e:
        logger.warning("Falha ao carregar documentos IPE: %s", e)

    # 4. Exporta arquivos detalhados
    cnpjs_to_process = set(dre_history.keys()).union(
        c["cnpj"] for c in catalog if c.get("ticker_principal") or c.get("is_active")
    )
    logger.info("Gerando arquivos detalhados com histórico multi-ano para %d companhias...", len(cnpjs_to_process))

    count = 0
    for cnpj in cnpjs_to_process:
        cad = catalog_by_cnpj.get(cnpj, {})
        if not cad:
            continue

        available_years = sorted(list(company_years.get(cnpj, set())))
        ultimo_ano = available_years[-1] if available_years else max(years)
        ano_anterior = str(ultimo_ano - 1)
        ultimo_ano_str = str(ultimo_ano)

        # Processa DRE
        dre_accounts_raw = dre_history.get(cnpj, {})
        rec_liq_recente = (dre_accounts_raw.get("3.01", {}).get("valores", {}).get(ultimo_ano_str, 0.0))

        dre_list = []
        for cd, acc in sorted(dre_accounts_raw.items()):
            vals = acc["valores"]
            val_rec = vals.get(ultimo_ano_str)
            val_ant = vals.get(ano_anterior)
            var_yoy = (
                round(((val_rec - val_ant) / abs(val_ant)) * 100, 2)
                if (val_ant and val_ant != 0 and val_rec is not None)
                else None
            )
            av = (
                round((val_rec / rec_liq_recente) * 100, 2)
                if (rec_liq_recente and rec_liq_recente > 0 and val_rec is not None)
                else None
            )
            dre_list.append({
                "cd_conta": cd,
                "ds_conta": acc["ds_conta"],
                "nivel": acc["nivel"],
                "valores": vals,
                "valor_recente": val_rec if val_rec is not None else (vals.get(ano_anterior) or 0.0),
                "var_yoy": var_yoy,
                "analise_vertical": av,
            })

        # Processa BPA
        bpa_accounts_raw = bpa_history.get(cnpj, {})
        ativo_tot_recente = (bpa_accounts_raw.get("1", {}).get("valores", {}).get(ultimo_ano_str, 0.0))
        bpa_list = []
        for cd, acc in sorted(bpa_accounts_raw.items()):
            vals = acc["valores"]
            val_rec = vals.get(ultimo_ano_str)
            val_ant = vals.get(ano_anterior)
            var_yoy = (
                round(((val_rec - val_ant) / abs(val_ant)) * 100, 2)
                if (val_ant and val_ant != 0 and val_rec is not None)
                else None
            )
            av = (
                round((val_rec / ativo_tot_recente) * 100, 2)
                if (ativo_tot_recente and ativo_tot_recente > 0 and val_rec is not None)
                else None
            )
            bpa_list.append({
                "cd_conta": cd,
                "ds_conta": acc["ds_conta"],
                "nivel": acc["nivel"],
                "valores": vals,
                "valor_recente": val_rec if val_rec is not None else (vals.get(ano_anterior) or 0.0),
                "var_yoy": var_yoy,
                "analise_vertical": av,
            })

        # Processa BPP
        bpp_accounts_raw = bpp_history.get(cnpj, {})
        passivo_tot_recente = (bpp_accounts_raw.get("2", {}).get("valores", {}).get(ultimo_ano_str, 0.0))
        bpp_list = []
        for cd, acc in sorted(bpp_accounts_raw.items()):
            vals = acc["valores"]
            val_rec = vals.get(ultimo_ano_str)
            val_ant = vals.get(ano_anterior)
            var_yoy = (
                round(((val_rec - val_ant) / abs(val_ant)) * 100, 2)
                if (val_ant and val_ant != 0 and val_rec is not None)
                else None
            )
            av = (
                round((val_rec / passivo_tot_recente) * 100, 2)
                if (passivo_tot_recente and passivo_tot_recente > 0 and val_rec is not None)
                else None
            )
            bpp_list.append({
                "cd_conta": cd,
                "ds_conta": acc["ds_conta"],
                "nivel": acc["nivel"],
                "valores": vals,
                "valor_recente": val_rec if val_rec is not None else (vals.get(ano_anterior) or 0.0),
                "var_yoy": var_yoy,
                "analise_vertical": av,
            })

        # Resumo financeiro mais recente e histórico resumido
        pl_recente = bpp_accounts_raw.get("2.03", {}).get("valores", {}).get(ultimo_ano_str)
        lucro_raw = dre_accounts_raw.get("3.11", dre_accounts_raw.get("3.09", {}))
        lucro_recente = lucro_raw.get("valores", {}).get(ultimo_ano_str)

        # Histórico resumido de KPIs por ano
        historico_kpis = []
        for y_val in available_years:
            y_str = str(y_val)
            historico_kpis.append({
                "ano": y_val,
                "ativo_total": bpa_accounts_raw.get("1", {}).get("valores", {}).get(y_str),
                "patrimonio_liquido": bpp_accounts_raw.get("2.03", {}).get("valores", {}).get(y_str),
                "receita_liquida": dre_accounts_raw.get("3.01", {}).get("valores", {}).get(y_str),
                "lucro_liquido": lucro_raw.get("valores", {}).get(y_str),
            })

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
            "anos_disponiveis": available_years,
            "ano_balanco_recente": ultimo_ano,
            "resumo_financeiro": {
                "ativo_total": ativo_tot_recente or cad.get("ativo_total"),
                "patrimonio_liquido": pl_recente or cad.get("patrimonio_liquido"),
                "receita_liquida": rec_liq_recente or cad.get("receita_liquida"),
                "lucro_liquido": lucro_recente if lucro_recente is not None else cad.get("lucro_liquido"),
                "historico": historico_kpis,
            },
            "dre": dre_list,
            "bpa": bpa_list,
            "bpp": bpp_list,
            "acionistas": sorted(shareholders_by_cnpj.get(cnpj, []), key=lambda x: x["percentual"], reverse=True),
            "documentos": docs_by_cnpj.get(cnpj, []),
            "url_cvm": f"https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx?codigoCVM={cad.get('cd_cvm')}"
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
