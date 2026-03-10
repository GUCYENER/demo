# Soru Sorma ve Dialog Yönetimi

| Bilgi | Değer |
|-------|-------|
| **Versiyon** | v2.36.1 |
| **Son Güncelleme** | 2026-02-10 |
| **Durum** | ✅ Güncel |

---

## 1. VYRA'ya Sor (AI Chatbot)

"VYRA'ya Sor" sekmesi, yapay zeka destekli soru-cevap arayüzüdür. VPN, Outlook, ağ sorunları ve benzeri IT konularında anlık çözüm almanızı sağlar.

### Soru Sorma Adımları
1. Ana sayfada **"🤖 VYRA'ya Sor"** sekmesinin aktif olduğundan emin olun
2. Alt taraftaki metin kutusuna sorunuzu yazın
3. **Enter** tuşuna basın veya **Gönder** butonuna tıklayın
4. VYRA yapay zekası yanıtınızı oluşturur

### Soru Örnekleri
| Soru | Beklenen Yanıt Tipi |
|------|---------------------|
| "VPN nasıl bağlanırım?" | Adım adım kılavuz |
| "Outlook şifremi unuttum" | Şifre sıfırlama talimatları |
| "Excel dosyam açılmıyor" | Sorun giderme rehberi |
| "Ağ ayarlarını nasıl kontrol ederim?" | Komut listesi |

---

## 2. Yanıt Yapısı

VYRA yanıtları zengin formatta sunulur:

### Yanıt Bileşenleri
| Bileşen | Açıklama | Görünüm |
|---------|----------|---------|
| **Çözüm Metni** | Ana yanıt içeriği | Markdown formatında |
| **Kaynak Referansları** | Bilginin alındığı doküman | 📚 altında listelenir |
| **Görseller** | Varsa ilgili ekran görüntüleri | Inline olarak gösterilir |
| **Güven Skoru** | Yanıtın doğruluk oranı | Yıldız veya bar olarak |

### Görsel Özellikler
- **Lightbox:** Görsele tıklayarak büyütülmüş görünüm
- **OCR Metin:** Görsel üzerindeki metinleri 📝 butonuyla görebilirsiniz
- **Hover Menu:** Görselin üzerine geldiğinizde büyütme ve OCR butonları görünür

---

## 3. Sesli Mesaj 🎤

VYRA'ya yazarak olduğu gibi konuşarak da soru sorabilirsiniz.

### Kullanım
1. Mesaj kutusunun yanındaki **🎤 mikrofon** ikonuna tıklayın
2. Konuşmaya başlayın
3. Bittiğinde tekrar tıklayın veya otomatik durur
4. Metin otomatik olarak mesaj kutusuna yazılır
5. Göndermek için Enter'a basın

### Desteklenen Diller
- Türkçe (varsayılan)

---

## 4. Quick Reply (Hızlı Yanıtlar)

Bazı sorularda VYRA size hazır butonlar sunar:

| Quick Reply Tipi | Açıklama |
|------------------|----------|
| Evet / Hayır | Onay gereken durumlarda |
| Çağrı Aç | Destek talebi oluşturma |
| Daha Fazla Bilgi | Ek detay isteme |

---

## 5. Dialog Geçmişi

### Mevcut Dialog
- Her oturum bir "dialog" oluşturur
- Sol panelden önceki dialoglarınızı görebilirsiniz

### Dialog Durumları
| Durum | Açıklama |
|-------|----------|
| **Açık** | Aktif konuşma devam ediyor |
| **Kapalı** | Konuşma sonlandırılmış |

### Geçmişe Erişim
1. Sol paneldeki **dialog listesinden** önceki konuşmalarınızı seçin
2. Veya **"Geçmiş Çözümler"** sekmesine tıklayın

---

## 6. Geri Bildirim

Her yanıttan sonra **geri bildirim** verebilirsiniz:

| Aksiyon | İkon | Açıklama |
|---------|------|----------|
| Beğen | 👍 | Yanıt faydalıydı |
| Beğenme | 👎 | Yanıt yetersizdi |

Geri bildirimleriniz ML modelinin öğrenmesine katkı sağlar.

---

## 7. Destek Talebi Oluşturma (Dialog Üzerinden)

Eğer VYRA'nın yanıtı sorununuzu çözmezse:
1. Yanıttaki **"Çağrı Aç"** butonuna tıklayın
2. Ticket otomatik olarak oluşturulur
3. Dialog içeriği ticket'a eklenir

> 📌 Detaylı ticket yönetimi için: [Destek Talepleri](destek_talepleri.md)

---

> 📌 Sonraki adım: [RAG Bilgi Bankası](rag_bilgi_bankasi.md)
