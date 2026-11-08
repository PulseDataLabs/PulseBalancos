# 📊 PulseBalanços (PulseBalancos)

Plataforma aberta de ingestão, normalização, séries históricas (TTM) e consulta de demonstrações contábeis e indicadores de empresas brasileiras (padrão CVM / B3), desenvolvida pela **[PulseDataLabs](https://github.com/PulseDataLabs)**.

Inspirado nas funcionalidades e na transparência de dados públicos de portais como o **Balanços.AI** (com foco exclusivo em dados estruturados, séries históricas e consultas analíticas de alta performance, sem IA/MCP).

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

3. **Rankings e Insights:**
   - Maiores Empresas por Ativo Total e por Receita Líquida.
   - Empresas com Maiores Lucros Líquidos.
   - Empresas com Maiores Margens Operacionais e Líquidas.
   - Empresas que Mais Crescem (crescimento anual YoY).

4. **Diretório e Navegação Geográfica / Setorial:**
   - Filtro por 21 seções da CNAE (A até U).
   - Filtro por 27 Unidades Federativas (UFs) e Municípios.

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
├── .github/workflows/etl.yml   # Automação agendada serverless via GitHub Actions
├── src/
│   ├── extractors/
│   │   └── cvm.py             # Ingestão em memória com Polars, saneamento de moeda e escala
│   ├── transformers/
│   │   └── ttm.py             # Motor de cálculo TTM, margens e variações YoY
│   └── api/
│       └── routes.py          # Endpoints REST para buscas, perfis, matrizes e rankings
├── sql/
│   └── schema.sql             # DDL PostgreSQL completo com índices compostos e views
├── requirements.txt
├── run_all.py                 # Orquestrador central de execução
└── README.md
```

---

## 🚀 Execução Local

```bash
# 1. Clonar e entrar no diretório
cd ~/projects/PulseBalancos

# 2. Criar e ativar ambiente virtual
python3 -m venv .venv
source .venv/bin/activate

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Executar pipeline de teste para o ano corrente
python run_all.py --year 2024 --doc-type ALL
```

---

## 📄 Licença
Open-source sob licença MIT. Desenvolvido com carinho pela equipe da **PulseDataLabs**.
