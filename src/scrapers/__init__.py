"""PulseBalanços - Suíte de Scrapers Oficiais de Demonstrações Financeiras e Documentos."""

from .bacen_ifdata import BacenIFDataScraper
from .base import BaseScraper
from .cvm_fii import CVMFIIScraper, FIIAssetRecord, FIISummaryRecord
from .cvm_ipe_documents import CVMIPEDocumentsScraper, CompanyFilingDocument
from .cvm_shareholders import CVMShareholdersScraper, CompanyShareStructure, ShareholderPosition
from .cvm_statements import CVMStatementsScraper
from .diarios_oficiais import DiariosOficiaisScraper
from .models import OfficialPublicationMetadata, UnifiedStatementRecord
from .unificador import UnifiedStatementsManager

__all__ = [
    "BaseScraper",
    "UnifiedStatementRecord",
    "OfficialPublicationMetadata",
    "CVMStatementsScraper",
    "CVMIPEDocumentsScraper",
    "CompanyFilingDocument",
    "CVMShareholdersScraper",
    "ShareholderPosition",
    "CompanyShareStructure",
    "CVMFIIScraper",
    "FIISummaryRecord",
    "FIIAssetRecord",
    "DiariosOficiaisScraper",
    "BacenIFDataScraper",
    "UnifiedStatementsManager",
]
