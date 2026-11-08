"""PulseBalanços - Scraper de Documentos, Fatos Relevantes e Comunicados (CVM IPE).

Captura todos os documentos públicos oficiais protocolados pelas companhias na CVM:
- Fatos Relevantes (M&A, aquisições, guidances)
- Comunicados ao Mercado
- Avisos aos Acionistas (Proventos, Dividendos e JCP)
- Atas de Assembleias (Aprovação de Contas e Balanços)
- Apresentações Institucionais e Relatórios de Resultados
- Link oficial rastreável direto para o documento na CVM (rad.cvm.gov.br).
"""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterator, List, Optional

import polars as pl

from .base import BaseScraper

logger = logging.getLogger("pulsebalancos.scrapers.ipe")


@dataclass(slots=True)
class CompanyFilingDocument:
    """Documento corporativo oficial protocolado na CVM."""

    cnpj: str
    razao_social: str
    cd_cvm: Optional[int]
    ano: int
    data_referencia: str
    data_entrega: str
    categoria: str  # Ex: 'Fato Relevante', 'Comunicado ao Mercado', 'Assembleia'
    tipo: str  # Ex: 'AGE', 'AGO', 'Aviso aos Acionistas'
    especie: str  # Ex: 'Ata', 'Edital', 'Comunicado'
    assunto: str
    protocolo: Optional[str]
    versao: int
    url_download: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CVMIPEDocumentsScraper(BaseScraper):
    """Extrator de alto rendimento para arquivos IPE da CVM."""

    BASE_URL_IPE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{year}.zip"

    def __init__(self, timeout: int = 120) -> None:
        super().__init__(name="cvm_ipe", timeout=timeout)

    def extract_year(self, year: int) -> Iterator[CompanyFilingDocument]:
        """Extrai todos os documentos protocolados na CVM para o ano de referência."""
        url = self.BASE_URL_IPE.format(year=year)
        logger.info("[cvm_ipe] Baixando documentos IPE de %d...", year)

        content, hit = self.download_in_memory(url)
        if not content:
            logger.info("[cvm_ipe] IPE %d sem alterações (Cache Hit).", year)
            return

        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            matching = [f for f in zf.namelist() if f.endswith(".csv")]
            if not matching:
                return

            with zf.open(matching[0]) as f:
                csv_bytes = f.read()

        # Leitura com Polars com quote_char desativado para suportar aspas livres no campo Assunto
        df = pl.read_csv(
            io.BytesIO(csv_bytes),
            separator=";",
            encoding="iso-8859-1",
            quote_char=None,
            truncate_ragged_lines=True,
            ignore_errors=True,
        )

        df = df.rename({c: c.strip() for c in df.columns})

        df_clean = df.with_columns(
            [
                pl.col("CNPJ_Companhia").str.replace_all(r"\D", "").str.zfill(14).alias("cnpj_limpo"),
                pl.col("Codigo_CVM").cast(pl.Int64, strict=False).alias("cd_cvm_int"),
                pl.col("Versao").cast(pl.Int32, strict=False).fill_null(1).alias("versao_int"),
            ]
        )

        for row in df_clean.iter_rows(named=True):
            yield CompanyFilingDocument(
                cnpj=row["cnpj_limpo"],
                razao_social=(row.get("Nome_Companhia") or "").strip(),
                cd_cvm=row["cd_cvm_int"],
                ano=year,
                data_referencia=str(row.get("Data_Referencia") or ""),
                data_entrega=str(row.get("Data_Entrega") or ""),
                categoria=(row.get("Categoria") or "").strip(),
                tipo=(row.get("Tipo") or "").strip(),
                especie=(row.get("Especie") or "").strip(),
                assunto=(row.get("Assunto") or "").strip(),
                protocolo=str(row.get("Protocolo_Entrega") or ""),
                versao=row["versao_int"],
                url_download=str(row.get("Link_Download") or ""),
            )
