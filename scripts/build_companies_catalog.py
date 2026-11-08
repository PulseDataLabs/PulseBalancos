#!/usr/bin/env python3
"""PulseBalanços - Gerador do Catálogo Mestre de Companhias Abertas (CVM + B3).

Ingere e consolida:
1. Cadastro oficial da CVM (cad_cia_aberta.csv) com CNPJ, CVM, Razão Social, UF e Município.
2. Mapeamento de Tickers B3 via CVM FCA (fca_cia_aberta_valor_mobiliario).
3. Geração de slugs padronizados para navegação web (estilo Balanços.AI).
4. Exportação colunar (Parquet) e JSON de alta velocidade.
"""

from __future__ import annotations

import io
import json
import logging
import re
import sys
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import polars as pl
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pulsebalancos.companies_catalog")

URL_CAD_CVM = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
URL_FCA_TEMPLATE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{year}.zip"
URL_DFP_TEMPLATE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{year}.zip"


def slugify(text: str) -> str:
    """Converte um nome corporativo em um slug amigável para URLs."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


def download_bytes(url: str, session: requests.Session) -> bytes:
    logger.info("Baixando: %s", url)
    resp = session.get(url, timeout=60)
    resp.raise_for_status()
    return resp.content


def fetch_b3_tickers(session: requests.Session, year: int = 2024) -> pl.DataFrame:
    """Extrai os códigos de negociação (tickers) da B3 a partir do formulário cadastral FCA."""
    url = URL_FCA_TEMPLATE.format(year=year)
    try:
        content = download_bytes(url, session)
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            matching = [f for f in zf.namelist() if "fca_cia_aberta_valor_mobiliario" in f]
            if not matching:
                logger.warning("Arquivo de valores mobiliários não encontrado no FCA %d", year)
                return pl.DataFrame()

            with zf.open(matching[0]) as csv_file:
                raw_bytes = csv_file.read()

        df_vm = pl.read_csv(
            io.BytesIO(raw_bytes),
            separator=";",
            encoding="iso-8859-1",
            ignore_errors=True,
            infer_schema_length=5000,
        )

        df_vm = df_vm.rename({c: c.strip() for c in df_vm.columns})

        # Filtra apenas ações e units negociadas na B3 com ticker válido
        df_tickers = (
            df_vm.filter(
                (pl.col("Codigo_Negociacao").is_not_null())
                & (pl.col("Codigo_Negociacao").str.strip_chars() != "")
                & (pl.col("Codigo_Negociacao").str.strip_chars() != "NÃO HÁ")
                & (pl.col("Codigo_Negociacao").str.strip_chars() != "-")
                & (
                    (pl.col("Mercado").str.to_uppercase() == "BOLSA")
                    | (pl.col("Sigla_Entidade_Administradora").str.to_uppercase() == "B3")
                )
            )
            .select(
                [
                    pl.col("CNPJ_Companhia").str.replace_all(r"\D", "").str.zfill(14).alias("cnpj"),
                    pl.col("Codigo_Negociacao").str.strip_chars().str.to_uppercase().alias("ticker"),
                ]
            )
            .unique()
        )

        logger.info("Tickers extraídos da B3 via FCA: %d registros únicos.", len(df_tickers))
        return df_tickers

    except Exception as e:
        logger.warning("Não foi possível carregar tickers do FCA %d: %s", year, e)
        return pl.DataFrame()


def fetch_latest_financial_metrics(session: requests.Session, year: int = 2024) -> pl.DataFrame:
    """Extrai métricas financeiras essenciais (PL, Receita, Lucro, Ativo) do DFP mais recente."""
    url = URL_DFP_TEMPLATE.format(year=year)
    try:
        content = download_bytes(url, session)
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            file_names = zf.namelist()

            def read_file(name_pattern: str) -> Optional[pl.DataFrame]:
                matching = [f for f in file_names if re.search(name_pattern, f, re.IGNORECASE)]
                if not matching:
                    return None
                with zf.open(matching[0]) as f:
                    df = pl.read_csv(io.BytesIO(f.read()), separator=";", encoding="iso-8859-1", ignore_errors=True)
                df = df.rename({c: c.strip().upper() for c in df.columns})
                if "ORDEM_EXERC" in df.columns:
                    df = df.filter(pl.col("ORDEM_EXERC").str.strip_chars().str.to_uppercase() == "ÚLTIMO")
                return df

            df_dre = read_file(rf"dfp_cia_aberta_DRE_con_{year}\.csv")
            df_bpp = read_file(rf"dfp_cia_aberta_BPP_con_{year}\.csv")
            df_bpa = read_file(rf"dfp_cia_aberta_BPA_con_{year}\.csv")

            if df_dre is None or df_bpp is None or df_bpa is None:
                return pl.DataFrame()

            def clean_df(df_input: pl.DataFrame, cd_conta_val: str, alias_name: str) -> pl.DataFrame:
                filtered = df_input.filter(pl.col("CD_CONTA").str.strip_chars() == cd_conta_val)
                if filtered.is_empty():
                    return pl.DataFrame(schema={"cnpj": pl.Utf8, alias_name: pl.Float64})

                val_num = (
                    pl.when(filtered["VL_CONTA"].dtype.is_numeric())
                    .then(pl.col("VL_CONTA").cast(pl.Float64))
                    .otherwise(
                        pl.col("VL_CONTA").cast(pl.Utf8).str.replace(",", ".").cast(pl.Float64, strict=False)
                    )
                )
                escala = pl.col("ESCALA_MOEDA").str.strip_chars().str.to_uppercase()
                adjusted = pl.when(escala == "MIL").then(val_num * 1000.0).otherwise(val_num)

                return (
                    filtered.with_columns(
                        [
                            pl.col("CNPJ_CIA").str.replace_all(r"\D", "").str.zfill(14).alias("cnpj"),
                            adjusted.alias(alias_name),
                        ]
                    )
                    .select(["cnpj", alias_name])
                    .unique(subset=["cnpj"])
                )

            # Ativo Total (1)
            df_ativo = clean_df(df_bpa, "1", "ativo_total")
            # PL (2.03)
            df_pl = clean_df(df_bpp, "2.03", "patrimonio_liquido")
            # Receita Líquida (3.01)
            df_rec = clean_df(df_dre, "3.01", "receita_liquida")
            # Lucro Líquido (3.11 ou 3.09)
            df_lucro_raw = df_dre.filter(pl.col("CD_CONTA").str.strip_chars().is_in(["3.11", "3.09"]))
            if not df_lucro_raw.is_empty():
                val_num = (
                    pl.when(df_lucro_raw["VL_CONTA"].dtype.is_numeric())
                    .then(pl.col("VL_CONTA").cast(pl.Float64))
                    .otherwise(
                        pl.col("VL_CONTA").cast(pl.Utf8).str.replace(",", ".").cast(pl.Float64, strict=False)
                    )
                )
                escala = pl.col("ESCALA_MOEDA").str.strip_chars().str.to_uppercase()
                adjusted = pl.when(escala == "MIL").then(val_num * 1000.0).otherwise(val_num)
                df_lucro = (
                    df_lucro_raw.with_columns(
                        [
                            pl.col("CNPJ_CIA").str.replace_all(r"\D", "").str.zfill(14).alias("cnpj"),
                            adjusted.alias("lucro_liquido"),
                        ]
                    )
                    .group_by("cnpj")
                    .agg(pl.col("lucro_liquido").last())
                )
            else:
                df_lucro = pl.DataFrame(schema={"cnpj": pl.Utf8, "lucro_liquido": pl.Float64})

            # Join das métricas contábeis com coalesce das chaves CNPJ
            metrics = df_ativo.join(df_pl, on="cnpj", how="full", coalesce=True)
            metrics = metrics.join(df_rec, on="cnpj", how="full", coalesce=True)
            metrics = metrics.join(df_lucro, on="cnpj", how="full", coalesce=True)
            metrics = metrics.with_columns(pl.lit(year).alias("ano_balanco_recente"))
            logger.info("Métricas financeiras do DFP %d extraídas para %d companhias.", year, len(metrics))
            return metrics

    except Exception as e:
        logger.warning("Não foi possível carregar demonstrações financeiras do DFP %d: %s", year, e)
        return pl.DataFrame()


def build_companies_catalog(year: int = 2024, output_dir: Optional[Path] = None) -> pl.DataFrame:
    """Gera o catálogo mestre de companhias da CVM enriquecido com dados de B3 e Geografia."""
    output_dir = Path(output_dir or Path("data"))
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": "PulseDataLabs-PulseBalancos/1.0"})

    # 1. Download do cadastro oficial CVM
    cad_bytes = download_bytes(URL_CAD_CVM, session)
    df_cad = pl.read_csv(
        io.BytesIO(cad_bytes),
        separator=";",
        encoding="iso-8859-1",
        ignore_errors=True,
    )
    df_cad = df_cad.rename({col: col.upper() for col in df_cad.columns})

    # 2. Download e agregação de tickers da B3
    df_tickers = fetch_b3_tickers(session, year=year)

    # Agrupa tickers por CNPJ
    if not df_tickers.is_empty():
        # Lógica para definir ticker principal: prioriza ações terminadas em 4 (PN) ou 3 (ON) ou 11 (Unit)
        def pick_primary_ticker(tickers: Any) -> Optional[str]:
            if tickers is None or len(tickers) == 0:
                return None
            tickers_list = list(tickers)
            for suffix in ("4", "3", "11"):
                for t in tickers_list:
                    if t and t.endswith(suffix):
                        return t
            return tickers_list[0]

        grouped_tickers = (
            df_tickers.group_by("cnpj")
            .agg(pl.col("ticker").alias("tickers_list"))
            .with_columns(
                pl.col("tickers_list")
                .map_elements(pick_primary_ticker, return_dtype=pl.Utf8)
                .alias("ticker_principal")
            )
        )
    else:
        grouped_tickers = pl.DataFrame(
            schema={"cnpj": pl.Utf8, "tickers_list": pl.List(pl.Utf8), "ticker_principal": pl.Utf8}
        )

    # 3. Tratamento e normalização dos dados cadastrais
    df_companies = df_cad.select(
        [
            pl.col("CNPJ_CIA").str.replace_all(r"\D", "").str.zfill(14).alias("cnpj"),
            pl.col("CD_CVM").cast(pl.Int64, strict=False).alias("cd_cvm"),
            pl.col("DENOM_SOCIAL").str.strip_chars().alias("razao_social"),
            pl.col("DENOM_COMERC").str.strip_chars().alias("nome_fantasia"),
            pl.col("SETOR_ATIV").str.strip_chars().alias("setor_cvm"),
            pl.col("CATEG_REG").str.strip_chars().alias("categoria_registro"),
            pl.col("SIT").str.strip_chars().str.to_uppercase().alias("situacao_cvm"),
            (pl.col("SIT").str.strip_chars().str.to_uppercase() == "ATIVO").alias("is_active"),
            pl.col("MUN").str.strip_chars().alias("cidade"),
            pl.col("UF").str.strip_chars().alias("uf"),
            pl.col("DT_REG").str.to_date("%Y-%m-%d", strict=False).alias("dt_registro"),
            pl.col("DT_CANCEL").str.to_date("%Y-%m-%d", strict=False).alias("dt_cancelamento"),
            pl.col("AUDITOR").str.strip_chars().alias("auditor"),
        ]
    ).unique(subset=["cnpj"])

    # 4. Join com os tickers
    df_final = df_companies.join(grouped_tickers, on="cnpj", how="left")

    # 5. Enriquecimento com as métricas financeiras mais recentes (DFP 2023)
    df_metrics = fetch_latest_financial_metrics(session, year=2023)
    if not df_metrics.is_empty():
        df_final = df_final.join(df_metrics, on="cnpj", how="left")
    else:
        df_final = df_final.with_columns(
            [
                pl.lit(None).cast(pl.Float64).alias("ativo_total"),
                pl.lit(None).cast(pl.Float64).alias("patrimonio_liquido"),
                pl.lit(None).cast(pl.Float64).alias("receita_liquida"),
                pl.lit(None).cast(pl.Float64).alias("lucro_liquido"),
                pl.lit(None).cast(pl.Int32).alias("ano_balanco_recente"),
            ]
        )

    # 6. Gera slugs amigáveis
    slugs = [slugify(name) for name in df_final["razao_social"].to_list()]
    df_final = df_final.with_columns(pl.Series("slug", slugs))

    # Ordena por atividade, patrimônio líquido ou receita
    df_final = df_final.sort(["is_active", "patrimonio_liquido", "razao_social"], descending=[True, True, False])

    # 6. Exportação para Parquet e JSON
    parquet_path = output_dir / "companies_catalog.parquet"
    json_path = output_dir / "companies_catalog.json"

    df_final.write_parquet(parquet_path)

    # Converte para lista de dicionários para JSON
    companies_dict = df_final.to_dicts()
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(companies_dict, f, ensure_ascii=False, indent=2, default=str)

    logger.info("Catálogo consolidado com sucesso!")
    logger.info("Total de companhias: %d", len(df_final))
    logger.info("Companhias ATIVAS: %d", len(df_final.filter(pl.col("is_active"))))
    logger.info(
        "Companhias com tickers na B3: %d",
        len(df_final.filter(pl.col("ticker_principal").is_not_null())),
    )
    logger.info("Arquivos gerados:")
    logger.info(" - %s (%.2f KB)", parquet_path, parquet_path.stat().st_size / 1024)
    logger.info(" - %s (%.2f KB)", json_path, json_path.stat().st_size / 1024)

    return df_final


def main() -> int:
    df = build_companies_catalog()
    # Exibe amostra das empresas ativas com ticker na B3
    sample = (
        df.filter(pl.col("ticker_principal").is_not_null())
        .select(["ticker_principal", "razao_social", "setor_cvm", "uf", "cidade"])
        .head(10)
    )
    print("\n--- Amostra de Empresas Cadastradas (B3 / CVM) ---")
    print(sample)
    return 0


if __name__ == "__main__":
    sys.exit(main())
