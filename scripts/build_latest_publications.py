#!/usr/bin/env python3
"""PulseBalanços - Monitor de Últimas Publicações e Fatos Relevantes CVM (IPE).

Extrai e consolida em tempo real:
- Fatos Relevantes (M&A, Guidances, Aumentos de Capital, Reorganizações)
- Comunicados ao Mercado
- Proventos e Avisos aos Acionistas (Dividendos e JCP)
- Dados Econômico-Financeiros e Informações Trimestrais/Anuais
- Atas e Convocações de Assembleias Gerais (AGO/AGE)

Gera:
    data/ultimas_publicacoes.json
"""

from __future__ import annotations

import io
import json
import logging
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import polars as pl
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pulsebalancos.latest_publications")

URL_IPE_TEMPLATE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{year}.zip"


def download_bytes(url: str) -> bytes:
    logger.info("Baixando: %s", url)
    resp = requests.get(url, timeout=90, headers={"User-Agent": "PulseDataLabs-PulseBalancos/1.0"})
    resp.raise_for_status()
    return resp.content


def parse_ipe_zip(content: bytes, year: int) -> pl.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        matching = [f for f in zf.namelist() if f.endswith(".csv")]
        if not matching:
            return pl.DataFrame()
        with zf.open(matching[0]) as f:
            csv_bytes = f.read()

    df = pl.read_csv(
        io.BytesIO(csv_bytes),
        separator=";",
        encoding="iso-8859-1",
        quote_char=None,
        truncate_ragged_lines=True,
        ignore_errors=True,
    )
    df = df.rename({c: c.strip() for c in df.columns})

    return df.with_columns(
        [
            pl.col("CNPJ_Companhia").str.replace_all(r"\D", "").str.zfill(14).alias("cnpj"),
            pl.col("Codigo_CVM").cast(pl.Int64, strict=False).alias("cd_cvm_int"),
            pl.lit(year).alias("ano_filing"),
        ]
    )


def build_latest_publications(output_path: Optional[Path] = None, limit: int = 1000) -> int:
    output_path = Path(output_path or Path("data/ultimas_publicacoes.json"))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Carrega catálogo de companhias para enriquecer com ticker e setor
    catalog_path = Path("data/companies_catalog.json")
    catalog_map = {}
    if catalog_path.exists():
        try:
            with open(catalog_path, "r", encoding="utf-8") as f:
                cat = json.load(f)
            catalog_map = {
                c["cnpj"]: {
                    "ticker": c.get("ticker_principal"),
                    "slug": c.get("slug"),
                    "setor": c.get("setor_cvm"),
                    "uf": c.get("uf"),
                }
                for c in cat
            }
        except Exception as e:
            logger.warning("Não foi possível carregar catálogo para enriquecimento: %s", e)

    # 2. Ingestão dos arquivos IPE mais recentes (2026 prioritário, complementando com 2025 se necessário)
    dfs = []
    for year in [2026, 2025]:
        try:
            content = download_bytes(URL_IPE_TEMPLATE.format(year=year))
            df = parse_ipe_zip(content, year)
            if not df.is_empty():
                dfs.append(df)
                logger.info("Carregados %d documentos IPE de %d.", len(df), year)
        except Exception as e:
            logger.warning("Falha ao baixar IPE %d: %s", year, e)

    if not dfs:
        logger.error("Nenhum dado IPE disponível.")
        return 0

    df_all = pl.concat(dfs, how="diagonal")

    # 3. Tratamento de campos e seleção dos mais recentes
    # Ordena por Data_Entrega (formato YYYY-MM-DD ou com hora)
    df_sorted = (
        df_all.filter(pl.col("Data_Entrega").is_not_null())
        .sort(["Data_Entrega", "Protocolo_Entrega"], descending=[True, True])
        .head(limit)
    )

    publications: List[Dict[str, Any]] = []
    for r in df_sorted.iter_rows(named=True):
        cnpj = r["cnpj"]
        info_cat = catalog_map.get(cnpj, {})

        cat = (r.get("Categoria") or "").strip()
        tipo = (r.get("Tipo") or "").strip()
        esp = (r.get("Especie") or "").strip()
        assunto = (r.get("Assunto") or "").strip()

        # Determina tag de destaque
        badge = "Documento"
        if "Fato Relevante" in cat:
            badge = "Fato Relevante"
        elif "Comunicado ao Mercado" in cat:
            badge = "Comunicado"
        elif "Aviso aos Acionistas" in cat or "Proventos" in assunto or "JCP" in assunto or "Dividendos" in assunto:
            badge = "Proventos"
        elif "Dados Econômico" in cat or "DFP" in cat or "ITR" in cat or "Balanço" in assunto:
            badge = "Resultados"
        elif "Assembleia" in cat or "AGO" in tipo or "AGE" in tipo:
            badge = "Assembleia"

        # Título descritivo limpo
        titulo = assunto if assunto and assunto != "None" else (esp if esp and esp != "None" else tipo)
        if not titulo or titulo == "None":
            titulo = f"Publicação Oficial CVM - {cat}"

        doc_item = {
            "cnpj": cnpj,
            "razao_social": (r.get("Nome_Companhia") or "").strip(),
            "ticker": info_cat.get("ticker"),
            "slug": info_cat.get("slug"),
            "setor": info_cat.get("setor"),
            "uf": info_cat.get("uf"),
            "cd_cvm": r.get("cd_cvm_int"),
            "data_entrega": str(r.get("Data_Entrega") or ""),
            "data_referencia": str(r.get("Data_Referencia") or ""),
            "categoria": cat,
            "tipo": tipo,
            "especie": esp,
            "assunto": titulo,
            "badge": badge,
            "url_download": str(r.get("Link_Download") or ""),
            "url_cvm": f"https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx?codigoCVM={r.get('cd_cvm_int')}"
            if r.get("cd_cvm_int")
            else "https://dados.cvm.gov.br",
        }
        publications.append(doc_item)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(publications, f, ensure_ascii=False, indent=2)

    logger.info("Salvos %d documentos mais recentes em %s (%.2f KB).", len(publications), output_path, output_path.stat().st_size / 1024)
    return len(publications)


def main() -> int:
    build_latest_publications()
    return 0


if __name__ == "__main__":
    sys.exit(main())
