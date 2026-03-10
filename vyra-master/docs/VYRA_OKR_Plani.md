# 📋 VYRA L1 Destek Platformu — OKR Planı

> **Proje:** VYRA (Çözümü Burada Ara) — AI Destekli L1 IT Destek Asistanı  
> **Metodoloji:** OKR (Objective & Key Results)  
> **Hedef Kitle:** L1 Çağrı Merkezi Destek Ekibi  
> **Tarih:** 18 Şubat 2026  

---

## 📊 OKR Puanlama Ölçeği

| Puan | Anlam | Açıklama |
|------|-------|----------|
| **1.0** | 🔴 Başlanmadı | Hiçbir ilerleme yok |
| **2.0** | 🟠 Başlangıç | Çalışmaya başlandı, erken aşamada |
| **3.0** | 🟡 Orta Düzey | İlerleme var ama hedefin altında |
| **4.0** | 🟢 İyi | Hedefin büyük bölümü karşılandı |
| **5.0** | 🏆 Mükemmel | Hedef tam olarak veya üstünde karşılandı |

> **Not:** OKR'de ideal hedef puanı **3.5 - 4.5** arasıdır. 5.0 almak hedefin yeterince iddialı olmadığını gösterebilir. 1.0-2.0 almak ise yeniden planlama gerektiğini ifade eder.

---

## 🟦 FAZ 1 — Giriş: Projenin Özetlenmesi

### 🎯 Objective (Amaç)
**L1 destek ekibinin tekrarlayan IT sorunlarını hızlıca çözmesini sağlayan bir AI asistan sistemi oluşturmak.**

### Neden Bu Proje?
- L1 destek ekipleri her gün aynı soruları tekrar tekrar yanıtlar (VPN bağlantı sorunu, Outlook ayarları, şifre sıfırlama vb.)
- Çözüm bilgileri farklı Excel, PDF ve Word dosyalarında dağınık durumda
- Yeni başlayan personelin bilgiye ulaşması uzun zaman alıyor
- **Çözüm:** Tüm dökümanları tek bir yerde toplayıp, kullanıcı sorusuna en doğru cevabı otomatik olarak bulup sunan bir AI sistemi

### 📌 Key Results (Temel Sonuçlar)

| # | Key Result | Başarı Kriteri | OKR Puanı |
|---|-----------|----------------|-----------|
| KR 1.1 | Proje amacı ve kapsamı net bir şekilde tanımlandı | Proje tanıtım belgesi hazırlandı ve ekiple paylaşıldı | **5.0** 🏆 |
| KR 1.2 | Hedef kullanıcı profili belirlendi | L1 destek ajanı persona dokümanı oluşturuldu (kim, ne yapar, neye ihtiyaç duyar) | **5.0** 🏆 |
| KR 1.3 | Çözülecek problem net olarak ifade edildi | "Dağınık bilgiye hızlı erişim" problemi, somut örneklerle belgelendi | **5.0** 🏆 |
| KR 1.4 | Proje başarı metrikleri tanımlandı | Yanıt süresi, doğruluk oranı, kullanıcı memnuniyeti hedefleri belirlendi | **4.0** 🟢 |

> **Faz 1 Ortalama OKR Puanı: 4.75 / 5.0** 🏆

---

## 🟦 FAZ 2 — Kavramların Araştırılması

### 🎯 Objective (Amaç)
**Projenin kullandığı temel teknolojileri ve kavramları anlamak, ekibin bu kavramları bilmesi gereken düzeyde öğrenmesini sağlamak.**

### Araştırılacak Kavramlar (Basit Açıklamalar)

| Kavram | Ne Anlama Geliyor? | Neden Lazım? |
|--------|---------------------|--------------|
| **RAG** (Retrieval-Augmented Generation) | "Dökümanlardan bilgi bul + AI ile cevap üret" sistemi. Önce ilgili bilgiyi bulur, sonra AI bu bilgiyi kullanarak yanıt oluşturur. | Destek ekibinin dosyalarda arama yapmadan doğru cevabı bulabilmesi için |
| **LLM** (Large Language Model) | ChatGPT gibi büyük dil modeli. Metin anlayan ve üreten yapay zeka. | Bulunan bilgiyi düzenleyip anlaşılır bir cevap olarak sunmak için |
| **Embedding** | Metni sayılara (vektörlere) çevirme işlemi. Her kelimenin/cümlenin bir "sayısal parmak izi" oluşur. | İki metnin ne kadar benzer olduğunu bilgisayarın anlayabilmesi için |
| **Cosine Similarity** | İki metnin birbirine ne kadar benzediğini ölçen matematiksel yöntem. 1.0 = aynı, 0.0 = hiç alakasız. | Kullanıcının sorusu ile döküman parçaları arasındaki benzerliği hesaplamak için |
| **Chunk** (Parça) | Büyük dökümanların küçük, anlamlı parçalara bölünmesi. Örneğin 50 sayfalık bir PDF → 100 küçük metin parçası. | AI'ın büyük dökümanları işleyememesi sorunu. Küçük parçalar daha iyi sonuç verir |
| **Vector Database** | Embedding'lerin (sayısal parmak izlerinin) saklandığı özel veritabanı. | Hızlı benzerlik araması yapmak için |
| **PostgreSQL** | Güvenilir, güçlü bir veritabanı sistemi. Hem normal verileri hem de vektörleri saklıyor. | Tüm verilerin (kullanıcılar, dökümanlar, sohbet geçmişi) tutulması için |
| **FastAPI** | Python ile hızlı web API geliştirme çerçevesi. Backend'in üzerine kurulduğu platform. | Ön yüz ile arka plan arasındaki iletişimi sağlamak için |
| **BM25** | Anahtar kelime tabanlı arama algoritması. Google'ın ilk yıllarında kullandığı yönteme benzer. | Tam kelime eşleşmesi ile sonuç bulmak için (semantik aramanın tamamlayıcısı) |
| **Hybrid Search** | Semantik (anlam) + Leksikal (kelime) aramanın birlikte kullanılması. | Tek başına anlam araması veya kelime araması yetersiz kalabilir; ikisinin birleşimi en iyi sonucu verir |

### 📌 Key Results (Temel Sonuçlar)

| # | Key Result | Başarı Kriteri | OKR Puanı |
|---|-----------|----------------|-----------|
| KR 2.1 | RAG kavramı ekip tarafından anlaşıldı | "Bul + Üret" mantığı örneklerle açıklandı, ekip sunumu yapıldı | **5.0** 🏆 |
| KR 2.2 | LLM ve Embedding kavramları öğrenildi | Embedding = "metnin sayısal parmak izi" anlayışı oluştu, demo gösterildi | **4.0** 🟢 |
| KR 2.3 | Hibrit arama mantığı (BM25 + Semantik) kavrandı | Neden iki yöntemin birlikte kullanıldığı belgelendi | **4.0** 🟢 |
| KR 2.4 | Teknoloji stack'i araştırması tamamlandı | FastAPI, PostgreSQL ve SentenceTransformers tercihleri gerekçelendirildi | **5.0** 🏆 |
| KR 2.5 | Rakip/benzer çözümler incelendi | En az 3 alternatif araç değerlendirildi (ChatGPT, özel çözümler vb.) | **4.0** 🟢 |

> **Faz 2 Ortalama OKR Puanı: 4.40 / 5.0** 🟢

---

## 🟦 FAZ 3 — Tasarım Süreci: Mimari & Algoritma

### 🎯 Objective (Amaç)
**Sistemin teknik mimarisini, veri akışını ve temel algoritmalarını tasarlayarak geliştirme sürecine hazır hale getirmek.**

### Mimari Tasarım Özeti

```
┌─────────────────────────────────────────────────────┐
│                    KULLANICI                         │
│              (L1 Destek Ajanı)                      │
│         "VPN bağlantı hatası nasıl çözülür?"        │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│              FRONTEND (Tarayıcı)                     │
│   ┌──────────┐  ┌───────────┐  ┌────────────────┐   │
│   │ Sohbet   │  │ Dosya     │  │ Geçmiş         │   │
│   │ Ekranı   │  │ Yükleme   │  │ Çözümler       │   │
│   └──────────┘  └───────────┘  └────────────────┘   │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP / WebSocket
                       ▼
┌──────────────────────────────────────────────────────┐
│              BACKEND (FastAPI)                        │
│                                                      │
│  1️⃣ SORU GELDİ                                      │
│     │                                                │
│  2️⃣ SMART ROUTER (~10ms)                            │
│     "Bu soru RAG aramaya uygun mu?"                  │
│     │                                                │
│  3️⃣ RAG ARAMA (Hibrit)                              │
│     ├── Semantik Arama (anlam benzerliği)            │
│     ├── BM25 Arama (kelime eşleşmesi)               │
│     └── Sonuçları birleştir (RRF Fusion)             │
│     │                                                │
│  4️⃣ ML RERANKING (CatBoost)                         │
│     "En iyi sonuçları üste çıkar"                    │
│     │                                                │
│  5️⃣ LLM SENTEZİ (Deep Think)                        │
│     "Bulunan bilgiyi düzenle, cevap yaz"             │
│     │                                                │
│  6️⃣ YANIT → Kullanıcıya gönder                      │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│              VERİTABANI (PostgreSQL)                  │
│                                                      │
│  📄 uploaded_files  → Yüklenen dökümanlar            │
│  🧩 rag_chunks     → Döküman parçaları + embedding   │
│  👤 users          → Kullanıcı bilgileri              │
│  💬 dialogs        → Sohbet oturumları               │
│  📝 dialog_messages→ Mesajlar                         │
│  🎫 tickets        → Destek talepleri                 │
└──────────────────────────────────────────────────────┘
```

### Temel Algoritma Akışı

```
Adım 1: DÖKÜMAN YÜKLEME
   PDF/DOCX dosyası → Metne çevir → Küçük parçalara böl (chunk)
   → Her parçayı sayıya çevir (embedding) → Veritabanına kaydet

Adım 2: SORU SORMA
   Soru metni → Sayıya çevir (embedding)
   → Veritabanındaki tüm parçalarla karşılaştır
   → En benzer parçaları bul (skor hesapla)
   → Sonuçları sırala

Adım 3: CEVAP ÜRETME
   En iyi parçalar + Kullanıcı sorusu → LLM'e gönder
   → LLM düzenli, anlaşılır bir cevap üretir
   → Kullanıcıya göster
```

### 📌 Key Results (Temel Sonuçlar)

| # | Key Result | Başarı Kriteri | OKR Puanı |
|---|-----------|----------------|-----------|
| KR 3.1 | Sistem mimarisi diyagramı oluşturuldu | Frontend → Backend → Veritabanı akışı görselleştirildi | **5.0** 🏆 |
| KR 3.2 | Veritabanı şeması tasarlandı | Temel tablolar (users, uploaded_files, rag_chunks, dialogs) tanımlandı | **5.0** 🏆 |
| KR 3.3 | RAG arama algoritması tasarlandı | Embedding → Cosine Similarity → Sıralama akışı belgelendi | **4.0** 🟢 |
| KR 3.4 | Döküman işleme stratejisi belirlendi | PDF ve DOCX için chunk boyutu (500 karakter) ve overlap (100 karakter) belirlendi | **4.0** 🟢 |
| KR 3.5 | API endpoint tasarımı yapıldı | Yükleme, arama, sohbet, kullanıcı yönetimi endpointleri listelendi | **5.0** 🏆 |
| KR 3.6 | Güvenlik tasarımı tamamlandı | JWT token, rate limiting, kullanıcı onay akışı planlandı | **4.0** 🟢 |

> **Faz 3 Ortalama OKR Puanı: 4.50 / 5.0** 🟢

---

## 🟦 FAZ 4 — MVP Basit: Döküman Yükleme + RAG ile Doğru Yanıtı Bulma

### 🎯 Objective (Amaç)
**PDF ve DOCX dosyalarını sisteme yükleyebilen, kullanıcının sorusuna RAG ile en doğru döküman parçasını bulup gösteren ilk çalışan prototipi oluşturmak.**

### Bu Fazda Ne Var?
- ✅ PDF ve DOCX dosyalarını yükleme ekranı
- ✅ Dosyaları otomatik olarak parçalara (chunk) bölme
- ✅ Her parçayı embedding'e çevirip veritabanına kaydetme
- ✅ Kullanıcının soru yazabileceği basit bir arayüz
- ✅ Soruya en benzer döküman parçalarını bulup listeleme
- ❌ Bu aşamada LLM sentezi YOK — sadece en benzer parçalar gösteriliyor

### Bu Fazda Ne YOK?
- ❌ LLM ile cevap iyileştirme (Faz 5'te)
- ❌ Çok turlu sohbet
- ❌ Excel/PPTX desteği
- ❌ ML reranking

### Görsel Akış

```
┌────────────────────────────────────────────────────┐
│   📤 DÖKÜMAN YÜKLEME EKRANI                       │
│                                                    │
│   [Dosya Seç: VPN_Çözümleri.pdf  ]  [📤 Yükle]    │
│                                                    │
│   ✅ Dosya yüklendi!                               │
│   → 45 parçaya bölündü                             │
│   → Embedding'ler oluşturuldu                      │
│   → Veritabanına kaydedildi                        │
└────────────────────────────────────────────────────┘

             ↓ Yükleme tamamlandıktan sonra ↓

┌────────────────────────────────────────────────────┐
│   🔍 SORU SORMA EKRANI                            │
│                                                    │
│   Sorunuzu yazın:                                  │
│   ┌──────────────────────────────────┐  ┌───────┐  │
│   │ VPN bağlanamıyorum ne yapmalıyım │  │ Ara 🔍│  │
│   └──────────────────────────────────┘  └───────┘  │
│                                                    │
│   📋 EN YAKIN SONUÇLAR:                             │
│   ┌────────────────────────────────────────────┐   │
│   │ 📄 VPN_Çözümleri.pdf — Parça #12          │   │
│   │ Skor: %87                                  │   │
│   │ "VPN bağlantı hatası alıyorsanız, önce     │   │
│   │  ağ ayarlarını kontrol edin. Ardından..."   │   │
│   └────────────────────────────────────────────┘   │
│   ┌────────────────────────────────────────────┐   │
│   │ 📄 Ağ_Sorunları.docx — Parça #7           │   │
│   │ Skor: %72                                  │   │
│   │ "Cisco AnyConnect VPN istemcisini           │   │
│   │  yeniden başlatın..."                       │   │
│   └────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────┘
```

### Yazılımsal İmplementasyon Özeti

| Bileşen | Kullanılan Teknoloji | Açıklama |
|---------|---------------------|----------|
| Dosya Yükleme API | FastAPI + python-docx + pypdf | Dosyayı alır, metin çıkarır |
| Chunk'lama | Python (Recursive Splitter) | 500 karakter, 100 overlap ile parçalar |
| Embedding Üretimi | SentenceTransformers (MiniLM-L12) | Her chunk → 384 boyutlu vektör |
| Veritabanı Kayıt | PostgreSQL (FLOAT[]) | Vektörleri normal array olarak saklar |
| Arama API | FastAPI + NumPy | Soru embedding → cosine similarity ile eşleştir |
| Arayüz | Vanilla HTML/CSS/JS | Basit yükleme ve arama ekranı |

### 📌 Key Results (Temel Sonuçlar)

| # | Key Result | Başarı Kriteri | OKR Puanı |
|---|-----------|----------------|-----------|
| KR 4.1 | PDF dosyaları başarıyla yüklenip parçalanıyor | En az 3 farklı PDF yüklenip chunk'ları veritabanında doğrulandı | **5.0** 🏆 |
| KR 4.2 | DOCX dosyaları başarıyla yüklenip parçalanıyor | En az 3 farklı DOCX yüklenip chunk'ları veritabanında doğrulandı | **5.0** 🏆 |
| KR 4.3 | Embedding vektörleri doğru üretiliyor | Her chunk için 384-dim vektör oluşturulduğu doğrulandı | **5.0** 🏆 |
| KR 4.4 | Kullanıcı sorusuna en benzer 5 sonuç gösteriliyor | Benzerlik skoru %50 üzeri olan sonuçlar sıralı listeleniyor | **4.0** 🟢 |
| KR 4.5 | Arama süresi 3 saniyenin altında | 100 chunk'lık veritabanında ortalama arama süresi ölçüldü | **4.0** 🟢 |
| KR 4.6 | Basit ve kullanılabilir bir arayüz mevcut | Dosya yükleme + soru sorma ekranı çalışır durumda | **4.0** 🟢 |
| KR 4.7 | Doğruluk oranı kabul edilebilir düzeyde | Manuel test ile 10 sorudan en az 6'sında doğru parça ilk 3'te | **3.5** 🟡 |

> **Faz 4 Ortalama OKR Puanı: 4.36 / 5.0** 🟢

---

## 🟦 FAZ 5 — MVP Orta Düzey: RAG + LLM ile Yanıt İyileştirme

### 🎯 Objective (Amaç)
**RAG ile bulunan döküman parçalarını LLM'e (yapay zeka dil modeli) göndererek, ham metin parçaları yerine düzenli, anlaşılır ve profesyonel cevaplar üretmek.**

### Bu Fazda Ne Ekleniyor?
- ✅ Bulunan RAG sonuçları → LLM'e gönderiliyor
- ✅ LLM sonuçları sentezleyip adım adım çözüm üretiyor
- ✅ Yanıt formatı profesyonelleştiriliyor (numaralı adımlar, başlıklar)
- ✅ Kaynak bilgisi yanıta ekleniyor ("Bu bilgi VPN_Çözümleri.pdf dosyasından alınmıştır")
- ✅ Birden fazla parçadan bilgi birleştirilip tek tutarlı cevap oluşturuluyor

### Faz 4 vs Faz 5 Karşılaştırması

| Özellik | Faz 4 (MVP Basit) | Faz 5 (MVP Orta) |
|---------|-------------------|-------------------|
| Arama | ✅ RAG ile parça bulma | ✅ RAG ile parça bulma |
| Sonuç Gösterimi | Ham döküman parçaları | **LLM ile düzenlenmiş profesyonel cevap** |
| Birden Fazla Kaynaktan Birleştirme | ❌ Yok | **✅ LLM farklı parçaları sentezliyor** |
| Adım Adım Talimatlar | ❌ Yok | **✅ Numaralı adımlar halinde** |
| Kaynak Referansı | Dosya adı gösterilir | **✅ "📁 Kaynak: dosya_adı" formatında** |
| Kullanıcı Deneyimi | Teknik, ham metin | **Premium, anlaşılır format** |

### Görsel Akış (Faz 5 — LLM Sentez Sonrası)

```
┌────────────────────────────────────────────────────┐
│   💬 VYRA SOHBET EKRANI                            │
│                                                    │
│   👤 Kullanıcı:                                    │
│   "VPN bağlantım sürekli kopuyor, ne yapmalıyım?" │
│                                                    │
│   🤖 VYRA:                                        │
│   ┌────────────────────────────────────────────┐   │
│   │ 🔧 VPN Bağlantı Kopma Sorunu - Çözüm      │   │
│   │                                            │   │
│   │ 1️⃣ Ağ Bağlantısını Kontrol Edin            │   │
│   │    Wi-Fi sinyal gücünüzü kontrol edin.     │   │
│   │    Mümkünse kablolu bağlantı kullanın.     │   │
│   │                                            │   │
│   │ 2️⃣ VPN İstemcisini Yeniden Başlatın         │   │
│   │    Cisco AnyConnect'i kapatıp tekrar açın. │   │
│   │    Bağlantı profilini yeniden seçin.       │   │
│   │                                            │   │
│   │ 3️⃣ DNS Ayarlarını Sıfırlayın               │   │
│   │    CMD açın → ipconfig /flushdns yazın     │   │
│   │    → ipconfig /renew ile IP yenileyin      │   │
│   │                                            │   │
│   │ 📁 Kaynaklar:                               │   │
│   │ • VPN_Çözümleri.pdf - Sayfa 12             │   │
│   │ • Ağ_Sorunları.docx - Bölüm 3             │   │
│   └────────────────────────────────────────────┘   │
│                                                    │
│   [👍 Faydalı]  [👎 Yetersiz]                      │
│                                                    │
│   ┌──────────────────────────────────┐  ┌───────┐  │
│   │ Başka bir sorunuz var mı?        │  │Gönder │  │
│   └──────────────────────────────────┘  └───────┘  │
└────────────────────────────────────────────────────┘
```

### LLM Sentez Algoritması

```
ADIM 1: RAG SONUÇLARINI TOPLA
   → En iyi 5-10 döküman parçasını al
   → Skorlarına göre sırala

ADIM 2: BAĞLAM HAZIRLA
   → Parçaları birleştir
   → Kaynak bilgilerini ekle
   → Soru tipini tespit et (liste? adım adım? sorun giderme?)

ADIM 3: LLM'E GÖNDER
   Prompt = "Sen bir L1 IT destek asistanısın.
             Aşağıdaki bilgilere dayanarak soruyu yanıtla.
             Adım adım talimatlar ver.
             Kaynak dosya adlarını belirt."
   + Bağlam (RAG parçaları)
   + Kullanıcı sorusu

ADIM 4: YANITI İŞLE
   → LLM'den gelen cevabı formatla
   → Numaralı adımlara dönüştür
   → Kaynak referansları ekle
   → Kullanıcıya göster
```

### 📌 Key Results (Temel Sonuçlar)

| # | Key Result | Başarı Kriteri | OKR Puanı |
|---|-----------|----------------|-----------|
| KR 5.1 | LLM API entegrasyonu tamamlandı | En az 1 LLM sağlayıcısı (Gemini veya OpenAI) başarıyla bağlandı | **5.0** 🏆 |
| KR 5.2 | RAG sonuçları LLM'e bağlam olarak gönderiliyor | Bulunan parçalar prompt'a ekleniyor ve LLM bunları kullanarak cevap üretiyor | **5.0** 🏆 |
| KR 5.3 | LLM yanıtları profesyonel formatta | Adım adım talimatlar, başlıklar ve kaynak referansları içeriyor | **4.0** 🟢 |
| KR 5.4 | Birden fazla kaynaktan bilgi sentezleniyor | Farklı dosyalardan gelen parçalar tutarlı tek cevaba dönüştürülüyor | **4.0** 🟢 |
| KR 5.5 | Yanıt süresi kabul edilebilir düzeyde (<15 sn) | RAG arama + LLM sentez toplam süresi ölçüldü ve 15 sn altı | **3.5** 🟡 |
| KR 5.6 | Doğruluk oranı belirgin şekilde arttı | Manuel test ile 10 sorudan en az 8'inde doğru ve faydalı cevap | **4.0** 🟢 |
| KR 5.7 | Halüsinasyon (uydurma) oranı düşük | LLM'in döküman dışı bilgi üretmediği 10 test ile doğrulandı | **3.5** 🟡 |
| KR 5.8 | Kullanıcı geri bildirimi mekanizması eklendi | 👍/👎 butonları ile kullanıcı memnuniyeti toplanıyor | **4.0** 🟢 |

> **Faz 5 Ortalama OKR Puanı: 4.0 / 5.0** 🟢

---

## 📊 GENEL OKR SKOR TABLOSU

| Faz | Başlık | Ortalama OKR | Durum |
|-----|--------|:------------:|-------|
| **Faz 1** | Giriş — Proje Özetleme | **4.75** | 🏆 Mükemmel |
| **Faz 2** | Kavramların Araştırılması | **4.40** | 🟢 İyi |
| **Faz 3** | Tasarım — Mimari & Algoritma | **4.50** | 🟢 İyi |
| **Faz 4** | MVP Basit — RAG Arama | **4.36** | 🟢 İyi |
| **Faz 5** | MVP Orta — RAG + LLM Sentez | **4.00** | 🟢 İyi |
| | **PROJE GENEL OKR** | **4.40** | **🟢 İyi** |

### Genel Değerlendirme
- **Faz 1-3** (Planlama & Tasarım): Güçlü temel atıldı, kavramlar ve mimari net ✅
- **Faz 4** (MVP Basit): RAG araması çalışıyor ancak doğruluk optimizasyonu devam ediyor 🔄
- **Faz 5** (MVP Orta): LLM sentezi çalışıyor, yanıt süreleri ve halüsinasyon kontrolü iyileştirmeye açık 🔄

### Sonraki Adımlar (Faz 6+)
Eldeki MVP üzerinden ilerlenebilecek konular:
- 🔄 Excel/PPTX dosya desteği ekleme
- 🔄 CatBoost ML reranking ile sıralama iyileştirme
- 🔄 Çok turlu sohbet (dialog) desteği
- 🔄 Multi-tenant organizasyon izolasyonu
- 🔄 WebSocket ile gerçek zamanlı bildirimler
- 🔄 Otonom ML model yeniden eğitimi

---

> 📝 **Not:** Bu OKR planı, VYRA projesinin L1 destek ekibi perspektifinden anlaşılabilir şekilde hazırlanmıştır. Her faz bağımsız olarak değerlendirilebilir ve gerektiğinde hedefler güncellenebilir.
