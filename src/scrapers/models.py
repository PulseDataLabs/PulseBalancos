"""PulseBalanços - Modelos de Dados Unificados para Demonstrações Financeiras.

Define o esquema canônico que padroniza os balanços contábeis independentemente
da fonte oficial de origem (CVM, Diários Oficiais, BACEN IF.data).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass(slots=True)
class UnifiedStatementRecord:
    """Registro atômico de uma rubrica contábil com auditoria e rastreabilidade da origem."""

    cnpj: str  # 14 dígitos limpos
    razao_social: str
    nome_fantasia: Optional[str]
    tipo_empresa: str  # 'CIA_ABERTA', 'CIA_FECHADA_EMISSORA', 'SOCIEDADE_GRANDE_PORTE', 'INSTITUICAO_FINANCEIRA'
    exercicio: int  # Ano de referência contábil (ex: 2023)
    dt_referencia: str  # Data exata do balanço (YYYY-MM-DD)
    tipo_documento: str  # 'DFP', 'ITR', 'BALANCO_PUBLICADO_DO', 'IFDATA'
    demonstracao: str  # 'BPA', 'BPP', 'DRE', 'DFC_MD', 'DFC_MI', 'DVA'
    cd_conta: str  # Código estruturado IFRS (ex: '3.01', '1.01.01')
    ds_conta: str  # Descrição oficial da conta (ex: 'Receita Líquida')
    vl_conta: float  # Valor nominal ajustado em Reais (BRL)
    is_consolidado: bool  # True para balanço consolidado, False para individual
    fonte_origem: str  # 'CVM', 'DOU', 'DOESP', 'DOESC', 'BACEN'
    url_origem: str  # Link rastreável para conferência do documento original
    numero_protocolo: Optional[str] = None  # Número do protocolo de entrega ou autenticação
    edicao_pagina: Optional[str] = None  # Edição e página em caso de publicação em Diário Oficial

    def to_dict(self) -> Dict[str, Any]:
        """Serializa o registro para dicionário."""
        return asdict(self)


@dataclass(slots=True)
class OfficialPublicationMetadata:
    """Metadados de publicação oficial de balanço para conferência pública."""

    cnpj: str
    razao_social: str
    tipo_empresa: str
    exercicio: int
    data_publicacao: str
    veiculo_publicacao: str  # Ex: 'Diário Oficial da União', 'DOESP', 'CVM'
    edicao: Optional[str]
    pagina: Optional[str]
    url_documento: str
    tipo_documento: str
    possui_auditoria: bool
    auditor_independente: Optional[str] = None
