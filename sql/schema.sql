-- ==============================================================================
-- PulseDataLabs - PulseFinancials
-- DDL PostgreSQL Completo: Demonstrações Contábeis, Séries Históricas e Rankings
-- Modelagem equivalente às funcionalidades e consultas públicas do Balanços.AI
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ==============================================================================
-- 1. TABELA: cnae_sections (Classificação Nacional de Atividades Econômicas)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS cnae_sections (
    codigo CHAR(1) PRIMARY KEY, -- Ex: 'A', 'B', 'C' ... 'U'
    descricao VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc', NOW())
);

-- ==============================================================================
-- 2. TABELA: companies (Companhias Abertas e Emissores Registrados CVM)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS companies (
    id SERIAL PRIMARY KEY,
    cnpj VARCHAR(14) NOT NULL UNIQUE,
    cd_cvm BIGINT UNIQUE,
    ticker_principal VARCHAR(10),
    razao_social VARCHAR(255) NOT NULL,
    nome_fantasia VARCHAR(255),
    slug VARCHAR(255) UNIQUE,
    cnae_secao CHAR(1) REFERENCES cnae_sections(codigo),
    cnae_codigo VARCHAR(10),
    cnae_descricao VARCHAR(255),
    setor_cvm VARCHAR(100),
    cidade VARCHAR(100),
    uf CHAR(2),
    situacao_cvm VARCHAR(50) DEFAULT 'ATIVO',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    categoria_registro VARCHAR(20), -- 'A' (Ações), 'B' (Dívida/Outros)
    dt_registro DATE,
    dt_cancelamento DATE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc', NOW()),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc', NOW())
);

-- ==============================================================================
-- 3. TABELA: documents (Protocolos e Arquivos Oficiais CVM - DFP/ITR/FRE/FCA)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS documents (
    id BIGSERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    tipo_documento VARCHAR(20) NOT NULL, -- 'DFP', 'ITR', 'FRE', 'FCA'
    ano_referencia INT NOT NULL,
    versao INT NOT NULL DEFAULT 1,
    dt_referencia DATE NOT NULL,
    dt_recebimento TIMESTAMP WITH TIME ZONE,
    status_documento VARCHAR(20) DEFAULT 'ATIVO',
    numero_protocolo_cvm VARCHAR(50),
    url_cvm_documento TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc', NOW()),
    CONSTRAINT uq_documents_protocol UNIQUE (company_id, tipo_documento, ano_referencia, versao, dt_referencia)
);

-- ==============================================================================
-- 4. TABELA: accounts (Plano de Contas IFRS / CVM)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS accounts (
    id SERIAL PRIMARY KEY,
    cd_conta VARCHAR(50) NOT NULL,
    ds_conta VARCHAR(255) NOT NULL,
    demonstracao VARCHAR(20) NOT NULL CHECK (demonstracao IN ('DRE', 'BPA', 'BPP', 'DFC_MD', 'DFC_MI', 'DVA')),
    is_standard BOOLEAN NOT NULL DEFAULT FALSE,
    nivel INT GENERATED ALWAYS AS (LENGTH(cd_conta) - LENGTH(REPLACE(cd_conta, '.', '')) + 1) STORED,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc', NOW()),
    CONSTRAINT uq_accounts_code_demo UNIQUE (cd_conta, demonstracao)
);

-- ==============================================================================
-- 5. TABELA: report_periods (Períodos Contábeis: Anuais, Trimestrais e TTM)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS report_periods (
    id SERIAL PRIMARY KEY,
    dt_referencia DATE NOT NULL,
    dt_ini_exerc DATE,
    dt_fim_exerc DATE,
    tipo_documento VARCHAR(10) NOT NULL CHECK (tipo_documento IN ('DFP', 'ITR')),
    frequencia VARCHAR(20) NOT NULL DEFAULT 'ACUMULADO' CHECK (frequencia IN ('ANUAL', 'ACUMULADO', 'ISOLADO_3M', 'TTM_12M')),
    ano INT NOT NULL,
    trimestre INT CHECK (trimestre IN (1, 2, 3, 4)),
    versao INT NOT NULL DEFAULT 1,
    ordem_exercicio VARCHAR(20) NOT NULL DEFAULT 'ÚLTIMO',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc', NOW()),
    CONSTRAINT uq_report_periods UNIQUE (dt_referencia, tipo_documento, frequencia, versao, ordem_exercicio)
);

-- ==============================================================================
-- 6. TABELA: financial_statements (Saldos Contábeis das Demonstrações)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS financial_statements (
    id BIGSERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    account_id INT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    period_id INT NOT NULL REFERENCES report_periods(id) ON DELETE CASCADE,
    document_id BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    consolidado BOOLEAN NOT NULL DEFAULT TRUE,
    vl_conta_ajustado NUMERIC(20, 2) NOT NULL,
    escala_original VARCHAR(20),
    moeda VARCHAR(10) DEFAULT 'REAL',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc', NOW()),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc', NOW()),
    CONSTRAINT uq_financial_statements_cell UNIQUE (company_id, account_id, period_id, consolidado)
);

-- ==============================================================================
-- 7. TABELA: company_financial_summaries (Séries Históricas e Métricas TTM)
-- Para abastecer consultas rápidas estilo Balanços.AI (Receita, Lucro, Margens e YoY)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS company_financial_summaries (
    id BIGSERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    period_id INT NOT NULL REFERENCES report_periods(id) ON DELETE CASCADE,
    document_id BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    consolidado BOOLEAN NOT NULL DEFAULT TRUE,
    
    -- Valores em Reais (Nominal)
    ativo_total NUMERIC(20, 2),
    patrimonio_liquido NUMERIC(20, 2),
    receita_liquida NUMERIC(20, 2),
    resultado_bruto NUMERIC(20, 2),
    ebitda NUMERIC(20, 2),
    lucro_liquido NUMERIC(20, 2),
    fluxo_caixa_operacional NUMERIC(20, 2),
    divida_bruta NUMERIC(20, 2),
    divida_liquida NUMERIC(20, 2),
    
    -- Variações Horizontais YoY (%)
    crescimento_receita_yoy NUMERIC(10, 4),
    crescimento_lucro_yoy NUMERIC(10, 4),
    crescimento_ativo_yoy NUMERIC(10, 4),
    
    -- Margens e Indicadores de Eficiência
    margem_bruta NUMERIC(10, 4),
    margem_ebitda NUMERIC(10, 4),
    margem_liquida NUMERIC(10, 4),
    roe NUMERIC(10, 4),
    roic NUMERIC(10, 4),
    
    -- Integridade Contábil
    is_balance_balanced BOOLEAN DEFAULT TRUE, -- Ativo == Passivo + PL
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc', NOW()),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc', NOW()),
    CONSTRAINT uq_company_financial_summaries UNIQUE (company_id, period_id, consolidado)
);

-- ==============================================================================
-- ÍNDICES OTIMIZADOS PARA BUSCA, GEOGRAFIA, SETOR E RANKINGS
-- ==============================================================================

-- Busca Instantânea e Slugs
CREATE INDEX IF NOT EXISTS idx_companies_search ON companies (ticker_principal, cnpj, razao_social);
CREATE INDEX IF NOT EXISTS idx_companies_slug ON companies (slug);
CREATE INDEX IF NOT EXISTS idx_companies_geo ON companies (uf, cidade);
CREATE INDEX IF NOT EXISTS idx_companies_cnae ON companies (cnae_secao, cnae_codigo);

-- Consultas Matriciais de Balanços
CREATE INDEX IF NOT EXISTS idx_fs_matrix_lookup ON financial_statements (company_id, period_id, consolidado);
CREATE INDEX IF NOT EXISTS idx_fs_account_lookup ON financial_statements (account_id, period_id);
CREATE INDEX IF NOT EXISTS idx_fs_composite ON financial_statements (company_id, account_id, consolidado);

-- Rankings & Insights de Alta Performance
CREATE INDEX IF NOT EXISTS idx_rank_ativo ON company_financial_summaries (period_id, consolidado, ativo_total DESC);
CREATE INDEX IF NOT EXISTS idx_rank_receita ON company_financial_summaries (period_id, consolidado, receita_liquida DESC);
CREATE INDEX IF NOT EXISTS idx_rank_lucro ON company_financial_summaries (period_id, consolidado, lucro_liquido DESC);
CREATE INDEX IF NOT EXISTS idx_rank_margem ON company_financial_summaries (period_id, consolidado, margem_liquida DESC);
CREATE INDEX IF NOT EXISTS idx_rank_crescimento ON company_financial_summaries (period_id, consolidado, crescimento_receita_yoy DESC);

-- ==============================================================================
-- VIEWS DE CONSULTA PÚBLICA (ESTILO BALANÇOS.AI)
-- ==============================================================================

-- 1. View do Ranking das Maiores Empresas (Último Período Homologado)
CREATE OR REPLACE VIEW vw_ranking_maiores_empresas AS
WITH latest_summary AS (
    SELECT DISTINCT ON (cfs.company_id)
        cfs.*,
        p.dt_referencia,
        p.ano,
        p.trimestre,
        p.tipo_documento,
        p.frequencia
    FROM company_financial_summaries cfs
    JOIN report_periods p ON p.id = cfs.period_id
    WHERE cfs.consolidado = TRUE
    ORDER BY cfs.company_id, p.dt_referencia DESC, p.versao DESC
)
SELECT 
    c.id AS company_id,
    c.cnpj,
    c.ticker_principal,
    c.razao_social,
    c.nome_fantasia,
    c.slug,
    c.uf,
    c.cidade,
    c.cnae_secao,
    c.cnae_descricao,
    ls.dt_referencia,
    ls.tipo_documento,
    ls.frequencia,
    ls.ativo_total,
    ls.receita_liquida,
    ls.lucro_liquido,
    ls.margem_liquida,
    ls.crescimento_receita_yoy,
    ls.roe
FROM latest_summary ls
JOIN companies c ON c.id = ls.company_id
WHERE c.is_active = TRUE;
