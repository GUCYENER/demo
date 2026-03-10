# Kod Standartları — Geliştirici Rehberi

| Bilgi | Değer |
|-------|-------|
| **Versiyon** | v2.36.1 |
| **Son Güncelleme** | 2026-02-10 |
| **Durum** | ✅ Güncel |

---

## 1. Genel Prensipler

| Prensip | Açıklama |
|---------|----------|
| **Modülerlik** | Backend ve frontend kodu modüler yapıda |
| **DRY** | Tekrar eden kod yok |
| **SRP** | Her modül tek sorumluluk |
| **Regresyon önleme** | Mevcut çalışan kod bozulmamalı |

---

## 2. CSS Standartları

### ❌ Inline CSS Yasak
```html
<!-- ❌ YANLIŞ — KESİNLİKLE YASAK -->
<div style="color: red; margin: 10px;">İçerik</div>

<!-- ✅ DOĞRU — Harici CSS -->
<div class="error-message">İçerik</div>
```

### CSS Dosya Organizasyonu
| Dosya | Amaç |
|-------|------|
| `global.css` | Genel stiller, CSS değişkenleri |
| `home.css` | Ana sayfa düzeni |
| `login.css` | Giriş sayfası |
| `modal.css` | Modal/popup stiller |
| `dialog-chat.css` | Chat arayüzü |
| `modules/*.css` | Modül-spesifik stiller |

### CSS Değişkenleri (Custom Properties)
Mevcut CSS değişkenlerini kullanın, yeni renk oluşturmayın:
```css
/* Mevcut değişkenler */
var(--primary-color)
var(--secondary-color)
var(--bg-dark)
var(--text-light)
var(--border-color)
```

### İstisna: Dinamik Değerler
```javascript
// ✅ Sadece runtime hesaplanan değerler için inline style KABUL
element.style.width = calculatedWidth + 'px';
element.style.transform = `translateX(${offset}px)`;
```

---

## 3. Modern SaaS Tasarım

Yeni ekranlar Modern SaaS tasarım diline uygun olmalı:
- ✅ Ferah layout (whitespace kullanımı)
- ✅ Tutarlı renk paleti
- ✅ Responsive yapı
- ✅ Hover efektleri ve geçiş animasyonları
- ❌ Hantal "Bootstrap varsayılanı" görünüm

---

## 4. Modal/Popup Standartları

| Kural | Uygulama |
|-------|----------|
| ESC kapatma | ✅ Zorunlu — `keydown` listener |
| Overlay tıklama | ❌ KAPATMAZ — veri kaybını önleme |
| Kapat butonu | ✅ Zorunlu — X veya İptal butonu |

```javascript
// ✅ DOĞRU — Standart modal davranışı
modal.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
});

overlay.addEventListener('click', (e) => {
    // Overlay tıklamada KAPATMA — veri kaybını önle
    e.stopPropagation();
});
```

---

## 5. Backend Standartları

### Loglama (Zorunlu)
```python
# ✅ Her route'da request/response loglama
@router.post("/api/example")
async def example_endpoint(request: Request):
    logger.info(f"[API] POST /api/example - user_id: {user_id}")
    try:
        result = process()
        logger.info(f"[API] POST /api/example - success")
        return result
    except Exception as e:
        logger.error(f"[API] POST /api/example - error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

### Hata Yönetimi (Zorunlu)
```python
# ✅ Try/Catch blokları eksiksiz
try:
    result = risky_operation()
except SpecificError as e:
    logger.error(f"Spesifik hata: {e}")
    raise HTTPException(status_code=400, detail="Anlaşılır mesaj")
except Exception as e:
    logger.error(f"Beklenmeyen hata: {e}")
    raise HTTPException(status_code=500, detail="Sunucu hatası")
```

### SQL Güvenliği
```python
# ✅ DOĞRU — Parameterized query
cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))

# ❌ YANLIŞ — String interpolation
cur.execute(f"SELECT * FROM users WHERE id = {user_id}")
```

---

## 6. Frontend JavaScript Standartları

### Modül Yapısı
```javascript
// ✅ IIFE veya module pattern
const MyModule = (() => {
    // Private
    let state = {};
    
    // Public
    return {
        init() { ... },
        handleEvent() { ... }
    };
})();
```

### API İstekleri
```javascript
// ✅ api_client.js wrapper'ını kullan
const data = await apiGet('/api/endpoint');

// ❌ Doğrudan fetch kullanma
const data = await fetch('/api/endpoint');
```

---

## 7. Versiyon Yönetimi

### Semantic Versioning
| Tip | Açıklama | Örnek |
|-----|----------|-------|
| MAJOR | Breaking change | 2.0.0 → 3.0.0 |
| MINOR | Yeni özellik | 2.36.0 → 2.37.0 |
| PATCH | Bug fix | 2.36.0 → 2.36.1 |

### Güncelleme Adımları
1. `app/core/config.py` → `APP_VERSION` güncelle
2. `README.md` güncellenme tarihi ve changelog
3. `sss/CHANGELOG.md` → Yeni versiyon girişi
4. `sss/INDEX.md` → Versiyon numarası
5. Statik dosya `?v=` parametreleri

### Cache Busting (Zorunlu)
```html
<!-- ✅ DOĞRU — Versiyon parametresi -->
<script src="assets/js/main.js?v=2.36.1"></script>

<!-- ❌ YANLIŞ — Versiyonsuz -->
<script src="assets/js/main.js"></script>
```

---

## 8. Veritabanı Kuralları

### Schema Senkronizasyonu
- ORM model değişikliği → `schema.py` güncelle → DB'de uygula
- "Kodda var DB'de yok" ❌ KABUL EDİLEMEZ

### İndeks Bakımı
- Yeni tablo veya sık sorgulanan alan → İndeks ekle
- `CREATE INDEX IF NOT EXISTS` kullan

---

> 📌 Test rehberi: [Test Rehberi](testing_guide.md)
