"""
TXT Document Processor
Plain text file processing with encoding detection
Enhanced with heading detection and semantic chunking (2024 Best Practices)
"""

import logging
import re
from pathlib import Path
from typing import BinaryIO, List

from .base import BaseDocumentProcessor

logger = logging.getLogger("vyra")


class TXTProcessor(BaseDocumentProcessor):
    """TXT dosyalarını işleyen processor (Enhanced)"""
    
    SUPPORTED_EXTENSIONS = ['.txt']
    PROCESSOR_NAME = "TXTProcessor"
    
    # Denenecek encoding'ler
    ENCODINGS = ['utf-8', 'utf-16', 'latin-1', 'cp1254', 'iso-8859-9']
    
    # Heading pattern'leri (Markdown ve genel)
    HEADING_PATTERNS = [
        r'^#{1,6}\s+.+$',                  # Markdown: # Heading
        r'^[A-Z][A-Z\s]{3,50}$',           # BÜYÜK HARF BAŞLIK
        r'^\d+\.\s+[A-ZĞÜŞİÖÇ].+$',        # 1. Numaralı Başlık
        r'^\d+\.\d+\s+[A-ZĞÜŞİÖÇ].+$',     # 1.1 Alt Başlık
        r'^(Madde|MADDE|Bölüm|BÖLÜM)\s*\d*\.?\s*.+$',  # Madde 1.
        r'^={3,}$',                         # === separator
        r'^-{3,}$',                         # --- separator
    ]
    
    def extract_text(self, file_path: Path) -> str:
        """TXT dosyasından metin çıkarır"""
        for encoding in self.ENCODINGS:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    text = f.read()
                    # 🇹🇷 Türkçe karakter düzeltme
                    return self._fix_turkish_chars(text)
            except (UnicodeDecodeError, UnicodeError):
                continue
        
        # Son çare: binary okuma
        try:
            with open(file_path, 'rb') as f:
                text = f.read().decode('utf-8', errors='ignore')
                return self._fix_turkish_chars(text)
        except Exception as e:
            raise RuntimeError(f"TXT okuma hatası: {str(e)}")
    
    def extract_text_from_bytes(self, file_obj: BinaryIO, file_name: str) -> str:
        """BytesIO'dan TXT metni çıkarır — charset-normalizer ile akıllı encoding tespiti"""
        content = file_obj.read()
        
        # 🆕 v3.2.0 RAG-6: charset-normalizer ile otomatik encoding tespiti
        try:
            from charset_normalizer import from_bytes
            result = from_bytes(content).best()
            if result and result.encoding:
                detected_encoding = result.encoding
                logger.debug("[TXTProcessor] charset-normalizer encoding: %s (dosya: %s)", detected_encoding, file_name)
                text = str(result)
                return self._fix_turkish_chars(text)
        except ImportError:
            logger.debug("[TXTProcessor] charset-normalizer bulunamadı, fallback kullanılıyor")
        except Exception:
            logger.debug("[TXTProcessor] charset-normalizer hatası, fallback kullanılıyor", exc_info=True)
        
        # Fallback: manuel encoding denemesi
        for encoding in self.ENCODINGS:
            try:
                text = content.decode(encoding)
                return self._fix_turkish_chars(text)
            except (UnicodeDecodeError, UnicodeError):
                continue
        
        # Son çare: hataları ignore et
        text = content.decode('utf-8', errors='ignore')
        return self._fix_turkish_chars(text)
    
    # =========================================================================
    # HEADING DETECTION & SEMANTIC CHUNKING (2024 Best Practices)
    # =========================================================================
    
    def _is_heading(self, line: str) -> bool:
        """Bir satırın heading olup olmadığını tespit eder."""
        line = line.strip()
        
        # Çok kısa veya çok uzun satırlar heading değil
        if len(line) < 2 or len(line) > 100:
            return False
        
        # Heading pattern kontrolü
        for pattern in self.HEADING_PATTERNS:
            if re.match(pattern, line):
                return True
        
        # Tüm büyük harf ve kısa ise heading
        if line.isupper() and len(line) < 60 and len(line) > 3:
            return True
        
        # v3.4.1: Title Case tespiti
        if len(line) < 60 and not line.endswith('.'):
            words = line.split()
            if 2 <= len(words) <= 10:
                tc_count = sum(1 for w in words if len(w) > 1 and w[0].isupper())
                if tc_count / len(words) >= 0.7:
                    return True
        
        return False
    
    def _is_separator(self, line: str) -> bool:
        """Satırın separator olup olmadığını kontrol eder."""
        line = line.strip()
        if len(line) >= 3:
            if all(c == '=' for c in line):
                return True
            if all(c == '-' for c in line):
                return True
            if all(c == '*' for c in line):
                return True
        return False
    
    def _extract_sections(self, text: str) -> List[dict]:
        """
        Metni heading'lere ve paragraflara göre bölümlere ayırır.
        
        Returns:
            List[dict]: [{"heading": "...", "content": "...", "line_start": N}, ...]
        """
        sections = []
        current_heading = ""
        current_content = []
        current_line_start = 1
        
        lines = text.split('\n')
        
        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            
            # Separator satırlarını atla
            if self._is_separator(stripped):
                continue
            
            # Boş satır
            if not stripped:
                current_content.append('')
                continue
            
            # Heading tespiti
            if self._is_heading(stripped):
                # Önceki section'ı kaydet
                if current_content:
                    content_text = '\n'.join(current_content).strip()
                    if content_text:
                        sections.append({
                            "heading": current_heading,
                            "content": content_text,
                            "line_start": current_line_start
                        })
                
                # Markdown heading'den # işaretlerini temizle
                current_heading = re.sub(r'^#+\s*', '', stripped)
                current_content = []
                current_line_start = line_num
            else:
                current_content.append(stripped)
        
        # Son section'ı kaydet
        if current_content:
            content_text = '\n'.join(current_content).strip()
            if content_text:
                sections.append({
                    "heading": current_heading,
                    "content": content_text,
                    "line_start": current_line_start
                })
        
        return sections
    
    def _split_large_content(self, text: str, max_size: int = 800) -> List[str]:
        """Büyük içeriği paragraf sınırlarında böler."""
        if len(text) <= max_size:
            return [text]
        
        chunks = []
        paragraphs = text.split('\n\n')
        
        current_chunk = ""
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            if len(current_chunk) + len(para) + 2 > max_size:
                if current_chunk:
                    chunks.append(current_chunk)
                
                # Paragraf tek başına çok büyükse, cümlelere böl
                if len(para) > max_size:
                    sentences = para.replace('. ', '.|').split('|')
                    current_chunk = ""
                    for sentence in sentences:
                        if len(current_chunk) + len(sentence) + 1 > max_size:
                            if current_chunk:
                                chunks.append(current_chunk)
                            current_chunk = sentence
                        else:
                            current_chunk = (current_chunk + " " + sentence).strip()
                else:
                    current_chunk = para
            else:
                current_chunk = (current_chunk + "\n\n" + para).strip()
        
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks
    
    def extract_chunks(self, file_obj: BinaryIO, file_name: str) -> List[dict]:
        """
        TXT dosyasından zengin metadata ile chunk'lar çıkarır.
        PDF/DOCX/PPTX processor ile tutarlı format.
        
        v3.2.0: Chunk overlap ve file_type metadata desteği.
        
        Returns:
            List[dict]: [{"text": "...", "metadata": {"heading": "...", "type": "..."}}, ...]
        """
        # File position'ı başa al
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)
        
        # Metni çıkar
        text = self.extract_text_from_bytes(file_obj, file_name)
        
        if not text or not text.strip():
            return []
        
        chunks = []
        chunk_index = 0
        OVERLAP_SIZE = 100  # v3.2.0 RAG-1: Chunk overlap — bağlam kaybını önler
        
        # Heading'lere göre bölümle
        sections = self._extract_sections(text)
        
        if not sections:
            # Heading bulunamadıysa, paragraf bazlı chunking yap
            sub_chunks = self._split_large_content(text)
            for i, chunk_text in enumerate(sub_chunks):
                if len(chunk_text.strip()) >= 30:
                    # Overlap: önceki chunk'ın sonundan bağlam ekle
                    overlap_prefix = ""
                    if i > 0 and len(sub_chunks[i - 1]) > OVERLAP_SIZE:
                        overlap_prefix = sub_chunks[i - 1][-OVERLAP_SIZE:].strip() + "\n"
                    
                    chunks.append({
                        "text": (overlap_prefix + chunk_text).strip(),
                        "metadata": {
                            "type": "paragraph",
                            "heading": "",
                            "file_type": "txt",
                            "chunk_index": chunk_index,
                            "source": file_name
                        }
                    })
                    chunk_index += 1
        else:
            # Heading bazlı chunking
            for section in sections:
                content = section["content"]
                heading = section["heading"]
                line_start = section.get("line_start")
                
                # Büyük section'ları böl
                sub_chunks = self._split_large_content(content)
                for i, sub_text in enumerate(sub_chunks):
                    if len(sub_text.strip()) >= 30:
                        # Overlap: önceki chunk'ın sonundan bağlam ekle
                        overlap_prefix = ""
                        if i > 0 and len(sub_chunks[i - 1]) > OVERLAP_SIZE:
                            overlap_prefix = sub_chunks[i - 1][-OVERLAP_SIZE:].strip() + "\n"
                        
                        # v3.2.1: Heading prefix → embedding search için bölüm contexti
                        heading_prefix = f"[Bölüm: {heading}]\n" if heading else ""
                        chunk_text_final = (heading_prefix + overlap_prefix + sub_text).strip()
                        
                        chunks.append({
                            "text": chunk_text_final,
                            "metadata": {
                                "type": "section",
                                "heading": heading,
                                "line_start": line_start,
                                "file_type": "txt",
                                "chunk_index": chunk_index,
                                "source": file_name
                            }
                        })
                        chunk_index += 1
        
        return chunks
    
    def get_metadata(self, file_path: Path = None, file_name: str = None) -> dict:
        """TXT metadata'sını çıkarır"""
        base_meta = {"processor": self.PROCESSOR_NAME}
        
        if file_path:
            base_meta.update({
                "file_name": file_path.name,
                "file_size_bytes": file_path.stat().st_size,
            })
        else:
            base_meta["file_name"] = file_name
        
        return base_meta

