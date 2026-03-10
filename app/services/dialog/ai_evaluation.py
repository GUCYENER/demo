"""
VYRA L1 Support API - AI Evaluation Service
=============================================
LLM bazlı RAG sonuç değerlendirmesi.

Refactored from dialog_service.py (v2.29.14)
"""

from __future__ import annotations

from typing import List, Dict

from app.services.logging_service import log_system_event, log_error


def evaluate_with_llm(query: str, rag_results: List[Dict]) -> str:
    """
    RAG sonuçlarını LLM ile değerlendir.
    
    🔒 STRICT MODE: LLM sadece verilen RAG verisini kullanır,
    kendi bilgisini EKLEMEZ.
    """
    from app.core.llm import call_llm_api, LLMConnectionError, LLMConfigError
    
    # RAG sonuçlarını formatla
    rag_formatted_parts = []
    for i, result in enumerate(rag_results, 1):
        file_name = result.get("file_name", "Kaynak")
        chunk_text = result.get("chunk_text", "")
        score = result.get("similarity_score", 0)
        
        rag_formatted_parts.append(
            f"---\n"
            f"📄 SONUÇ {i} (Eşleşme: %{int(score * 100)})\n"
            f"Dosya: {file_name}\n"
            f"İçerik:\n{chunk_text}\n"
        )
    
    rag_formatted = "\n".join(rag_formatted_parts)
    
    # LLM Prompt - Strict mode, kullanıcıya hitaben format
    system_prompt = """ROL: Sen VYRA L1 Teknik Destek Uzmanısın. Kullanıcıya doğrudan ve samimi bir dille hitap ediyorsun.

KESİN KURALLAR:
1. SADECE aşağıda verilen RAG sonuçlarını kullan
2. Kendi bilgini ASLA ekleme
3. Alakalı sonuçları seç, alakasızları ATLA (bahsetme bile)
4. Seçtiğin sonuçları birleştirip TUTARLI ve AKICI bir DOĞRUDAN CEVAP oluştur
5. Ara işlem adımları veya analiz süreçlerini GÖSTERME (Adım 1, Adım 2 gibi yazma)
6. Kullanıcıya hitaben, sanki sohbet ediyormuşsun gibi yanıt ver
7. Kaynak dosya adlarını cevabın sonunda "📁 Kaynak: dosya_adi" formatında belirt
8. Türkçe yanıt ver

FORMAT ÖRNEĞİ:
❌ YANLIŞ: "Adım 1: Cisco Switch komutunu belirliyorum. Adım 2: İlgili dosyayı inceliyorum..."
✅ DOĞRU: "Sorunuza göre Cisco Switch için şu komutu kullanmalısınız: [komut]. Bu komut [açıklama]... 📁 Kaynak: Komutlar.xlsx"

ÖNEMLİ: Eğer RAG sonuçlarında alakalı bilgi yoksa "Bu konuda bilgi tabanında yeterli bilgi bulunamadı" de."""

    user_message = f"""KULLANICI SORUSU: {query}

RAG BİLGİ TABANI SONUÇLARI:
{rag_formatted}

Yukarıdaki sonuçları değerlendir ve kullanıcının sorusuna SADECE bu bilgilere dayanarak yanıt ver."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]
    
    try:
        log_system_event("INFO", f"AI Değerlendirme: {len(rag_results)} sonuç LLM'e gönderiliyor", "dialog")
        
        llm_response = call_llm_api(messages)
        
        # Yanıtı formatla
        formatted_response = (
            f"🤖 **AI Değerlendirmesi**\n\n"
            f"{llm_response}\n\n"
            f"---\n"
            f"[FEEDBACK_SECTION]\n"
            f"**Bu değerlendirme işinize yaradı mı?**\n"
            f"[/FEEDBACK_SECTION]"
        )
        
        log_system_event("INFO", f"AI Değerlendirme: Yanıt alındı ({len(llm_response)} karakter)", "dialog")
        
        return formatted_response
        
    except LLMConnectionError as e:
        log_error(f"AI Değerlendirme LLM bağlantı hatası: {e}", "dialog")
        return (
            f"🌐 **LLM Bağlantı Hatası**\n\n"
            f"AI değerlendirmesi şu anda yapılamıyor. VPN bağlantınızı kontrol edin.\n\n"
            f"Seçenekleri manuel olarak inceleyebilirsiniz."
        )
    except LLMConfigError as e:
        log_error(f"AI Değerlendirme LLM config hatası: {e}", "dialog")
        return (
            f"⚠️ **LLM Yapılandırma Hatası**\n\n"
            f"AI değerlendirmesi için aktif LLM bulunamadı.\n"
            f"Parametreler menüsünden LLM ekleyin."
        )
    except Exception as e:
        log_error(f"AI Değerlendirme beklenmeyen hata: {e}", "dialog")
        return (
            f"❌ **Değerlendirme Hatası**\n\n"
            f"AI değerlendirmesi sırasında bir hata oluştu.\n"
            f"Lütfen sonuçları manuel olarak inceleyin."
        )
