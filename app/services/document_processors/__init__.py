# Document Processors Module
# Modüler dosya işleme sistemi

from .base import BaseDocumentProcessor
from .pdf_processor import PDFProcessor
from .docx_processor import DOCXProcessor
from .excel_processor import ExcelProcessor
from .pptx_processor import PPTXProcessor
from .txt_processor import TXTProcessor

# Processor Registry - Dosya uzantısına göre işleyici seçimi
PROCESSOR_REGISTRY = {
    '.pdf': PDFProcessor,
    '.docx': DOCXProcessor,
    '.doc': DOCXProcessor,
    '.xlsx': ExcelProcessor,
    '.xls': ExcelProcessor,
    '.pptx': PPTXProcessor,
    '.ppt': PPTXProcessor,
    '.txt': TXTProcessor,
}

SUPPORTED_EXTENSIONS = list(PROCESSOR_REGISTRY.keys())


def get_processor(file_extension: str) -> BaseDocumentProcessor:
    """
    Dosya uzantısına göre uygun processor'ı döndürür.
    """
    ext = file_extension.lower()
    if ext not in PROCESSOR_REGISTRY:
        raise ValueError(f"Desteklenmeyen dosya formatı: {ext}. Desteklenen: {SUPPORTED_EXTENSIONS}")
    
    return PROCESSOR_REGISTRY[ext]()


def get_processor_for_extension(file_extension: str) -> BaseDocumentProcessor:
    """
    Dosya uzantısına göre uygun processor'ı döndürür.
    Alias for get_processor - RAG modülü uyumluluğu için.
    """
    ext = file_extension.lower()
    if ext not in PROCESSOR_REGISTRY:
        return None
    
    return PROCESSOR_REGISTRY[ext]()

