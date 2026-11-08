"""Rotas e Endpoints da API Pública do PulseBalanços.

Espelha 100% das consultas, navegações e rankings do Balanços.AI:
- Busca instantânea (Nome, CNPJ, Ticker)
- Perfil completo da empresa com metadados, links CVM e séries históricas
- Matriz contábil (DRE, BPA, BPP, DFC, DVA) com Análise Vertical (% AV) e Horizontal (% AH)
- Módulo de Rankings & Insights (Maiores Ativos, Receitas, Lucros, Margens e Crescimento)
- Diretório Geográfico (Estados e Cidades) e Setorial (21 seções CNAE)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1", tags=["PulseBalanços Public API"])


# -----------------------------------------------------------------------------
# SCHEMAS DE RESPOSTA
# -----------------------------------------------------------------------------

class CompanySearchItem(BaseModel):
    id: int
    cnpj: str
    ticker_principal: Optional[str]
    razao_social: str
    nome_fantasia: Optional[str]
    slug: str
    uf: Optional[str]
    cidade: Optional[str]
    cnae_secao: Optional[str]
    is_active: bool


class CompanyProfile(BaseModel):
    id: int
    cnpj: str
    cd_cvm: Optional[int]
    ticker_principal: Optional[str]
    razao_social: str
    nome_fantasia: Optional[str]
    slug: str
    cnae_secao: Optional[str]
    cnae_descricao: Optional[str]
    setor_cvm: Optional[str]
    cidade: Optional[str]
    uf: Optional[str]
    situacao_cvm: str
    is_active: bool
    total_documentos_cvm: int


class FinancialSummaryYear(BaseModel):
    periodo: str  # Ex: "2023-12-31" ou "3T24"
    tipo_documento: str  # "DFP" ou "ITR"
    frequencia: str  # "ANUAL" ou "TTM_12M"
    receita_liquida: Optional[float]
    resultado_bruto: Optional[float]
    ebitda: Optional[float]
    lucro_liquido: Optional[float]
    ativo_total: Optional[float]
    patrimonio_liquido: Optional[float]
    margem_liquida: Optional[float]
    crescimento_receita_yoy: Optional[float]
    crescimento_lucro_yoy: Optional[float]
    url_documento_cvm: Optional[str]


class AccountRow(BaseModel):
    cd_conta: str
    ds_conta: str
    nivel: int
    valores_por_periodo: Dict[str, Optional[float]]
    analise_vertical: Dict[str, Optional[float]] = Field(default_factory=dict)
    analise_horizontal_yoy: Dict[str, Optional[float]] = Field(default_factory=dict)


class StatementsMatrixResponse(BaseModel):
    empresa_slug: str
    demonstracao: str  # "DRE", "BPA", "BPP", "DFC_MD", "DFC_MI", "DVA"
    consolidado: bool
    frequencia: str  # "ANUAL", "TRIMESTRAL", "TTM"
    periodos: List[str]  # Lista ordenada de datas (ex: ["2020", "2021", "2022", "2023"])
    linhas: List[AccountRow]


class RankingCompanyItem(BaseModel):
    posicao: int
    cnpj: str
    ticker_principal: Optional[str]
    razao_social: str
    slug: str
    uf: Optional[str]
    cidade: Optional[str]
    cnae_secao: Optional[str]
    cnae_descricao: Optional[str]
    ano_referencia: int
    valor_metrica: float
    margem_liquida: Optional[float]
    crescimento_yoy: Optional[float]


# -----------------------------------------------------------------------------
# 1. BUSCA E AUTOCOMPLETE
# -----------------------------------------------------------------------------

@router.get("/search", response_model=List[CompanySearchItem])
async def search_companies(
    q: str = Query(..., min_length=2, description="Ticker, CNPJ ou Nome da Empresa"),
    limit: int = Query(15, ge=1, le=50),
) -> Any:
    """Busca rápida instantânea no catálogo oficial de empresas."""
    # Implementação via consulta SQL com ILIKE / Trigram index
    return []


# -----------------------------------------------------------------------------
# 2. PERFIL DA EMPRESA E SÉRIES HISTÓRICAS TTM
# -----------------------------------------------------------------------------

@router.get("/empresas/{identifier}", response_model=CompanyProfile)
async def get_company_profile(
    identifier: str,  # CNPJ (com ou sem pontuação) ou slug
) -> Any:
    """Retorna dados cadastrais oficiais, localização e metadados CVM."""
    return {}


@router.get("/empresas/{identifier}/resumo-historico", response_model=List[FinancialSummaryYear])
async def get_company_historical_summary(
    identifier: str,
    consolidado: bool = Query(True, description="Balanço consolidado (True) ou individual (False)"),
    modo: str = Query("TTM", regex="^(TTM|ANUAL|TRIMESTRAL)$", description="Visão 12M TTM, DFP anual ou ITR trimestral"),
) -> Any:
    """Retorna tabela resumida histórica com Receita, Lucro, Margens, YoY e links para DFP/ITR da CVM."""
    return []


# -----------------------------------------------------------------------------
# 3. MATRIZ CONTÁBIL COMPLETA (ÁRVORE DE CONTAS IFRS)
# -----------------------------------------------------------------------------

@router.get("/empresas/{identifier}/demonstracoes", response_model=StatementsMatrixResponse)
async def get_financial_statements_matrix(
    identifier: str,
    demonstracao: str = Query("DRE", regex="^(DRE|BPA|BPP|DFC_MD|DFC_MI|DVA)$"),
    consolidado: bool = Query(True),
    frequencia: str = Query("ANUAL", regex="^(ANUAL|TRIMESTRAL|TTM)$"),
    anos: Optional[str] = Query(None, description="Lista de anos separados por vírgula (ex: 2020,2021,2022,2023)"),
) -> Any:
    """Retorna a matriz contábil estruturada em árvore com períodos em colunas, AV (%) e AH (YoY %)."""
    return {}


# -----------------------------------------------------------------------------
# 4. DOCUMENTOS PROTOCOLADOS NA CVM
# -----------------------------------------------------------------------------

@router.get("/empresas/{identifier}/documentos")
async def get_company_documents(
    identifier: str,
    tipo: Optional[str] = Query(None, regex="^(DFP|ITR|FRE|FCA)$"),
) -> Any:
    """Retorna histórico cronológico de publicações CVM com data de entrega, versão e link oficial."""
    return []


# -----------------------------------------------------------------------------
# 5. RANKINGS & INSIGHTS (EQUIVALENTE AO BALANÇOS.AI/INSIGHTS)
# -----------------------------------------------------------------------------

@router.get("/insights/maiores-empresas", response_model=List[RankingCompanyItem])
async def get_top_companies(
    metrica: str = Query("ativo_total", regex="^(ativo_total|receita_liquida)$"),
    cnae: Optional[str] = Query(None, description="Letra da seção CNAE (A-U)"),
    uf: Optional[str] = Query(None, max_length=2, description="Sigla do Estado (ex: SP, RJ, MG)"),
    ano: Optional[int] = Query(None, description="Ano de referência (padrão: último homologado)"),
    limit: int = Query(50, ge=1, le=200),
) -> Any:
    """Ranking oficial das maiores empresas brasileiras por Ativo Total ou Receita Líquida."""
    return []


@router.get("/insights/maiores-lucros", response_model=List[RankingCompanyItem])
async def get_top_profits(
    ano: Optional[int] = Query(None),
    cnae: Optional[str] = Query(None),
    uf: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> Any:
    """Ranking das empresas mais lucrativas do Brasil."""
    return []


@router.get("/insights/maiores-margens", response_model=List[RankingCompanyItem])
async def get_top_margins(
    min_receita: float = Query(100_000_000.0, description="Receita líquida mínima para filtrar distorções (padrão: 100M BRL)"),
    ano: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> Any:
    """Ranking das empresas mais eficientes por Margem Líquida."""
    return []


@router.get("/insights/empresas-que-mais-crescem", response_model=List[RankingCompanyItem])
async def get_fastest_growing(
    metrica: str = Query("crescimento_receita_yoy", regex="^(crescimento_receita_yoy|crescimento_lucro_yoy)$"),
    min_receita: float = Query(50_000_000.0),
    limit: int = Query(50, ge=1, le=200),
) -> Any:
    """Ranking de empresas com maior expansão anual (YoY)."""
    return []


# -----------------------------------------------------------------------------
# 6. DIRETÓRIO GEOGRÁFICO E SETORIAL
# -----------------------------------------------------------------------------

@router.get("/geo/estados")
async def list_states_summary() -> Any:
    """Lista todos os 27 estados com contagem de empresas registradas e total de ativos."""
    return []


@router.get("/geo/cidades")
async def list_cities_by_state(
    uf: str = Query(..., min_length=2, max_length=2),
) -> Any:
    """Lista cidades de uma UF com empresas e histórico de publicações contábeis."""
    return []


@router.get("/cnae/secoes")
async def list_cnae_sections() -> Any:
    """Lista as 21 seções econômicas do CNAE (A a U) com contagem de empresas e receita agregada."""
    return []
