"""PulseBalanços - Orquestrador e Unificador de Demonstrações Financeiras Oficiais.

Consolida em uma única base analítica padronizada os balanços contábeis de:
1. CVM (Companhias Abertas e Emissores de Dívida)
2. Diários Oficiais (Sociedades Anônimas Fechadas e Sociedades de Grande Porte)
3. BACEN IF.data (Instituições Financeiras Abertas e Fechadas)

Garante:
- Organização unificada por CNPJ, Razão Social e Exercício Social.
- Rastreabilidade com link para a fonte oficial de origem para conferência.
- Exportação colunar (Parquet) e carga em banco de dados relacional.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import polars as pl

from .bacen_ifdata import BacenIFDataScraper
from .cvm_statements import CVMStatementsScraper
from .diarios_oficiais import DiariosOficiaisScraper
from .models import UnifiedStatementRecord

logger = logging.getLogger("pulsebalancos.scrapers.unificador")


class UnifiedStatementsManager:
    """Gerenciador de consolidação de demonstrações contábeis de fontes públicas."""

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self.data_dir = Path(data_dir or Path("data"))
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.cvm_scraper = CVMStatementsScraper()
        self.do_scraper = DiariosOficiaisScraper()
        self.bacen_scraper = BacenIFDataScraper()

    def run_year_pipeline(
        self,
        year: int,
        sources: Optional[List[str]] = None,
    ) -> pl.DataFrame:
        """Executa a coleta unificada para o ano e exporta a base em Parquet."""
        sources = sources or ["CVM", "DIARIOS_OFICIAIS", "BACEN"]
        all_records: List[Dict] = []

        # 1. CVM (Companhias Abertas e Emissores de Debêntures)
        if "CVM" in sources:
            logger.info("Executando extração CVM para o exercício %d...", year)
            count = 0
            for record in self.cvm_scraper.extract_year(year):
                all_records.append(record.to_dict())
                count += 1
            logger.info("CVM: %d registros contábeis extraídos.", count)

        # 2. Diários Oficiais (Sociedades de Grande Porte e S.A.s Fechadas)
        if "DIARIOS_OFICIAIS" in sources:
            logger.info("Executando extração de Diários Oficiais para %d...", year)
            count_do = 0
            for record in self.do_scraper.extract_year(year):
                all_records.append(record.to_dict())
                count_do += 1
            logger.info("Diários Oficiais: %d registros extraídos.", count_do)

        # 3. BACEN IF.data (Instituições Financeiras)
        if "BACEN" in sources:
            logger.info("Executando extração BACEN IF.data para %d...", year)
            count_bacen = 0
            for record in self.bacen_scraper.extract_year(year):
                all_records.append(record.to_dict())
                count_bacen += 1
            logger.info("BACEN: %d registros extraídos.", count_bacen)

        if not all_records:
            logger.warning("Nenhum registro extraído para o exercício %d.", year)
            return pl.DataFrame()

        df_unified = pl.DataFrame(all_records)

        # Exportação para arquivo Parquet otimizado
        output_file = self.data_dir / f"demonstracoes_unificadas_{year}.parquet"
        df_unified.write_parquet(output_file)

        logger.info(
            "Base unificada do exercício %d exportada com sucesso: %s (%d registros, %.2f MB)",
            year,
            output_file,
            len(df_unified),
            output_file.stat().st_size / (1024 * 1024),
        )

        return df_unified

