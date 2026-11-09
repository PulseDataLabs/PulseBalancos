import io
import zipfile
from datetime import datetime
import openpyxl
import pytest

from src.scrapers.bacen_conglomerados import BacenConglomeradoRecord, BacenConglomeradosScraper


def create_mock_conglomerado_zip(reverse_name: bool = False, year: int = 2026, month: int = 10) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Plan1"

    # Metadata rows
    ws.cell(1, 1, "BANCO CENTRAL DO BRASIL - BACEN")
    ws.cell(2, 1, "DEPARTAMENTO DE MONITORAMENTO DO SISTEMA FINANCEIRO - DESIG")
    ws.cell(5, 1, "CONGLOMERADOS PRUDENCIAIS*")
    ws.cell(6, 1, "* a partir da data-base janeiro/2023...")
    ws.cell(7, 1, f"Posição: 30.{month:02d}.{year}")

    # Header at row 10
    headers = [
        "NOME DO CONGLOMERADO",
        "CLASSE DO CONGLOMERADO",
        "CNPJ PARTICIPANTE",
        "NOME DO PARTICIPANTE",
        "TIPO PARTICIPAÇÃO",
        "DATA INÍCIO",
        "UF",
    ]
    for c_idx, h in enumerate(headers, start=1):
        ws.cell(10, c_idx, h)

    # Sample rows
    ws.cell(11, 1, "ABC-BRASIL - PRUDENCIAL   ")
    ws.cell(11, 2, "Privado Nacional com Controle Estrangeiro")
    ws.cell(11, 3, "28195667   ")
    ws.cell(11, 4, "BANCO ABC BRASIL S.A.")
    ws.cell(11, 5, "LIDER")
    ws.cell(11, 6, datetime(2014, 1, 2))
    ws.cell(11, 7, "SP")

    ws.cell(12, 1, "ABC-BRASIL - PRUDENCIAL")
    ws.cell(12, 2, "Privado Nacional com Controle Estrangeiro")
    ws.cell(12, 3, "           ")
    ws.cell(12, 4, "APOEMA FUND LTD")
    ws.cell(12, 5, "PARTICIPANTE")
    ws.cell(12, 6, datetime(2024, 5, 1))
    ws.cell(12, 7, "EX")

    ws.cell(13, 1, "FONTE: INSTITUIÇÕES FINANCEIRAS")

    excel_buffer = io.BytesIO()
    wb.save(excel_buffer)
    excel_bytes = excel_buffer.getvalue()

    zip_buffer = io.BytesIO()
    fname = f"{month:02d}{year}CONGLOMERADO.xlsx" if reverse_name else f"{year}{month:02d}CONGLOMERADO.xlsx"
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(fname, excel_bytes)

    return zip_buffer.getvalue()


def test_bacen_conglomerados_mock_new_pattern(monkeypatch):
    """Testa padrão novo MMYYYYCONGLOMERADO.zip (introduzido em 10/2026)."""
    scraper = BacenConglomeradosScraper()
    mock_zip = create_mock_conglomerado_zip(reverse_name=True, year=2026, month=10)

    class MockResponse:
        status_code = 200
        content = mock_zip

    def mock_get(url, **kwargs):
        assert "102026CONGLOMERADO.zip" in url
        return MockResponse()

    monkeypatch.setattr(scraper.session, "get", mock_get)

    records = scraper.extract_conglomerados(2026, 10)
    assert len(records) == 2

    r1 = records[0]
    assert r1.nome_conglomerado == "ABC-BRASIL - PRUDENCIAL"
    assert r1.cnpj_base == "28195667"
    assert r1.is_lider is True
    assert r1.uf == "SP"
    assert r1.data_inicio == "2014-01-02"

    r2 = records[1]
    assert r2.nome_conglomerado == "ABC-BRASIL - PRUDENCIAL"
    assert r2.cnpj_base is None
    assert r2.is_lider is False
    assert r2.uf == "EX"


def test_bacen_conglomerados_mock_old_pattern(monkeypatch):
    """Testa fallback para padrão histórico YYYYMMCONGLOMERADO.zip (até 09/2026)."""
    scraper = BacenConglomeradosScraper()
    mock_zip = create_mock_conglomerado_zip(reverse_name=False, year=2026, month=9)

    class MockResponse404:
        status_code = 404
        content = b""

    class MockResponse200:
        status_code = 200
        content = mock_zip

    def mock_get(url, **kwargs):
        if "092026CONGLOMERADO.zip" in url:
            return MockResponse404()
        if "202609CONGLOMERADO.zip" in url:
            return MockResponse200()
        return MockResponse404()

    monkeypatch.setattr(scraper.session, "get", mock_get)

    records = scraper.extract_conglomerados(2026, 9)
    assert len(records) == 2
    assert records[0].nome_conglomerado == "ABC-BRASIL - PRUDENCIAL"


def test_bacen_conglomerados_extract_year(monkeypatch):
    """Testa extract_year buscando o mês mais recente disponível."""
    scraper = BacenConglomeradosScraper()
    mock_zip = create_mock_conglomerado_zip(reverse_name=True, year=2026, month=10)

    class MockResponse:
        status_code = 200
        content = mock_zip

    def mock_get(url, **kwargs):
        if "102026" in url or "202610" in url:
            return MockResponse()
        class Res404:
            status_code = 404
            content = b""
        return Res404()

    monkeypatch.setattr(scraper.session, "get", mock_get)

    records = list(scraper.extract_year(2026))
    assert len(records) == 2
