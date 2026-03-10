"""
Base Document Processor
Abstract base class for all document processors
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, BinaryIO
from pathlib import Path
from io import BytesIO


@dataclass
class DocumentChunk:
    """Bir doküman parçasını temsil eder"""
    text: str  # 'content' yerine 'text' daha tutarlı
    metadata: dict = field(default_factory=dict)
    chunk_index: int = 0
    source_file: str = ""
    page_number: Optional[int] = None
    
    # Geriye uyumluluk için property
    @property
    def content(self) -> str:
        return self.text


@dataclass
class ProcessedDocument:
    """İşlenmiş dokümanı temsil eder"""
    file_name: str
    file_type: str
    total_chunks: int
    chunks: List[DocumentChunk]
    raw_text: str
    metadata: dict = field(default_factory=dict)
    file_path: str = ""  # Artık optional (DB'den gelirse yok)


class BaseDocumentProcessor(ABC):
    """
    Tüm document processor'lar için abstract base class.
    Her yeni format desteği bu class'ı extend etmeli.
    
    Hem dosya yolu hem de bytes ile çalışabilir.
    """
    
    # Alt sınıflar bu değerleri override etmeli
    SUPPORTED_EXTENSIONS: List[str] = []
    PROCESSOR_NAME: str = "BaseProcessor"
    
    # Chunk ayarları
    DEFAULT_CHUNK_SIZE: int = 1000  # karakter
    DEFAULT_CHUNK_OVERLAP: int = 200  # karakter
    
    def __init__(self, chunk_size: int = None, chunk_overlap: int = None):
        self.chunk_size = chunk_size or self.DEFAULT_CHUNK_SIZE
        self.chunk_overlap = chunk_overlap or self.DEFAULT_CHUNK_OVERLAP
    
    @abstractmethod
    def extract_text(self, file_path: Path) -> str:
        """
        Dosya yolundan ham metni çıkarır.
        Alt sınıflar bu metodu implemente etmeli.
        """
        pass
    
    @abstractmethod
    def extract_text_from_bytes(self, file_obj: BinaryIO, file_name: str) -> str:
        """
        BytesIO'dan ham metni çıkarır.
        PostgreSQL BYTEA desteği için gerekli.
        """
        pass
    
    def _fix_turkish_chars(self, text: str) -> str:
        """
        Metindeki Türkçe karakter sorunlarını düzeltir.
        
        PDF, DOCX, XLSX, PPTX - tüm formatlar için ortak kullanılır.
        Font encoding sorunları, ligature'lar ve görünmez karakterleri düzeltir.
        """
        if not text:
            return text
        
        import unicodedata
        import re
        
        # Önce Unicode normalizasyonu yap
        text = unicodedata.normalize('NFKC', text)
        
        # Yaygın font encoding hataları ve düzeltmeleri
        replacements = {
            # Ligature düzeltmeleri
            'ﬁ': 'fi',
            'ﬂ': 'fl',
            'ﬀ': 'ff',
            'ﬃ': 'ffi',
            'ﬄ': 'ffl',
            
            # Türkçe karakter düzeltmeleri (encoding hataları)
            'þ': 'ş',  # Latin Extended
            'Þ': 'Ş',
            'ð': 'ğ',  
            'Ð': 'Ğ',
            'ý': 'ı',  # Bazen ı bu şekilde encode edilir
            'Ý': 'İ',
            '¤': 'ğ',  # Bazı eski dosyalarda
            '¦': 'ş',
            
            # Boşluk ve görünmez karakter düzeltmeleri
            '\u00a0': ' ',  # Non-breaking space
            '\u2003': ' ',  # Em space
            '\u2002': ' ',  # En space
            '\u200b': '',   # Zero-width space
            '\u200c': '',   # Zero-width non-joiner
            '\u200d': '',   # Zero-width joiner
            '\ufeff': '',   # BOM
            '\x00': '',     # NUL karakter (PostgreSQL için)
        }
        
        for old, new in replacements.items():
            text = text.replace(old, new)
        
        # Çift boşlukları tek boşluğa indir
        text = re.sub(r' {2,}', ' ', text)
        
        return text
    
    def get_metadata(self, file_path: Path = None, file_name: str = None) -> dict:
        """
        Dosya metadata'sını çıkarır.
        Varsayılan implementasyon - alt sınıflar override edebilir.
        """
        return {
            "processor": self.PROCESSOR_NAME,
            "file_name": file_name or (file_path.name if file_path else "unknown"),
        }
    
    def chunk_text(self, text: str, source_file: str) -> List[DocumentChunk]:
        """
        Metni chunk'lara böler.
        Sliding window yaklaşımı kullanır.
        """
        if not text or not text.strip():
            return []
        
        chunks = []
        start = 0
        chunk_index = 0
        
        while start < len(text):
            end = start + self.chunk_size
            
            # Kelime ortasında bölmemeye çalış
            if end < len(text):
                # Son boşluğu bul
                last_space = text.rfind(' ', start, end)
                if last_space > start:
                    end = last_space
            
            chunk_content = text[start:end].strip()
            
            if chunk_content:
                chunks.append(DocumentChunk(
                    text=chunk_content,
                    metadata={
                        "processor": self.PROCESSOR_NAME,
                        "chunk_size": self.chunk_size,
                        "start_char": start,
                        "end_char": end
                    },
                    chunk_index=chunk_index,
                    source_file=source_file
                ))
                chunk_index += 1
            
            # Overlap ile ilerle
            start = end - self.chunk_overlap
            if start < 0:
                start = 0
            if start >= len(text):
                break
            # Sonsuz döngü önleme
            if end >= len(text):
                break
        
        return chunks
    
    def process(self, file_path: Path) -> ProcessedDocument:
        """
        Dosya yolundan işleme.
        Text extraction + chunking + metadata toplama.
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"Dosya bulunamadı: {file_path}")
        
        # Text çıkar
        raw_text = self.extract_text(file_path)
        
        # Metadata al
        metadata = self.get_metadata(file_path=file_path)
        
        # Chunk'la
        chunks = self.chunk_text(raw_text, file_path.name)
        
        return ProcessedDocument(
            file_name=file_path.name,
            file_path=str(file_path),
            file_type=file_path.suffix.lower(),
            total_chunks=len(chunks),
            chunks=chunks,
            raw_text=raw_text,
            metadata=metadata
        )
    
    def process_bytes(self, file_obj: BinaryIO, file_name: str) -> ProcessedDocument:
        """
        BytesIO'dan işleme (PostgreSQL BYTEA için).
        Text extraction + chunking + metadata toplama.
        
        Eğer processor'da extract_chunks metodu varsa, onu kullanır.
        Bu sayede Excel, DOCX gibi yapısal dosyalar 
        satır/paragraf bazlı chunk'lanabilir.
        """
        # Dosya uzantısını al
        file_type = f".{file_name.rsplit('.', 1)[-1].lower()}" if "." in file_name else ""
        
        # Metadata al
        metadata = self.get_metadata(file_name=file_name)
        
        # Alt sınıfta extract_chunks varsa onu kullan (Excel, DOCX için)
        if hasattr(self, 'extract_chunks'):
            try:
                # File position'ı başa al
                if hasattr(file_obj, 'seek'):
                    file_obj.seek(0)
                
                custom_chunks = self.extract_chunks(file_obj=file_obj, file_name=file_name)
                
                # Dict formatından DocumentChunk'a çevir
                chunks = [
                    DocumentChunk(
                        text=c["text"],
                        metadata={**c.get("metadata", {}), "processor": self.PROCESSOR_NAME},
                        chunk_index=i,
                        source_file=file_name
                    )
                    for i, c in enumerate(custom_chunks)
                ]
                
                # Raw text = tüm chunk'ların birleşimi
                raw_text = "\n\n---\n\n".join([c["text"] for c in custom_chunks])
                
                return ProcessedDocument(
                    file_name=file_name,
                    file_path="",
                    file_type=file_type,
                    total_chunks=len(chunks),
                    chunks=chunks,
                    raw_text=raw_text,
                    metadata=metadata
                )
            except Exception as e:
                # ❌ Hata oluştu - logla ve yukarı fırlat (sessizce yutma!)
                from app.services.logging_service import log_error
                log_error(
                    f"Dosya işleme hatası ({file_name}): {str(e)}", 
                    "document_processor", 
                    error_detail=str(e)
                )
                # Hatayı yukarı fırlat - UI'da gösterilecek
                raise ValueError(f"Dosya işlenemedi ({file_name}): {str(e)}") from e
        
        # Standart işleme (fallback)
        raw_text = self.extract_text_from_bytes(file_obj, file_name)
        chunks = self.chunk_text(raw_text, file_name)
        
        return ProcessedDocument(
            file_name=file_name,
            file_path="",  # DB'den geldiği için yol yok
            file_type=file_type,
            total_chunks=len(chunks),
            chunks=chunks,
            raw_text=raw_text,
            metadata=metadata
        )

