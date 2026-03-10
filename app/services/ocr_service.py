"""
VYRA L1 Support API - OCR Service
==================================
EasyOCR ile taranmış belgelerden metin çıkarma.
Modüler ve lazy-load tasarım.
"""

from __future__ import annotations

from typing import List, Optional
import io

from app.services.logging_service import log_system_event, log_error


class OCRService:
    """
    EasyOCR tabanlı OCR servisi.
    
    Özellikler:
    - Lazy loading (model sadece gerektiğinde yüklenir)
    - Türkçe ve İngilizce dil desteği
    - GPU varsa otomatik kullanır
    """
    
    def __init__(self, languages: List[str] = None):
        """
        Args:
            languages: OCR dilleri (varsayılan: ['tr', 'en'])
        """
        self._reader = None
        self._languages = languages or ['tr', 'en']
        self._initialized = False
    
    @property
    def reader(self):
        """EasyOCR reader'ı lazy load eder"""
        if self._reader is None:
            try:
                import easyocr
                
                log_system_event("INFO", f"EasyOCR yükleniyor (diller: {self._languages})...", "ocr")
                
                # GPU varsa kullan, yoksa CPU
                self._reader = easyocr.Reader(
                    self._languages,
                    gpu=False,  # Windows'ta genelde CPU daha stabil
                    verbose=False
                )
                
                self._initialized = True
                log_system_event("INFO", "EasyOCR başarıyla yüklendi", "ocr")
                
            except ImportError:
                log_error("EasyOCR yüklü değil. 'pip install easyocr' çalıştırın.", "ocr")
                raise ImportError("EasyOCR yüklü değil. 'pip install easyocr' çalıştırın.")
            except Exception as e:
                log_error(f"EasyOCR yükleme hatası: {str(e)}", "ocr", error_detail=str(e))
                raise
        
        return self._reader
    
    def extract_text_from_image(self, image_path: str) -> str:
        """
        Görsel dosyadan metin çıkarır.
        
        Args:
            image_path: Görsel dosya yolu
            
        Returns:
            Çıkarılan metin
        """
        try:
            results = self.reader.readtext(image_path)
            
            # Sonuçları birleştir
            texts = [result[1] for result in results]
            return "\n".join(texts)
            
        except Exception as e:
            log_error(f"OCR hatası: {str(e)}", "ocr", error_detail=str(e))
            raise
    
    def extract_text_from_image_bytes(self, image_bytes: bytes) -> str:
        """
        Görsel byte'larından metin çıkarır.
        
        Args:
            image_bytes: Görsel içeriği (bytes)
            
        Returns:
            Çıkarılan metin
        """
        try:
            import numpy as np
            from PIL import Image
            
            # Bytes'dan PIL Image oluştur
            image = Image.open(io.BytesIO(image_bytes))
            
            # RGB'ye çevir (RGBA veya diğer formatlar için)
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # NumPy array'e çevir (EasyOCR için)
            image_array = np.array(image)
            
            # OCR uygula
            results = self.reader.readtext(image_array)
            
            # Sonuçları birleştir
            texts = [result[1] for result in results]
            return "\n".join(texts)
            
        except Exception as e:
            log_error(f"OCR hatası (bytes): {str(e)}", "ocr", error_detail=str(e))
            raise
    
    def extract_text_from_pdf_pages(self, pdf_bytes: bytes) -> str:
        """
        PDF sayfalarını görsel olarak işler ve OCR uygular.
        
        Args:
            pdf_bytes: PDF içeriği (bytes)
            
        Returns:
            Tüm sayfalardan çıkarılan metin
        """
        try:
            from pdf2image import convert_from_bytes
            import numpy as np
            
            log_system_event("INFO", "PDF OCR işlemi başlatılıyor...", "ocr")
            
            # PDF'i sayfa görsellerine çevir
            # poppler_path gerekebilir Windows'ta
            try:
                images = convert_from_bytes(pdf_bytes, dpi=200)
            except Exception as e:
                # Poppler yüklü değilse hata mesajı
                if "poppler" in str(e).lower():
                    raise RuntimeError(
                        "Poppler yüklü değil. Windows için: "
                        "https://github.com/oschwartz10612/poppler-windows/releases "
                        "adresinden indirin ve PATH'e ekleyin."
                    )
                raise
            
            all_texts = []
            
            for page_num, image in enumerate(images, 1):
                # RGB'ye çevir
                if image.mode != 'RGB':
                    image = image.convert('RGB')
                
                # NumPy array'e çevir
                image_array = np.array(image)
                
                # OCR uygula
                results = self.reader.readtext(image_array)
                
                # Sonuçları birleştir
                page_texts = [result[1] for result in results]
                page_text = "\n".join(page_texts)
                
                if page_text.strip():
                    all_texts.append(f"[Sayfa {page_num}]\n{page_text}")
                    
                log_system_event("INFO", f"OCR: Sayfa {page_num}/{len(images)} işlendi", "ocr")
            
            final_text = "\n\n".join(all_texts)
            
            # NUL karakterlerini temizle
            final_text = final_text.replace('\x00', '')
            
            log_system_event(
                "INFO", 
                f"PDF OCR tamamlandı: {len(images)} sayfa, {len(final_text)} karakter", 
                "ocr"
            )
            
            return final_text
            
        except ImportError as e:
            log_error(f"OCR bağımlılık hatası: {str(e)}", "ocr", error_detail=str(e))
            raise
        except Exception as e:
            log_error(f"PDF OCR hatası: {str(e)}", "ocr", error_detail=str(e))
            raise
    
    def is_available(self) -> bool:
        """OCR servisinin kullanılabilir olup olmadığını kontrol eder"""
        try:
            import easyocr as _easyocr  # availability check
            _ = _easyocr  # suppress unused import warning
            return True
        except ImportError as e:
            log_error(f"easyocr import hatası: {e}", "ocr")
            return False


# Singleton instance
_ocr_service: Optional[OCRService] = None


def get_ocr_service() -> OCRService:
    """OCR Service singleton instance döndürür"""
    global _ocr_service
    if _ocr_service is None:
        _ocr_service = OCRService()
    return _ocr_service
