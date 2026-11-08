"""PulseBalanços - Scraper de Governança, Posição Acionária e Capital Social (CVM FRE).

Extrai informações cruciais do Formulário de Referência (FRE):
- Acionistas Controladores e participações acionárias relevantes (> 5%).
- Composição do Capital Social (Ações Ordinárias, Preferenciais e Total).
- Base necessária para cálculo de LPA (Lucro por Ação) e VPA (Valor Patrimonial por Ação).
"""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterator, List, Optional

import polars as pl

from .base import BaseScraper

logger = logging.getLogger("pulsebalancos.scrapers.shareholders")


@dataclass(slots=True)
class ShareholderPosition:
    """Acionista relevante ou controlador da companhia."""

    cnpj_companhia: str
    razao_social: str
    ano: int
    data_referencia: str
    acionista: str
    cpf_cnpj_acionista: Optional[str]
    tipo_pessoa: str
    is_controlador: bool
    quantidade_acoes_on: float
    quantidade_acoes_pn: float
    quantidade_total_acoes: float
    percentual_total_acoes: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CompanyShareStructure:
    """Estrutura do Capital Social da companhia."""

    cnpj: str
    razao_social: str
    ano: int
    data_referencia: str
    valor_capital_social: float
    quantidade_acoes_on: int
    quantidade_acoes_pn: int
    quantidade_total_acoes: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CVMShareholdersScraper(BaseScraper):
    """Extrator de estrutura acionária e capital social da CVM."""

    BASE_URL_FRE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FRE/DADOS/fre_cia_aberta_{year}.zip"

    def __init__(self, timeout: int = 120) -> None:
        super().__init__(name="cvm_shareholders", timeout=timeout)

    def extract_shareholders(self, year: int) -> Iterator[ShareholderPosition]:
        """Extrai os acionistas relevantes e controladores das companhias."""
        url = self.BASE_URL_FRE.format(year=year)
        logger.info("[cvm_shareholders] Baixando posição acionária FRE de %d...", year)

        content, hit = self.download_in_memory(url)
        if not content:
            return

        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            matching = [f for f in zf.namelist() if "posicao_acionaria" in f and not "classe_acao" in f]
            if not matching:
                return

            with zf.open(matching[0]) as f:
                df = pl.read_csv(io.BytesIO(f.read()), separator=";", encoding="iso-8859-1", ignore_errors=True)

        df = df.rename({c: c.strip() for c in df.columns})

        df_clean = df.with_columns(
            [
                pl.col("CNPJ_Companhia").str.replace_all(r"\D", "").str.zfill(14).alias("cnpj_limpo"),
                (pl.col("Acionista_Controlador").str.strip_chars().str.to_uppercase() == "SIM").alias("is_ctrl"),
            ]
        )

        for row in df_clean.iter_rows(named=True):
            pct = row.get("Percentual_Total_Acoes_Circulacao")
            try:
                pct_val = float(str(pct).replace(",", ".")) if pct is not None else 0.0
            except ValueError:
                pct_val = 0.0

            yield ShareholderPosition(
                cnpj_companhia=row["cnpj_limpo"],
                razao_social=(row.get("Nome_Companhia") or "").strip(),
                ano=year,
                data_referencia=str(row.get("Data_Referencia") or ""),
                acionista=(row.get("Acionista") or "").strip(),
                cpf_cnpj_acionista=str(row.get("CPF_CNPJ_Acionista") or "").strip() or None,
                tipo_pessoa=str(row.get("Tipo_Pessoa_Acionista") or "").strip(),
                is_controlador=bool(row["is_ctrl"]),
                quantidade_acoes_on=float(row.get("Quantidade_Acao_Ordinaria_Circulacao") or 0),
                quantidade_acoes_pn=float(row.get("Quantidade_Acao_Preferencial_Circulacao") or 0),
                quantidade_total_acoes=float(row.get("Quantidade_Total_Acoes_Circulacao") or 0),
                percentual_total_acoes=pct_val,
            )

    def extract_share_structure(self, year: int) -> Iterator[CompanyShareStructure]:
        """Extrai o número total de ações e capital social para cálculo de VPA e LPA."""
        url = self.BASE_URL_FRE.format(year=year)
        content, hit = self.download_in_memory(url)
        if not content:
            return

        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            matching = [f for f in zf.namelist() if f == f"fre_cia_aberta_capital_social_{year}.csv"]
            if not matching:
                return

            with zf.open(matching[0]) as f:
                df = pl.read_csv(io.BytesIO(f.read()), separator=";", encoding="iso-8859-1", ignore_errors=True)

        df = df.rename({c: c.strip() for c in df.columns})

        df_clean = df.with_columns(
            pl.col("CNPJ_Companhia").str.replace_all(r"\D", "").str.zfill(14).alias("cnpj_limpo")
        )

        for row in df_clean.iter_rows(named=True):
            val_cap = row.get("Valor_Capital")
            try:
                cap_float = float(str(val_cap).replace(",", ".")) if val_cap is not None else 0.0
            except ValueError:
                cap_float = 0.0

            yield CompanyShareStructure(
                cnpj=row["cnpj_limpo"],
                razao_social=(row.get("Nome_Companhia") or "").strip(),
                ano=year,
                data_referencia=str(row.get("Data_Referencia") or ""),
                valor_capital_social=cap_float,
                quantidade_acoes_on=int(row.get("Quantidade_Acoes_Ordinarias") or 0),
                quantidade_acoes_pn=int(row.get("Quantidade_Acoes_Preferenciais") or 0),
                quantidade_total_acoes=int(row.get("Quantidade_Total_Acoes") or 0),
            )

    def extract_year(self, year: int) -> Iterator[Any]:
        yield from self.extract_shareholders(year)

