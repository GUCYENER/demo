"""
VYRA L1 Support API - Document Enhancement Service (Facade)
=============================================================
CatBoost chunk kalite analizi + LLM ile doküman iyileştirme.

Bu dosya orchestrator (facade) rolündedir. İş mantığı alt modüllere
delege edilir:
  - enhancer/section_extractors.py: Doküman → bölümler
  - enhancer/catboost_prioritizer.py: CatBoost/heuristic priority
  - enhancer/llm_enhancement.py: LLM iyileştirme + anchor + integrity
  - enhancer/output_pdf.py: PDF oluşturma
  - enhancer/output_docx.py: DOCX oluşturma/güncelleme
  - enhancer/output_xlsx.py: XLSX güncelleme
  - enhancer/image_helpers.py: Görsel eşleştirme

Akış:
1. Maturity ihlallerini al
2. Doküman içeriğini bölümlere ayır
3. CatBoost ile her bölümün RAG kalitesini tahmin et
4. LLM ile düşük kaliteli bölümleri iyileştir
5. İyileştirilmiş çıktı dosyası oluştur

Author: VYRA AI Team
Version: 2.0.0 (v3.3.3) — Modular refactoring
"""

import os
import time
import tempfile
import uuid
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from app.services.logging_service import log_system_event, log_error, log_warning


# ============================================
# Enhancement Data Classes
# ============================================

@dataclass
class EnhancedSection:
    """Bir bölümün orijinal ve iyileştirilmiş hali"""
    section_index: int
    heading: str
    original_text: str
    enhanced_text: str
    change_type: str          # "heading_added", "content_restructured", "table_fixed", "encoding_fixed", "no_change", "llm_error", "integrity_failed"
    explanation: str          # İyileştirme açıklaması
    priority: float           # CatBoost priority skoru (0-1)
    violations: List[str] = field(default_factory=list)
    integrity_score: float = 1.0    # Bütünlük doğrulama skoru (0-1)
    integrity_issues: List[str] = field(default_factory=list)  # Bütünlük sorunları


@dataclass
class EnhancementResult:
    """Tüm iyileştirme sonucu"""
    file_name: str
    file_type: str
    total_sections: int
    enhanced_count: int
    sections: List[EnhancedSection] = field(default_factory=list)
    catboost_summary: Dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    enhanced_docx_path: str = ""
    error: Optional[str] = None


# ============================================
# Geçici dosya deposu (session bazlı)
# ============================================
_enhanced_files: Dict[str, str] = {}  # session_id → temp file path


# ============================================
# Document Enhancer — Orchestrator (Facade)
# ============================================

class DocumentEnhancer:
    """
    Doküman iyileştirme ana sınıfı.

    İş mantığını alt modüllere delege eder:
    - SectionExtractor: Dokümanı bölümlere ayırma
    - CatBoostPrioritizer: Kalite tahmini
    - LLMEnhancer: LLM ile iyileştirme
    - Output generators: Çıktı dosyası oluşturma (PDF/DOCX/XLSX)
    """

    def __init__(self):
        from app.services.enhancer.section_extractors import SectionExtractor
        from app.services.enhancer.catboost_prioritizer import CatBoostPrioritizer
        from app.services.enhancer.llm_enhancement import LLMEnhancer

        self._section_extractor = SectionExtractor()
        self._catboost_prioritizer = CatBoostPrioritizer()
        self._llm_enhancer = LLMEnhancer()

    # ─────────────────────────────────────────
    #  ANA PİPELINE
    # ─────────────────────────────────────────

    def analyze_and_enhance(
        self,
        file_content: bytes,
        file_name: str,
        maturity_result: Dict[str, Any],
        progress_callback=None
    ) -> EnhancementResult:
        """
        Ana iyileştirme pipeline'ı.

        Args:
            file_content: Dosya binary içeriği
            file_name: Dosya adı
            maturity_result: Maturity analyzer sonucu
            progress_callback: WebSocket progress fonksiyonu (current, total, heading, status)

        Returns:
            EnhancementResult: İyileştirme sonucu
        """
        start_time = time.time()

        try:
            file_type = maturity_result.get("file_type", "TXT").upper().replace(".", "")
            violations = maturity_result.get("violations", [])

            # ADIM 1: Dokümanı bölümlere ayır
            sections = self._section_extractor.extract_sections(file_content, file_name, file_type)

            if not sections:
                return EnhancementResult(
                    file_name=file_name,
                    file_type=file_type,
                    total_sections=0,
                    enhanced_count=0,
                    error="Dosyadan hiçbir bölüm çıkarılamadı."
                )

            log_system_event("INFO",
                f"Section extraction: {len(sections)} bölüm ({file_type})",
                "enhancer")

            # ADIM 2: CatBoost ile önceliklendirme
            catboost_analysis = self._catboost_prioritizer.catboost_prioritize(
                sections, file_type, violations
            )

            # ADIM 3: LLM ile iyileştirme
            enhanced_sections = self._llm_enhancer.llm_enhance(
                sections, violations, file_type, catboost_analysis,
                progress_callback=progress_callback
            )

            # ADIM 4: Çıktı dosyası oluştur
            session_id = str(uuid.uuid4())[:8]
            docx_path = self._generate_enhanced_output(
                enhanced_sections, file_name, session_id,
                original_content=file_content, file_type=file_type
            )

            # Sonucu derle
            enhanced_count = sum(1 for s in enhanced_sections if s.change_type not in ("no_change", "llm_error", "integrity_failed"))
            error_count = sum(1 for s in enhanced_sections if s.change_type in ("llm_error", "integrity_failed"))

            result = EnhancementResult(
                file_name=file_name,
                file_type=file_type,
                total_sections=len(sections),
                enhanced_count=enhanced_count,
                sections=enhanced_sections,
                catboost_summary=catboost_analysis.get("summary", {}),
                session_id=session_id,
                enhanced_docx_path=docx_path
            )

            elapsed = round(time.time() - start_time, 2)
            log_system_event("INFO", f"Enhancement tamamlandı: {enhanced_count}/{len(sections)} bölüm iyileştirildi, {error_count} hata, {elapsed}s", "enhancer")

            return result

        except Exception as e:
            log_error(f"Enhancement pipeline hatası: {e}", "enhancer")
            return EnhancementResult(
                file_name=file_name,
                file_type="",
                total_sections=0,
                enhanced_count=0,
                error="İyileştirme sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin."
            )

    # ─────────────────────────────────────────
    #  ÇIKTI DOSYASI OLUŞTURMA (Router)
    # ─────────────────────────────────────────

    def _generate_enhanced_output(
        self,
        sections: List[EnhancedSection],
        original_name: str,
        session_id: str,
        original_content: bytes = None,
        file_type: str = ""
    ) -> str:
        """
        İyileştirilmiş doküman oluştur.

        Dosya tipine göre uygun output generator'a yönlendirir:
        - PDF orijinalse: fpdf2 ile doğrudan PDF oluşturulur
        - XLSX/XLS orijinalse: Orijinal XLSX korunur + iyileştirilmiş sheet eklenir
        - DOCX orijinalse: Orijinal DOCX şablon olarak açılır, metinler güncellenir
        - Diğerleri (PPTX/TXT): Sıfırdan DOCX oluşturulur
        """

        # Orijinal dosyadan görselleri çıkar (tüm format'lar için ortak)
        # v3.4.2: Performans — 50'den fazla görseli olan dosyalarda
        # görsel eşleştirme atlanır (OCR + mapping çok yavaş).
        # Görseller RAG upload sırasında ayrıca çıkarılır.
        original_images = []
        if original_content:
            try:
                from app.services.document_processors.image_extractor import ImageExtractor
                img_extractor = ImageExtractor()
                ext_for_extract = file_type if file_type.startswith(".") else f".{file_type.lower()}"
                original_images = img_extractor.extract(original_content, ext_for_extract, skip_ocr=True)
                if original_images:
                    if len(original_images) > 50:
                        log_system_event("INFO",
                            f"Enhanced çıktı: {len(original_images)} görsel var, "
                            f"performans için preview'da görseller atlanıyor (>50 limit)",
                            "enhancer")
                        original_images = []  # Preview'da görsel ekleme
                    else:
                        log_system_event("INFO", f"Enhanced çıktı için {len(original_images)} görsel çıkarıldı", "enhancer")
            except Exception as e:
                log_warning(f"Enhanced çıktı görsel çıkarma hatası: {e}", "enhancer")

        # PDF orijinalse: doğrudan PDF oluştur
        if file_type.upper() in ("PDF", ".PDF"):
            try:
                from app.services.enhancer.output_pdf import create_fresh_pdf
                pdf_path = create_fresh_pdf(
                    sections, original_name, session_id,
                    original_images, original_content=original_content
                )
                if pdf_path and os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                    _enhanced_files[session_id] = pdf_path
                    log_system_event("INFO", f"Enhanced PDF oluşturuldu: {pdf_path}", "enhancer")
                    return pdf_path
            except Exception as e:
                log_system_event("WARNING", f"PDF oluşturma başarısız, DOCX fallback: {e}", "enhancer")
                # Fallback: DOCX olarak devam et

        # XLSX/XLS orijinalse
        if original_content and file_type.upper().replace(".", "") in ("XLSX", "XLS"):
            try:
                from app.services.enhancer.output_xlsx import apply_to_original_xlsx
                xlsx_path = apply_to_original_xlsx(
                    original_content, sections, session_id, file_type
                )
                if xlsx_path and os.path.exists(xlsx_path) and os.path.getsize(xlsx_path) > 0:
                    _enhanced_files[session_id] = xlsx_path
                    log_system_event("INFO", f"Enhanced XLSX oluşturuldu: {xlsx_path}", "enhancer")
                    return xlsx_path
            except Exception as e:
                log_system_event("WARNING", f"XLSX oluşturma başarısız, DOCX fallback: {e}", "enhancer")

        # DOCX veya diğer formatlar
        from app.services.enhancer.output_docx import (
            apply_to_original_docx, create_fresh_docx
        )

        if original_content and file_type.upper() in ("DOCX", ".DOCX"):
            doc = apply_to_original_docx(original_content, sections)
        else:
            doc = create_fresh_docx(sections, original_name, original_images)

        # Geçici DOCX dosyasına kaydet
        temp_docx_path = tempfile.mktemp(suffix=".docx", prefix=f"enhanced_{session_id}_")
        doc.save(temp_docx_path)

        # Session registry'ye ekle
        _enhanced_files[session_id] = temp_docx_path

        log_system_event("INFO", f"Enhanced DOCX oluşturuldu: {temp_docx_path}", "enhancer")
        return temp_docx_path

    def generate_selective_docx(
        self,
        original_content: bytes,
        sections: List[EnhancedSection],
        approved_indexes: List[int],
        session_id: str,
        file_type: str = ""
    ) -> str:
        """
        Sadece onaylanan section'ları uygulayarak yeni çıktı oluştur.
        Onaylanmayan bölümler orijinal haliyle kalır.
        """
        # Sadece onaylanan section'ları aktif yap, diğerlerini no_change'e çevir
        selective_sections = []
        for s in sections:
            if s.section_index in approved_indexes:
                selective_sections.append(s)
            else:
                # Onaylanmayan → orijinal metin korunsun
                selective_sections.append(EnhancedSection(
                    section_index=s.section_index,
                    heading=s.heading,
                    original_text=s.original_text,
                    enhanced_text=s.original_text,
                    change_type="no_change",
                    explanation="Kullanıcı tarafından reddedildi.",
                    priority=s.priority,
                    violations=s.violations
                ))

        return self._generate_enhanced_output(
            selective_sections, "", session_id,
            original_content=original_content, file_type=file_type
        )

    def to_dict(self, result: EnhancementResult) -> Dict[str, Any]:
        """EnhancementResult'ı JSON-serializable dict'e çevir"""
        return {
            "file_name": result.file_name,
            "file_type": result.file_type,
            "total_sections": result.total_sections,
            "enhanced_count": result.enhanced_count,
            "session_id": result.session_id,
            "error": result.error,
            "catboost_summary": result.catboost_summary,
            "sections": [
                {
                    "section_index": s.section_index,
                    "heading": s.heading,
                    "original_text": s.original_text,
                    "enhanced_text": s.enhanced_text,
                    "change_type": s.change_type,
                    "explanation": s.explanation,
                    "priority": s.priority,
                    "violations": s.violations,
                    "integrity_score": s.integrity_score,
                    "integrity_issues": s.integrity_issues,
                }
                for s in result.sections
            ]
        }


# ============================================
# Module-level helpers (backward compatible)
# ============================================

def get_enhanced_file_path(session_id: str) -> Optional[str]:
    """Session ID ile geçici dosya yolunu getir"""
    return _enhanced_files.get(session_id)


def cleanup_enhanced_file(session_id: str):
    """Geçici dosyayı temizle"""
    path = _enhanced_files.pop(session_id, None)
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except Exception as e:
            log_warning(f"Geçici dosya silme hatası ({path}): {e}", "enhancer")
