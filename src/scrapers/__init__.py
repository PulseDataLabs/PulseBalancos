"""PulseBalanços - Suíte de Scrapers Oficiais de Demonstrações Financeiras e Documentos."""

from .bacen_conglomerados import BacenConglomeradoRecord, BacenConglomeradosScraper
from .bacen_ifdata import BacenIFDataScraper
from .base import BaseScraper
from .diarios_oficiais import DiariosOficiaisScraper
from .models import OfficialPublicationMetadata, UnifiedStatementRecord

try:
    from .cvm_fii import CVMFIIScraper, FIIAssetRecord, FIISummaryRecord
    from .cvm_ipe_documents import CVMIPEDocumentsScraper, CompanyFilingDocument
    from .cvm_shareholders import CVMShareholdersScraper, CompanyShareStructure, ShareholderPosition
    from .cvm_statements import CVMStatementsScraper
    from .unificador import UnifiedStatementsManager
except ImportError:
    CVMFIIScraper = None  # type: ignore
    FIIAssetRecord = None  # type: ignore
    FIISummaryRecord = None  # type: ignore
    CVMIPEDocumentsScraper = None  # type: ignore
    CompanyFilingDocument = None  # type: ignore
    CVMShareholdersScraper = None  # type: ignore
    CompanyShareStructure = None  # type: ignore
    ShareholderPosition = None  # type: ignore
    CVMStatementsScraper = None  # type: ignore
    UnifiedStatementsManager = None  # type: ignore

__all__ = [
    "BaseScraper",
    "UnifiedStatementRecord",
    "OfficialPublicationMetadata",
    "BacenConglomeradosScraper",
    "BacenConglomeradoRecord",
    "BacenIFDataScraper",
    "DiariosOficiaisScraper",
    "CVMStatementsScraper",
    "CVMIPEDocumentsScraper",
    "CompanyFilingDocument",
    "CVMShareholdersScraper",
    "ShareholderPosition",
    "CompanyShareStructure",
    "CVMFIIScraper",
    "FIISummaryRecord",
    "FIIAssetRecord",
    "UnifiedStatementsManager",
]

