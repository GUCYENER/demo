# Destek Talepleri (Ticket Sistemi)

| Bilgi | Değer |
|-------|-------|
| **Versiyon** | v2.36.1 |
| **Son Güncelleme** | 2026-02-10 |
| **Durum** | ✅ Güncel |

---

## 1. Genel Bakış

VYRA'nın yapay zeka yanıtı sorununuzu çözmezse, bir destek talebi (ticket) oluşturabilirsiniz. Ticket'lar CYM (Çağrı Yönetim Merkezi) sistemine aktarılır.

---

## 2. Ticket Oluşturma

### Dialog Üzerinden (Önerilen Yol)
1. VYRA'ya sorunuzu sorun
2. Yanıt yetersizse, **"Çağrı Aç"** butonuna tıklayın
3. Ticket otomatik olarak oluşturulur
4. Dialog içeriği ticket'a eklenir

### Önemli Bilgiler
| Bilgi | Açıklama |
|-------|----------|
| Ticket No | Otomatik atanır (#60, #61, ...) |
| Durum | Açık → Çözüm → Kapalı |
| Atama | İlgili birime otomatik yönlendirilir |

---

## 3. Geçmiş Çözümler

**"Geçmiş Çözümler"** sekmesinden tüm ticket geçmişinizi görebilirsiniz.

### Ticket Listesi
Her ticket kartında şu bilgiler görünür:

| Alan | Açıklama |
|------|----------|
| Ticket No | Benzersiz numara |
| Konu | Sorunun özeti |
| Durum | Açık / Çözüldü / Kapalı |
| Tarih | Oluşturulma tarihi |
| Kategori | VPN, Outlook, Ağ vb. |

### Filtreleme
- **Tarih aralığı:** Başlangıç ve bitiş tarihi seçerek filtreleme
- **Durum:** Tüm / Açık / Kapalı

---

## 4. Ticket Detayı

Bir ticket'a tıkladığınızda:

### Görüntülenen Bilgiler
| Bölüm | İçerik |
|--------|--------|
| **Soru** | Kullanıcının sorduğu orijinal soru |
| **Çözüm** | VYRA'nın oluşturduğu yanıt |
| **CYM Bilgisi** | Ticket sistem bilgileri |
| **Zaman Çizelgesi** | Ticket durumundaki değişiklikler |

### Chat Görünümü
Ticket detayında dialog formatındaki mesajları görebilirsiniz:
- 👤 Kullanıcı mesajları (sağda)
- 🤖 VYRA yanıtları (solda)

---

## 5. LLM Değerlendirme

Her ticket için LLM değerlendirmesi görüntülenebilir:

| Değerlendirme | Açıklama |
|---------------|----------|
| Doğruluk | Yanıtın teknik doğruluğu |
| Bütünlük | Yanıtın eksiksizliği |
| Uygunluk | Soruyla ilgisi |

---

## 6. Bildirimler

Ticket durumu değiştiğinde bildirim alırsınız:
- 🔔 Sağ üst köşedeki bildirim ikonunda sayı artar
- Bildirime tıklayarak ilgili ticket'a gidebilirsiniz

---

> 📌 Sonraki adım: [Admin Paneli](admin_paneli.md)
