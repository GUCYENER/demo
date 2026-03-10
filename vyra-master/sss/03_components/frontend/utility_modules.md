# Yardımcı Modüller — Frontend Bileşen Dokümantasyonu

| Bilgi | Değer |
|-------|-------|
| **Versiyon** | v2.36.1 |
| **Son Güncelleme** | 2026-02-10 |
| **Konum** | `frontend/assets/js/modules/` |
| **Durum** | ✅ Güncel |

---

## 1. Modül Listesi

| Modül | Dosya | Amaç |
|-------|-------|------|
| **Image Lightbox** | `rag_image_lightbox.js` | Görsel büyütme modalı |
| **OCR Popup** | `rag_ocr_popup.js` | OCR metin popup |
| **Sidebar** | `sidebar_module.js` | Sol menü yönetimi |
| **Image Handler** | `image_handler.js` | Genel görsel işlemleri |
| **VPN Handler** | `vpn_handler.js` | VPN bağlantı yardımcısı |
| **Solution Display** | `solution_display.js` | Çözüm görüntüleme |
| **Solution Formatter** | `solution_formatter.js` | Çözüm metin formatlama |

---

## 2. `rag_image_lightbox.js` — Lightbox

### Özellikler
- Tıklama ile tam ekran görsel görüntüleme
- **ESC** tuşu ile kapatma (standart UX)
- Overlay'e tıklama → **KAPATMAZ** (veri kaybı önleme)
- **X** butonu ile kapatma
- Zoom (yakınlaştırma/uzaklaştırma)

### Ana Fonksiyonlar
| Fonksiyon | Açıklama |
|-----------|----------|
| `openLightbox(imgSrc, altText)` | Lightbox'ı aç |
| `closeLightbox()` | Lightbox'ı kapat |
| `initLightboxListeners()` | Event listener'ları ekle |

---

## 3. `rag_ocr_popup.js` — OCR Popup

### Özellikler
- Görselin üzerine hover → **"📝 Metin"** butonu
- Tıklama → Floating popup ile OCR metin gösterimi
- Metin kopyalama butonu
- Loading spinner (OCR yüklenirken)

### Ana Fonksiyonlar
| Fonksiyon | Açıklama |
|-----------|----------|
| `showOCRPopup(imageId, anchorElement)` | Popup'ı göster |
| `fetchOCRText(imageId)` | OCR API'den metin getir |
| `copyOCRText(text)` | Panoya kopyala |
| `hideOCRPopup()` | Popup'ı gizle |

### API Çağrısı
```javascript
// GET /api/rag/images/{imageId}/ocr
const response = await fetch(`/api/rag/images/${imageId}/ocr`, {
    headers: { 'Authorization': `Bearer ${token}` }
});
const data = await response.json();
// data.ocr_text → "Adım 1: VPN'i açın..."
```

---

## 4. `sidebar_module.js` — Sol Menü

### Menü Öğeleri
| Öğe | İkon | Sekme/Sayfa | Yetki |
|-----|------|-------------|-------|
| VYRA'ya Sor | 🤖 | dialog tab | Herkese açık |
| Geçmiş | 📋 | history tab | Herkese açık |
| RAG | 📚 | RAG section | ⚙️ |
| Admin | ⚙️ | Admin section | Admin only |
| Çıkış | 🚪 | login page | Herkese açık |

### Responsive Davranış
- Daraltılabilir (collapse/expand)
- Mobilde hamburger menü
- Aktif sayfa vurgulaması

---

## 5. `image_handler.js` — Genel Görsel İşlemleri

| Fonksiyon | Açıklama |
|-----------|----------|
| `loadImage(url)` | Lazy load görsel |
| `handleImageError(imgElement)` | Fallback görsel |
| `getImageUrl(imageId)` | API URL oluştur |

---

## 6. Genel Kütüphaneler

### `api_client.js`
| Fonksiyon | Açıklama |
|-----------|----------|
| `apiGet(path)` | GET isteği (auto auth header) |
| `apiPost(path, body)` | POST isteği |
| `apiPut(path, body)` | PUT isteği |
| `apiDelete(path)` | DELETE isteği |
| `handleApiError(response)` | Hata yönetimi, token refresh |

### `toast.js`
| Fonksiyon | Açıklama |
|-----------|----------|
| `showToast(message, type)` | Bildirim göster |
| Type: `success` | ✅ Yeşil bildirim |
| Type: `error` | ❌ Kırmızı bildirim |
| Type: `warning` | ⚠️ Sarı bildirim |
| Type: `info` | ℹ️ Mavi bildirim |

### `websocket_client.js`
| Fonksiyon | Açıklama |
|-----------|----------|
| `connect(dialogId)` | WebSocket bağlantısı kur |
| `send(data)` | Mesaj gönder |
| `onMessage(callback)` | Mesaj alım callback |
| `reconnect()` | Otomatik yeniden bağlanma |
