"""
PDF Document Processor
=======================
Uses PyMuPDF (fitz) for font-aware text extraction with heading detection.
Falls back to pypdf for text-only extraction.
Falls back to OCR (EasyOCR) for scanned documents.

v2.43.0: Font-level heading detection — font size, bold, italic bilgileriyle
         başlık tespiti. Heading hiyerarşi (breadcrumb) koruması.
"""

import logging
import re
from pathlib import Path
from typing import List, BinaryIO, Dict, Any, Optional
import io

from .base import BaseDocumentProcessor, DocumentChunk

logger = logging.getLogger("vyra")


# Minimum metin uzunluğu - bunun altında OCR denenecek
MIN_TEXT_LENGTH_FOR_OCR = 50

# Font-based heading tespiti eşik değerleri
HEADING_FONT_SIZE_RATIO = 1.15  # Ortalama font boyutunun %15 üstü → heading adayı
MIN_HEADING_FONT_SIZE = 10.0    # Minimum heading font boyutu (çok küçük fontları eleme)


class PDFProcessor(BaseDocumentProcessor):
    """PDF dosyalarını işleyen processor (OCR destekli)"""
    
    SUPPORTED_EXTENSIONS = ['.pdf']
    PROCESSOR_NAME = "PDFProcessor"
    
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 100):
        super().__init__(chunk_size, chunk_overlap)
        self._ocr_available = None
    
    def _is_ocr_available(self) -> bool:
        """OCR'ın kullanılabilir olup olmadığını kontrol eder (lazy)"""
        if self._ocr_available is None:
            try:
                from app.services.ocr_service import get_ocr_service
                service = get_ocr_service()
                self._ocr_available = service.is_available()
            except Exception:
                self._ocr_available = False
        return self._ocr_available
    
    def extract_text(self, file_path: Path) -> str:
        """PDF dosyasından metin çıkarır"""
        try:
            from pypdf import PdfReader
            
            reader = PdfReader(str(file_path))
            text = self._extract_from_reader(reader)
            
            # Metin yetersizse ve OCR varsa, OCR dene
            if len(text.strip()) < MIN_TEXT_LENGTH_FOR_OCR and self._is_ocr_available():
                with open(file_path, 'rb') as f:
                    text = self._try_ocr(f.read(), file_path.name)
            
            return text
            
        except ImportError:
            raise ImportError("pypdf kütüphanesi yüklü değil. 'pip install pypdf' komutunu çalıştırın.")
        except Exception as e:
            raise RuntimeError(f"PDF işleme hatası: {str(e)}")
    
    def extract_text_from_bytes(self, file_obj: BinaryIO, file_name: str) -> str:
        """BytesIO'dan PDF metni çıkarır (OCR fallback destekli)"""
        # Önce byte'ları sakla (OCR için lazım olabilir)
        pdf_bytes = file_obj.read()
        file_obj.seek(0)  # Pozisyonu başa al
        
        try:
            from pypdf import PdfReader
            
            reader = PdfReader(io.BytesIO(pdf_bytes))
            text = self._extract_from_reader(reader)
            
            # Metin yetersizse ve OCR varsa, OCR dene
            if len(text.strip()) < MIN_TEXT_LENGTH_FOR_OCR:
                ocr_text = self._try_ocr(pdf_bytes, file_name)
                if len(ocr_text.strip()) > len(text.strip()):
                    text = ocr_text
            
            return text
            
        except ImportError as e:
            logger.warning("[PDFProcessor] pypdf import hatası: %s", e)
            raise ImportError("pypdf kütüphanesi yüklü değil.")
        except Exception as e:
            # pypdf başarısız olursa OCR dene
            if self._is_ocr_available():
                try:
                    return self._try_ocr(pdf_bytes, file_name)
                except Exception as ocr_error:
                    raise RuntimeError(f"PDF işleme hatası: {str(e)} | OCR hatası: {str(ocr_error)}")
            raise RuntimeError(f"PDF işleme hatası: {str(e)}")
    
    # =========================================================================
    # PyMuPDF FONT-AWARE EXTRACTION (v2.43.0)
    # =========================================================================
    
    def _extract_structured_blocks_fitz(self, pdf_bytes: bytes) -> Optional[List[Dict[str, Any]]]:
        """
        PyMuPDF (fitz) ile font bilgisi dahil yapısal bloklar çıkarır.
        
        v2.43.0: Font size, bold, italic bilgileri ile heading tespiti.
        PDF'teki görsel ipuçlarını (font boyutu, kalınlık) kullanarak
        regex'ten çok daha güvenilir heading detection sağlar.
        
        Returns:
            List[{"text": str, "font_size": float, "is_bold": bool,
                  "is_heading": bool, "page": int, "heading_level": int}]
            veya None (fitz yoksa / hata varsa)
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            return None
        
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception:
            return None
        
        try:
            # 1. Tüm font boyutlarını topla → ortalama hesapla
            all_font_sizes = []
            raw_blocks = []  # (page_num, block_lines)
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
                
                for block in text_dict.get("blocks", []):
                    if block.get("type") != 0:  # Sadece text block'ları
                        continue
                    
                    for line in block.get("lines", []):
                        line_spans = []
                        for span in line.get("spans", []):
                            text = span.get("text", "").strip()
                            if not text:
                                continue
                            font_size = span.get("size", 12.0)
                            font_name = span.get("font", "")
                            flags = span.get("flags", 0)
                            # flags bit 0 = superscript, bit 1 = italic, bit 4 = bold
                            is_bold = bool(flags & (1 << 4)) or "Bold" in font_name or "bold" in font_name
                            is_italic = bool(flags & (1 << 1)) or "Italic" in font_name or "italic" in font_name
                            
                            line_spans.append({
                                "text": text,
                                "font_size": font_size,
                                "is_bold": is_bold,
                                "is_italic": is_italic,
                                "font_name": font_name,
                                "color": span.get("color", 0),  # v3.4.1: RGB packed int
                            })
                            all_font_sizes.append(font_size)
                        
                        if line_spans:
                            raw_blocks.append({
                                "line_spans": line_spans,
                                "page": page_num + 1,
                            })
            
            if not all_font_sizes:
                return None
            
            # 2. Ortalama ve medyan font boyutunu hesapla
            avg_font_size = sum(all_font_sizes) / len(all_font_sizes)
            sorted_sizes = sorted(all_font_sizes)
            median_font_size = sorted_sizes[len(sorted_sizes) // 2]
            body_font_size = max(avg_font_size, median_font_size)
            heading_threshold = body_font_size * HEADING_FONT_SIZE_RATIO
            
            # 3. Satırları işle → heading tespiti
            structured = []
            for raw in raw_blocks:
                # Satırdaki tüm span'ları birleştir
                full_text = " ".join(s["text"] for s in raw["line_spans"])
                full_text = full_text.strip()
                if not full_text:
                    continue
                
                # Dominant font size, bold ve renk durumu (en uzun span baz alınır)
                dominant_span = max(raw["line_spans"], key=lambda s: len(s["text"]))
                font_size = dominant_span["font_size"]
                is_bold = dominant_span["is_bold"]
                text_color = dominant_span.get("color", 0)  # v3.4.1: 0 = siyah
                is_colored = text_color != 0  # Siyah (body) dışı renk = potansiyel heading
                
                # Heading tespiti: font büyük VEYA (bold VE yeterli boyut)
                is_heading = False
                heading_level = 0
                
                if font_size >= heading_threshold and len(full_text) < 200:
                    is_heading = True
                elif is_bold and font_size >= MIN_HEADING_FONT_SIZE and len(full_text) < 150:
                    is_heading = True
                # v3.4.1: Renkli + kısa satır → heading adayı
                elif is_colored and font_size >= MIN_HEADING_FONT_SIZE and len(full_text) < 100:
                    is_heading = True
                
                # Heading level belirleme (font size'a göre)
                if is_heading:
                    size_diff = font_size - body_font_size
                    if size_diff > 6 or font_size > body_font_size * 1.5:
                        heading_level = 1  # Ana başlık
                    elif size_diff > 3 or font_size > body_font_size * 1.3:
                        heading_level = 2  # Alt başlık
                    elif is_bold and size_diff > 1:
                        heading_level = 2
                    else:
                        heading_level = 3  # Alt-alt başlık
                    
                    # Ek kontrol: çok uzun satırlar heading olmaz
                    if len(full_text) > 100 and heading_level > 1:
                        is_heading = False
                        heading_level = 0
                
                # Regex tabanlı heading kontrolü de ekle (ek güvence)
                if not is_heading and self._detect_heading(full_text):
                    is_heading = True
                    heading_level = heading_level or 2
                
                # v3.4.1: Title Case tespiti — bold olmasa bile kısa Title Case satırlar heading olabilir
                # "Tanımsız Seri Okutma İşlemi", "Depo Sayım İşlemleri" gibi
                # v3.4.1-fix: Cümle parçası false-positive filtresi
                if not is_heading and len(full_text) < 60 and not full_text.endswith('.'):
                    # Küçük harfle başlayan → heading olamaz
                    if full_text and full_text[0].isupper():
                        # Fiil eki kontrolü
                        _ve = ('ır.','ir.','ur.','ür.','ar.','er.','ler.','lar.',
                               'dır.','dir.','dur.','dür.','tır.','tir.','tur.','tür.',
                               'bilir','mektedir','ması','mesi','malıdır','melidir')
                        ft_lower = full_text.lower()
                        if not any(ft_lower.endswith(e) for e in _ve):
                            words = full_text.split()
                            if 2 <= len(words) <= 10:
                                title_case_count = sum(
                                    1 for w in words 
                                    if len(w) > 1 and w[0].isupper()
                                )
                                if title_case_count / len(words) >= 0.7:
                                    is_heading = True
                                    heading_level = heading_level or 3
                
                structured.append({
                    "text": full_text,
                    "font_size": font_size,
                    "is_bold": is_bold,
                    "is_heading": is_heading,
                    "heading_level": heading_level,
                    "page": raw["page"],
                })
            
            return structured
        
        except Exception:
            return None
        finally:
            doc.close()
    
    def _build_sections_from_structured(
        self, blocks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Yapısal bloklardan heading-bazlı section'lar oluşturur.
        Heading hiyerarşisini (breadcrumb path) korur.
        
        v2.43.0: heading_path ve heading_level metadata desteği.
        
        Returns:
            List[{"heading": str, "content": str, "page": int,
                  "heading_level": int, "heading_path": list,
                  "is_table": bool}]
        """
        sections = []
        heading_stack = []  # [(level, text), ...]
        current_heading = ""
        current_heading_level = 0
        current_content = []
        current_page = None
        
        def _get_heading_path() -> List[str]:
            """Heading stack'ten breadcrumb path oluşturur."""
            return [h[1] for h in heading_stack]
        
        def _save_section():
            """Mevcut bölümü kaydet."""
            if current_content:
                content_text = "\n".join(current_content).strip()
                if content_text:
                    sections.append({
                        "heading": current_heading,
                        "content": content_text,
                        "page": current_page,
                        "heading_level": current_heading_level,
                        "heading_path": _get_heading_path(),
                        "is_table": self._detect_table_content(content_text),
                    })
        
        for block in blocks:
            if block["is_heading"]:
                # Önceki section'ı kaydet
                _save_section()
                
                # Heading stack güncelle
                level = block["heading_level"]
                text = block["text"]
                
                # Bu seviyeden büyük veya eşit heading'leri stack'ten çıkar
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, text))
                
                current_heading = text
                current_heading_level = level
                current_content = []
                current_page = block["page"]
            else:
                current_content.append(block["text"])
                if current_page is None:
                    current_page = block["page"]
        
        # Son section
        _save_section()
        
        return sections
    
    def _clean_header_footer_blocks(
        self, blocks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Tekrarlayan header/footer satırlarını filtreler.
        
        v2.43.0: Birden fazla sayfada aynı pozisyonda tekrar eden
        kısa metinler (sayfa no, şirket adı vb.) tespit edilip kaldırılır.
        
        Strateji:
        - Her sayfadaki kısa satırları (<80 karakter) grupla
        - Sayfaların %50+'sında tekrar eden → header/footer
        - Sayfa numarası pattern'leri otomatik temizle
        """
        if not blocks or len(blocks) < 5:
            return blocks
        
        # Toplam sayfa sayısı bul
        pages = set(b["page"] for b in blocks)
        total_pages = len(pages)
        if total_pages < 3:
            return blocks  # Çok az sayfa, filtre anlamsız
        
        # Kısa satırları sayfaya göre grupla
        from collections import Counter
        short_text_counter = Counter()
        
        for block in blocks:
            text = block["text"].strip()
            if len(text) < 80 and not block.get("is_heading", False):
                # Sayfa numarası varyasyonlarını normalize et
                normalized = re.sub(r'\d+', '#', text)
                short_text_counter[normalized] += 1
        
        # Sayfaların %50+'sında tekrar eden → header/footer
        threshold = max(2, total_pages * 0.5)
        header_footer_patterns = set()
        for text_pattern, count in short_text_counter.items():
            if count >= threshold:
                header_footer_patterns.add(text_pattern)
        
        # Sayfa numarası pattern'leri
        page_num_patterns = [
            re.compile(r'^\d+$'),                        # "5"
            re.compile(r'^Sayfa\s+\d+', re.IGNORECASE),  # "Sayfa 5"
            re.compile(r'^Page\s+\d+', re.IGNORECASE),   # "Page 5"
            re.compile(r'^\d+\s*/\s*\d+$'),               # "5 / 10"
            re.compile(r'^-\s*\d+\s*-$'),                 # "- 5 -"
        ]
        
        # Filtreleme
        cleaned = []
        for block in blocks:
            text = block["text"].strip()
            
            # Sayfa numarası pattern kontrolü
            if any(p.match(text) for p in page_num_patterns):
                continue
            
            # Header/footer pattern kontrolü
            if len(text) < 80 and not block.get("is_heading", False):
                normalized = re.sub(r'\d+', '#', text)
                if normalized in header_footer_patterns:
                    continue
            
            cleaned.append(block)
        
        return cleaned
    
    def _extract_image_positions_fitz(self, pdf_bytes: bytes) -> Dict[int, List[Dict]]:
        """
        PyMuPDF ile PDF'teki görsellerin pozisyonlarını çıkarır.
        
        v2.43.0 Faz 4: Görsel-chunk eşleme için sayfa bazlı görsel pozisyonları.
        
        Returns:
            Dict[int, List[Dict]]: {page_num: [{xref, bbox, width, height, y_pos}]}
        """
        try:
            import fitz
        except ImportError:
            return {}
        
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception:
            return {}
        
        image_positions: Dict[int, List[Dict]] = {}
        
        try:
            for page_num in range(len(doc)):
                page = doc[page_num]
                page_images = []
                
                # Sayfadaki tüm görselleri al
                image_list = page.get_images(full=True)
                
                for img_idx, img_info in enumerate(image_list):
                    xref = img_info[0]  # Image xref numarası
                    
                    # Görselin sayfadaki pozisyonunu bul
                    try:
                        img_rects = page.get_image_rects(xref)
                        if img_rects:
                            rect = img_rects[0]  # İlk rect
                            page_images.append({
                                "xref": xref,
                                "bbox": [rect.x0, rect.y0, rect.x1, rect.y1],
                                "width": rect.width,
                                "height": rect.height,
                                "y_pos": rect.y0,  # Dikey pozisyon (üstten)
                                "page": page_num + 1,
                                "img_index": img_idx,
                            })
                    except Exception:
                        # Bazı görsellerde rect alınamayabilir
                        continue
                
                if page_images:
                    # y_pos'a göre sırala (üstten alta)
                    page_images.sort(key=lambda x: x["y_pos"])
                    image_positions[page_num + 1] = page_images
            
            doc.close()
        except Exception:
            try:
                doc.close()
            except Exception:
                pass
        
        return image_positions
    
    def _detect_toc_section(self, section: Dict[str, Any]) -> bool:
        """
        İçindekiler bölümünü tespit eder.
        
        v2.43.0: TOC pattern kontrolü ile otomatik toc tiplemesi.
        """
        heading = (section.get("heading") or "").lower()
        content = section.get("content", "")
        
        # Heading kontrolü
        toc_headings = ["içindekiler", "i̇çindekiler", "table of contents", "contents", "index"]
        if any(h in heading for h in toc_headings):
            return True
        
        # İçerik kontrolü: Çok sayıda "....." veya sayfa numarası referansı
        dot_lines = len(re.findall(r'\.{3,}', content))
        page_refs = len(re.findall(r'\d+\s*$', content, re.MULTILINE))
        total_lines = content.count('\n') + 1
        
        if total_lines > 5 and (dot_lines / total_lines > 0.3 or page_refs / total_lines > 0.4):
            return True
        
        return False
    
    def _try_ocr(self, pdf_bytes: bytes, file_name: str) -> str:
        """OCR ile metin çıkarmayı dener"""
        try:
            from app.services.ocr_service import get_ocr_service
            from app.services.logging_service import log_system_event
            
            log_system_event("INFO", f"OCR fallback aktif: {file_name}", "pdf_processor")
            
            ocr_service = get_ocr_service()
            text = ocr_service.extract_text_from_pdf_pages(pdf_bytes)
            
            log_system_event(
                "INFO", 
                f"OCR tamamlandı: {file_name} ({len(text)} karakter)", 
                "pdf_processor"
            )
            
            return text
            
        except Exception as e:
            from app.services.logging_service import log_error
            log_error(f"OCR fallback hatası: {str(e)}", "pdf_processor", error_detail=str(e))
            return ""
    
    def _extract_from_reader(self, reader) -> str:
        """PdfReader'dan metin çıkarır (ortak mantık)"""
        text_parts = []
        
        for page_num, page in enumerate(reader.pages, 1):
            page_text = page.extract_text()
            if page_text:
                # ⚡ NUL karakterlerini temizle (PostgreSQL text alanı kabul etmez)
                page_text = page_text.replace('\x00', '')
                
                # 🇹🇷 Türkçe karakter düzeltme (PDF font encoding sorunları)
                page_text = self._fix_turkish_chars(page_text)
                
                text_parts.append(f"[Sayfa {page_num}]\n{page_text}")
        
        return "\n\n".join(text_parts)
    
    def _fix_turkish_chars(self, text: str) -> str:
        """
        PDF'den çıkan metindeki Türkçe karakter sorunlarını düzeltir.
        
        Bazı PDF'lerde font encoding sorunu nedeniyle:
        - 'ı' (dotless i) yanlış encode edilir
        - Harfler birleştirilir veya kaybolur
        
        Bu fonksiyon yaygın sorunları tespit edip düzeltir.
        """
        import unicodedata
        
        # Önce Unicode normalizasyonu yap
        text = unicodedata.normalize('NFKC', text)
        
        # Yaygın PDF font encoding hataları ve düzeltmeleri
        # (Fi, fl gibi ligature'lar ve encoding hataları)
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
            '¤': 'ğ',  # Bazı eski PDF'lerde
            '¦': 'ş',
            '\u0131': 'ı',  # Dotless i - bu doğru ama bazen görünmez
            
            # Boşluk ve görünmez karakter düzeltmeleri
            '\u00a0': ' ',  # Non-breaking space
            '\u2003': ' ',  # Em space
            '\u2002': ' ',  # En space
            '\u200b': '',   # Zero-width space
            '\u200c': '',   # Zero-width non-joiner
            '\u200d': '',   # Zero-width joiner
            '\ufeff': '',   # BOM
            '\x00': '',     # NUL karakter (PostgreSQL için kritik!)
        }
        
        for old, new in replacements.items():
            text = text.replace(old, new)
        
        # Çift boşlukları tek boşluğa indir
        text = re.sub(r' {2,}', ' ', text)
        
        return text
    
    # =========================================================================
    # HEADING DETECTION & SEMANTIC CHUNKING (2024 Best Practices)
    # =========================================================================
    
    # Heading pattern'leri (regex)
    HEADING_PATTERNS = [
        r'^[A-Z][A-Z\s]{3,50}$',           # BÜYÜK HARF BAŞLIK
        r'^\d+\.\s+[A-ZĞÜŞİÖÇ].+$',        # 1. Numaralı Başlık
        r'^\d+\.\d+\s+[A-ZĞÜŞİÖÇ].+$',     # 1.1 Alt Başlık
        r'^[A-ZĞÜŞİÖÇ][a-zğüşıöç]+(\s+[A-ZĞÜŞİÖÇ][a-zğüşıöç]+)*:$',  # Başlık:
        r'^(Madde|MADDE|Bölüm|BÖLÜM|Kısım|KISIM)\s*\d*\.?\s*.+$',  # Madde 1.
        r'^(GİRİŞ|SONUÇ|ÖZET|ABSTRACT|INTRODUCTION|CONCLUSION)$',  # Standart bölümler
    ]
    
    def _detect_heading(self, line: str) -> bool:
        """
        Bir satırın heading olup olmadığını tespit eder.
        
        Kriterler:
        1. Kısa satır (< 80 karakter)
        2. Heading pattern'lerine uyuyor
        3. Büyük harfle başlıyor
        4. Nokta ile bitmiyor (paragraf değil)
        """
        import re
        
        line = line.strip()
        
        # Çok kısa veya çok uzun satırlar heading değil
        if len(line) < 3 or len(line) > 100:
            return False
        
        # Nokta ile bitiyorsa muhtemelen cümle
        if line.endswith('.') and not re.match(r'^\d+\.', line):
            return False
        
        # Heading pattern kontrolü
        for pattern in self.HEADING_PATTERNS:
            if re.match(pattern, line, re.IGNORECASE):
                return True
        
        # Tüm büyük harf ve kısa ise heading
        if line.isupper() and len(line) < 60:
            return True
        
        return False
    
    def _detect_sub_heading(self, text: str) -> Optional[str]:
        """
        v3.4.1: Alt-chunk içindeki heading satırını tespit eder.
        
        Büyük section'lar _split_large_section() ile parçalandığında,
        alt-chunk'ın ilk satırlarında yeni bir başlık olabilir.
        Bu başlığı tespit edip döndürür.
        
        v3.4.1-fix: Sıkı filtreleme — cümle parçalarını heading olarak
        algılamayı önler (küçük harf, fiil ekleri, uzunluk kontrolleri).
        
        Returns:
            Tespit edilen heading metni veya None
        """
        if not text or len(text.strip()) < 10:
            return None
        
        # Türkçe fiil ekleri — heading'de ASLA bulunmaz
        _VERB_ENDINGS = (
            'ır.', 'ir.', 'ur.', 'ür.', 'ar.', 'er.',
            'ler.', 'lar.', 'nır', 'nir', 'lir', 'lır',
            'bilir', 'mektedir', 'ması', 'mesi',
            'dır.', 'dir.', 'dur.', 'dür.',
            'tır.', 'tir.', 'tur.', 'tür.',
            'caktır', 'cektir', 'malıdır', 'melidir',
        )
        
        lines = text.strip().split('\n')
        
        # İlk 3 satıra bak (heading genelde başta olur, 5 çok agresif)
        for line in lines[:3]:
            stripped = line.strip()
            if not stripped or len(stripped) < 3:
                continue
            
            # ❌ Çok uzun satırlar heading olamaz
            if len(stripped) > 80:
                continue
            
            # ❌ Küçük harfle başlayan satırlar heading olamaz
            if stripped[0].islower():
                continue
            
            # ❌ Nokta ile biten (numaralı başlık hariç: "1. Başlık")
            if stripped.endswith('.') and not re.match(r'^\d+\.', stripped):
                continue
            
            # ❌ v3.4.2: Virgülle biten satırlar heading olamaz ("SP miktarı,")
            if stripped.endswith(','):
                continue
            
            # ❌ v3.4.2: İki nokta ile biten — cümle devamı ("Teslimat Paket (Ana):")
            if stripped.endswith(':') and not re.match(r'^\d+[\.\)]\s', stripped):
                continue
            
            # ❌ v3.4.2: Parantez içi cümle parçası ("alanlarının otomatik")
            if stripped.endswith(("'", '"')) or stripped[-1] in (';', '…'):
                continue
            
            # ❌ Fiil eki içeren satırlar cümle parçası
            stripped_lower = stripped.lower()
            if any(stripped_lower.endswith(ve) for ve in _VERB_ENDINGS):
                continue
            
            # ✅ Heading tespiti: _detect_heading (regex patterns)
            if self._detect_heading(stripped):
                return stripped
            
            # ✅ Title Case kontrolü (ek güvence)
            words = stripped.split()
            if 3 <= len(words) <= 10 and len(stripped) < 60:
                title_case_count = sum(
                    1 for w in words 
                    if w[0].isupper() and len(w) > 1
                )
                if title_case_count / len(words) >= 0.7:
                    return stripped
        
        return None
    
    def _detect_table_content(self, text: str) -> bool:
        """
        Metin içinde tablo yapısı olup olmadığını tespit eder.
        
        Kriterler:
        1. Çoklu | karakteri (pipe separated)
        2. Tab karakterleri ile ayrılmış sütunlar
        3. Düzenli boşluk pattern'i (fixed width columns)
        """
        lines = text.split('\n')
        
        # Pipe karakteri sayısı - tablo göstergesi
        pipe_lines = sum(1 for line in lines if line.count('|') >= 2)
        if pipe_lines >= 2:
            return True
        
        # Tab ile ayrılmış satırlar
        tab_lines = sum(1 for line in lines if '\t' in line and line.count('\t') >= 2)
        if tab_lines >= 2:
            return True
        
        return False
    
    def _extract_sections_with_headings(self, text: str) -> List[dict]:
        """
        Metni heading'lere göre bölümlere ayırır.
        
        Returns:
            List[dict]: [{"heading": "Başlık", "content": "İçerik", "page": N}, ...]
        """
        sections = []
        current_heading = ""
        current_content = []
        current_page = None
        
        lines = text.split('\n')
        
        for line in lines:
            stripped = line.strip()
            
            # Sayfa numarası tespiti
            if stripped.startswith('[Sayfa ') and ']' in stripped:
                try:
                    page_str = stripped.split('[Sayfa ')[1].split(']')[0]
                    current_page = int(page_str)
                    continue
                except (ValueError, IndexError):
                    pass
            
            # Boş satır - atla
            if not stripped:
                current_content.append('')
                continue
            
            # Heading tespiti
            if self._detect_heading(stripped):
                # Önceki section'ı kaydet
                if current_content:
                    content_text = '\n'.join(current_content).strip()
                    if content_text:
                        sections.append({
                            "heading": current_heading,
                            "content": content_text,
                            "page": current_page,
                            "is_table": self._detect_table_content(content_text)
                        })
                
                current_heading = stripped
                current_content = []
            else:
                current_content.append(stripped)
        
        # Son section'ı kaydet
        if current_content:
            content_text = '\n'.join(current_content).strip()
            if content_text:
                sections.append({
                    "heading": current_heading,
                    "content": content_text,
                    "page": current_page,
                    "is_table": self._detect_table_content(content_text)
                })
        
        return sections
    
    def _split_large_section(self, text: str, max_size: int = 2000, overlap_size: int = 100) -> List[str]:
        """
        Büyük section'ları semantic bölümlere ayırır.
        Paragraf sınırlarında veya cümle sonlarında böler.
        v3.3.0: Chunk'lar arası overlap ile bağlam korunması.
        v2.38.0: Türkçe-uyumlu cümle bölme (kısaltmaları korur).
        """
        if len(text) <= max_size:
            return [text]
        
        
        chunks = []
        
        # Önce paragraflara böl
        paragraphs = text.split('\n\n')
        
        current_chunk = ""
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            # Mevcut chunk + yeni paragraf max_size'ı aşıyor mu?
            if len(current_chunk) + len(para) + 2 > max_size:
                # Mevcut chunk'ı kaydet
                if current_chunk:
                    chunks.append(current_chunk)
                
                # v3.3.0: Önceki chunk'ın son overlap_size karakterini overlap olarak al
                overlap_prefix = ""
                if chunks and overlap_size > 0:
                    prev_chunk = chunks[-1]
                    # Kelime sınırından overlap al
                    overlap_start = max(0, len(prev_chunk) - overlap_size)
                    overlap_candidate = prev_chunk[overlap_start:]
                    # İlk boşluktan itibaren al (kelime ortasından bölme)
                    space_pos = overlap_candidate.find(' ')
                    if space_pos > 0:
                        overlap_prefix = overlap_candidate[space_pos + 1:]
                    else:
                        overlap_prefix = overlap_candidate
                
                # Paragraf tek başına çok büyükse, cümlelere böl
                if len(para) > max_size:
                    # Türkçe-uyumlu cümle bölme: .!? sonrası + büyük harf başlangıcı
                    sentences = re.split(r'(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜa-zçğıöşü])', para)
                    current_chunk = (overlap_prefix + " " + sentences[0]).strip() if overlap_prefix else sentences[0]
                    for sentence in sentences[1:]:
                        if len(current_chunk) + len(sentence) + 1 > max_size:
                            if current_chunk:
                                chunks.append(current_chunk)
                            # Overlap al
                            overlap_prefix = ""
                            if chunks and overlap_size > 0:
                                prev = chunks[-1]
                                ov_start = max(0, len(prev) - overlap_size)
                                ov_cand = prev[ov_start:]
                                sp = ov_cand.find(' ')
                                overlap_prefix = ov_cand[sp + 1:] if sp > 0 else ov_cand
                            current_chunk = (overlap_prefix + " " + sentence).strip() if overlap_prefix else sentence
                        else:
                            current_chunk = (current_chunk + " " + sentence).strip()
                else:
                    current_chunk = (overlap_prefix + " " + para).strip() if overlap_prefix else para
            else:
                current_chunk = (current_chunk + "\n\n" + para).strip()
        
        # Son chunk'ı kaydet
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks
    
    def extract_chunks(self, file_obj: BinaryIO, file_name: str) -> List[dict]:
        """
        PDF dosyasından zengin metadata ile chunk'lar çıkarır.
        DOCX processor ile tutarlı format.
        
        v2.43.0: PyMuPDF font-aware heading detection + heading hiyerarşi.
        Fallback: pypdf + regex heading detection.
        
        Returns:
            List[dict]: [{"text": "...", "metadata": {"heading": "...", "page": N,
                          "type": "...", "heading_level": N, "heading_path": [...]}}, ...]
        """
        # Byte'ları oku (fitz için gerekli)
        pdf_bytes = file_obj.read()
        file_obj.seek(0)
        
        chunks = []
        chunk_index = 0
        sections = []
        
        # 🆕 v2.43.0 Faz 4: Görsel pozisyonlarını çıkar
        image_positions = self._extract_image_positions_fitz(pdf_bytes)
        
        # 1. PyMuPDF ile font-aware extraction dene
        structured_blocks = self._extract_structured_blocks_fitz(pdf_bytes)
        
        if structured_blocks:
            # v2.43.0 Faz 6: Header/footer filtreleme
            structured_blocks = self._clean_header_footer_blocks(structured_blocks)
            sections = self._build_sections_from_structured(structured_blocks)
        
        # 2. Fallback: pypdf + regex heading detection
        if not sections:
            text = self.extract_text_from_bytes(file_obj, file_name)
            if not text or not text.strip():
                return []
            sections = self._extract_sections_with_headings(text)
            # Fallback section'lara heading_level ve heading_path ekle
            for sec in sections:
                if "heading_level" not in sec:
                    sec["heading_level"] = 0
                if "heading_path" not in sec:
                    sec["heading_path"] = [sec["heading"]] if sec.get("heading") else []
        
        if not sections:
            # Heading bulunamadıysa, basit chunking
            text = self.extract_text_from_bytes(file_obj, file_name)
            for chunk_text in self._split_large_section(text):
                if len(chunk_text.strip()) >= 50:
                    chunks.append({
                        "text": chunk_text.strip(),
                        "metadata": {
                            "type": "paragraph",
                            "heading": "",
                            "heading_level": 0,
                            "heading_path": [],
                            "file_type": "pdf",
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
                page = section.get("page")
                is_table = section.get("is_table", False)
                heading_level = section.get("heading_level", 0)
                heading_path = section.get("heading_path", [])
                
                # v2.43.0 Faz 6: TOC tespiti
                is_toc = self._detect_toc_section(section)
                
                if is_toc:
                    content_type = "toc"
                elif is_table:
                    content_type = "table"
                else:
                    content_type = "paragraph"
                
                for sub_text in self._split_large_section(content):
                    if len(sub_text.strip()) >= 50:
                        # v3.4.1: Alt-chunk içinde yeni heading varsa kullan
                        effective_heading = heading
                        effective_path = list(heading_path)
                        sub_heading = self._detect_sub_heading(sub_text)
                        if sub_heading and sub_heading != heading:
                            effective_heading = sub_heading
                            # heading_path'i güncelle (üst path + yeni heading)
                            effective_path = list(heading_path) + [sub_heading]
                        
                        chunk_meta = {
                            "type": content_type,
                            "heading": effective_heading,
                            "heading_level": heading_level,
                            "heading_path": effective_path,
                            "page": page,
                            "file_type": "pdf",
                            "chunk_index": chunk_index,
                            "source": file_name
                        }
                        
                        # 🆕 v2.43.0 Faz 4: Görsel eşleme
                        if page and page in image_positions:
                            chunk_meta["image_refs"] = image_positions[page]
                        
                        chunks.append({
                            "text": sub_text.strip(),
                            "metadata": chunk_meta
                        })
                        chunk_index += 1
        
        return chunks
    
    def get_metadata(self, file_path: Path = None, file_name: str = None) -> dict:
        """PDF metadata'sını çıkarır"""
        base_meta = {"processor": self.PROCESSOR_NAME}
        
        if file_path:
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(file_path))
                meta = reader.metadata or {}
                
                base_meta.update({
                    "title": meta.get("/Title", file_path.stem),
                    "author": meta.get("/Author", ""),
                    "page_count": len(reader.pages),
                })
            except Exception:
                logger.warning("[PDFProcessor] Metadata okuma hatası", exc_info=True)
                base_meta["title"] = file_path.stem if file_path else file_name
        else:
            base_meta["file_name"] = file_name
        
        return base_meta
    
    def chunk_text(self, text: str, source_file: str) -> List[DocumentChunk]:
        """PDF için sayfa bazlı chunk'lama"""
        if not text or not text.strip():
            return []
        
        chunks = []
        chunk_index = 0
        
        # Sayfa bazlı bölme
        pages = text.split("[Sayfa ")
        
        for page_section in pages:
            if not page_section.strip():
                continue
            
            # Sayfa numarasını çıkar
            page_num = None
            if "]" in page_section:
                try:
                    page_num_str = page_section.split("]")[0]
                    page_num = int(page_num_str)
                    page_content = "]".join(page_section.split("]")[1:])
                except ValueError:
                    page_content = page_section
            else:
                page_content = page_section
            
            page_content = page_content.strip()
            if not page_content:
                continue
            
            # Eğer sayfa çok büyükse, parçala
            if len(page_content) > self.chunk_size:
                start = 0
                while start < len(page_content):
                    end = start + self.chunk_size
                    
                    if end < len(page_content):
                        last_space = page_content.rfind(' ', start, end)
                        if last_space > start:
                            end = last_space
                    
                    chunk_content = page_content[start:end].strip()
                    
                    if chunk_content:
                        chunks.append(DocumentChunk(
                            text=chunk_content,
                            metadata={
                                "processor": self.PROCESSOR_NAME,
                                "page_number": page_num
                            },
                            chunk_index=chunk_index,
                            source_file=source_file,
                            page_number=page_num
                        ))
                        chunk_index += 1
                    
                    start = end - self.chunk_overlap
                    if start >= len(page_content) or end >= len(page_content):
                        break
            else:
                chunks.append(DocumentChunk(
                    text=page_content,
                    metadata={
                        "processor": self.PROCESSOR_NAME,
                        "page_number": page_num
                    },
                    chunk_index=chunk_index,
                    source_file=source_file,
                    page_number=page_num
                ))
                chunk_index += 1
        
        return chunks
