"""
VYRA L1 Support API - PDF Output Generator
=============================================
fpdf2 ile doğrudan PDF oluşturma.
Türkçe karakter desteği, Markdown rendering, görsel yerleştirme dahil.

Author: VYRA AI Team
Version: 1.0.0 (v3.3.3)
"""

import io
import os
import re
import tempfile
from typing import List

from app.services.logging_service import log_system_event, log_warning
from app.services.enhancer.image_helpers import (
    get_section_text, map_images_to_sections, organize_images_at_positions
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.services.document_enhancer import EnhancedSection


def create_fresh_pdf(
    sections: List['EnhancedSection'],
    original_name: str,
    session_id: str,
    original_images: list = None,
    original_content: bytes = None
) -> str:
    """
    fpdf2 ile doğrudan PDF oluştur.
    Saf Python — Word/COM/internet gerektirmez.
    Türkçe karakter desteği için Windows Arial TTF kullanılır.
    Markdown syntax temizlenerek düzgün tipografi ile render edilir.

    v2.40.1: Orijinal dosyadan çıkarılan görseller bölüm heading'lerine
    eşleştirilerek ilgili bölümün sonuna eklenir.
    """
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Türkçe karakter desteği: Arial TTF (Windows sistem fontu)
    font_name = "Helvetica"  # Fallback
    has_bold = True  # Helvetica built-in bold var
    font_dir = r"C:\Windows\Fonts"
    arial_regular = os.path.join(font_dir, "arial.ttf")
    arial_bold = os.path.join(font_dir, "arialbd.ttf")

    if os.path.exists(arial_regular):
        font_name = "ArialTR"
        pdf.add_font(font_name, "", arial_regular)
        if os.path.exists(arial_bold):
            pdf.add_font(font_name, "B", arial_bold)
        else:
            has_bold = False

    pdf.set_font(font_name, size=11)

    # v3.3.0 [C6]: Orijinal PDF'den font bilgisi çıkar (varsa)
    original_body_size = 11  # Varsayılan
    try:
        import fitz  # PyMuPDF
        if original_content:
            orig_doc = fitz.open(stream=original_content, filetype="pdf")
            font_sizes = []
            # İlk 5 sayfa (performans) üzerinden font boyutlarını topla
            for page_num in range(min(5, len(orig_doc))):
                page = orig_doc[page_num]
                blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE).get("blocks", [])
                for block in blocks:
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            fs = span.get("size", 0)
                            text = span.get("text", "").strip()
                            if 8 <= fs <= 14 and len(text) > 20:
                                font_sizes.append(round(fs, 1))
            orig_doc.close()
            if font_sizes:
                # En sık kullanılan font boyutu = body text boyutu
                from collections import Counter
                original_body_size = Counter(font_sizes).most_common(1)[0][0]
                log_system_event("INFO", f"[C6] Orijinal PDF body font size: {original_body_size}pt", "enhancer")
    except Exception as e:
        log_warning(f"[C6] PDF font tespiti başarısız, varsayılan kullanılıyor: {e}", "enhancer")

    # Tespit edilen font boyutunu body text için kullan
    pdf.set_font(font_name, size=original_body_size)

    # Orijinal görselleri section + paragraf pozisyonuna eşleştir
    section_image_map = map_images_to_sections(sections, original_images)

    def _clean_markdown(text: str) -> str:
        """Markdown formatting'i temizle."""
        # Bold/italic markers
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'__(.+?)__', r'\1', text)
        text = re.sub(r'_(.+?)_', r'\1', text)
        # Inline code
        text = re.sub(r'`(.+?)`', r'\1', text)
        return text.strip()

    def _render_line(line: str):
        """Tek satırı markdown tipine göre render et."""
        stripped = line.strip()
        if not stripped:
            return

        # Heading tespiti: ## veya ### ile başlıyorsa
        if stripped.startswith('### '):
            heading_text = _clean_markdown(stripped[4:])
            if has_bold:
                pdf.set_font(font_name, "B", original_body_size)
            else:
                pdf.set_font(font_name, size=original_body_size)
            pdf.multi_cell(0, 6, heading_text)
            pdf.ln(1)
            pdf.set_font(font_name, size=original_body_size)
        elif stripped.startswith('## '):
            heading_text = _clean_markdown(stripped[3:])
            if has_bold:
                pdf.set_font(font_name, "B", original_body_size + 1)
            else:
                pdf.set_font(font_name, size=original_body_size + 1)
            pdf.multi_cell(0, 7, heading_text)
            pdf.ln(2)
            pdf.set_font(font_name, size=original_body_size)
        elif stripped.startswith('# '):
            heading_text = _clean_markdown(stripped[2:])
            if has_bold:
                pdf.set_font(font_name, "B", original_body_size + 3)
            else:
                pdf.set_font(font_name, size=original_body_size + 3)
            pdf.multi_cell(0, 8, heading_text)
            pdf.ln(3)
            pdf.set_font(font_name, size=original_body_size)
        elif stripped.startswith(('- ', '* ', '• ')):
            bullet_text = _clean_markdown(stripped[2:])
            pdf.multi_cell(0, 6, f"  •  {bullet_text}")
            pdf.ln(1)
        elif re.match(r'^\d+[\.\\)]\s', stripped):
            clean = _clean_markdown(stripped)
            pdf.multi_cell(0, 6, f"  {clean}")
            pdf.ln(1)
        elif stripped.startswith('---') or stripped.startswith('==='):
            pdf.ln(3)
        else:
            clean = _clean_markdown(stripped)
            pdf.multi_cell(0, 6, clean)
            pdf.ln(2)

    def _add_image_to_pdf(img_obj):
        """Tek bir görseli PDF'e ekle."""
        try:
            from PIL import Image as PILImage
            img_data = getattr(img_obj, "image_data", None)
            if not img_data:
                return

            # PIL ile aç ve geçici dosyaya kaydet (fpdf2 bytes desteklemez)
            pil_img = PILImage.open(io.BytesIO(img_data))
            if pil_img.mode in ("RGBA", "P"):
                pil_img = pil_img.convert("RGB")

            # Boyut hesapla: sayfa genişliğine sığdır (max 170mm)
            img_w, img_h = pil_img.size
            max_width_mm = 170  # A4 page width - margins

            # DPI hesabı: varsayılan 96 DPI
            w_mm = (img_w / 96.0) * 25.4
            h_mm = (img_h / 96.0) * 25.4

            # Ölçekle
            if w_mm > max_width_mm:
                scale = max_width_mm / w_mm
                w_mm = max_width_mm
                h_mm *= scale

            # Sayfa taşması kontrolü
            available_h = pdf.h - pdf.get_y() - pdf.b_margin - 5
            if h_mm > available_h:
                pdf.add_page()

            # Geçici dosyaya kaydet
            temp_img_path = tempfile.mktemp(suffix=".png")
            pil_img.save(temp_img_path, format="PNG")

            try:
                pdf.image(temp_img_path, x=20, w=w_mm, h=h_mm)
                pdf.ln(4)
            finally:
                # Geçici dosyayı sil
                try:
                    os.remove(temp_img_path)
                except OSError:
                    pass

        except Exception as e:
            log_warning(f"PDF görsel ekleme hatası: {e}", "enhancer")

    for section in sections:
        heading_text = section.heading or f"Bölüm {section.section_index + 1}"
        # Heading'deki markdown prefix'lerini temizle
        heading_text = re.sub(r'^#{1,6}\s+', '', heading_text).strip()
        heading_text = _clean_markdown(heading_text)

        # Section başlığı
        if has_bold:
            pdf.set_font(font_name, "B", original_body_size + 3)
        else:
            pdf.set_font(font_name, size=original_body_size + 3)
        pdf.cell(0, 10, heading_text, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        # İçerik — görselleri paragraflar arasına yerleştir
        text = get_section_text(section)
        lines = [l for l in (text or "").split("\n")]
        visible_lines = [l for l in lines if l.strip()]
        sec_imgs = section_image_map.get(section.section_index, [])

        # Görselleri satır pozisyonlarına organize et
        imgs_at_line = organize_images_at_positions(sec_imgs, len(visible_lines))

        # Satırları ve görselleri sıralı render et
        visible_idx = 0
        if text:
            pdf.set_font(font_name, size=original_body_size)
            for paragraph_text in lines:
                _render_line(paragraph_text)
                if paragraph_text.strip():
                    # Bu satırdan sonra eklenecek görseller var mı?
                    for img_obj in imgs_at_line.get(visible_idx, []):
                        pdf.ln(2)
                        _add_image_to_pdf(img_obj)
                    visible_idx += 1

        # Section sonuna eklenmesi gereken görseller (pozisyonsuz)
        for img_obj in imgs_at_line.get(len(visible_lines), []):
            pdf.ln(2)
            _add_image_to_pdf(img_obj)

        pdf.ln(4)

    # Geçici dosyaya kaydet
    temp_pdf_path = tempfile.mktemp(suffix=".pdf", prefix=f"enhanced_{session_id}_")
    pdf.output(temp_pdf_path)

    return temp_pdf_path
