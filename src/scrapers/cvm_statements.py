"""PulseBalanços - Scraper Oficial de Demonstrações Contábeis da CVM (DFP / ITR).

Processa arquivos oficiais da CVM com streaming em memória via Polars:
- Balanço Patrimonial Ativo (BPA) e Passivo (BPP)
- Demonstração do Resultado (DRE)
- Fluxo de Caixa Método Direto (DFC_MD) e Indireto (DFC_MI)
- Demonstração do Valor Adicionado (DVA)
- Companhias Abertas (Categoria A) e Sociedades Emissoras de Dívida (Categoria B)
- Auditoria com link para conferência no sistema ENET/CVM.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from typing import Iterator, List, Optional, Tuple

import polars as pl

from .base import BaseScraper
from .models import UnifiedStatementRecord

logger = logging.getLogger("pulsebalancos.scrapers.cvm")


class CVMStatementsScraper(BaseScraper):
    """Extrator de alto rendimento para demonstrativos contábeis da CVM."""

    BASE_URL_DFP = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{year}.zip"
    BASE_URL_ITR = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{year}.zip"

    STATEMENTS = ("BPA", "BPP", "DRE", "DFC_MD", "DFC_MI", "DVA")

    def __init__(self, timeout: int = 120) -> None:
        super().__init__(name="cvm_statements", timeout=timeout)

    def _extract_zip_file(
        self,
        zip_bytes: bytes,
        doc_type: str,
        year: int,
    ) -> Iterator[UnifiedStatementRecord]:
        """Lê os CSVs de demonstrações contábeis de dentro do ZIP sem gravar em disco."""
        doc_type_lower = doc_type.lower()
        prefix = f"{doc_type_lower}_cia_aberta_"

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            file_names = zf.namelist()

            for statement in self.STATEMENTS:
                for cons_ind, is_cons in (("con", True), ("ind", False)):
                    pattern = re.compile(
                        rf"^{prefix}{statement}_{cons_ind}_{year}\.csv$",
                        re.IGNORECASE,
                    )
                    matching = [f for f in file_names if pattern.match(f)]
                    if not matching:
                        continue

                    csv_name = matching[0]
                    with zf.open(csv_name) as f:
                        csv_data = f.read()

                    # Leitura direta em Polars
                    df = pl.read_csv(
                        io.BytesIO(csv_data),
                        separator=";",
                        encoding="iso-8859-1",
                        ignore_errors=True,
                        infer_schema_length=5000,
                    )

                    if df.is_empty():
                        continue

                    df = df.rename({c: c.strip().upper() for c in df.columns})

                    # Filtro de exercício: evita registros duplicados comparativos
                    if "ORDEM_EXERC" in df.columns:
                        df = df.filter(
                            pl.col("ORDEM_EXERC").str.strip_chars().str.to_uppercase() == "ÚLTIMO"
                        )

                    # Limpeza de CNPJ
                    cnpj_clean = (
                        pl.col("CNPJ_CIA")
                        .str.replace_all(r"\D", "")
                        .str.zfill(14)
                        .alias("cnpj_limpo")
                    )

                    # Ajuste de escala monetária: se 'MIL', multiplica por 1.000
                    if df["VL_CONTA"].dtype.is_numeric():
                        val_numeric = pl.col("VL_CONTA").cast(pl.Float64)
                    else:
                        val_numeric = (
                            pl.col("VL_CONTA")
                            .cast(pl.Utf8)
                            .str.replace(",", ".")
                            .cast(pl.Float64, strict=False)
                        )
                    escala = pl.col("ESCALA_MOEDA").str.strip_chars().str.to_uppercase()
                    val_ajustado = (
                        pl.when(escala == "MIL")
                        .then(val_numeric * 1000.0)
                        .otherwise(val_numeric)
                        .alias("vl_ajustado")
                    )

                    df_clean = df.with_columns([cnpj_clean, val_ajustado])

                    # Itera sobre as linhas de forma vetorizada
                    for row in df_clean.iter_rows(named=True):
                        cnpj = row["cnpj_limpo"]
                        razao = (row.get("DENOM_CIA") or "").strip()
                        dt_ref = str(row.get("DT_REFER") or f"{year}-12-31")
                        cd_conta = str(row.get("CD_CONTA") or "").strip()
                        ds_conta = str(row.get("DS_CONTA") or "").strip()
                        vl = float(row.get("vl_ajustado") or 0.0)
                        cd_cvm = row.get("CD_CVM")
                        versao = row.get("VERSAO")

                        url_cvm = (
                            f"https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx?codigoCVM={cd_cvm}"
                            if cd_cvm
                            else "https://dados.cvm.gov.br"
                        )

                        yield UnifiedStatementRecord(
                            cnpj=cnpj,
                            razao_social=razao,
                            nome_fantasia=None,
                            tipo_empresa="CIA_ABERTA",
                            exercicio=year,
                            dt_referencia=dt_ref,
                            tipo_documento=doc_type.upper(),
                            demonstracao=statement,
                            cd_conta=cd_conta,
                            ds_conta=ds_conta,
                            vl_conta=vl,
                            is_consolidado=is_cons,
                            fonte_origem="CVM",
                            url_origem=url_cvm,
                            numero_protocolo=f"CVM-{cd_cvm}-V{versao}" if cd_cvm else None,
                        )

    def extract_year(self, year: int) -> Iterator[UnifiedStatementRecord]:
        """Extrai todas as demonstrações do ano (DFP e ITR) de forma unificada."""
        # 1. Extração DFP (Anual)
        url_dfp = self.BASE_URL_DFP.format(year=year)
        logger.info("[cvm_statements] Baixando DFP oficial de %d...", year)
        dfp_bytes, hit = self.download_in_memory(url_dfp)
        if dfp_bytes:
            yield from self._extract_zip_file(dfp_bytes, doc_type="DFP", year=year)

        # 2. Extração ITR (Trimestral)
        url_itr = self.BASE_URL_ITR.format(year=year)
        logger.info("[cvm_statements] Baixando ITR oficial de %d...", year)
        itr_bytes, hit = self.download_in_memory(url_itr)
        if itr_bytes:
            yield from self._extract_zip_file(itr_bytes, doc_type="ITR", year=year)
