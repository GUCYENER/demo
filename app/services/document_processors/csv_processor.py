"""
CSV Document Processor
v3.3.0: CSV dosyalarını RAG için işler.

Özellikler:
- Otomatik delimiter tespiti (csv.Sniffer)
- Header row detection
- Satır bazlı chunking + heading prefix
- charset-normalizer ile encoding detection
"""

import csv
import io
import logging
from pathlib import Path
from typing import BinaryIO, List

from .base import BaseDocumentProcessor

logger = logging.getLogger("vyra")


class CSVProcessor(BaseDocumentProcessor):
    """CSV dosyalarını işleyen processor"""
    
    SUPPORTED_EXTENSIONS = ['.csv']
    PROCESSOR_NAME = "CSVProcessor"
    
    # Grup chunk'lama — kısa satırları birleştir
    MIN_CHUNK_LENGTH = 30
    MAX_ROWS_PER_CHUNK = 25
    
    def extract_text(self, file_path: Path) -> str:
        """CSV dosyasından metin çıkarır"""
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    
    def extract_text_from_bytes(self, file_obj: BinaryIO, file_name: str) -> str:
        """BytesIO'dan CSV metni çıkarır — akıllı encoding tespiti"""
        content = file_obj.read()
        
        # charset-normalizer ile encoding tespiti
        try:
            from charset_normalizer import from_bytes
            result = from_bytes(content).best()
            if result and result.encoding:
                logger.debug("[CSVProcessor] encoding: %s (dosya: %s)", result.encoding, file_name)
                return str(result)
        except ImportError:
            pass
        except Exception:
            logger.debug("[CSVProcessor] charset-normalizer hatası, fallback", exc_info=True)
        
        # Fallback encoding'ler
        for enc in ['utf-8', 'utf-8-sig', 'cp1254', 'iso-8859-9', 'latin-1']:
            try:
                return content.decode(enc)
            except (UnicodeDecodeError, UnicodeError):
                continue
        
        return content.decode('utf-8', errors='replace')
    
    def _detect_delimiter(self, text: str) -> str:
        """CSV delimiter'ını otomatik tespit et"""
        try:
            # İlk birkaç satırdan delimiter tahmin et
            sample = "\n".join(text.split("\n")[:10])
            dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
            return dialect.delimiter
        except csv.Error:
            # Fallback: en sık kullanılan separatör
            counts = {
                ',': text.count(','),
                ';': text.count(';'),
                '\t': text.count('\t'),
                '|': text.count('|'),
            }
            return max(counts, key=counts.get)
    
    def _detect_header(self, rows: List[List[str]]) -> bool:
        """İlk satırın header olup olmadığını tespit et"""
        if not rows or len(rows) < 2:
            return False
        
        first_row = rows[0]
        # Header heuristik: kısa metin, sayısal değil, benzersiz
        non_empty = [c for c in first_row if c.strip()]
        if not non_empty:
            return False
        
        all_text = all(not c.strip().replace('.', '').replace(',', '').isdigit() for c in non_empty)
        all_short = all(len(c) < 50 for c in non_empty)
        all_unique = len(set(c.strip().lower() for c in non_empty)) == len(non_empty)
        
        return all_text and all_short and all_unique and len(non_empty) >= 2
    
    def extract_chunks(self, file_obj: BinaryIO, file_name: str) -> List[dict]:
        """
        CSV dosyasından chunk'lar çıkarır.
        Her chunk MAX_ROWS_PER_CHUNK satır içerir.
        Header satırı her chunk'a prefix olarak eklenir.
        """
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)
        
        text = self.extract_text_from_bytes(file_obj, file_name)
        
        if not text or not text.strip():
            return []
        
        # Delimiter tespit et
        delimiter = self._detect_delimiter(text)
        logger.debug("[CSVProcessor] delimiter='%s' dosya=%s", delimiter, file_name)
        
        # CSV parse
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        all_rows = []
        for row in reader:
            all_rows.append(row)
        
        if not all_rows:
            return []
        
        # Header tespiti
        has_header = self._detect_header(all_rows)
        header_row = all_rows[0] if has_header else None
        data_rows = all_rows[1:] if has_header else all_rows
        
        header_text = ""
        if header_row:
            header_text = " | ".join(c.strip() for c in header_row if c.strip())
        
        # Chunk oluştur: her chunk MAX_ROWS_PER_CHUNK satır
        chunks = []
        chunk_index = 0
        
        for i in range(0, len(data_rows), self.MAX_ROWS_PER_CHUNK):
            batch = data_rows[i:i + self.MAX_ROWS_PER_CHUNK]
            
            # Satırları pipe-separated metin olarak birleştir
            row_texts = []
            for row in batch:
                row_text = " | ".join(c.strip() for c in row if c.strip())
                if row_text:
                    row_texts.append(row_text)
            
            if not row_texts:
                continue
            
            # Header prefix ekle
            chunk_text = ""
            if header_text:
                chunk_text = f"[Başlıklar: {header_text}]\n"
            chunk_text += "\n".join(row_texts)
            
            if len(chunk_text.strip()) >= self.MIN_CHUNK_LENGTH:
                chunks.append({
                    "text": chunk_text.strip(),
                    "metadata": {
                        "type": "table",
                        "heading": header_text or f"CSV Veri Bloğu {chunk_index + 1}",
                        "file_type": "csv",
                        "chunk_index": chunk_index,
                        "source": file_name,
                        "row_start": i + (2 if has_header else 1),
                        "row_end": min(i + self.MAX_ROWS_PER_CHUNK, len(data_rows)) + (1 if has_header else 0),
                    }
                })
                chunk_index += 1
        
        logger.debug("[CSVProcessor] %d chunk oluşturuldu (delimiter='%s', header=%s)", 
                     len(chunks), delimiter, has_header)
        
        return chunks
    
    def get_metadata(self, file_path: Path = None, file_name: str = None) -> dict:
        """CSV metadata"""
        base_meta = {"processor": self.PROCESSOR_NAME}
        if file_path:
            base_meta.update({
                "file_name": file_path.name,
                "file_size_bytes": file_path.stat().st_size,
            })
        else:
            base_meta["file_name"] = file_name
        return base_meta
