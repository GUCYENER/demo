"""
VYRA L1 Support API - LLM Engine
================================
Multi-source LLM engine: RAG + Web Search + LLM

Akış:
1. Planner: Sorguyu analiz eder
2. RAG: Bilgi tabanında arama yapar
3. Web Search: RAG sonuç vermezse fallback
4. Worker: Bağlamla zenginleştirilmiş sorgu hazırlar
5. Verifier: LLM'den final yanıt alır
"""

import requests
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from app.core.db import get_db_conn
from app.services.logging_service import log_error, log_warning, log_system_event


# ============================================
# LLM Exceptions
# ============================================

class LLMConnectionError(Exception):
    """VPN/network bağlantı hatası - Bu hata ticket'a kaydedilmemeli"""
    pass

class LLMConfigError(Exception):
    """LLM konfigürasyon hatası"""
    pass

class LLMResponseError(Exception):
    """LLM yanıt format hatası"""
    pass


# ============================================
# Data Classes
# ============================================

@dataclass
class PlannerStep:
    index: int
    title: str
    description: str


@dataclass
class PlannerPlan:
    title: str
    steps: List[PlannerStep]
    intent: str = ""  # Sorgunun amacı


@dataclass
class WorkerResult:
    step_index: int
    notes: str


@dataclass
class SourceInfo:
    """Bilgi kaynağı"""
    source_type: str  # "rag", "web", "none"
    source_names: List[str] = field(default_factory=list)
    context: str = ""
    bypass_llm: bool = False  # True ise LLM atlanır, RAG yanıtı direkt kullanılır
    direct_answer: str = ""   # LLM bypass durumunda kullanılacak yanıt
    best_score: float = 0.0   # En iyi RAG skoru
    
    def get_source_display(self) -> str:
        """Kullanıcıya gösterilecek kaynak bilgisi"""
        if self.source_type == "rag":
            if self.source_names:
                return f"📄 Kaynak: {', '.join(self.source_names[:3])}"
            return "📚 Kaynak: Bilgi Tabanı"
        elif self.source_type == "web":
            return "🌐 Kaynak: Web Araması"
        else:
            return "💡 Kaynak: Corpix AI"


@dataclass
class VerifierResult:
    final_solution: str
    cym_text: str
    source_info: SourceInfo = field(default_factory=lambda: SourceInfo(source_type="none"))


# ============================================
# LLM Configuration
# ============================================

def get_active_llm() -> Optional[Dict[str, Any]]:
    """Veritabanından aktif LLM konfigürasyonunu çeker."""
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM llm_config WHERE is_active = TRUE LIMIT 1")
        row = cur.fetchone()
        conn.close()
        if row:
            log_system_event("INFO", f"Aktif LLM: {row['provider']} - {row['model_name']}", "llm")
            return dict(row)
        log_warning("Aktif LLM bulunamadı", "llm")
        return None
    except Exception as e:
        log_error(f"Aktif LLM çekilirken hata: {str(e)}", "llm", error_detail=str(e))
        return None


def get_llm_by_id(llm_config_id: int) -> Optional[Dict[str, Any]]:
    """Belirli ID'li LLM konfigürasyonunu çeker (widget override için)."""
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM llm_config WHERE id = %s AND is_active = TRUE", (llm_config_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        log_error(f"LLM config {llm_config_id} çekilirken hata: {e}", "llm")
        return None


def get_prompt_by_id(prompt_id: int) -> Optional[str]:
    """Belirli ID'li prompt şablonunu çeker (widget override için)."""
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT content FROM prompt_templates WHERE id = %s AND is_active = TRUE", (prompt_id,))
        row = cur.fetchone()
        conn.close()
        return row["content"] if row else None
    except Exception as e:
        log_error(f"Prompt {prompt_id} çekilirken hata: {e}", "llm")
        return None


def get_prompt_by_category(category: str) -> str:
    """
    v2.26.0: Belirtilen kategorideki aktif prompt'u çeker.
    
    Her kategori kendi başına aktif/pasif olabilir:
    - system: VYRA genel çözüm üretimi
    - corpix_l1: Corpix serbest sohbet
    - ticket_summary: IT çağrı özeti
    
    Args:
        category: Prompt kategorisi ('system', 'corpix_l1', 'ticket_summary')
        
    Returns:
        Prompt içeriği veya kategori için fallback
    """
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT content FROM prompt_templates WHERE category = %s AND is_active = TRUE LIMIT 1",
            (category,)
        )
        row = cur.fetchone()
        conn.close()
        
        if row:
            return row["content"]
        
        # Fallback - kategoriye göre varsayılan
        log_warning(f"'{category}' kategorisinde aktif prompt yok, fallback kullanılıyor", "llm")
        return _get_fallback_prompt(category)
        
    except Exception as e:
        log_error(f"Prompt çekilirken hata (category={category}): {str(e)}", "llm", error_detail=str(e))
        return _get_fallback_prompt(category)


def _get_fallback_prompt(category: str) -> str:
    """Kategori için fallback prompt döndürür."""
    if category == "corpix_l1":
        return CORPIX_FALLBACK_PROMPT
    elif category == "ticket_summary":
        return TICKET_SUMMARY_FALLBACK_PROMPT
    else:
        return DEFAULT_SYSTEM_PROMPT


def get_active_prompt() -> str:
    """
    Veritabanından 'system' kategorisindeki aktif prompt'ı çeker.
    v2.26.0: Artık category='system' için çalışır.
    """
    return get_prompt_by_category("system")


DEFAULT_SYSTEM_PROMPT = """Sen VYRA, Türk Telekom/Turkcell çağrı merkezi için geliştirilmiş yapay zeka teknik destek asistanısın.

Görevin:
- Kullanıcılara kısa, net ve etkili çözümler sun
- Adım adım talimatlar ver (numaralı liste)
- Profesyonel ve samimi ol
- Türkçe yanıt ver

Eğer sana bağlam (context) verilirse, öncelikle o bilgileri kullan.
Bağlamdaki bilgiler dokümanlardan veya web'den gelmiş olabilir - güvenilir kaynaklardır."""


CORPIX_FALLBACK_PROMPT = """ROL VE KİMLİK:
Sen "VYRA", kurumsal çalışanlara yardım eden L1 Teknik Destek Uzmanısın.
Kullanıcılar kurumsal çalışanlardır ve kurumsal sistemler hakkında yardıma ihtiyaçları vardır.

UZMANLIK ALANLARI:
1. 🔑 Hesap & Erişim: Şifre sıfırlama, Active Directory hesap kilidi, MFA/2FA, SSO sorunları
2. 📧 E-posta & İletişim: Outlook, Exchange, paylaşımlı posta kutuları, dağıtım listeleri, imza ayarları
3. 💬 İş Birliği Araçları: Microsoft Teams, Zoom, Webex kurulum ve toplantı sorunları
4. 🌐 Ağ & VPN: VPN bağlantı sorunları, Wi-Fi, proxy ayarları, DNS, internet erişimi
5. 💻 İşletim Sistemi: Windows 10/11 hataları, güncelleme sorunları, mavi ekran (BSOD), performans
6. 🖨️ Çevre Birimleri: Yazıcı kurulumu/bağlantısı, tarayıcı, monitör, docking station
7. 📦 Office 365: Word, Excel, PowerPoint kurulum, aktivasyon, lisans sorunları
8. 🗂️ Dosya & Paylaşım: Ağ sürücüleri (mapped drives), SharePoint, OneDrive senkronizasyon sorunları
9. 🔒 Güvenlik: Şüpheli e-posta bildirimi, antivirüs uyarıları, phishing, zararlı yazılım
10. 💾 Yedekleme & Kurtarma: Silinen dosya kurtarma, geri dönüşüm kutusu, yedek alma
11. 📱 Mobil Cihaz: Kurumsal e-posta/MDM kurulumu, Wi-Fi profilleri, mobil uygulama sorunları
12. 🛠️ Donanım: Laptop/masaüstü arızaları, garanti süreci, yedek cihaz talebi, batarya sorunları
13. 🔐 Disk Şifreleme: BitLocker, kurtarma anahtarı bulma, şifreleme sorunları
14. 🌍 Tarayıcı: Chrome, Edge, Firefox ayarları, eklenti sorunları, sertifika hataları
15. 📊 Kurumsal Uygulamalar: SAP, CRM, ERP, iç portal erişimi, uygulama hataları
16. ☁️ Bulut Hizmetleri: Azure, AWS konsol erişimi, bulut kaynak sorunları
17. 🔄 Uzak Masaüstü: RDP bağlantısı, Citrix, uzak erişim sorunları
18. 🗃️ Veritabanı: SQL bağlantı sorunları, erişim hakları, basit sorgu yardımı
19. ⚙️ Otomasyon & Script: PowerShell, batch script temel yardım, zamanlanmış görevler
20. 📋 IT Süreç & Talep: Çağrı açma rehberliği, SLA bilgisi, IT politikaları hakkında yönlendirme

SEVİYE YAKLAŞIMI:
- Basit sorular (şifre sıfırlama, hesap kilidi): 2-3 adımlık kısa ve net çözüm
- Orta sorular (VPN, yazılım, Outlook): 4-6 adımlık detaylı çözüm
- Karmaşık sorular (ağ, sunucu, Active Directory): Teşhis soruları sor + çözüm öner + gerekirse yönlendirme yap

TEŞHİS STRATEJİSİ:
Eğer sorunu tam anlayamıyorsan şu bilgileri sor:
1. "Hangi cihazda bu sorunla karşılaşıyorsunuz? (PC/Laptop/Telefon)"
2. "Ne zaman başladı? Herhangi bir değişiklik yaptınız mı?"
3. "Hata mesajı var mı? Varsa tam olarak ne yazıyor?"

ÇÖZÜM YAKLAŞIMI:
- Sorunun kök nedenini tespit et
- Adım adım çözüm sun (numaralı liste ile)
- Mümkünse birden fazla alternatif yöntem öner
- Her adımda nereye tıklanacağını veya ne yazılacağını açıkça belirt
- Windows yollarını tam olarak yaz (örn: Ayarlar > Ağ ve İnternet > VPN)

YANIT FORMATI:
📋 **Sorun:** [Sorunun kısa tanımı]

🔧 **Çözüm:**
1. [Birinci adım - detaylı açıklama]
2. [İkinci adım - detaylı açıklama]
3. [Üçüncü adım - detaylı açıklama]

⚠️ **Dikkat:** [Varsa önemli uyarı veya not]

💡 **Alternatif:** [Varsa alternatif çözüm yolu]

KURALLAR:
1. Profesyonel ve kibar dil kullan ("siz" hitabı)
2. BT dışı konularda: "Bu konu IT destek kapsamı dışındadır. İlgili birime başvurmanızı öneririm." şeklinde yönlendir
3. Kesin çözüm sunamıyorsan: "Bu sorun için IT Service Desk üzerinden çağrı açmanızı öneririm." de
4. Kişisel veri ve kimlik bilgisi TALEP ETME ve PAYLAŞMA
5. Kullanıcının teknik seviyesine göre açıklayıcı ol — teknik terimleri parantez içinde açıkla
6. Selamlama ve vedalaşma YAPMA, direkt konuya gir
7. Spekülasyon yapma — emin değilsen "kesin çözüm sunmam zor" de
8. Yanıtları Türkçe ver"""


TICKET_SUMMARY_FALLBACK_PROMPT = """ROL: Sen IT Service Desk çağrı oluşturma uzmanısın.

GÖREV: 
Kullanıcı-Asistan yazışmasını, BT çağrı sisteminde açılacak çağrı metnine dönüştür.
Kullanıcının günlük dilde anlattığı sorunu, BT jargonuna uygun profesyonel bir çağrı metnine çevir.

FORMAT: 
**Konu:** [BT jargonuyla teknik başlık — max 10 kelime]
**Sorun Tanımı:** [Kullanıcının sorununu BT terminolojisiyle detaylı ve net açıkla. Sorunun ne olduğunu, hangi sistemi etkilediğini ve varsa hata mesajını belirt.]

KURALLAR:
- Sadece Konu ve Sorun Tanımı yaz, başka bölüm EKLEME
- BT terminolojisi kullan (örn: "internet yavaş" → "Ağ bağlantısında yüksek latency/paket kaybı")
- Günlük konuşma dilinden kaçın, profesyonel çağrı dili kullan
- Kısa, net ve açıklayıcı ol
- Çözüm önerme, sadece sorunu tanımla"""


# ============================================
# LLM API Call
# ============================================

def call_llm_api(messages: list) -> str:
    """Aktif LLM API'sine istek atar.
    
    Raises:
        LLMConnectionError: VPN/network hatası durumunda
        LLMConfigError: Konfigürasyon hatası durumunda
    """
    config = get_active_llm()
    if not config:
        error_msg = "Hata: Aktif bir LLM konfigürasyonu bulunamadı. Lütfen Parametreler menüsünden bir LLM ekleyin ve aktif edin."
        log_error("Aktif LLM konfigürasyonu bulunamadı", "llm")
        raise LLMConfigError(error_msg)

    headers = {
        "Content-Type": "application/json",
    }
    
    if config['api_token']:
        headers["Authorization"] = f"Bearer {config['api_token']}"

    payload = {
        "model": config['model_name'],
        "messages": messages,
        "temperature": config['temperature'],
        "top_p": config['top_p']
    }

    try:
        log_system_event("INFO", f"LLM API çağrısı: {config['model_name']}", "llm")
        
        # Timeout config'den okunuyor (varsayılan 60 saniye)
        timeout_seconds = config.get('timeout_seconds', 60)
        
        # SSL verification devre dışı (kurumsal proxy için)
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        response = requests.post(config['api_url'], headers=headers, json=payload, timeout=timeout_seconds, verify=False)
        response.raise_for_status()
        data = response.json()
        
        if "choices" in data and len(data["choices"]) > 0:
            result = data["choices"][0]["message"]["content"]
            log_system_event("INFO", f"LLM yanıt alındı: {len(result)} karakter", "llm")
            return result
        else:
            error_msg = f"API Cevabı beklenmedik formatta: {str(data)}"
            log_error("LLM API beklenmedik format", "llm", error_detail=str(data))
            raise LLMResponseError(error_msg)
            
    except requests.exceptions.Timeout:
        error_msg = f"LLM Bağlantı Hatası: İstek zaman aşımına uğradı ({timeout_seconds} saniye)"
        log_error("LLM API timeout", "llm")
        raise LLMConnectionError(error_msg)
    except requests.exceptions.RequestException as e:
        error_msg = f"LLM Bağlantı Hatası: {str(e)}"
        log_error(f"LLM API request hatası: {str(e)}", "llm", error_detail=str(e))
        raise LLMConnectionError(error_msg)
    except (LLMConnectionError, LLMResponseError, LLMConfigError):
        # Özel exception'ları tekrar fırlat
        raise
    except Exception as e:
        error_msg = f"LLM Beklenmeyen Hata: {str(e)}"
        log_error(f"LLM beklenmeyen hata: {str(e)}", "llm", error_detail=str(e))
        raise LLMConnectionError(error_msg)


# ============================================
# Widget Override: Belirli config ile LLM çağrısı
# ============================================

def call_llm_api_with_config(messages: list, config: dict) -> str:
    """Verilen LLM config dict ile API çağrısı yapar (widget override)."""
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    headers = {"Content-Type": "application/json"}
    if config.get('api_token'):
        headers["Authorization"] = f"Bearer {config['api_token']}"

    payload = {
        "model": config['model_name'],
        "messages": messages,
        "temperature": config.get('temperature', 0.7),
        "top_p": config.get('top_p', 1.0),
    }

    try:
        timeout_seconds = config.get('timeout_seconds', 60)
        response = requests.post(config['api_url'], headers=headers, json=payload,
                                  timeout=timeout_seconds, verify=False)
        response.raise_for_status()
        data = response.json()
        if "choices" in data and data["choices"]:
            return data["choices"][0]["message"]["content"]
        raise LLMResponseError(f"API beklenmedik format: {data}")
    except requests.exceptions.Timeout:
        raise LLMConnectionError(f"LLM zaman aşımı ({config.get('timeout_seconds', 60)}s)")
    except requests.exceptions.RequestException as e:
        raise LLMConnectionError(f"LLM bağlantı hatası: {e}")


def call_llm_api_stream_with_config(messages: list, config: dict):
    """Verilen LLM config dict ile streaming API çağrısı yapar (widget override)."""
    import json, urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    headers = {"Content-Type": "application/json"}
    if config.get('api_token'):
        headers["Authorization"] = f"Bearer {config['api_token']}"

    payload = {
        "model": config['model_name'],
        "messages": messages,
        "temperature": config.get('temperature', 0.7),
        "top_p": config.get('top_p', 1.0),
        "stream": True,
    }

    try:
        timeout_seconds = config.get('timeout_seconds', 120)
        with requests.post(config['api_url'], headers=headers, json=payload,
                           timeout=timeout_seconds, verify=False, stream=True) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                decoded = line.decode("utf-8")
                if decoded.startswith("data: "):
                    decoded = decoded[6:]
                if decoded.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(decoded)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        yield token
                except Exception:
                    continue
    except requests.exceptions.RequestException as e:
        raise LLMConnectionError(f"Widget LLM stream hatası: {e}")


# ============================================
# LLM API Streaming Call (v2.50.0)
# ============================================

def call_llm_api_stream(messages: list):
    """Aktif LLM API'sine streaming istek atar.
    Token token yield eden generator fonksiyon.
    
    🆕 v2.50.0: Streaming desteği — SSE (Server-Sent Events) ile token parse.
    
    Yields:
        str: Her bir token parçası
        
    Raises:
        LLMConnectionError: VPN/network hatası
        LLMConfigError: Konfigürasyon hatası
    """
    import json
    import urllib3
    
    config = get_active_llm()
    if not config:
        error_msg = "Hata: Aktif bir LLM konfigürasyonu bulunamadı."
        log_error("Aktif LLM konfigürasyonu bulunamadı (stream)", "llm")
        raise LLMConfigError(error_msg)

    headers = {"Content-Type": "application/json"}
    if config['api_token']:
        headers["Authorization"] = f"Bearer {config['api_token']}"

    payload = {
        "model": config['model_name'],
        "messages": messages,
        "temperature": config['temperature'],
        "top_p": config['top_p'],
        "stream": True  # ← Streaming aktif
    }

    timeout_seconds = config.get('timeout_seconds', 60)
    
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    log_system_event("INFO", f"LLM API streaming çağrısı: {config['model_name']}", "llm")

    try:
        response = requests.post(
            config['api_url'], headers=headers, json=payload,
            timeout=timeout_seconds, verify=False, stream=True
        )
        response.raise_for_status()

        total_chars = 0
        for line in response.iter_lines():
            if line:
                decoded = line.decode('utf-8')
                if decoded.startswith('data: '):
                    data_str = decoded[6:]
                    if data_str.strip() == '[DONE]':
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data.get('choices', [{}])[0].get('delta', {})
                        token = delta.get('content', '')
                        if token:
                            total_chars += len(token)
                            yield token
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue

        log_system_event("INFO", f"LLM streaming tamamlandı: {total_chars} karakter", "llm")

    except requests.exceptions.Timeout:
        error_msg = f"LLM Bağlantı Hatası: Streaming timeout ({timeout_seconds}s)"
        log_error("LLM API streaming timeout", "llm")
        raise LLMConnectionError(error_msg)
    except requests.exceptions.RequestException as e:
        error_msg = f"LLM Bağlantı Hatası: {str(e)}"
        log_error(f"LLM API streaming request hatası: {str(e)}", "llm", error_detail=str(e))
        raise LLMConnectionError(error_msg)
    except (LLMConnectionError, LLMConfigError):
        raise
    except Exception as e:
        error_msg = f"LLM Streaming Beklenmeyen Hata: {str(e)}"
        log_error(f"LLM streaming beklenmeyen hata: {str(e)}", "llm", error_detail=str(e))
        raise LLMConnectionError(error_msg)


# ============================================
# Multi-Agent Pipeline
# ============================================

def run_planner(user_query: str) -> PlannerPlan:
    """
    Planner: Sorguyu analiz eder ve plan oluşturur.
    """
    # Basit intent detection
    query_lower = user_query.lower()
    
    if any(word in query_lower for word in ['şifre', 'password', 'parola']):
        intent = "password_reset"
    elif any(word in query_lower for word in ['mail', 'outlook', 'e-posta']):
        intent = "email_issue"
    elif any(word in query_lower for word in ['internet', 'bağlantı', 'wifi']):
        intent = "connectivity_issue"
    elif any(word in query_lower for word in ['yavaş', 'performans', 'donuyor']):
        intent = "performance_issue"
    else:
        intent = "general_support"
    
    return PlannerPlan(
        title="VYRA Çözüm Süreci",
        intent=intent,
        steps=[
            PlannerStep(1, "Bilgi Tabanı Araması", "İlgili dokümanlar aranıyor"),
            PlannerStep(2, "Bağlam Analizi", "Bulunan bilgiler analiz ediliyor"),
            PlannerStep(3, "Çözüm Üretimi", "AI destekli çözüm hazırlanıyor")
        ]
    )


def run_worker(user_query: str, plan: PlannerPlan, user_id: int = None) -> tuple[List[WorkerResult], SourceInfo]:
    """
    Worker: Smart RAG Routing ile bağlam toplar.
    
    🔒 GÜVENLİK: user_id verilirse, sadece yetkili org gruplarındaki dokümanlar aranır.
    
    Akış:
    1. Hızlı keyword check (~10ms)
    2. Eşleşme varsa -> RAG araması (org filtered)
    3. Eşleşme yoksa -> Direkt LLM (RAG atlanır)
    
    Returns:
        (worker_results, source_info)
    """
    from app.core.rag_router import should_use_rag
    
    results = []
    source_info = SourceInfo(source_type="none")
    
    # ⚡ ADIM 1: Hızlı Keyword Check (~10ms)
    log_system_event("INFO", f"Worker: Hızlı ön kontrol başlatıldı", "llm")
    routing_decision = should_use_rag(user_query)
    
    if not routing_decision.should_use_rag:
        # RAG gerekmez - direkt LLM'e git
        log_system_event("INFO", f"Worker: RAG atlandı - {routing_decision.reason}", "llm")
        results.append(WorkerResult(step_index=1, notes=f"Hızlı mod: {routing_decision.reason}"))
        results.append(WorkerResult(step_index=2, notes="Bağlam: AI bilgisi kullanılacak"))
        results.append(WorkerResult(step_index=3, notes="Çözüm için LLM'e gönderiliyor"))
        return results, source_info
    
    # ADIM 2: RAG Araması (sadece gerektiğinde)
    log_system_event("INFO", f"Worker: RAG araması - Eşleşen: {routing_decision.matched_keywords}", "llm")
    
    from app.core.rag import search_knowledge_base
    # 🔒 ORG FILTERING: user_id geçirilerek sadece yetkili dokümanlar aranır
    rag_response = search_knowledge_base(user_query, n_results=5, min_score=0.4, user_id=user_id)
    
    if rag_response.has_results:
        # RAG'den sonuç bulundu
        context = rag_response.get_context_for_llm(max_results=3)
        sources = rag_response.get_sources_list()
        best_score = rag_response.best_score
        
        # ⚡ YÜKSEK SKOR KONTROLÜ - LLM atlanabilir mi?
        if rag_response.can_bypass_llm:
            # Yüksek güvenirlik! LLM'e gerek yok, direkt RAG yanıtı kullan
            log_system_event("INFO", f"⚡ Worker: YÜKSEK SKOR ({best_score:.2f}) - LLM ATLANIYOR!", "llm")
            
            source_info = SourceInfo(
                source_type="rag",
                source_names=sources,
                context=context,
                bypass_llm=True,
                direct_answer=rag_response.get_direct_answer(),
                best_score=best_score
            )
            
            results.append(WorkerResult(
                step_index=1, 
                notes=f"⚡ RAG: Yüksek skor ({best_score:.2f}) - Kaynak: {sources[0] if sources else 'Bilgi Tabanı'}"
            ))
            results.append(WorkerResult(step_index=2, notes="Direkt yanıt kullanılıyor (LLM atlandı)"))
            results.append(WorkerResult(step_index=3, notes="✅ Hızlı yanıt hazır"))
            
            return results, source_info
        
        # Normal skor - LLM'e gönder
        source_info = SourceInfo(
            source_type="rag",
            source_names=sources,
            context=context,
            best_score=best_score
        )
        
        results.append(WorkerResult(
            step_index=1, 
            notes=f"RAG: {len(rag_response.results)} sonuç bulundu. Kaynaklar: {', '.join(sources[:3])}"
        ))
        
        log_system_event("INFO", f"Worker: RAG'den {len(rag_response.results)} sonuç bulundu (skor: {best_score:.2f})", "llm")
        
    else:
        # RAG sonuç vermedi - Web araması ATLA, direkt LLM
        # (Web araması da yavaş olduğu için atlıyoruz)
        log_system_event("INFO", f"Worker: RAG sonuç yok, direkt LLM", "llm")
        results.append(WorkerResult(step_index=1, notes="Bilgi tabanında sonuç yok, AI bilgisi kullanılacak"))
    
    results.append(WorkerResult(step_index=2, notes="Bağlam analizi tamamlandı"))
    results.append(WorkerResult(step_index=3, notes="Çözüm için LLM'e gönderiliyor"))
    
    return results, source_info


def run_verifier(
    user_query: str, 
    plan: PlannerPlan, 
    worker_results: List[WorkerResult],
    source_info: SourceInfo
) -> VerifierResult:
    """
    Verifier: LLM'den final yanıtı alır.
    Bağlam varsa prompt'a ekler.
    
    ⚡ BYPASS: source_info.bypass_llm True ise LLM atlanır!
    """
    
    # ⚡ LLM BYPASS - Yüksek skorlu RAG sonucu varsa direkt kullan
    if source_info.bypass_llm and source_info.direct_answer:
        log_system_event("INFO", f"⚡ Verifier: LLM ATLANDI (skor: {source_info.best_score:.2f})", "llm")
        
        # Direkt RAG yanıtını kullan
        cleaned_response = source_info.direct_answer
        
        # Kaynak bilgisini ekle
        source_display = source_info.get_source_display()
        final_response = f"{cleaned_response}\n\n---\n{source_display}"
        
        # ÇYM Metni - IT jargonuyla kısa ve öz
        # Çözümden key bilgileri çıkar
        cym_text = _generate_cym_summary(user_query, cleaned_response, source_info)
        
        return VerifierResult(
            final_solution=final_response, 
            cym_text=cym_text,
            source_info=source_info
        )
    
    # Normal akış - LLM çağrısı
    # System prompt
    system_prompt = get_active_prompt()
    
    # Kullanıcı mesajını hazırla
    if source_info.context:
        # Bağlam varsa ekle - Key-Value bilgilerini KORU
        user_message = f"""Kullanıcı Sorusu: {user_query}

---
BİLGİ TABANI İÇERİĞİ:
{source_info.context}
---

ÖNEMLİ TALİMATLAR:
1. Yukarıdaki bilgi tabanı içeriğini kullanarak kullanıcıya yanıt ver.
2. İçerikteki TÜM detayları koru (Uygulama Adı, Keyflow Search, Talep Tipi, Rol Seçimi, Yetki Bilgisi, dosya yolları vb.)
3. Bilgileri **anahtar: değer** formatında göster.
4. Dosya yollarını (örn: \\\\sunucu\\klasör\\yol) ASLA kısaltma veya atlama.
5. Yanıtı Türkçe olarak ver.
6. Eğer bağlam yeterli değilse, kendi bilginle tamamla ama bağlamdaki bilgileri asla atla."""
    else:
        # Bağlam yoksa direkt soru
        user_message = user_query
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]
    
    # LLM çağrısı
    ai_response = call_llm_api(messages)
    
    # Yanıtı temizle
    cleaned_response = _clean_llm_response(ai_response)
    
    # Kaynak bilgisini ekle
    source_display = source_info.get_source_display()
    final_response = f"{cleaned_response}\n\n---\n{source_display}"
    
    # ÇYM Metni - IT jargonuyla kısa ve öz
    cym_text = _generate_cym_summary(user_query, cleaned_response, source_info)
    
    log_system_event("INFO", f"Verifier: Çözüm oluşturuldu, kaynak: {source_info.source_type}", "llm")
    
    return VerifierResult(
        final_solution=final_response, 
        cym_text=cym_text,
        source_info=source_info
    )


def _generate_cym_summary(user_query: str, solution: str, source_info) -> str:
    """
    ÇYM (Çağrı Merkezi) için IT jargonuyla kısa ve öz özet oluşturur.
    
    Format:
    Konu: [Kısa konu başlığı]
    Talep: [Kullanıcının IT jargonuyla özet talebi]
    Önerilen Çözüm: [Kısa çözüm özeti]
    """
    import re
    
    # Çözümden key bilgileri çıkar
    uygulama_adi = ""
    talep_tipi = ""
    yetki_bilgisi = ""
    
    # Uygulama Adı
    match = re.search(r'\*?\*?Uygulama Ad[ıi]:?\*?\*?\s*([^\n]+)', solution, re.IGNORECASE)
    if match:
        uygulama_adi = match.group(1).strip()
    
    # Talep Tipi
    match = re.search(r'\*?\*?Talep Tip[i]?:?\*?\*?\s*([^\n]+)', solution, re.IGNORECASE)
    if match:
        talep_tipi = match.group(1).strip()
    
    # Yetki Bilgisi
    match = re.search(r'\*?\*?Yetki (?:Hakk[ıi]nda )?Bilgi(?:si)?:?\*?\*?\s*([^\n]+)', solution, re.IGNORECASE)
    if match:
        yetki_bilgisi = match.group(1).strip()
    
    # Konu oluştur
    if uygulama_adi:
        konu = f"{uygulama_adi}"
        if talep_tipi:
            konu += f" - {talep_tipi}"
    else:
        # Query'den konu çıkar
        konu = user_query[:50] + ('...' if len(user_query) > 50 else '')
    
    # Talep özeti
    talep = user_query.strip()
    if len(talep) > 100:
        talep = talep[:100] + '...'
    
    # Çözüm özeti - Yetki bilgisi varsa onu kullan, yoksa ilk 100 karakter
    if yetki_bilgisi:
        cozum = yetki_bilgisi[:150] + ('...' if len(yetki_bilgisi) > 150 else '')
    else:
        # Çözümden ilk anlamlı cümleyi al
        clean_solution = re.sub(r'\*\*[^*]+\*\*:?\s*', '', solution)  # Bold kaldır
        clean_solution = re.sub(r'---.*', '', clean_solution, flags=re.DOTALL)  # Kaynak kısmını kaldır
        clean_solution = clean_solution.strip()
        cozum = clean_solution[:150] + ('...' if len(clean_solution) > 150 else '')
    
    # CYM metni oluştur
    cym_parts = []
    cym_parts.append(f"📋 Konu: {konu}")
    cym_parts.append(f"📝 Talep: {talep}")
    
    if uygulama_adi:
        cym_parts.append(f"🖥️ Uygulama: {uygulama_adi}")
    
    if talep_tipi:
        cym_parts.append(f"📂 Talep Tipi: {talep_tipi}")
    
    cym_parts.append(f"✅ Önerilen Çözüm: {cozum}")
    
    return '\n'.join(cym_parts)


def _clean_llm_response(response: str) -> str:
    """LLM yanıtını temizler"""
    cleaned = response.strip()
    
    # "Merhaba, ben VYRA" gibi kendini tanıtma kaldır
    if "merhaba" in cleaned.lower()[:50] and "vyra" in cleaned.lower()[:100]:
        lines = cleaned.split('\n')
        if len(lines) > 1:
            cleaned = '\n'.join(lines[1:]).strip()
    
    return cleaned
