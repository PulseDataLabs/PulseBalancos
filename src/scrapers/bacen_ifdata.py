"""PulseBalanços - Extrator de Demonstrações Contábeis do Banco Central (BACEN IF.data).

Captura balanços e DREs de instituições financeiras brasileiras (tanto abertas quanto fechadas):
- Bancos Comerciais e Múltiplos
- Cooperativas de Crédito (Singulares e Centrais)
- Sociedades de Crédito Direto (SCD) e Fintechs de Crédito
- Distribuidoras e Corretoras de Títulos e Valores Mobiliários (DTVM/CTVM)
- Fonte Oficial: Sistema IF.data / COSIF do Banco Central do Brasil.
"""

from __future__ import annotations

import logging
from typing import Iterator

from .base import BaseScraper
from .models import UnifiedStatementRecord

logger = logging.getLogger("pulsebalancos.scrapers.bacen")


class BacenIFDataScraper(BaseScraper):
    """Extrator de dados contábeis regulatórios do Banco Central do Brasil."""

    BASE_URL_BACEN = "https://www3.bcb.gov.br/ifdata/dados/{year}{quarter:02d}.zip"

    def __init__(self, timeout: int = 90) -> None:
        super().__init__(name="bacen_ifdata", timeout=timeout)

    def extract_year(self, year: int) -> Iterator[UnifiedStatementRecord]:
        """Extrai balanços dos 4 trimestres do BACEN IF.data para o ano."""
        logger.info("[bacen_ifdata] Ingestão de demonstrações financeiras do BACEN para %d...", year)

        for quarter in (3, 6, 9, 12):
            dt_ref = f"{year}-{quarter:02d}-30" if quarter in (6, 9) else (f"{year}-03-31" if quarter == 3 else f"{year}-12-31")
            url_origem = f"https://www3.bcb.gov.br/ifdata/#relatorio?dt={year}{quarter:02d}"

            # Yield de demonstrações COSIF / IF.data mapeadas
            # Permite consulta imediata e rastreabilidade com o portal do Banco Central

