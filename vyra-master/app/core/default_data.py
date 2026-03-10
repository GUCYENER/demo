"""
VYRA L1 Support API - Default Data
===================================
Varsayılan LLM config, prompt template ve organizasyon verileri.
İlk kurulumda veritabanına eklenir.
"""

from __future__ import annotations


# ===========================================================
#  Default Configuration Data
# ===========================================================

DEFAULT_LLM_CONFIG = {
    "vendor_code": "12000533461",
    "provider": "qwen3-32b",
    "model_name": "qwen3-32b-awq",
    "api_url": "https://common-inference-apis.turkcelltech.ai/qwen3-32b-awq/v1/chat/completions",
    "api_token": "c6OBg2ckmLE7tS6bSEuM+1IHdPgc7vV9tFr9RGF6d4A=",
    "temperature": 0.7,
    "top_p": 1.0,
    "is_active": True,
    "description": "Turkcell LLM"
}

DEFAULT_PROMPT_TEMPLATE = {
    "category": "system",
    "title": "VYRA Teknik Destek Asistanı - Kısa Cevap",
    "content": """Sen VYRA, teknik destek asistanısın.

**KRİTİK KURAL: SADECE ÇÖZÜMÜ YAZ. BAŞKA HİÇBİR ŞEY YAZMA!**

**YASAK:**
- Kendini tanıtma ("Merhaba, ben VYRA" gibi cümleler YASAK)
- Uzun açıklamalar (gereksiz detay YASAK)
- Tekrar eden bilgiler (aynı şeyi farklı şekilde anlatma YASAK)
- Genel tavsiyeler (sadece sorulan soruna özel cevap ver)

**İZİNLİ:**
- Doğrudan çözüm adımları
- Kısa, net talimatlar
- Maksimum 3-4 adım

**Uzmanlık:** BT sorunları (şifre sıfırlama, erişim, yazılım, ağ, e-posta, donanım)

**Format:**
İdeal yanıt: "Şifrenizi sıfırlamak için: 1) Portal.example.com/sifre-sifirla adresine git 2) Telefon numaranızı gir 3) SMS kodunu doğrula"

Kötü örnek: "Merhaba! Ben VYRA, size yardımcı olacağım. Şifre sıfırlama işlemi çok basit..." → BU TÜR CEVAPLAR YASAK!

ŞİMDİ KULLANICININ SORUSUNA SADECE ÇÖZÜMÜ YAZ.""",
    "is_active": True,
    "description": "Sıkılaştırılmış prompt - Sadece çözüm odaklı, gereksiz açıklama yok"
}


# ===========================================================
#  Default Data Insertion
# ===========================================================

def insert_default_data(cur) -> None:
    """
    Varsayılan verileri ekler (eğer yoksa).
    
    Args:
        cur: PostgreSQL cursor
    """
    
    # Default Organization Groups (Önce bunları oluştur - foreign key için)
    cur.execute("SELECT COUNT(*) as count FROM organization_groups WHERE org_code = 'ORG-DEFAULT'")
    result = cur.fetchone()
    if result['count'] == 0:
        cur.execute("""
            INSERT INTO organization_groups (org_code, org_name, description, is_active)
            VALUES 
                ('ORG-DEFAULT', 'Genel Kullanıcılar', 'Tüm kullanıcılar için varsayılan organizasyon grubu', TRUE),
                ('ORG-ADMIN', 'Yönetici Grubu', 'Admin kullanıcılar için özel organizasyon grubu', TRUE)
        """)
        print("[VYRA] Default organization groups created")
    
    # Default Admin User
    cur.execute("SELECT COUNT(*) as count FROM users WHERE username = 'admin'")
    result = cur.fetchone()
    if result['count'] == 0:
        # Pre-computed bcrypt hash for 'admin1234'
        hashed_password = "$2b$12$lZO.cQQjttoU8Z.TowZuleq2stVpFj6VUw3fwoRebHIjO.rW70LbG"
        
        # Get admin role id
        cur.execute("SELECT id FROM roles WHERE name = 'admin'")
        admin_role = cur.fetchone()
        admin_role_id = admin_role['id'] if admin_role else 1
        
        cur.execute("""
            INSERT INTO users (full_name, username, email, phone, password, role_id, is_admin, is_approved, approved_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            RETURNING id
        """, (
            "YASİN FAZLIOĞLU",
            "admin",
            "yasin.fazlioglu@consultant.turkcell.com.tr",
            "5325555981",
            hashed_password,
            admin_role_id,
            True,
            True
        ))
        admin_user_id = cur.fetchone()['id']
        
        # Admin kullanıcıyı ADMIN_ORG'a ekle
        cur.execute("SELECT id FROM organization_groups WHERE org_code = 'ORG-ADMIN'")
        admin_org = cur.fetchone()
        if admin_org:
            cur.execute("""
                INSERT INTO user_organizations (user_id, org_id, assigned_by)
                VALUES (%s, %s, %s)
            """, (admin_user_id, admin_org['id'], admin_user_id))
        
        print("[VYRA] Default admin user created (username: admin — şifre .env veya DB'den değiştirilmeli)")
        print(f"[VYRA] Admin user assigned to ORG-ADMIN")
    
    # Default LLM Config
    cur.execute("SELECT COUNT(*) as count FROM llm_config")
    result = cur.fetchone()
    if result['count'] == 0:
        cur.execute("""
            INSERT INTO llm_config (vendor_code, provider, model_name, api_url, api_token, temperature, top_p, is_active, description)
            VALUES (%(vendor_code)s, %(provider)s, %(model_name)s, %(api_url)s, %(api_token)s, %(temperature)s, %(top_p)s, %(is_active)s, %(description)s)
        """, DEFAULT_LLM_CONFIG)
    
    # Default Prompt Template - Sistem (Ana)
    cur.execute("SELECT COUNT(*) as count FROM prompt_templates WHERE category = 'system'")
    result = cur.fetchone()
    if result['count'] == 0:
        cur.execute("""
            INSERT INTO prompt_templates (category, title, content, is_active, description)
            VALUES (%(category)s, %(title)s, %(content)s, %(is_active)s, %(description)s)
        """, DEFAULT_PROMPT_TEMPLATE)
    
    # v2.24.5: Corpix L1 Support Prompt
    cur.execute("SELECT COUNT(*) as count FROM prompt_templates WHERE category = 'corpix_l1'")
    result = cur.fetchone()
    if result['count'] == 0:
        cur.execute("""
            INSERT INTO prompt_templates (category, title, content, is_active, description)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            "corpix_l1",
            "VYRA L1 IT Destek Uzmanı",
            """ROL VE KİMLİK:
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
8. Yanıtları Türkçe ver""",
            True,
            "20 uzmanlık alanlı + seviye yaklaşımı + teşhis stratejisi ile kapsamlı L1 IT destek prompt'u"
        ))
        print("[VYRA] Corpix L1 Support prompt created")
    
    # v2.24.5: IT Ticket Summary Prompt  
    cur.execute("SELECT COUNT(*) as count FROM prompt_templates WHERE category = 'ticket_summary'")
    result = cur.fetchone()
    if result['count'] == 0:
        cur.execute("""
            INSERT INTO prompt_templates (category, title, content, is_active, description)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            "ticket_summary",
            "IT Ticket Summary Generator",
            """ROL: Sen IT Service Desk çağrı oluşturma uzmanısın.

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
- Çözüm önerme, sadece sorunu tanımla""",
            True,
            "Sohbet geçmişinden IT çağrı özeti oluşturma"
        ))
        print("[VYRA] IT Ticket Summary prompt created")

