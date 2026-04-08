"""
VYRA L1 Support API - Response Formatting Helpers
==================================================
RAG sonuçlarını formatlama, chunk parsing ve UI rendering.

Refactored from dialog_service.py (v2.29.14)
"""

from __future__ import annotations

import re
from typing import List, Dict, Any, Tuple, Optional
from urllib.parse import quote as url_quote

from app.core.db import get_db_context



# =============================================================================
# RESPONSE BUILDING
# =============================================================================

def build_response(
    rag_results: List[Dict[str, Any]], 
    ocr_text: str,
    user_id: int = None,
    original_query: str = None
) -> Tuple[str, Dict[str, Any], Optional[Dict[str, Any]]]:
    """
    RAG sonuçlarına göre yanıt içeriği, metadata ve quick_reply oluşturur.
    
    v2.24.5: Yetkili doküman yoksa Corpix fallback mesajı gösterir.
    
    Returns:
        (assistant_content, assistant_metadata, quick_reply)
    """
    quick_reply = None
    assistant_metadata = {"rag_results": []}
    
    if not rag_results:
        # Sonuç yok - Yetkili doküman var mı kontrol et
        has_docs = True  # Default: True (eski davranış)
        if user_id is not None:
            has_docs = check_user_has_accessible_documents(user_id)
        
        if not has_docs:
            # v2.24.5: Yetkili doküman yok - Corpix fallback
            assistant_content = (
                "📭 **Yetkiniz dahilinde sistemde ekli doküman yok.**\n\n"
                "Bilgi tabanında arama yapılamadı çünkü henüz size tanımlı doküman bulunmuyor.\n\n"
                "Corpix'e sormak ister misiniz? 🤖"
            )
            quick_reply = {
                "type": "corpix_fallback",
                "options": [
                    {"id": "yes_corpix", "label": "✅ Evet, Corpix'e Sor", "action": "ask_corpix"},
                    {"id": "no_corpix", "label": "❌ Hayır", "action": "no_corpix"}
                ]
            }
            assistant_metadata["corpix_fallback"] = True
            assistant_metadata["original_query"] = original_query
        else:
            # v2.26.0: Doküman var ama sonuç bulunamadı - Corpix sohbet öner
            assistant_content = (
                "🤔 Bu konuda bilgi tabanımda bir kayıt bulamadım.\n\n"
                "Sorununuzu daha detaylı açıklayabilir misiniz? "
                "Veya farklı anahtar kelimeler kullanmayı deneyelim."
            )
            # v2.26.0: Corpix Sohbet butonlarını göster
            quick_reply = {
                "type": "corpix_fallback",
                "options": [
                    {"id": "corpix_mode", "label": "💬 Corpix Sohbete Geç", "action": "switch_corpix"},
                    {"id": "ask_corpix", "label": "🤖 Bu Soruyu Corpix'e Sor", "action": "ask_corpix"}
                ]
            }
            assistant_metadata["corpix_fallback"] = True
            assistant_metadata["original_query"] = original_query
    elif len(rag_results) == 1:
        best_match = rag_results[0]
        assistant_content = format_single_result(best_match)
        assistant_metadata["rag_results"] = [best_match]
        assistant_metadata["match_type"] = "single"
        assistant_metadata["best_score"] = best_match.get("similarity_score", 0)  # v2.49.0
    else:
        # Çoklu potansiyel eşleşme - kullanıcıya sor
        top_matches = rag_results[:15]
        assistant_content = format_multiple_choices(top_matches, ocr_text)
        assistant_metadata["rag_results"] = top_matches
        assistant_metadata["match_type"] = "multiple"
        assistant_metadata["best_score"] = max((m.get("similarity_score", 0) for m in top_matches), default=0)  # v2.49.0
        
        quick_reply = {
            "type": "document_selection",
            "options": [
                {
                    "id": i,
                    "label": get_short_label(match),
                    "chunk_id": match.get("chunk_id"),
                    "file_name": match.get("file_name", "Kaynak"),
                    "file_type": match.get("file_type", "").lower().replace(".", ""),
                    "heading": match.get("heading", ""),
                    "score": int(match.get("similarity_score", 0) * 100),
                    "chunk_preview": (match.get("chunk_text", "")[:200] + "...") if len(match.get("chunk_text", "")) > 200 else match.get("chunk_text", ""),
                    "details": parse_chunk_details(match.get("chunk_text", ""))
                }
                for i, match in enumerate(top_matches)
            ]
        }
    
    # Quick reply'ı metadata'ya ekle (sayfa yenilendiğinde kartlar görünsün)
    if quick_reply:
        assistant_metadata["quick_reply"] = quick_reply
    
    return assistant_content, assistant_metadata, quick_reply


# =============================================================================
# FORMAT HELPERS
# =============================================================================

def format_single_result(match: Dict) -> str:
    """Tek RAG sonucunu formatla."""
    chunk_text = match.get("chunk_text", "")
    file_name = match.get("file_name", "Bilinmeyen Kaynak")
    score = match.get("similarity_score", 0)
    
    encoded_file_name = url_quote(file_name, safe='')
    
    # Chunk metadata'sından görsel referanslarını al
    metadata = match.get("metadata", {})
    if isinstance(metadata, str):
        import json
        try:
            metadata = json.loads(metadata)
        except Exception as e:
            import sys
            print(f"[ResponseBuilder] metadata JSON parse hatası: {e}", file=sys.stderr)
            metadata = {}
    
    image_ids = metadata.get("image_ids", []) if isinstance(metadata, dict) else []
    
    image_section = ""
    if image_ids:
        image_tags = " ".join(
            f'<img class="rag-inline-image" src="/api/rag/images/{img_id}" '
            f'alt="Doküman görseli" data-image-id="{img_id}" loading="lazy" />'
            for img_id in image_ids[:8]  # Max 8 görsel
        )
        image_section = f"\n\n📷 **İlgili Görseller:**\n\n{image_tags}\n"
    
    return (
        f"📚 **Bilgi Tabanından Buldum!**\n\n"
        f"{chunk_text}\n\n"
        f"{image_section}"
        f"---\n"
        f"📁 Kaynak: [{file_name}](/api/rag/download/{encoded_file_name}) 📥\n"
        f"📊 Eşleşme: %{int(score * 100)}\n\n"
        f"---\n"
        f"[FEEDBACK_SECTION]\n"
        f"**Bu bilgi işinize yaradı mı?**\n"
        f"[/FEEDBACK_SECTION]\n\n"
        f"---\n"
        f"Başka bir sorunuz var mı? 👍 👎"
    )


def format_multiple_choices(matches: List[Dict], ocr_text: str = "") -> str:
    """Çoklu RAG sonuçlarını seçim olarak formatla - detaylar kartlarda gösterilir."""
    if ocr_text:
        intro = "📷 Görseldeki metni anladım. Bununla ilgili birkaç kayıt buldum:"
    else:
        intro = "🔍 Vyra birden fazla ilgili kayıt buldu:"
    
    return f"{intro}\n\nHangisi ile ilgili yardım istersiniz?"


def format_confirmed_solution(match: Dict) -> str:
    """Onaylanmış çözümü formatla."""
    chunk_text = match.get("chunk_text", "")
    file_name = match.get("file_name", "Kaynak")
    
    encoded_file_name = url_quote(file_name, safe='')
    
    return (
        f"✅ **Çözüm Bulundu!**\n\n"
        f"{chunk_text}\n\n"
        f"---\n"
        f"📁 Kaynak: [{file_name}](/api/rag/download/{encoded_file_name}) 📥\n\n"
        f"---\n"
        f"[FEEDBACK_SECTION]\n"
        f"**Bu çözüm işinize yaradı mı?**\n"
        f"[/FEEDBACK_SECTION]"
    )


def format_multi_solution(matches: list) -> str:
    """
    Birden fazla RAG sonucunu modern SaaS formatta formatla.
    Her seçim ayrı card tarzında, detaylar okunabilir şekilde gösterilir.
    """
    if not matches:
        return "Seçilen sonuç bulunamadı."
    
    parts = [f"✅ **{len(matches)} Çözüm Seçildi!**\n\n"]
    
    for i, match in enumerate(matches, 1):
        file_name = match.get("file_name", "Kaynak")
        chunk_text = match.get("chunk_text", "")
        heading = match.get("heading", "")
        score = match.get("score", 0) or int(match.get("similarity_score", 0) * 100)
        
        parts.append("---\n\n")
        
        if score > 0:
            parts.append(f"**🎯 Eşleşme:** %{score}\n\n")
        
        encoded_file_name = url_quote(file_name, safe='')
        parts.append(f"### 📄 {i}. [{file_name}](/api/rag/download/{encoded_file_name}) 📥\n\n")
        
        if heading and heading.strip():
            parts.append(f"**📑 Bölüm:** {heading}\n\n")
        
        if chunk_text and chunk_text.strip():
            parts.append(f"{chunk_text}\n\n")
    
    parts.append(
        "---\n\n"
        "[FEEDBACK_SECTION]\n"
        "**Bu çözümler işinize yaradı mı?** 👍 👎\n"
        "[/FEEDBACK_SECTION]\n\n"
        "---\n"
        "Başka bir sorunuz var mı?"
    )
    
    return "".join(parts)


def get_short_label(match: Dict) -> str:
    """Kısa etiket oluştur."""
    file_name = match.get("file_name", "Kaynak")
    return file_name[:30] + "..." if len(file_name) > 30 else file_name


def parse_chunk_details(chunk_text: str) -> Dict[str, str]:
    """
    Chunk text'ten detay bilgileri parse et.
    Excel chunk formatı: **Header:** Değer şeklinde.
    Çok satırlı değerler (dosya yolları vb.) için satırları birleştirir.
    """
    details = {}
    
    if not chunk_text:
        return details
    
    # Bilinen alan adları ve eşleştirmeleri
    field_mappings = {
        "uygulama adı": "uygulama_adi",
        "uygulama adi": "uygulama_adi",
        "keyflow search": "keyflow_search",
        "keyflow": "keyflow_search",
        "talep tipi": "talep_tipi",
        "rol seçimi": "rol_secimi",
        "rol adı": "rol_secimi",
        "yetki adı": "rol_secimi",
        "rol seçimi/rol adı/yetki adı": "rol_secimi",
        "yetki hakkında bilgi": "yetki_bilgisi",
        "yetki bilgisi": "yetki_bilgisi",
        "açıklama": "aciklama",
        "description": "aciklama",
    }
    
    # Satır bazlı parse - çok satırlı değerleri destekle
    lines = chunk_text.split('\n')
    current_field = None
    current_value = []
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        
        # **Header:** Değer formatı
        md_match = re.match(r'^\*\*([^:*]+):\*\*\s*(.*)?$', stripped)
        if md_match:
            # Önceki alanı kaydet
            if current_field and current_value:
                details[current_field] = ' '.join(current_value).strip()
            
            header = md_match.group(1).strip().lower()
            value = md_match.group(2) or ""
            
            # Eşleştirme bul
            current_field = None
            for key, field in field_mappings.items():
                if key in header:
                    current_field = field
                    break
            
            if not current_field:
                current_field = header.replace(" ", "_").replace("/", "_")
            
            current_value = [value.strip()] if value.strip() else []
            continue
        
        # Basit "Header: Değer" formatı (markdown olmadan)
        simple_match = re.match(r'^([^:]+):\s*(.+)?$', stripped)
        if simple_match and len(simple_match.group(1)) < 50:
            # Önceki alanı kaydet
            if current_field and current_value:
                details[current_field] = ' '.join(current_value).strip()
            
            header = simple_match.group(1).strip().lower()
            value = simple_match.group(2) or ""
            
            # Eşleştirme bul
            current_field = None
            for key, field in field_mappings.items():
                if key in header:
                    current_field = field
                    break
            
            if not current_field:
                current_field = header.replace(" ", "_").replace("/", "_")
            
            current_value = [value.strip()] if value.strip() else []
            continue
        
        # Mevcut alana devam eden satır
        if current_field:
            current_value.append(stripped)
    
    # Son alanı kaydet
    if current_field and current_value:
        details[current_field] = ' '.join(current_value).strip()
    
    # Eğer parse edilemezse, ilk 200 karakteri önizleme olarak ver
    if not details and chunk_text:
        details["onizleme"] = chunk_text[:200] + ("..." if len(chunk_text) > 200 else "")
    
    return details


def create_error_response(dialog_id: int, error_msg: str) -> Dict[str, Any]:
    """Hata yanıtı oluştur."""
    from datetime import datetime
    from app.services.dialog.messages import add_message
    
    content = f"⚠️ {error_msg}"
    msg_id = add_message(dialog_id, "assistant", content, "text")
    return {
        "id": msg_id,
        "role": "assistant",
        "content": content,
        "content_type": "text",
        "created_at": datetime.now().isoformat()
    }


# =============================================================================
# DOCUMENT ACCESS CHECK
# =============================================================================

def check_user_has_accessible_documents(user_id: int) -> bool:
    """
    v2.24.5: Kullanıcının yetkili olduğu en az bir doküman var mı kontrol et.
    
    Returns:
        True: Kullanıcının erişebileceği en az 1 doküman var
        False: Kullanıcının hiç yetkili dokümanı yok
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        
        # Kullanıcının aktif org_id'lerini al
        cur.execute("""
            SELECT uo.org_id 
            FROM user_organizations uo
            JOIN organization_groups o ON uo.org_id = o.id
            JOIN users u ON uo.user_id = u.id
            WHERE uo.user_id = %s 
              AND o.is_active = true
              AND u.is_approved = true
        """, (user_id,))
        user_org_rows = cur.fetchall()
        user_org_ids = [row['org_id'] for row in user_org_rows]
        
        if not user_org_ids:
            cur.execute("""
                SELECT COUNT(*) as cnt FROM uploaded_files uf
                LEFT JOIN document_organizations doc_org ON uf.id = doc_org.file_id
                WHERE doc_org.file_id IS NULL
            """)
            row = cur.fetchone()
            return row["cnt"] > 0
        
        # Yetkili org'lara ait VEYA legacy dosyaları say
        placeholders = ','.join(['%s'] * len(user_org_ids))
        cur.execute(f"""
            SELECT COUNT(*) as cnt FROM uploaded_files uf
            WHERE EXISTS (
                SELECT 1 FROM document_organizations doc_org
                JOIN organization_groups o ON doc_org.org_id = o.id
                WHERE doc_org.file_id = uf.id
                AND doc_org.org_id IN ({placeholders})
                AND o.is_active = true
            )
            OR NOT EXISTS (
                SELECT 1 FROM document_organizations doc_org2
                WHERE doc_org2.file_id = uf.id
            )
        """, user_org_ids)
        row = cur.fetchone()
        return row["cnt"] > 0
