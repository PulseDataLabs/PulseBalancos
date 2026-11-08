-- ==============================================================================
-- PulseDataLabs - PulseFinancials
-- DDL PostgreSQL para Demonstrações Financeiras e Indicadores Fundamentalistas
-- ==============================================================================

-- 1. Criação das Extensões Necessárias
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ==============================================================================
-- TABELA: companies (Companhias Abertas / Emissores)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS companies (
    id SERIAL PRIMARY KEY,
    cnpj VARCHAR(14) NOT NULL UNIQUE,
    cd_cvm BIGINT UNIQUE,
    ticker_principal VARCHAR(10),
    razao_social VARCHAR(255) NOT NULL,
    nome_fantasia VARCHAR(255),
    setor VARCHAR(100),
    subsetor VARCHAR(100),
    segmento_listagem VARCHAR(50),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    dt_registro DATE,
    dt_cancelamento DATE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc', NOW()),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc', NOW())
);

-- ==============================================================================
-- TABELA: accounts (Plano de Contas Padronizado CVM / IFRS)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS accounts (
    id SERIAL PRIMARY KEY,
    cd_conta VARCHAR(50) NOT NULL,
    ds_conta VARCHAR(255) NOT NULL,
    demonstracao VARCHAR(20) NOT NULL CHECK (demonstracao IN ('DRE', 'BPA', 'BPP', 'DFC_MD', 'DFC_MI')),
    is_standard BOOLEAN NOT NULL DEFAULT FALSE,
    nivel INT GENERATED ALWAYS AS (LENGTH(cd_conta) - LENGTH(REPLACE(cd_conta, '.', '')) + 1) STORED,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc', NOW()),
    CONSTRAINT uq_accounts_code_demo UNIQUE (cd_conta, demonstracao)
);

-- ==============================================================================
-- TABELA: report_periods (Períodos de Referência Contábil)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS report_periods (
    id SERIAL PRIMARY KEY,
    dt_referencia DATE NOT NULL,
    dt_ini_exerc DATE,
    dt_fim_exerc DATE,
    tipo_documento VARCHAR(10) NOT NULL CHECK (tipo_documento IN ('DFP', 'ITR')),
    ano INT NOT NULL,
    trimestre INT CHECK (trimestre IN (1, 2, 3, 4)),
    versao INT NOT NULL DEFAULT 1,
    ordem_exercicio VARCHAR(20) NOT NULL DEFAULT 'ÚLTIMO',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc', NOW()),
    CONSTRAINT uq_report_periods UNIQUE (dt_referencia, tipo_documento, versao, ordem_exercicio)
);

-- ==============================================================================
-- TABELA: financial_statements (Demonstrações Financeiras / Rubricas Contábeis)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS financial_statements (
    id BIGSERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    account_id INT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    period_id INT NOT NULL REFERENCES report_periods(id) ON DELETE CASCADE,
    consolidado BOOLEAN NOT NULL DEFAULT TRUE,
    vl_conta_ajustado NUMERIC(20, 2) NOT NULL,
    escala_original VARCHAR(20),
    moeda VARCHAR(10) DEFAULT 'REAL',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc', NOW()),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc', NOW()),
    CONSTRAINT uq_financial_statements_cell UNIQUE (company_id, account_id, period_id, consolidado)
);

-- ==============================================================================
-- TABELA: financial_ratios (Múltiplos e Indicadores Fundamentalistas Pré-calculados)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS financial_ratios (
    id BIGSERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    period_id INT NOT NULL REFERENCES report_periods(id) ON DELETE CASCADE,
    pl NUMERIC(12, 2),
    pvp NUMERIC(12, 2),
    ev_ebitda NUMERIC(12, 2),
    roe NUMERIC(10, 4),
    roic NUMERIC(10, 4),
    roa NUMERIC(10, 4),
    margem_bruta NUMERIC(10, 4),
    margem_ebitda NUMERIC(10, 4),
    margem_liquida NUMERIC(10, 4),
    divida_liquida_ebitda NUMERIC(10, 2),
    divida_liquida_patrimonio NUMERIC(10, 2),
    liquidez_corrente NUMERIC(10, 2),
    lucro_por_acao NUMERIC(12, 4),
    valor_patrimonial_acao NUMERIC(12, 4),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc', NOW()),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc', NOW()),
    CONSTRAINT uq_financial_ratios_period UNIQUE (company_id, period_id)
);

-- ==============================================================================
-- ÍNDICES OTIMIZADOS PARA CONSULTAS MATRICIAIS E ANÁLISE TEMPORAL
-- ==============================================================================

-- Busca rápida de companhias por ticker e CNPJ
CREATE INDEX IF NOT EXISTS idx_companies_ticker ON companies(ticker_principal) WHERE ticker_principal IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_companies_cnpj ON companies(cnpj);
CREATE INDEX IF NOT EXISTS idx_companies_cd_cvm ON companies(cd_cvm);

-- Índices de consulta matricial (Empresa + Período + Demonstração)
CREATE INDEX IF NOT EXISTS idx_fs_matrix_lookup 
    ON financial_statements (company_id, period_id, consolidado);

CREATE INDEX IF NOT EXISTS idx_fs_account_lookup 
    ON financial_statements (account_id, period_id);

CREATE INDEX IF NOT EXISTS idx_fs_composite_query 
    ON financial_statements (company_id, account_id, consolidado);

-- Índices temporais em períodos
CREATE INDEX IF NOT EXISTS idx_periods_dt_ref 
    ON report_periods (dt_referencia DESC);

CREATE INDEX IF NOT EXISTS idx_periods_ano_doc 
    ON report_periods (ano DESC, tipo_documento);

-- Índices em indicadores fundamentalistas
CREATE INDEX IF NOT EXISTS idx_ratios_company 
    ON financial_ratios (company_id, period_id);

CREATE INDEX IF NOT EXISTS idx_ratios_screener 
    ON financial_ratios (period_id, roe DESC, pl ASC) 
    WHERE roe IS NOT NULL AND pl IS NOT NULL;

-- ==============================================================================
-- VIEWS DE ALTO DESEMPENHO E CONSULTA
-- ==============================================================================

-- 1. View Analítica Completa para Exportação e Consultas Flat
CREATE OR REPLACE VIEW vw_financial_statements_flat AS
SELECT 
    c.id AS company_id,
    c.cnpj,
    c.cd_cvm,
    c.ticker_principal,
    c.razao_social,
    c.setor,
    p.id AS period_id,
    p.dt_referencia,
    p.tipo_documento,
    p.ano,
    p.trimestre,
    a.cd_conta,
    a.ds_conta,
    a.demonstracao,
    a.nivel,
    fs.consolidado,
    fs.vl_conta_ajustado
FROM financial_statements fs
JOIN companies c ON c.id = fs.company_id
JOIN accounts a ON a.id = fs.account_id
JOIN report_periods p ON p.id = fs.period_id;

-- 2. View de Screener Fundamentalista (Último Período Disponível por Companhia)
CREATE OR REPLACE VIEW vw_fundamental_screener AS
WITH latest_periods AS (
    SELECT DISTINCT ON (company_id)
        company_id,
        period_id,
        pl,
        pvp,
        ev_ebitda,
        roe,
        roic,
        margem_liquida,
        divida_liquida_ebitda,
        liquidez_corrente
    FROM financial_ratios fr
    JOIN report_periods rp ON rp.id = fr.period_id
    ORDER BY company_id, rp.dt_referencia DESC, rp.versao DESC
)
SELECT 
    c.id AS company_id,
    c.ticker_principal,
    c.razao_social,
    c.cnpj,
    c.setor,
    c.subsetor,
    c.segmento_listagem,
    rp.dt_referencia AS dt_ultimo_balanco,
    rp.tipo_documento AS tipo_ultimo_doc,
    lp.pl,
    lp.pvp,
    lp.ev_ebitda,
    lp.roe,
    lp.roic,
    lp.margem_liquida,
    lp.divida_liquida_ebitda,
    lp.liquidez_corrente
FROM latest_periods lp
JOIN companies c ON c.id = lp.company_id
JOIN report_periods rp ON rp.id = lp.period_id
WHERE c.is_active = TRUE;
