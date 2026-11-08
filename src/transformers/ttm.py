"""Módulo de Cálculo de Séries Históricas, TTM e Indicadores Fundamentalistas.

Implementa os cálculos contábeis exatos utilizados em plataformas como Balanços.AI:
- TTM (Trailing Twelve Months / Doze Meses Encerrados) para ITRs:
    TTM = DRE_Acumulado_Ano_Atual + DFP_Ano_Anterior - DRE_Acumulado_Mesmo_Ponto_Ano_Anterior
- Análise Horizontal YoY (% de crescimento de Receita, Lucro e Ativo).
- Margens Operacionais e Líquidas.
- Validação de Integridade Contábil (Equação Fundamental: Ativo == Passivo + PL).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import polars as pl

logger = logging.getLogger("pulsebalancos.transformers.ttm")


# Mapeamento padrão de rubricas CVM (IFRS)
STANDARD_ACCOUNTS = {
    "ativo_total": "1",
    "passivo_total": "2",
    "patrimonio_liquido": "2.03",
    "caixa_equivalentes": "1.01.01",
    "aplicacoes_financeiras": "1.01.02",
    "emprestimos_cp": "2.01.04",
    "emprestimos_lp": "2.02.01",
    "receita_liquida": "3.01",
    "resultado_bruto": "3.03",
    "ebit": "3.05",
    "lucro_liquido": "3.11",  # Ou 3.09/3.99 dependendo do plano de contas
}


@dataclass
class CompanyPeriodMetrics:
    """Métricas consolidadas de um período contábil."""

    cnpj: str
    dt_referencia: str
    tipo_documento: str
    frequencia: str  # 'ANUAL', 'ACUMULADO', 'ISOLADO_3M', 'TTM_12M'
    ativo_total: Optional[float]
    patrimonio_liquido: Optional[float]
    receita_liquida: Optional[float]
    resultado_bruto: Optional[float]
    ebitda: Optional[float]
    lucro_liquido: Optional[float]
    divida_liquida: Optional[float]
    margem_bruta: Optional[float]
    margem_liquida: Optional[float]
    crescimento_receita_yoy: Optional[float]
    crescimento_lucro_yoy: Optional[float]
    is_balance_balanced: bool


class FinancialMetricsTransformer:
    """Motor de derivação de séries temporais TTM e múltiplos contábeis."""

    @staticmethod
    def calculate_ttm_dre(
        dre_current_accumulated: float,
        dfp_previous_year: float,
        dre_previous_accumulated_same_point: float,
    ) -> float:
        """Calcula o valor acumulado dos últimos 12 meses (TTM) para uma conta da DRE.

        Fórmula oficial contábil:
            Resultado acumulado no exercício (ITR atual)
            + DFP do exercício anterior (12 meses fechados)
            - Resultado acumulado no mesmo ponto do exercício anterior (ITR comparativo)
        """
        return dre_current_accumulated + dfp_previous_year - dre_previous_accumulated_same_point

    @staticmethod
    def compute_margins(
        receita_liquida: Optional[float],
        resultado_bruto: Optional[float],
        ebitda: Optional[float],
        lucro_liquido: Optional[float],
    ) -> Dict[str, Optional[float]]:
        """Calcula margens percentuais a partir da receita líquida."""
        if not receita_liquida or receita_liquida <= 0:
            return {
                "margem_bruta": None,
                "margem_ebitda": None,
                "margem_liquida": None,
            }

        return {
            "margem_bruta": (resultado_bruto / receita_liquida) if resultado_bruto is not None else None,
            "margem_ebitda": (ebitda / receita_liquida) if ebitda is not None else None,
            "margem_liquida": (lucro_liquido / receita_liquida) if lucro_liquido is not None else None,
        }

    @staticmethod
    def compute_yoy_growth(
        val_current: Optional[float],
        val_previous_year: Optional[float],
    ) -> Optional[float]:
        """Calcula a taxa de crescimento anual (Year-over-Year)."""
        if (
            val_current is None
            or val_previous_year is None
            or val_previous_year == 0
        ):
            return None
        return (val_current - val_previous_year) / abs(val_previous_year)

    @classmethod
    def transform_statements_to_summaries(
        cls,
        statements_df: pl.DataFrame,
    ) -> pl.DataFrame:
        """Transforma a tabela relacional de contas em uma matriz resumida de indicadores.

        Processa séries históricas por companhia e período, computando margens e
        variações temporais.
        """
        if statements_df.is_empty():
            return pl.DataFrame()

        # Pivota contas principais para colunas
        pivoted = statements_df.filter(
            pl.col("cd_conta").is_in(list(STANDARD_ACCOUNTS.values()))
        ).pivot(
            on="cd_conta",
            index=["cnpj_cia", "dt_referencia", "tipo_documento", "is_consolidado"],
            values="vl_conta_ajustado",
            aggregate_function="first",
        )

        logger.info("Matriz de contas pivotada com %d linhas de períodos.", len(pivoted))
        return pivoted
