"""
VYRA L1 Support API - Image Helpers
=======================================
Görselleri bölümlere eşleştirme ve pozisyon hesaplama yardımcıları.
Tüm output generator'lar tarafından ortaklaşa kullanılır.

Author: VYRA AI Team
Version: 1.0.0 (v3.3.3)
"""

from typing import Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.document_enhancer import EnhancedSection


def get_section_text(section: 'EnhancedSection') -> str:
    """
    Section'dan render edilecek metni döndürür.

    Kural: change_type "no_change" ise orijinal metin,
    aksi halde iyileştirilmiş metin kullanılır.

    Returns:
        Boş string-safe metin (asla None dönmez)
    """
    if section.change_type != "no_change" and section.enhanced_text:
        return section.enhanced_text
    return section.original_text or ""


def map_images_to_sections(
    sections: List['EnhancedSection'],
    original_images: list
) -> Dict[int, List[tuple]]:
    """
    Orijinal görselleri section'lara eşleştirir ve bölüm içi
    paragraf-relative pozisyonlarını hesaplar.

    Eşleştirme stratejisi (öncelik sırasıyla):
      1. Heading bazlı — görselin context_heading'i section heading'iyle eşleştirilir
      2. chunk_index bazlı — görselin sayfa/chunk numarası section index'iyle eşleştirilir
      3. Son section'a atama — hiçbir eşleşme bulunamazsa son bölüme eklenir

    Pozisyon hesaplama:
      - paragraph_index ≥ 0 → section'ın satır sayısına göre relative pozisyon
      - paragraph_index = -1 → pozisyon bilinmiyor, section sonuna eklenir

    Returns:
        Dict[section_index, List[(relative_para_pos, img_obj)]]
        Her section'daki görseller pozisyona göre sıralıdır.
    """
    section_image_map: Dict[int, List[tuple]] = {}

    if not original_images:
        return section_image_map

    for img_obj in original_images:
        heading = getattr(img_obj, "context_heading", "") or ""
        chunk_idx = getattr(img_obj, "context_chunk_index", 0)
        para_idx = getattr(img_obj, "paragraph_index", -1)

        # ── 1. Heading bazlı section eşleştirmesi ──
        best_section = None
        for sec in sections:
            sec_heading = sec.heading or ""
            if heading and (heading in sec_heading or sec_heading in heading):
                best_section = sec
                break

        # ── 2. chunk_index ile section eşleştirmesi (fallback) ──
        if best_section is None:
            if chunk_idx < len(sections):
                best_section = sections[chunk_idx]
            elif sections:
                best_section = sections[-1]

        if best_section is None:
            continue

        sec_idx = best_section.section_index

        # ── 3. Bölüm içi relative pozisyon hesaplama ──
        relative_pos = -1
        if para_idx >= 0:
            text = get_section_text(best_section)
            total_lines = len([l for l in text.split("\n") if l.strip()])

            if total_lines > 0:
                # Global paragraph_index → section-local pozisyona dönüştür
                relative_pos = min(para_idx, total_lines - 1)

                # chunk_index üzerinden önceki section'ların satır sayısını çıkar
                if chunk_idx < len(sections):
                    sec_start_approx = sum(
                        len([l for l in get_section_text(s).split("\n") if l.strip()])
                        for s in sections[:chunk_idx]
                    )
                    relative_pos = max(0, para_idx - sec_start_approx)
                    relative_pos = min(relative_pos, total_lines - 1)

        section_image_map.setdefault(sec_idx, []).append((relative_pos, img_obj))

    # Her section'daki görselleri pozisyona göre sırala
    # (pozisyonsuz görseller → sonuç olarak sonuncu)
    for sec_idx in section_image_map:
        section_image_map[sec_idx].sort(
            key=lambda x: x[0] if x[0] >= 0 else 999999
        )

    return section_image_map


def organize_images_at_positions(
    sec_imgs: List[tuple],
    total_paragraphs: int
) -> Dict[int, list]:
    """
    Bir section'daki görselleri paragraf pozisyonuna göre dict'e organize eder.

    Rendering sırasında her paragraftan sonra bu dict kontrol edilerek
    ilgili görseller doğru konuma eklenir.

    Returns:
        Dict[para_position, [img_obj, ...]]
        Key = paragraf index'i (0-based) → o paragraftan sonra eklenecek görseller
        Key = total_paragraphs → section sonuna eklenecek görseller
    """
    imgs_at_pos: Dict[int, list] = {}

    for rel_pos, img_obj in sec_imgs:
        if rel_pos < 0:
            # Pozisyon bilinmiyor → section sonuna eklenecek
            imgs_at_pos.setdefault(total_paragraphs, []).append(img_obj)
        else:
            # Görseli bu paragraftan sonra ekle (bounds-safe)
            safe_pos = min(rel_pos, max(0, total_paragraphs - 1))
            imgs_at_pos.setdefault(safe_pos, []).append(img_obj)

    return imgs_at_pos
