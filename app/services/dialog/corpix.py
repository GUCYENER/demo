"""
VYRA L1 Support API - Corpix Fallback & Ticket Summary
=======================================================
Corpix L1 Destek ve IT çağrı özeti üretimi.

Refactored from dialog_service.py (v2.29.14)
"""

from __future__ import annotations

from app.services.logging_service import log_error, log_system_event


def ask_corpix(query: str, user_id: int) -> str:
    """
    v2.26.0: Corpix L1 Destek Görevlisi olarak LLM'e sor.
    
    DB'deki 'corpix_l1' kategorisindeki aktif prompt'u kullanır.
    Kurumsal, profesyonel, kibar ve özet cevap üretir.
    
    Args:
        query: Kullanıcı sorusu
        user_id: Kullanıcı ID (log için)
        
    Returns:
        LLM yanıtı (formatlanmış)
    """
    from app.core.llm import (
        LLMConfigError,
        LLMConnectionError,
        call_llm_api,
        get_prompt_by_category,
    )
    
    # v2.26.0: DB'den corpix_l1 kategorisindeki aktif prompt'u al
    system_prompt = get_prompt_by_category("corpix_l1")

    user_message = f"KULLANICI SORUSU: {query}"
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]
    
    try:
        log_system_event("INFO", f"Corpix sorgusu: '{query[:50]}...' (user_id={user_id})", "dialog")
        
        llm_response = call_llm_api(messages)
        
        formatted_response = (
            f"💬 **Corpix L1 Destek**\n\n"
            f"{llm_response}\n\n"
            f"---\n"
            f"[FEEDBACK_SECTION]\n"
            f"**Bu yanıt yardımcı oldu mu?**\n"
            f"[/FEEDBACK_SECTION]"
        )
        
        log_system_event("INFO", f"Corpix yanıtı alındı ({len(llm_response)} karakter)", "dialog", user_id)
        
        return formatted_response
        
    except LLMConnectionError as e:
        log_error(f"Corpix LLM bağlantı hatası: {e}", "dialog")
        return (
            "🌐 **Bağlantı Hatası**\n\n"
            "Şu anda Corpix'e ulaşılamıyor. VPN bağlantınızı kontrol edin.\n\n"
            "Alternatif olarak doğrudan IT destek hattını arayabilirsiniz."
        )
    except LLMConfigError as e:
        log_error(f"Corpix LLM config hatası: {e}", "dialog")
        return (
            "⚠️ **Yapılandırma Hatası**\n\n"
            "Corpix servisi şu anda kullanılamıyor.\n"
            "Lütfen sistem yöneticinize başvurun."
        )
    except Exception as e:
        log_error(f"Corpix beklenmeyen hata: {e}", "dialog")
        return (
            "❌ **Hata**\n\n"
            "Bir sorun oluştu. Lütfen tekrar deneyin."
        )


def generate_ticket_summary(dialog_id: int, user_id: int) -> str:
    """
    v2.24.5: Dialog akışından IT jargonuna uygun çağrı özeti üret.
    
    LLM kullanarak kullanıcının yazdıklarını profesyonel IT 
    çağrı metnine dönüştürür.
    
    Args:
        dialog_id: Dialog ID
        user_id: Kullanıcı ID
        
    Returns:
        IT jargonlu özet metin
    """
    from app.core.llm import LLMConfigError, LLMConnectionError, call_llm_api
    from app.services.dialog.messages import get_dialog_messages
    
    # Dialog mesajlarını al
    messages_raw = get_dialog_messages(dialog_id, limit=20)
    
    if not messages_raw:
        return "❌ Dialog boş, özet oluşturulamadı."
    
    # Mesajları formatla
    conversation_parts = []
    for msg in messages_raw:
        role = "Kullanıcı" if msg["role"] == "user" else "Asistan"
        content = msg["content"]
        # Quick reply ve sistem mesajlarını atla
        if msg.get("content_type") == "quick_reply":
            continue
        if content.startswith("👋") or content.startswith("🎉"):
            continue
        conversation_parts.append(f"[{role}]: {content[:500]}")
    
    if not conversation_parts:
        return "❌ Anlamlı mesaj bulunamadı."
    
    conversation_text = "\n".join(conversation_parts)
    
    # v2.26.0: DB'den ticket_summary kategorisindeki aktif prompt'u al
    from app.core.llm import get_prompt_by_category
    system_prompt = get_prompt_by_category("ticket_summary")

    user_message = f"""DIALOG KAYDI:
{conversation_text}

Bu dialog akışından TEK BİR IT çağrı özeti oluştur."""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]
    
    try:
        log_system_event("INFO", f"Ticket özeti oluşturuluyor: dialog #{dialog_id}", "dialog", user_id)
        
        llm_response = call_llm_api(messages)
        
        log_system_event("INFO", f"Ticket özeti oluşturuldu ({len(llm_response)} karakter)", "dialog", user_id)
        
        return llm_response
        
    except LLMConnectionError as e:
        log_error(f"Ticket özet LLM bağlantı hatası: {e}", "dialog")
        return "🌐 Özet oluşturulamadı - VPN bağlantınızı kontrol edin."
    except LLMConfigError as e:
        log_error(f"Ticket özet LLM config hatası: {e}", "dialog")
        return "⚠️ Özet oluşturulamadı - LLM yapılandırması eksik."
    except Exception as e:
        log_error(f"Ticket özet beklenmeyen hata: {e}", "dialog")
        return "❌ Özet oluşturulurken hata oluştu."
