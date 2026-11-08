"""PulseBalanços - Scraper de Demonstrações Contábeis e Ativos de FIIs (CVM FII).

Captura os informes anuais auditados e balanços patrimoniais dos Fundos Imobiliários:
- CNPJ, Nome do Fundo, Administrador, Segmento de Atuação e Quantidade de Cotas.
- Valor Contábil e Valor Justo de cada Ativo Imobiliário (Shopping Centers, Galpões, Edifícios).
- Fonte Oficial: CVM Informes Anuais de FIIs.
"""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterator, List, Optional

import polars as pl

from .base import BaseScraper

logger = logging.getLogger("pulsebalancos.scrapers.fii")


@dataclass(slots=True)
class FIISummaryRecord:
    """Resumo cadastral e patrimonial de um Fundo de Investimento Imobiliário."""

    cnpj_fundo: str
    nome_fundo: str
    ano: int
    data_referencia: str
    administrador: str
    cnpj_administrador: str
    segmento_atuacao: str
    publico_alvo: str
    quantidade_cotas: float
    cidade: str
    uf: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FIIAssetRecord:
    """Ativo imobiliário detido pelo FII com valor contábil e justo."""

    cnpj_fundo: str
    ano: int
    data_referencia: str
    nome_ativo: str
    valor_contabil: float
    is_valor_justo: bool
    percentual_valorizacao: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CVMFIIScraper(BaseScraper):
    """Extrator de demonstrativos de Fundos Imobiliários da CVM."""

    BASE_URL_FII = "https://dados.cvm.gov.br/dados/FII/DOC/INF_ANUAL/DADOS/inf_anual_fii_{year}.zip"

    def __init__(self, timeout: int = 120) -> None:
        super().__init__(name="cvm_fii", timeout=timeout)

    def extract_fii_summaries(self, year: int) -> Iterator[FIISummaryRecord]:
        """Extrai os dados gerais e patrimoniais de todos os FIIs registrados."""
        url = self.BASE_URL_FII.format(year=year)
        logger.info("[cvm_fii] Baixando informe anual de FIIs de %d...", year)

        content, hit = self.download_in_memory(url)
        if not content:
            return

        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            matching = [f for f in zf.namelist() if f == f"inf_anual_fii_geral_{year}.csv"]
            if not matching:
                return

            with zf.open(matching[0]) as f:
                df = pl.read_csv(io.BytesIO(f.read()), separator=";", encoding="iso-8859-1", ignore_errors=True)

        df = df.rename({c: c.strip() for c in df.columns})

        df_clean = df.with_columns(
            pl.col("CNPJ_Fundo_Classe").str.replace_all(r"\D", "").str.zfill(14).alias("cnpj_limpo")
        )

        for row in df_clean.iter_rows(named=True):
            qtd = row.get("Quantidade_Cotas_Emitidas")
            try:
                qtd_float = float(str(qtd).replace(",", ".")) if qtd is not None else 0.0
            except ValueError:
                qtd_float = 0.0

            yield FIISummaryRecord(
                cnpj_fundo=row["cnpj_limpo"],
                nome_fundo=(row.get("Nome_Fundo_Classe") or "").strip(),
                ano=year,
                data_referencia=str(row.get("Data_Referencia") or ""),
                administrador=(row.get("Nome_Administrador") or "").strip(),
                cnpj_administrador=(str(row.get("CNPJ_Administrador") or "").strip()),
                segmento_atuacao=(row.get("Segmento_Atuacao") or "Geral").strip(),
                publico_alvo=(row.get("Publico_Alvo") or "Geral").strip(),
                quantidade_cotas=qtd_float,
                cidade=(row.get("Cidade") or "").strip(),
                uf=(row.get("Estado") or "").strip(),
            )

    def extract_year(self, year: int) -> Iterator[Any]:
        yield from self.extract_fii_summaries(year)

