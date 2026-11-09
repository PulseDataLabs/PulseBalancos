"""PulseBalanços - Extrator de Conglomerados Prudenciais e Financeiros do Banco Central (BACEN).

Captura a relação de instituições participantes e líderes de conglomerados prudenciais
supervisionados pelo Banco Central do Brasil (Resolução CMN nº 4.950/2021).
Lida com a alternância de nomenclatura de URLs observada no portal do BACEN:
- Padrão novo (a partir de 10/2026): MMYYYYCONGLOMERADO.zip (ex: 102026CONGLOMERADO.zip)
- Padrão histórico (até 09/2026): YYYYMMCONGLOMERADO.zip (ex: 202609CONGLOMERADO.zip)
"""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import openpyxl

from .base import BaseScraper

logger = logging.getLogger("pulsebalancos.scrapers.bacen_conglomerados")


@dataclass(slots=True)
class BacenConglomeradoRecord:
    """Registro estruturado de uma entidade participante de um conglomerado prudencial."""

    nome_conglomerado: str
    classe_conglomerado: str
    cnpj_base: Optional[str]  # 8 dígitos do CNPJ da entidade (None para offshore/fundos internacionais)
    nome_participante: str
    tipo_participacao: str  # 'LIDER', 'PARTICIPANTE', 'LIDER/HOLDING', 'HOLDINGNÃOIF'
    data_inicio: Optional[str]  # YYYY-MM-DD
    uf: Optional[str]
    is_lider: bool
    ano_referencia: int
    mes_referencia: int
    url_origem: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BacenConglomeradosScraper(BaseScraper):
    """Scraper e extrator de arquivos de Conglomerados Prudenciais do Banco Central."""

    BASE_URL = "https://www.bcb.gov.br/content/estabilidadefinanceira/relacao_instituicoes_funcionamento/Conglomerados/"

    def __init__(self, timeout: int = 60) -> None:
        super().__init__(name="bacen_conglomerados", timeout=timeout)

    def _get_download_url(self, year: int, month: int) -> Tuple[str, bytes]:
        """Tenta baixar o arquivo ZIP buscando tanto o formato MMYYYY quanto YYYYMM."""
        filenames = [
            f"{month:02d}{year}CONGLOMERADO.zip",  # Padrão novo (ex: 102026CONGLOMERADO.zip)
            f"{year}{month:02d}CONGLOMERADO.zip",  # Padrão anterior (ex: 202609CONGLOMERADO.zip)
        ]

        errors = []
        for fname in filenames:
            url = f"{self.BASE_URL}{fname}"
            try:
                logger.info("[bacen_conglomerados] Tentando obter: %s", url)
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code == 200 and resp.content:
                    return url, resp.content
                errors.append(f"{url} -> status {resp.status_code}")
            except Exception as e:
                errors.append(f"{url} -> {e}")

        raise FileNotFoundError(
            f"Não foi possível localizar arquivo de Conglomerados para {month:02d}/{year}. Tentativas: {errors}"
        )

    def extract_conglomerados(self, year: int, month: int) -> List[BacenConglomeradoRecord]:
        """Extrai todos os participantes de conglomerados prudenciais do BACEN para o período informado."""
        url, zip_bytes = self._get_download_url(year, month)

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            xlsx_files = [f for f in zf.namelist() if f.lower().endswith(".xlsx")]
            if not xlsx_files:
                raise ValueError(f"Nenhum arquivo Excel (.xlsx) encontrado dentro do ZIP: {zf.namelist()}")

            raw_xlsx = zf.read(xlsx_files[0])

        wb = openpyxl.load_workbook(io.BytesIO(raw_xlsx), data_only=True)
        ws = wb.active

        # Localiza linha do cabeçalho da tabela
        header_row_idx = None
        for r in range(1, min(ws.max_row + 1, 30)):
            cell_val = str(ws.cell(r, 1).value or "").strip().upper()
            if "NOME DO CONGLOMERADO" in cell_val:
                header_row_idx = r
                break

        if not header_row_idx:
            raise ValueError(f"Cabeçalho da tabela de conglomerados não encontrado no arquivo {xlsx_files[0]}")

        col_names = [
            str(ws.cell(header_row_idx, c).value or "").strip()
            for c in range(1, ws.max_column + 1)
        ]

        records: List[BacenConglomeradoRecord] = []
        for r in range(header_row_idx + 1, ws.max_row + 1):
            first_val = ws.cell(r, 1).value
            if not first_val:
                continue

            first_text = str(first_val).strip()
            if first_text.upper().startswith("FONTE:"):
                continue

            nome_conglomerado = str(ws.cell(r, 1).value or "").strip()
            classe_conglomerado = str(ws.cell(r, 2).value or "").strip()
            cnpj_raw = ws.cell(r, 3).value
            nome_participante = str(ws.cell(r, 4).value or "").strip()
            tipo_participacao = str(ws.cell(r, 5).value or "").strip()
            dt_inicio_val = ws.cell(r, 6).value
            uf_val = str(ws.cell(r, 7).value or "").strip()

            # Normalização do CNPJ base (8 dígitos)
            cnpj_base = None
            if cnpj_raw is not None:
                cnpj_str = str(cnpj_raw).strip()
                digits = "".join(ch for ch in cnpj_str if ch.isdigit())
                if digits:
                    cnpj_base = digits.zfill(8)

            # Normalização da data
            dt_inicio_str = None
            if isinstance(dt_inicio_val, datetime):
                dt_inicio_str = dt_inicio_val.strftime("%Y-%m-%d")
            elif dt_inicio_val:
                dt_inicio_str = str(dt_inicio_val).strip()[:10]

            is_lider = "LIDER" in tipo_participacao.upper()

            rec = BacenConglomeradoRecord(
                nome_conglomerado=nome_conglomerado,
                classe_conglomerado=classe_conglomerado,
                cnpj_base=cnpj_base,
                nome_participante=nome_participante,
                tipo_participacao=tipo_participacao,
                data_inicio=dt_inicio_str,
                uf=uf_val if uf_val else None,
                is_lider=is_lider,
                ano_referencia=year,
                mes_referencia=month,
                url_origem=url,
            )
            records.append(rec)

        logger.info(
            "[bacen_conglomerados] Extraídos %d participantes (%d líderes) de %d/%02d via %s",
            len(records),
            sum(1 for r in records if r.is_lider),
            year,
            month,
            url,
        )
        return records

    def extract_year(self, year: int) -> Iterator[BacenConglomeradoRecord]:
        """Extrai os participantes dos conglomerados para os meses disponíveis do ano."""
        for month in range(12, 0, -1):
            try:
                records = self.extract_conglomerados(year, month)
                for rec in records:
                    yield rec
                # Se encontrou o mês mais recente disponível do ano, pode retornar a foto
                break
            except FileNotFoundError:
                continue

