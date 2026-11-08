"""Módulo de Ingestão e Extração em Memória de Dados Contábeis da CVM.

Responsável por:
- Download de arquivos DFP, ITR e FCA com suporte a ETag/Last-Modified.
- Descompactação e processamento direto em memória (Streams/BytesIO).
- Parsing de arquivos CSV (encoding ISO-8859-1) usando Polars.
- Saneamento de dados: filtro de 'ÚLTIMO' exercício, saneamento de CNPJ e
  ajuste de escala monetária (conversão de escala 'MIL' para valor nominal em Reais).
"""

from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import polars as pl
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configuração de Logger estruturado
logger = logging.getLogger("pulsebalancos.extractors.cvm")


@dataclass
class HttpCacheMetadata:
    """Metadados para controle de cache HTTP (ETag e Last-Modified)."""

    etag: Optional[str] = None
    last_modified: Optional[str] = None
    content_length: Optional[int] = None
    last_checked_iso: Optional[str] = None


@dataclass
class ExtractionSummary:
    """Sumário com estatísticas de processamento de um pacote DFP/ITR."""

    doc_type: str
    year: int
    statements_extracted: List[str] = field(default_factory=list)
    total_records: int = 0
    cache_hit: bool = False
    status: str = "PENDING"
    error_message: Optional[str] = None


class CVMExtractor:
    """Extrator de alto desempenho para demonstrações financeiras da CVM (DFP/ITR/FCA)."""

    BASE_URL_DFP = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{year}.zip"
    BASE_URL_ITR = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{year}.zip"
    BASE_URL_CAD = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
    BASE_URL_FCA = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{year}.zip"

    # Demonstrações financeiras padrão (incluindo DVA - Demonstração do Valor Adicionado)
    STATEMENTS = ("BPA", "BPP", "DRE", "DFC_MD", "DFC_MI", "DVA")

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        timeout: int = 90,
        max_retries: int = 3,
    ) -> None:
        """Inicializa o extrator com sessão HTTP resiliente e cache local."""
        self.timeout = timeout
        self.cache_dir = Path(cache_dir or Path("data/metadata"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.cache_dir / "http_cache_metadata.json"
        self._cache: Dict[str, Dict[str, Any]] = self._load_cache()

        # Configurar sessão HTTP com retry automático (backoff exponencial)
        self.session = requests.Session()
        retries = Retry(
            total=max_retries,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET"],
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update(
            {
                "User-Agent": "PulseDataLabs-PulseFinancials/1.0 (+https://github.com/PulseDataLabs)",
                "Accept-Encoding": "gzip, deflate",
            }
        )

    def _load_cache(self) -> Dict[str, Dict[str, Any]]:
        """Carrega metadados de cache HTTP persistidos em disco."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("Falha ao ler cache de metadados HTTP: %s", e)
        return {}

    def _save_cache(self) -> None:
        """Salva metadados de cache HTTP."""
        try:
            with open(self.metadata_file, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2)
        except Exception as e:
            logger.warning("Falha ao salvar cache de metadados HTTP: %s", e)

    def download_in_memory(self, url: str) -> Tuple[Optional[bytes], bool]:
        """Faz o download condicional de um recurso remoto em memória.

        Usa cabeçalhos ETag e If-Modified-Since. Se o servidor responder 304
        (Not Modified), evita o download completo e retorna None.

        Returns:
            Tuple[Optional[bytes], bool]: (conteúdo em bytes, cache_hit)
        """
        headers: Dict[str, str] = {}
        cached_info = self._cache.get(url, {})

        if cached_info.get("etag"):
            headers["If-None-Match"] = cached_info["etag"]
        if cached_info.get("last_modified"):
            headers["If-Modified-Since"] = cached_info["last_modified"]

        logger.info("Verificando/Baixando recurso: %s", url)

        try:
            response = self.session.get(url, headers=headers, stream=True, timeout=self.timeout)

            if response.status_code == 304:
                logger.info("Recurso não modificado (HTTP 304 - Cache Hit): %s", url)
                return None, True

            response.raise_for_status()

            content = response.content
            logger.info("Download concluído: %s (%.2f MB)", url, len(content) / (1024 * 1024))

            # Atualiza cache
            self._cache[url] = {
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "content_length": len(content),
            }
            self._save_cache()

            return content, False

        except requests.RequestException as e:
            logger.error("Erro na requisição para %s: %s", url, e)
            raise

    @staticmethod
    def clean_cnpj_expression() -> pl.Expr:
        """Expressão Polars para limpar e padronizar CNPJ (somente dígitos com 14 posições)."""
        return (
            pl.col("CNPJ_CIA")
            .str.replace_all(r"\D", "")
            .str.zfill(14)
            .alias("cnpj_cia")
        )

    @staticmethod
    def sanitize_monetary_value() -> pl.Expr:
        """Ajusta o valor da conta multiplicando por 1.000 se ESCALA_MOEDA == 'MIL'.

        Garante que todos os valores na base analítica estejam sempre em valor
        nominal integral em Reais (BRL).
        """
        # Trata caso a coluna venha como string ou float
        val_numeric = (
            pl.when(pl.col("VL_CONTA").dtype.is_numeric())
            .then(pl.col("VL_CONTA").cast(pl.Float64))
            .otherwise(
                pl.col("VL_CONTA")
                .cast(pl.Utf8)
                .str.replace(",", ".")
                .cast(pl.Float64, strict=False)
            )
        )

        escala = pl.col("ESCALA_MOEDA").str.strip_chars().str.to_uppercase()

        return (
            pl.when(escala == "MIL")
            .then(val_numeric * 1000.0)
            .otherwise(val_numeric)
            .alias("vl_conta_ajustado")
        )

    def extract_zip_statements(
        self,
        zip_bytes: bytes,
        doc_type: str,
        year: int,
        filter_last_exercise: bool = True,
    ) -> Iterator[Tuple[str, bool, pl.DataFrame]]:
        """Extrai e saneia demonstrações contábeis de um ZIP em memória.

        Args:
            zip_bytes: Bytes brutos do arquivo .zip
            doc_type: Tipo de documento ('DFP' ou 'ITR')
            year: Ano de referência do arquivo
            filter_last_exercise: Se True, mantém apenas ORDEM_EXERC == 'ÚLTIMO'

        Yields:
            Tuplas de (demonstracao, is_consolidado, polars.DataFrame)
        """
        doc_type_lower = doc_type.lower()
        prefix = f"{doc_type_lower}_cia_aberta_"

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            file_names = zf.namelist()

            for statement in self.STATEMENTS:
                for cons_ind, is_cons in (("con", True), ("ind", False)):
                    # Ex: dfp_cia_aberta_DRE_con_2024.csv
                    pattern = re.compile(
                        rf"^{prefix}{statement}_{cons_ind}_{year}\.csv$",
                        re.IGNORECASE,
                    )
                    matching = [f for f in file_names if pattern.match(f)]

                    if not matching:
                        continue

                    csv_file_name = matching[0]
                    logger.debug("Lendo arquivo do ZIP: %s", csv_file_name)

                    with zf.open(csv_file_name) as csv_file:
                        csv_bytes = csv_file.read()

                    # Leitura ultrarrápida via Polars
                    df = pl.read_csv(
                        io.BytesIO(csv_bytes),
                        separator=";",
                        encoding="iso-8859-1",
                        ignore_errors=True,
                        infer_schema_length=5000,
                    )

                    if df.is_empty():
                        continue

                    # Padronização de nomes de colunas para maiúsculas antes do saneamento
                    df = df.rename({col: col.upper() for col in df.columns})

                    # Filtro de exercício crítico: 'ÚLTIMO' evita duplicatas históricas
                    if filter_last_exercise and "ORDEM_EXERC" in df.columns:
                        df = df.filter(
                            pl.col("ORDEM_EXERC")
                            .str.strip_chars()
                            .str.to_uppercase()
                            == "ÚLTIMO"
                        )

                    # Aplicação do saneamento de CNPJ e valor monetário
                    transforms: List[pl.Expr] = [
                        self.clean_cnpj_expression(),
                        self.sanitize_monetary_value(),
                        pl.lit(statement).alias("demonstracao"),
                        pl.lit(is_cons).alias("is_consolidado"),
                        pl.lit(doc_type.upper()).alias("tipo_documento"),
                        pl.lit(year).alias("ano_documento"),
                    ]

                    # Parse de datas
                    if "DT_REFER" in df.columns:
                        transforms.append(
                            pl.col("DT_REFER").str.to_date("%Y-%m-%d").alias("dt_referencia")
                        )
                    if "DT_FIM_EXERC" in df.columns:
                        transforms.append(
                            pl.col("DT_FIM_EXERC").str.to_date("%Y-%m-%d").alias("dt_fim_exerc")
                        )
                    if "DT_INI_EXERC" in df.columns:
                        transforms.append(
                            pl.col("DT_INI_EXERC").str.to_date("%Y-%m-%d").alias("dt_ini_exerc")
                        )

                    # Seleção e renomeação uniforme
                    cols_to_keep = [
                        pl.col("cnpj_cia"),
                        pl.col("CD_CVM").cast(pl.Int64, strict=False).alias("cd_cvm"),
                        pl.col("DENOM_CIA").str.strip_chars().alias("razao_social"),
                        pl.col("VERSAO").cast(pl.Int32, strict=False).alias("versao"),
                        pl.col("CD_CONTA").str.strip_chars().alias("cd_conta"),
                        pl.col("DS_CONTA").str.strip_chars().alias("ds_conta"),
                        pl.col("ORDEM_EXERC").str.strip_chars().alias("ordem_exercicio"),
                        pl.col("MOEDA").str.strip_chars().alias("moeda"),
                        pl.col("ESCALA_MOEDA").str.strip_chars().alias("escala_original"),
                        pl.col("vl_conta_ajustado"),
                        pl.col("demonstracao"),
                        pl.col("is_consolidado"),
                        pl.col("tipo_documento"),
                        pl.col("ano_documento"),
                    ]

                    if "dt_referencia" in [e.meta.output_name() for e in transforms]:
                        cols_to_keep.append(pl.col("dt_referencia"))
                    if "dt_fim_exerc" in [e.meta.output_name() for e in transforms]:
                        cols_to_keep.append(pl.col("dt_fim_exerc"))
                    if "dt_ini_exerc" in [e.meta.output_name() for e in transforms]:
                        cols_to_keep.append(pl.col("dt_ini_exerc"))

                    df_clean = df.with_columns(transforms).select(cols_to_keep)

                    yield statement, is_cons, df_clean

    def fetch_cadastral_companies(self) -> pl.DataFrame:
        """Baixa e processa a tabela cadastral de companhias abertas da CVM.

        Mapeia CNPJ, Código CVM, Razão Social, Situação Cadastral e Setor.
        """
        logger.info("Baixando dados cadastrais oficiais da CVM: %s", self.BASE_URL_CAD)
        content, _ = self.download_in_memory(self.BASE_URL_CAD)

        if content is None:
            # Em caso de cache hit, caso o caller precise, pode ler do arquivo local
            pass

        df = pl.read_csv(
            io.BytesIO(content),
            separator=";",
            encoding="iso-8859-1",
            ignore_errors=True,
        )

        df = df.rename({col: col.upper() for col in df.columns})

        df_companies = df.select(
            [
                pl.col("CNPJ_CIA").str.replace_all(r"\D", "").str.zfill(14).alias("cnpj"),
                pl.col("CD_CVM").cast(pl.Int64, strict=False).alias("cd_cvm"),
                pl.col("DENOM_SOCIAL").str.strip_chars().alias("razao_social"),
                pl.col("DENOM_COMERC").str.strip_chars().alias("nome_fantasia"),
                pl.col("SETOR_ATIV").str.strip_chars().alias("setor_cvm"),
                (pl.col("SIT").str.strip_chars().str.to_uppercase() == "ATIVO").alias("is_active"),
                pl.col("DT_REG").str.to_date("%Y-%m-%d", strict=False).alias("dt_registro"),
                pl.col("DT_CANCEL").str.to_date("%Y-%m-%d", strict=False).alias("dt_cancelamento"),
            ]
        ).unique(subset=["cnpj"])

        return df_companies

    def process_financial_year(
        self,
        doc_type: str,
        year: int,
    ) -> ExtractionSummary:
        """Processa um ano específico de DFP ou ITR ponta a ponta em memória.

        Args:
            doc_type: 'DFP' ou 'ITR'
            year: Ano de referência (ex: 2024)

        Returns:
            ExtractionSummary com os dados do processamento.
        """
        summary = ExtractionSummary(doc_type=doc_type.upper(), year=year)
        url = (
            self.BASE_URL_DFP.format(year=year)
            if doc_type.upper() == "DFP"
            else self.BASE_URL_ITR.format(year=year)
        )

        try:
            zip_bytes, cache_hit = self.download_in_memory(url)
            summary.cache_hit = cache_hit

            if cache_hit or not zip_bytes:
                summary.status = "SKIPPED_NOT_MODIFIED"
                logger.info(
                    "Pacote %s %d pulado: sem alterações na CVM.",
                    doc_type.upper(),
                    year,
                )
                return summary

            for statement, is_cons, df in self.extract_zip_statements(
                zip_bytes, doc_type=doc_type, year=year
            ):
                summary.statements_extracted.append(
                    f"{statement}_{'CON' if is_cons else 'IND'}"
                )
                summary.total_records += len(df)
                logger.info(
                    "Demonstração %s (%s) %d extraída: %d registros saneados.",
                    statement,
                    "CON" if is_cons else "IND",
                    year,
                    len(df),
                )

            summary.status = "SUCCESS"
            return summary

        except Exception as e:
            logger.exception("Falha na extração de %s %d: %s", doc_type, year, e)
            summary.status = "ERROR"
            summary.error_message = str(e)
            return summary

