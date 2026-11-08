# 📊 PulseBalanços (PulseBalancos)

[![Pipeline CVM](https://github.com/PulseDataLabs/PulseBalancos/actions/workflows/etl.yml/badge.svg)](https://github.com/PulseDataLabs/PulseBalancos/actions/workflows/etl.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![Database: PostgreSQL](https://img.shields.io/badge/PostgreSQL-Ready-336791.svg)](sql/schema.sql)
[![Data: CVM & B3](https://img.shields.io/badge/Data-CVM%20%2F%20B3-00d4ff.svg)](https://dados.cvm.gov.br/)

Plataforma aberta de ingestão, normalização, séries históricas (**TTM**) e consulta pública de demonstrações contábeis e indicadores de empresas brasileiras (padrão CVM / B3), desenvolvida pela **[PulseDataLabs](https://github.com/PulseDataLabs)**.

Inspirado nas funcionalidades e na transparência de dados públicos de portais como o **Balanços.AI** (com foco exclusivo em dados estruturados, séries históricas e consultas analíticas de alta performance, sem IA/MCP).

🌐 **Acesse a Interface Pública:** [https://pulsedatalabs.github.io/PulseBalancos/](https://pulsedatalabs.github.io/PulseBalancos/)  
🔍 **Consulta Interativa de Empresas:** [https://pulsedatalabs.github.io/PulseBalancos/consulta.html](https://pulsedatalabs.github.io/PulseBalancos/consulta.html)

---

## 🎯 Principais Funcionalidades

1. **Demonstrações Contábeis Completas (IFRS/CVM):**
   - Balanço Patrimonial Ativo (**BPA**) e Passivo (**BPP**)
   - Demonstração do Resultado do Exercício (**DRE**)
   - Demonstração do Fluxo de Caixa Método Direto (**DFC_MD**) e Indireto (**DFC_MI**)
   - Demonstração do Valor Adicionado (**DVA**)
   - Visões Consolidadas (`CON`) e Individuais (`IND`).

2. **Séries Históricas e Métrica TTM (Trailing Twelve Months):**
   - Cálculo contábil oficial de doze meses encerrados para balanços trimestrais (ITRs):
     $$\text{TTM} = \text{ITR}_{\text{Atual Acumulada}} + \text{DFP}_{\text{Ano Anterior}} - \text{ITR}_{\text{Mesmo Ponto Anterior}}$$
   - Análise Vertical (**AV %**) e Análise Horizontal (**AH % YoY**).

3. **Catálogo Unificado de Companhias (CVM + B3):**
   - 2.532 empresas mapeadas com histórico contábil auditado.
   - 650 empresas com registro ativo na CVM.
   - 394 ações e units listadas na B3 cruzadas via formulários FCA.
   - Identificação de auditor independente, município e estado da sede.

4. **Rankings e Insights Públicos:**
   - Maiores Empresas por Ativo Total e por Receita Líquida.
   - Empresas com Maiores Lucros Líquidos.
   - Empresas com Maiores Margens Operacionais e Líquidas.
   - Empresas que Mais Crescem (crescimento anual YoY).

5. **Auditoria e Rastreabilidade Total:**
   - Vínculo direto de cada período contábil com o número do protocolo e link oficial na CVM.
   - Validação automática da equação fundamental da contabilidade ($Ativo = Passivo + PL$).

---

## 🏗️ Arquitetura e Filosofia Técnica

- **Serverless & GitHub Actions First:** Ingestão agendada via GitHub Actions (07h00 e 20h00 BRT nos dias úteis), sem necessidade de servidores dedicados ativos 24/7.
- **Processamento em Memória (Polars + BytesIO):** Download de pacotes `.zip` da CVM com parsing direto em stream de memória, sem escrita de gigabytes temporários em disco.
- **Cache HTTP 304:** Envio de cabeçalhos `ETag` e `If-Modified-Since` para evitar downloads e reprocessamento quando não houver retificações na CVM.
- **Idempotência no PostgreSQL:** Operações em lote com chaves compostas e `ON CONFLICT DO UPDATE`.

---

## 📁 Estrutura do Projeto

```text
PulseBalancos/
├── .github/workflows/
│   └── etl.yml                    # Pipeline serverless agendado (07h / 20h BRT)
├── src/
│   ├── extractors/
│   │   └── cvm.py                 # Ingestão em memória com Polars, saneamento de escala e codificação
│   ├── transformers/
│   │   └── ttm.py                 # Motor de cálculo TTM, margens e variações YoY
│   └── api/
│       └── routes.py              # Endpoints REST para buscas, matrizes, perfis e rankings
├── sql/
│   └── schema.sql                 # DDL PostgreSQL completo com índices compostos e views
├── scripts/
│   └── build_companies_catalog.py # Construtor do catálogo mestre enriquecido com tickers B3
├── data/
│   ├── companies_catalog.parquet  # Base colunar de alta performance (136 KB)
│   └── companies_catalog.json     # Catálogo completo para consumo web e APIs (1.4 MB)
├── index.html                     # Landing page institucional com Design System PulseDataLabs
├── consulta.html                  # Interface de busca e filtragem com DataTables e exportação
├── requirements.txt
├── run_all.py                     # Orquestrador central de execução
└── README.md
```

---

## 🚀 Execução Local

```bash
# 1. Clonar e entrar no diretório
git clone https://github.com/PulseDataLabs/PulseBalancos.git
cd PulseBalancos

# 2. Criar e ativar ambiente virtual (com uv ou python venv)
uv venv
source .venv/bin/activate

# 3. Instalar dependências
uv pip install -r requirements.txt

# 4. Gerar ou atualizar catálogo mestre de companhias CVM/B3
python scripts/build_companies_catalog.py

# 5. Executar pipeline de teste de demonstrações contábeis
python run_all.py --year 2024 --doc-type ALL
```

---

## 📊 Dicionário de Dados do Catálogo (`companies_catalog.parquet`)

| Campo | Tipo | Descrição | Exemplo |
|:---|:---:|:---|:---|
| `cnpj` | `Utf8` | CNPJ higienizado com 14 dígitos | `33000167000101` |
| `cd_cvm` | `Int64` | Código de registro na CVM | `9512` |
| `ticker_principal` | `Utf8` | Ticker de maior liquidez negociado na B3 | `PETR4` |
| `tickers_list` | `List[Utf8]` | Lista com todas as classes de ações listadas | `['PETR3', 'PETR4']` |
| `razao_social` | `Utf8` | Denominação social oficial registrada na CVM | `PETRÓLEO BRASILEIRO S.A. - PETROBRAS` |
| `nome_fantasia` | `Utf8` | Nome comercial / fantasia | `PETROBRAS` |
| `slug` | `Utf8` | Slug amigável padronizado para URLs | `petroleo-brasileiro-sa-petrobras` |
| `setor_cvm` | `Utf8` | Setor oficial de atividade na CVM | `Petróleo e Gás` |
| `categoria_registro`| `Utf8` | Categoria de registro CVM (`Categoria A` ou `B`) | `Categoria A` |
| `situacao_cvm` | `Utf8` | Situação cadastral (`ATIVO`, `CANCELADA`, etc.) | `ATIVO` |
| `is_active` | `Boolean`| Flag indicando se a empresa tem registro regular | `true` |
| `cidade` | `Utf8` | Município da sede corporativa | `RIO DE JANEIRO` |
| `uf` | `Utf8` | Unidade federativa da sede | `RJ` |
| `auditor` | `Utf8` | Razão social do auditor independente | `KPMG AUDITORES INDEPENDENTES LTDA.` |

---

## 📄 Licença
Open-source sob licença MIT. Desenvolvido com carinho pela equipe da **[PulseDataLabs](https://github.com/PulseDataLabs)**.
