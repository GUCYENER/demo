"""
VYRA L1 Support API - Dialog Processor (Orchestrator)
======================================================
Kullanıcı mesajı işleme, RAG arama ve Quick Reply akış orkestrasyonu.

Refactored from dialog_service.py (v2.29.14)
"""

from __future__ import annotations

import time
import traceback
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple

from app.services.rag_service import get_rag_service
from app.services.ocr_service import get_ocr_service
from app.services.logging_service import log_system_event, log_error

from app.services.dialog.messages import (
    add_message,
    update_message_metadata,
    get_last_assistant_with_quick_reply,
    get_message_by_id,
    find_rag_results_in_history,
    get_original_query,
)
from app.services.dialog.response_builder import (
    build_response,
    format_confirmed_solution,
    format_multi_solution,
    create_error_response,
)
from app.services.dialog.ai_evaluation import evaluate_with_llm
from app.services.dialog.crud import close_dialog


# =============================================================================
# HEADING-BASED IMAGE INSERTION HELPER
# =============================================================================

def _insert_images_by_heading(
    content: str, heading_images: Dict[str, List[int]]
) -> str:
    """
    LLM sentez yanıtındaki başlıkları heading_images mapping ile eşleyip
    görselleri ilgili başlığın paragraflarından sonra yerleştirir.
    
    Eşleşme mantığı: heading_images key'leri normalize edilerek
    sentez yanıtındaki başlıklarla fuzzy karşılaştırılır.
    Eşleşmeyen görseller yanıt sonuna eklenir.
    """
    import re
    
    if not heading_images:
        return content
    
    def _make_image_tags(img_ids: List[int]) -> str:
        tags = " ".join(
            f'<img class="rag-inline-image" src="/api/rag/images/{img_id}" '
            f'alt="Doküman görseli" data-image-id="{img_id}" />'
            for img_id in img_ids[:4]  # Her başlık altında max 4 görsel
        )
        return f"\n\n📷 **İlgili Görseller:**\n\n{tags}\n"
    
    def _normalize(text: str) -> str:
        """Başlık metnini karşılaştırma için normalize et"""
        text = re.sub(r'[*#•\-–—]+', '', text)  # Markdown ve bullet temizle
        text = re.sub(r'\s+', ' ', text).strip().lower()
        # Türkçe karakter normalize
        text = text.replace('ı', 'i').replace('ö', 'o').replace('ü', 'u')
        text = text.replace('ş', 's').replace('ç', 'c').replace('ğ', 'g')
        return text
    
    # heading_images key'lerini normalize et
    normalized_map = {}
    for heading, img_ids in heading_images.items():
        if heading == "__no_heading__":
            continue
        norm_key = _normalize(heading)
        if norm_key:
            normalized_map[norm_key] = img_ids
    
    if not normalized_map:
        # Sadece __no_heading__ görseller var — sona ekle
        all_ids = []
        for ids in heading_images.values():
            all_ids.extend(ids)
        if all_ids:
            content += _make_image_tags(all_ids[:8])
        return content
    
    # Yanıtı satır satır tara ve heading'leri bul
    lines = content.split('\n')
    result_lines = []
    matched_headings = set()
    
    i = 0
    while i < len(lines):
        line = lines[i]
        result_lines.append(line)
        
        # Bu satır bir heading mi? (** bold **, ### markdown header, veya emoji prefix)
        stripped = line.strip()
        norm_line = _normalize(stripped)
        
        # Heading eşleşme: sadece Markdown heading formatındaki satırlarda
        is_heading_line = (
            stripped.startswith('**') or 
            stripped.startswith('#') or 
            stripped.startswith('📌') or 
            stripped.startswith('📋') or
            stripped.startswith('🔹') or
            stripped.startswith('▶')
        )
        
        if norm_line and len(norm_line) > 5 and is_heading_line:
            # heading_images'deki key'lerle fuzzy eşleştir
            best_match = None
            for norm_heading, img_ids in normalized_map.items():
                if norm_heading in matched_headings:
                    continue
                # Minimum uzunluk kontrolü (false positive önleme)
                if len(norm_heading) < 5:
                    continue
                # Substring eşleşme (her iki yönde)
                if norm_heading in norm_line or norm_line in norm_heading:
                    best_match = (norm_heading, img_ids)
                    break
                # İlk 3+ kelime eşleşme
                h_words = norm_heading.split()[:3]
                l_words = norm_line.split()[:3]
                if len(h_words) >= 2 and h_words == l_words:
                    best_match = (norm_heading, img_ids)
                    break
            
            if best_match:
                norm_heading, img_ids = best_match
                matched_headings.add(norm_heading)
                
                # Bu heading'in paragraflarını topla (sonraki heading'e kadar)
                i += 1
                while i < len(lines):
                    next_stripped = lines[i].strip()
                    
                    # Yeni bir markdown heading mi?
                    is_next_heading = (
                        next_stripped.startswith('**') or 
                        next_stripped.startswith('#') or
                        next_stripped.startswith('📌') or
                        next_stripped.startswith('📋') or
                        next_stripped.startswith('🔹') or
                        next_stripped.startswith('▶')
                    )
                    
                    if is_next_heading:
                        next_norm = _normalize(next_stripped)
                        if next_norm and len(next_norm) > 5:
                            # Bu, eşleşme listesindeki bir heading mi?
                            for nh in normalized_map:
                                if nh not in matched_headings and (nh in next_norm or next_norm in nh):
                                    break  # Evet, yeni bölüm
                            else:
                                # Eşleşme listesinde değil, devam et
                                result_lines.append(lines[i])
                                i += 1
                                continue
                            break  # Yeni heading bulundu
                    
                    result_lines.append(lines[i])
                    i += 1
                
                # Görselleri bu bölümün sonuna ekle
                result_lines.append(_make_image_tags(img_ids))
                continue  # i zaten artırıldı
        
        i += 1
    
    # Eşleşmeyen görselleri sona ekle
    unmatched_ids = []
    for norm_heading, img_ids in normalized_map.items():
        if norm_heading not in matched_headings:
            unmatched_ids.extend(img_ids)
    # __no_heading__ görselleri de ekle
    if "__no_heading__" in heading_images:
        unmatched_ids.extend(heading_images["__no_heading__"])
    
    if unmatched_ids:
        result_lines.append(_make_image_tags(unmatched_ids[:8]))
    
    return '\n'.join(result_lines)


# =============================================================================
# RAG SEARCH & OCR
# =============================================================================

def perform_rag_search(query: str, user_id: int, n_results: int = 10) -> List[Dict[str, Any]]:
    """
    RAG araması yapar ve sonuçları dict listesi olarak döndürür.
    
    🛡️ Güvenli: Hata durumunda boş liste döner ama kritik hatalar loglanır.
    """
    rag_service = get_rag_service()
    
    try:
        rag_response = rag_service.search(
            query=query,
            n_results=n_results,
            user_id=user_id
        )
        
        if not rag_response or not rag_response.results:
            log_system_event(
                "DEBUG", 
                f"RAG arama: '{query[:50]}...' - Sonuç bulunamadı (user_id={user_id})",
                "dialog", 
                user_id
            )
            return []
        
        # SearchResult objelerini dict'e çevir
        results = []
        for r in rag_response.results:
            metadata = r.metadata or {}
            results.append({
                "chunk_id": r.chunk_id,
                "chunk_text": r.content,
                "file_name": r.source_file,
                "similarity_score": r.score,
                "file_type": metadata.get("file_type", ""),
                "heading": metadata.get("heading", ""),
                "metadata": metadata
            })
        
        log_system_event(
            "DEBUG", 
            f"RAG arama: '{query[:50]}...' - {len(results)} sonuç, "
            f"ilk_skor={results[0]['similarity_score']:.3f} (user_id={user_id})",
            "dialog", 
            user_id
        )
        
        return results
        
    except Exception as e:
        error_traceback = traceback.format_exc()
        log_error(
            f"RAG arama kritik hatası: {str(e)}", 
            "dialog",
            error_detail=f"Query: {query[:100]}, User: {user_id}\n{error_traceback}"
        )
        return []


def extract_ocr_texts(images: List[bytes]) -> Tuple[str, List[str], Dict[str, str]]:
    """
    Görsellerden OCR ile metin çıkarır.
    
    Returns:
        (formatted_ocr_text, raw_ocr_texts, metadata_dict)
    """
    if not images:
        return "", [], {}
    
    ocr_service = get_ocr_service()
    ocr_text = ""
    raw_texts = []
    metadata = {}
    
    for i, img_bytes in enumerate(images):
        try:
            extracted = ocr_service.extract_text_from_image_bytes(img_bytes)
            if extracted:
                ocr_text += f"\n[Görsel {i+1}]: {extracted}"
                raw_texts.append(extracted)
                metadata[f"ocr_{i}"] = extracted
        except Exception as e:
            log_error(f"OCR hatası (görsel {i+1}): {e}", "dialog")
    
    return ocr_text, raw_texts, metadata


# =============================================================================
# MAIN PROCESSING
# =============================================================================

def _process_widget_direct_llm(query: str, widget_config: dict) -> str:
    """
    Widget için RAG'sız direkt LLM çağrısı (use_rag=False durumu).
    Prompt ve LLM override'larını uygular.
    """
    from app.core.llm import (get_active_llm, get_llm_by_id,
                               get_prompt_by_id, call_llm_api,
                               call_llm_api_with_config)

    llm_cfg_id = widget_config.get("llm_config_id")
    prompt_id  = widget_config.get("prompt_id")

    config = get_llm_by_id(llm_cfg_id) if llm_cfg_id else get_active_llm()
    system_prompt = (get_prompt_by_id(prompt_id) if prompt_id
                     else "Sen yardımsever bir müşteri destek asistanısın. Kullanıcıya kısa ve net yanıtlar ver.")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": query},
    ]

    if config:
        return call_llm_api_with_config(messages, config)
    return call_llm_api(messages)


def _process_widget_direct_llm_stream(query: str, widget_config: dict):
    """
    Widget için RAG'sız direkt LLM streaming çağrısı (use_rag=False + stream).
    """
    from app.core.llm import (get_active_llm, get_llm_by_id,
                               get_prompt_by_id, call_llm_api_stream,
                               call_llm_api_stream_with_config)

    llm_cfg_id = widget_config.get("llm_config_id")
    prompt_id  = widget_config.get("prompt_id")

    config = get_llm_by_id(llm_cfg_id) if llm_cfg_id else get_active_llm()
    system_prompt = (get_prompt_by_id(prompt_id) if prompt_id
                     else "Sen yardımsever bir müşteri destek asistanısın. Kullanıcıya kısa ve net yanıtlar ver.")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": query},
    ]

    if config:
        yield from call_llm_api_stream_with_config(messages, config)
    else:
        yield from call_llm_api_stream(messages)


def process_user_message(
    dialog_id: int,
    user_id: int,
    content: str,
    images: List[bytes] = None,
    org_ids: List[int] = None,  # Deprecated - user_id ile org filtering yapılıyor
    use_deep_think: bool = True,  # v2.28.0: Deep Think default ON
    widget_config: dict = None,  # v2.61.0: Widget veri kaynağı override
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """
    Kullanıcı mesajını işle ve AI yanıtı üret.
    
    🔒 GÜVENLİK: Org filtering user_id üzerinden RAG service'de yapılır.
    🧠 v2.28.0: Deep Think - Intent detection + LLM synthesis
    
    Flow:
        1. OCR (görsel varsa)
        2. Kullanıcı mesajını kaydet
        3. Deep Think: Intent → Expanded RAG → LLM Synthesis
        4. Assistant mesajını kaydet
    
    Returns:
        (assistant_message, quick_reply_options)
    """
    timings = {}
    start_total = time.time()
    
    # 1. OCR işlemi
    t0 = time.time()
    ocr_text, raw_ocr_texts, user_metadata = extract_ocr_texts(images)
    timings["ocr"] = time.time() - t0
    
    # 2. Kullanıcı mesajını kaydet
    t0 = time.time()
    add_message(dialog_id, "user", content, "text", user_metadata if user_metadata else None)
    timings["save_user_msg"] = time.time() - t0
    
    # 3. Arama sorgusu hazırla
    search_query = " ".join(raw_ocr_texts) if raw_ocr_texts else content
    
    quick_reply = None
    assistant_metadata = {"rag_results": []}
    
    # 🆕 v2.61.0: Widget RAG-off → direkt LLM çağrısı
    if widget_config and not widget_config.get("use_rag", True):
        t0 = time.time()
        try:
            assistant_content = _process_widget_direct_llm(search_query, widget_config)
            assistant_metadata["widget_direct"] = True
            assistant_metadata["use_rag"] = False
        except Exception as e:
            log_error(f"Widget direkt LLM hatası: {e}", "dialog")
            assistant_content = "Üzgünüm, şu anda yanıt üretemiyorum. Lütfen tekrar deneyin."
        timings["widget_llm"] = time.time() - t0

    # 🧠 v2.28.0: Deep Think Pipeline
    elif use_deep_think:
        t0 = time.time()
        try:
            from app.services.deep_think_service import get_deep_think_service
            
            deep_think = get_deep_think_service()
            result = deep_think.process(search_query, user_id)
            
            timings["deep_think"] = time.time() - t0
            
            # Yanıt oluştur
            assistant_content = result.synthesized_response
            
            # 🆕 v2.37.1: Deep Think sonucundaki görselleri başlık altına yerleştir
            # NOT: getattr kullanılıyor çünkü eski cache entry'lerinde attribute olmayabilir
            _heading_images = getattr(result, 'heading_images', None) or {}
            _image_ids = getattr(result, 'image_ids', None) or []
            
            if _heading_images:
                # Heading bazlı görsel yerleştirme
                assistant_content = _insert_images_by_heading(
                    assistant_content, _heading_images
                )
            elif _image_ids:
                # Fallback: heading bilgisi yoksa eski davranış (sona ekle)
                image_tags = " ".join(
                    f'<img class="rag-inline-image" src="/api/rag/images/{img_id}" '
                    f'alt="Doküman görseli" data-image-id="{img_id}" />'
                    for img_id in _image_ids[:8]
                )
                assistant_content += f"\n\n📷 **İlgili Görseller:**\n\n{image_tags}\n"
            
            # Metadata güncelle
            assistant_metadata["deep_think"] = True
            assistant_metadata["intent"] = result.intent.intent_type.value
            assistant_metadata["rag_result_count"] = result.rag_result_count
            assistant_metadata["sources"] = result.sources
            assistant_metadata["processing_time_ms"] = result.processing_time_ms
            assistant_metadata["best_score"] = getattr(result, 'best_score', 0.0)  # v2.49.0
            if _image_ids:
                assistant_metadata["image_ids"] = _image_ids
            
            log_system_event(
                "INFO", 
                f"🧠 Deep Think: {result.intent.intent_type.value}, "
                f"{result.rag_result_count} sonuç, {result.processing_time_ms:.0f}ms",
                "dialog",
                user_id
            )
            
        except ImportError as e:
            log_system_event("WARNING", f"Deep Think import hatası, legacy fallback: {e}", "dialog")
            assistant_content, assistant_metadata, quick_reply = _legacy_process(
                search_query, user_id, ocr_text, timings
            )
        except Exception as e:
            log_error(f"Deep Think hatası: {e}", "dialog")
            assistant_content, assistant_metadata, quick_reply = _legacy_process(
                search_query, user_id, ocr_text, timings
            )
    else:
        assistant_content, assistant_metadata, quick_reply = _legacy_process(
            search_query, user_id, ocr_text, timings
        )
    
    # 4. Assistant yanıtını kaydet
    t0 = time.time()
    msg_id = add_message(dialog_id, "assistant", assistant_content, "text", assistant_metadata)
    timings["save_assistant_msg"] = time.time() - t0
    
    timings["total"] = time.time() - start_total
    
    # 🔍 Performans logu
    deep_think_time = timings.get("deep_think", timings.get("rag_search", 0))
    log_system_event(
        "DEBUG" if timings["total"] < 5 else "WARNING",
        f"⏱️ Dialog işlem süresi: {timings['total']:.2f}s | "
        f"AI: {deep_think_time:.2f}s | "
        f"OCR: {timings['ocr']:.2f}s | "
        f"DB: {timings['save_user_msg'] + timings['save_assistant_msg']:.2f}s",
        "dialog_perf",
        user_id
    )
    
    assistant_message = {
        "id": msg_id,
        "role": "assistant",
        "content": assistant_content,
        "content_type": "text",
        "metadata": assistant_metadata,
        "created_at": datetime.now().isoformat()
    }
    
    return assistant_message, quick_reply


# =============================================================================
# STREAMING ORCHESTRATOR (v2.50.0)
# =============================================================================

def process_user_message_stream(
    dialog_id: int,
    user_id: int,
    content: str,
    images: Optional[List[bytes]] = None,
    widget_config: dict = None,  # v2.61.0: Widget veri kaynağı override
):
    """
    🆕 v2.50.0: Streaming mesaj işleme orchestrator'ı.
    
    Akış:
    1. Kullanıcı mesajını kaydet
    2. OCR (görsel varsa)
    3. Deep Think streaming pipeline'ını çalıştır
    4. Done event'inde DB'ye kaydet + Quick Reply oluştur
    
    Yields:
        dict: {"type": ..., "data": ...} SSE eventleri
    """
    import json
    
    start_total = time.time()
    
    # 1. Kullanıcı mesajını kaydet
    user_metadata = {}
    if images:
        user_metadata["has_images"] = True
        user_metadata["image_count"] = len(images)
    
    add_message(dialog_id, "user", content, "text", user_metadata if user_metadata else None)
    
    # 2. OCR — görsel varsa metin çıkar
    ocr_text = ""
    if images:
        try:
            ocr_service = get_ocr_service()
            ocr_results = []
            for img_bytes in images:
                text = ocr_service.extract_text(img_bytes)
                if text:
                    ocr_results.append(text)
            if ocr_results:
                ocr_text = "\n".join(ocr_results)
                log_system_event("INFO", f"OCR: {len(ocr_results)} görselden metin çıkarıldı", "dialog", user_id)
        except Exception as e:
            log_error(f"OCR hatası: {e}", "dialog")
    
    # 3. Arama sorgusunu hazırla
    search_query = f"{content}\n{ocr_text}".strip() if ocr_text else content
    
    # 🆕 v2.61.0: Widget RAG-off → direkt LLM streaming
    if widget_config and not widget_config.get("use_rag", True):
        full_response = ""
        try:
            for token in _process_widget_direct_llm_stream(search_query, widget_config):
                full_response += token
                yield {"type": "token", "data": token}
        except Exception as e:
            log_error(f"Widget stream hatası: {e}", "dialog")
            full_response = "Üzgünüm, şu anda yanıt üretemiyorum. Lütfen tekrar deneyin."
            yield {"type": "token", "data": full_response}

        msg_id = add_message(dialog_id, "assistant", full_response, "text",
                             {"widget_direct": True, "use_rag": False})
        yield {"type": "done", "data": {"content": full_response, "message_id": msg_id}}
        return

    # 4. Deep Think Streaming Pipeline
    # 🆕 v2.53.1: Kısa/anlamsız sorgu koruması (Deep Think'e gitmeden ÖNCE)
    _sq = search_query.strip().rstrip('.?!,;:')
    _sq_words = [w for w in _sq.split() if len(w) >= 2]
    _sq_total = sum(len(w) for w in _sq_words)
    # Kesik kelime kontrolü: "bilg.", "yet." gibi
    _sq_orig_words = search_query.strip().split()
    _sq_truncated = any(
        w.endswith('.') and 2 <= len(w.rstrip('.?!,;:')) <= 5 and w.rstrip('.?!,;:').isalpha()
        and w.rstrip('.?!,;:').lower() not in {'vb', 'vs', 'dr', 'mr', 'ms', 'st', 'ave', 'inc'}
        for w in _sq_orig_words
    )
    _is_meaningless = len(_sq_words) < 2 or _sq_total < 10 or _sq_truncated
    
    if _is_meaningless:
        log_system_event("INFO", f"Dialog: Kısa/anlamsız sorgu reddedildi: '{search_query}'", "dialog", user_id)
        _no_result_msg = (
            "🤔 Bu konuda bilgi tabanında ilgili bir kayıt bulunamadı.\n\n"
            "Farklı anahtar kelimeler kullanarak tekrar deneyebilir veya "
            "Vyra ile sohbet modunda sorabilirsiniz."
        )
        msg_id = add_message(dialog_id, "assistant", _no_result_msg, "text",
                             {"deep_think": True, "short_query_rejected": True, "rag_result_count": 0})
        yield {"type": "done", "data": {
            "content": _no_result_msg,
            "message_id": msg_id,
            "metadata": {"rag_result_count": 0, "best_score": 0, "deep_think": True, "short_query_rejected": True}
        }}
        return
    
    try:
        from app.services.deep_think_service import get_deep_think_service
        deep_think = get_deep_think_service()
        
        final_content = None
        final_metadata = None
        
        for event in deep_think.process_stream(search_query, user_id):
            event_type = event.get("type")
            
            if event_type == "cached":
                # Cache hit — tam yanıtı al ve DB'ye kaydet
                data = event["data"]
                final_content = data["content"]
                final_metadata = {
                    "deep_think": True,
                    "intent": data.get("intent"),
                    "sources": data.get("sources", []),
                    "best_score": data.get("best_score", 0),
                    "rag_result_count": data.get("rag_result_count", 0),
                    "image_ids": data.get("image_ids", []),
                    "heading_images": data.get("heading_images", {}),
                    "cached": True
                }
                yield event
                
            elif event_type == "done":
                # Stream tamamlandı — final içeriği al
                data = event["data"]
                final_content = data.get("content", "")
                final_metadata = data.get("metadata", {"deep_think": True})
                
                # v3.3.2: Görselleri cevap metnine yerleştir (learned QA dahil)
                _h_images = final_metadata.get("heading_images", {})
                _i_ids = final_metadata.get("image_ids", [])
                if _h_images:
                    final_content = _insert_images_by_heading(final_content, _h_images)
                    data["content"] = final_content
                elif _i_ids:
                    img_tags = " ".join(
                        f'<img class="rag-inline-image" src="/api/rag/images/{img_id}" '
                        f'alt="Doküman görseli" data-image-id="{img_id}" />'
                        for img_id in _i_ids[:8]
                    )
                    final_content += f"\n\n📷 **İlgili Görseller:**\n\n{img_tags}\n"
                    data["content"] = final_content
                
                yield event
                
            else:
                # rag_complete, token, status — frontend'e aktar
                yield event
        
        # 5. DB'ye kaydet
        if final_content is not None:
            # Quick Reply oluştur
            quick_reply = None
            try:
                from app.services.dialog.response_builder import build_quick_reply_from_deep_think
                quick_reply = build_quick_reply_from_deep_think(final_metadata)
            except (ImportError, Exception):
                pass
            
            msg_id = add_message(dialog_id, "assistant", final_content, "text", final_metadata)
            
            elapsed = time.time() - start_total
            log_system_event(
                "INFO",
                f"⏱️ Streaming toplam: {elapsed:.2f}s | dialog #{dialog_id}",
                "dialog_perf",
                user_id
            )
            
            # Final DB kaydı event'ini gönder
            yield {"type": "saved", "data": {
                "message_id": msg_id,
                "quick_reply": quick_reply,
                "total_time": round(elapsed, 2)
            }}
    
    except Exception as e:
        log_error(f"Streaming orchestrator hatası: {e}", "dialog")
        yield {"type": "error", "data": str(e)}


def _legacy_process(
    search_query: str,
    user_id: int,
    ocr_text: str,
    timings: dict
) -> Tuple[str, Dict[str, Any], Optional[Dict[str, Any]]]:
    """
    Legacy RAG işleme akışı (Deep Think kapalıysa veya hata durumunda).
    """
    t0 = time.time()
    rag_results = perform_rag_search(
        query=search_query,
        user_id=user_id,
        n_results=10
    )
    timings["rag_search"] = time.time() - t0
    
    t0 = time.time()
    assistant_content, assistant_metadata, quick_reply = build_response(
        rag_results, ocr_text, user_id, search_query
    )
    timings["build_response"] = time.time() - t0
    
    return assistant_content, assistant_metadata, quick_reply


# =============================================================================
# QUICK REPLY PROCESSING
# =============================================================================

def process_quick_reply(
    dialog_id: int,
    user_id: int,
    action: str,
    selection_id: int = None,
    selection_ids: list = None,
    message_id: int = None
) -> Dict[str, Any]:
    """
    Hızlı yanıt işle (Evet/Hayır veya doküman seçimi).
    
    🔒 GÜVENLİK: message_id verilirse direkt o mesajı alır (daha güvenilir).
    """
    last_assistant = None
    
    # message_id varsa direkt o mesajı al
    if message_id:
        last_assistant = get_message_by_id(message_id)
    
    # Yoksa fallback: son quick_reply içeren mesajı ara
    if not last_assistant:
        last_assistant = get_last_assistant_with_quick_reply(dialog_id)
    
    if not last_assistant:
        return create_error_response(dialog_id, "Önceki mesaj bulunamadı.")
    
    metadata = last_assistant.get("metadata") or {}
    rag_results = metadata.get("rag_results", [])
    
    # Default user_content
    user_content = f"[Quick Reply: {action}]"
    
    if action == "yes":
        if rag_results:
            best = rag_results[0]
            content = format_confirmed_solution(best)
        else:
            content = "✅ Harika! Başka bir sorunuz var mı?"
        user_content = "👍 Evet, bu çözüm işime yaradı"
        
    elif action == "no":
        content = (
            "❌ Anladım, bu çözüm işe yaramadı.\n\n"
            "Sorununuzu farklı şekilde tarif edebilir misiniz? "
            "Veya bir ekran görüntüsü paylaşabilirsiniz."
        )
        user_content = "👎 Hayır, farklı bir çözüm istiyorum"
    
    elif action == "yes_more":
        content = (
            "🎉 Harika! Yeni sorunuzu yazabilirsiniz.\n\n"
            "Size yardımcı olmak için buradayım!"
        )
        user_content = "👍 Evet, başka sorum var"
        if last_assistant.get("id"):
            try:
                quick_reply = metadata.get("quick_reply", {})
                quick_reply["answered"] = True
                update_message_metadata(last_assistant["id"], "quick_reply", quick_reply)
            except Exception as e:
                log_error(f"Metadata güncellenemedi: {e}", "dialog")
        
    elif action == "no_more":
        close_dialog(dialog_id, user_id)
        content = (
            "✅ Tamamdır! Bu çözüm işinize yaradı ise, yukarıdaki "
            "\"Bu çözüm işinize yaradı mı?\" alanında 👍 like yaparsanız çok sevinirim! 😊\n\n"
            "Geri bildiriminiz bizi geliştirir. İyi günler dilerim!"
        )
        user_content = "👋 Hayır, teşekkürler"
        if last_assistant.get("id"):
            try:
                quick_reply = metadata.get("quick_reply", {})
                quick_reply["answered"] = True
                update_message_metadata(last_assistant["id"], "quick_reply", quick_reply)
            except Exception as e:
                log_error(f"Metadata güncellenemedi: {e}", "dialog")
    
    elif action == "not_interested":
        content = (
            "🆗 Anladım, bu seçenekler ilginizi çekmedi.\n\n"
            "Farklı bir soru sorabilirsiniz, size yardımcı olmaya devam edeceğim! 💬"
        )
        user_content = "⏭️ Bu seçenekler ilgimi çekmiyor, farklı bir soru sormak istiyorum"
        
    elif action == "select" and selection_id is not None:
        if selection_id < len(rag_results):
            selected = rag_results[selection_id]
            content = format_confirmed_solution(selected)
            selected_label = selected.get("file_name", f"Seçenek {selection_id + 1}")
            user_content = f'✅ "{selected_label}" seçeneği ile devam ediyorum'
            
            if last_assistant.get("id"):
                try:
                    quick_reply = metadata.get("quick_reply", {})
                    quick_reply["selected_option_id"] = selection_id
                    update_message_metadata(last_assistant["id"], "quick_reply", quick_reply)
                except Exception as e:
                    log_error(f"Metadata güncellenemedi: {e}", "dialog")
        else:
            content = "Geçersiz seçim. Lütfen tekrar deneyin."
            user_content = f"[Geçersiz seçim: {selection_id}]"
    
    elif action == "multi_select" and selection_ids:
        valid_selections = [sid for sid in selection_ids if sid < len(rag_results)]
        
        if valid_selections:
            selected_results = [rag_results[sid] for sid in valid_selections]
            
            if len(selected_results) == 1:
                content = format_confirmed_solution(selected_results[0])
                selected_label = selected_results[0].get("file_name", "Seçenek 1")
                user_content = f'✅ "{selected_label}" seçeneği ile devam ediyorum'
            else:
                content = format_multi_solution(selected_results)
                selected_labels = [r.get("file_name", f"Seçenek {i+1}") for i, r in enumerate(selected_results)]
                user_content = f'✅ {len(selected_results)} seçenek seçtim: {", ".join(selected_labels)}'
            
            if last_assistant.get("id"):
                try:
                    quick_reply = metadata.get("quick_reply", {})
                    quick_reply["selected_option_ids"] = valid_selections
                    update_message_metadata(last_assistant["id"], "quick_reply", quick_reply)
                except Exception as e:
                    log_error(f"Metadata güncellenemedi: {e}", "dialog")
        else:
            content = "Geçersiz seçim. Lütfen tekrar deneyin."
            user_content = "[Geçersiz çoklu seçim]"
    
    elif action == "ai_evaluate":
        eval_rag_results = rag_results
        if not eval_rag_results:
            eval_rag_results = find_rag_results_in_history(dialog_id)
        
        if eval_rag_results:
            original_query = get_original_query(dialog_id)
            content = evaluate_with_llm(original_query, eval_rag_results)
            user_content = "🤖 AI ile tüm sonuçları değerlendir"
            
            if last_assistant.get("id"):
                try:
                    quick_reply = metadata.get("quick_reply", {})
                    quick_reply["ai_evaluated"] = True
                    update_message_metadata(last_assistant["id"], "quick_reply", quick_reply)
                except Exception as e:
                    log_error(f"Metadata güncellenemedi: {e}", "dialog")
        else:
            content = "❌ Değerlendirilecek sonuç bulunamadı."
            user_content = "🤖 AI değerlendirmesi istendi (sonuç yok)"
    
    else:
        content = "Anlamadım. Lütfen sorununuzu tekrar açıklayın."
    
    # Yanıtı kaydet
    add_message(dialog_id, "user", user_content, "quick_reply")
    msg_id = add_message(dialog_id, "assistant", content, "text")
    
    return {
        "id": msg_id,
        "role": "assistant",
        "content": content,
        "content_type": "text",
        "created_at": datetime.now().isoformat()
    }
