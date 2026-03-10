"""
TXT Document Processor
Plain text file processing with encoding detection
Enhanced with heading detection and semantic chunking (2024 Best Practices)
"""

import re
from pathlib import Path
from typing import BinaryIO, List

from .base import BaseDocumentProcessor


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
        """BytesIO'dan TXT metni çıkarır"""
        content = file_obj.read()
        
        for encoding in self.ENCODINGS:
            try:
                text = content.decode(encoding)
                # 🇹🇷 Türkçe karakter düzeltme
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
        
        # Heading'lere göre bölümle
        sections = self._extract_sections(text)
        
        if not sections:
            # Heading bulunamadıysa, paragraf bazlı chunking yap
            for chunk_text in self._split_large_content(text):
                if len(chunk_text.strip()) >= 30:
                    chunks.append({
                        "text": chunk_text.strip(),
                        "metadata": {
                            "type": "paragraph",
                            "heading": "",
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
                for sub_text in self._split_large_content(content):
                    if len(sub_text.strip()) >= 30:
                        chunks.append({
                            "text": sub_text.strip(),
                            "metadata": {
                                "type": "section",
                                "heading": heading,
                                "line_start": line_start,
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

