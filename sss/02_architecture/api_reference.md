# API Referansı

| Bilgi | Değer |
|-------|-------|
| **Versiyon** | v3.3.0 |
| **Base URL** | `http://localhost:8002/api` |
| **Auth** | Bearer Token (JWT) |
| **Content-Type** | application/json |
| **Son Güncelleme** | 2026-04-03 |
| **Durum** | ✅ Güncel |

---

## 1. Auth — Kimlik Doğrulama

### `POST /api/auth/register`
Yeni kullanıcı kaydı. Admin onayı gerektirir.

**Request Body:**
```json
{
    "full_name": "Ahmet Yılmaz",
    "username": "ahmet.yilmaz",
    "email": "ahmet@example.com",
    "phone": "5551234567",
    "password": "GucluSifre123"
}
```

**Response (201):**
```json
{
    "message": "Kayıt başarılı. Admin onayı bekleniyor."
}
```

**Hatalar:**
| Kod | Durum |
|-----|-------|
| 400 | Kullanıcı adı veya email zaten mevcut |

---

### `POST /api/auth/login`
Kullanıcı girişi — JWT token döndürür.

**Request Body:**
```json
{
    "username": "ahmet.yilmaz",
    "password": "GucluSifre123"
}
```

**Response (200):**
```json
{
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer"
}
```

---

### `POST /api/auth/refresh`
Refresh token ile yeni access token alır.

### `GET /api/auth/me`
Mevcut kullanıcı bilgisini döndürür. **Auth required.**

**Response (200):**
```json
{
    "id": 1,
    "full_name": "Ahmet Yılmaz",
    "username": "ahmet.yilmaz",
    "email": "ahmet@example.com",
    "phone": "5551234567",
    "role": "admin",
    "is_admin": true
}
```

---

## 2. Dialog — Sohbet Yönetimi

### `POST /api/dialogs`
Yeni dialog oturumu oluşturur.

**Request Body:**
```json
{
    "title": "VPN Sorunu"
}
```

**Response (200):**
```json
{
    "dialog_id": 42,
    "title": "VPN Sorunu",
    "created_at": "2026-02-10T09:00:00"
}
```

---

### `POST /api/dialogs/{dialog_id}/message`
Dialog'a mesaj gönderir ve AI yanıtı alır.

**Request Body:**
```json
{
    "message": "VPN nasıl bağlanırım?"
}
```

**Response (200):**
```json
{
    "message_id": 123,
    "response": "VPN bağlantısı için aşağıdaki adımları izleyin...",
    "sources": [...],
    "images": [...]
}
```

---

### `GET /api/dialogs`
Kullanıcının tüm dialoglarını listeler.

### `GET /api/dialogs/{dialog_id}/messages`
Dialog mesaj geçmişini döndürür.

### `POST /api/dialogs/{dialog_id}/close`
Dialog'u kapatır.

---

## 3. RAG — Bilgi Bankası

### `POST /api/rag/upload`
Doküman yükler ve indeksler.

**Request:** `multipart/form-data`
| Alan | Tip | Açıklama |
|------|-----|----------|
| `file` | File | Yüklenecek dosya |
| `org_ids` | JSON | Organizasyon ID listesi (opsiyonel) |

**Response (200):**
```json
{
    "file_id": 15,
    "file_name": "vpn_guide.pdf",
    "chunk_count": 12,
    "images_extracted": 5,
    "status": "success"
}
```

---

### `GET /api/rag/search`
Doküman araması yapar.

**Query Parameters:**
| Parametre | Tip | Zorunlu | Açıklama |
|-----------|-----|---------|----------|
| `query` | string | ✅ | Arama sorgusu |
| `top_k` | int | ❌ | Sonuç sayısı (varsayılan: 5) |
| `org_ids` | string | ❌ | Org ID listesi (virgülle ayrılmış) |

**Response (200):**
```json
{
    "results": [
        {
            "chunk_id": 45,
            "content": "VPN bağlantısı için...",
            "score": 0.87,
            "file_name": "vpn_guide.pdf",
            "metadata": {"page": 3}
        }
    ],
    "total": 5
}
```

---

### `GET /api/rag/files`
Yüklenen dosya listesini döndürür.

### `DELETE /api/rag/files/{file_id}`
Dosyayı ve tüm ilişkili verileri siler (CASCADE).

---

## 4. RAG Images — Görsel Endpoint'leri

### `GET /api/rag/images/by-file/{file_id}`
Dosyaya ait görsellerin metadata listesi.

**Response (200):**
```json
{
    "file_id": 15,
    "total_images": 3,
    "images": [
        {
            "id": 1,
            "url": "/api/rag/images/1",
            "image_format": "png",
            "width_px": 800,
            "height_px": 600,
            "has_ocr": true,
            "ocr_preview": "VPN bağlantı adımları..."
        }
    ]
}
```

---

### `GET /api/rag/images/{image_id}`
Görsel binary verisi döndürür.

**Response Headers:**
| Header | Değer | Açıklama |
|--------|-------|----------|
| `Content-Type` | image/png | Görsel formatı |
| `X-Has-OCR` | true/false | OCR metin var mı |
| `Cache-Control` | max-age=86400 | 24 saat cache |

---

### `GET /api/rag/images/{image_id}/ocr`
Görseldeki OCR metnini döndürür.

**Response (200):**
```json
{
    "image_id": 1,
    "ocr_text": "1. VPN istemcisini açın\n2. Sunucu adresini girin",
    "has_text": true,
    "context_heading": "VPN Bağlantı Adımları",
    "alt_text": "VPN ekran görüntüsü"
}
```

---

## 5. RAG Enhance — Doküman İyileştirme

### `POST /api/rag/enhance/{file_id}`
Dokümanı LLM ile iyileştirir.

### `GET /api/rag/enhance/{file_id}/status`
İyileştirme durumunu kontrol eder.

### `GET /api/rag/enhance/{file_id}/download`
İyileştirilmiş dokümanı indirir.

### `GET /api/rag/enhancement-impact` (🆕 v3.3.0)
Enhancement etki ölçüm raporu.

**Query Parameters:**
| Parametre | Tip | Zorunlu | Açıklama |
|-----------|-----|---------|----------|
| `file_name` | string | ❌ | Dosya adı filtresi (ILIKE) |
| `limit` | int | ❌ | Sonuç sayısı (varsayılan: 20, max: 100) |

**Response (200):**
```json
{
    "summary": {
        "total_enhancements": 5,
        "measured_count": 3,
        "avg_score_before": 45.2,
        "avg_score_after": 72.8,
        "avg_improvement": 27.6,
        "avg_improvement_pct": 61.1
    },
    "items": [
        {
            "file_name": "rehber.pdf",
            "score_before": 42.0,
            "score_after": 78.5,
            "improvement": 36.5,
            "improvement_pct": 86.9
        }
    ]
}
```

---

## 6. Tickets — Destek Talepleri

### `POST /api/tickets`
Yeni ticket oluşturur.

### `GET /api/tickets`
Ticket listesini döndürür. Filtreleme destekler.

### `GET /api/tickets/{ticket_id}`
Ticket detayını döndürür.

---

## 7. Feedback — Geri Bildirim

### `POST /api/feedback`
Kullanıcı geri bildirimi kaydeder.

**Request Body:**
```json
{
    "feedback_type": "like",
    "chunk_ids": [1, 2, 3]
}
```

---

## 8. Admin Endpoint'leri

### Organizations
| Metod | Path | Açıklama |
|-------|------|----------|
| GET | `/api/organizations` | Org listesi |
| POST | `/api/organizations` | Org oluştur |
| PUT | `/api/organizations/{id}` | Org güncelle |
| DELETE | `/api/organizations/{id}` | Org sil |

### User Management
| Metod | Path | Açıklama |
|-------|------|----------|
| GET | `/api/admin/users` | Kullanıcı listesi |
| PUT | `/api/admin/users/{id}/approve` | Kullanıcı onayla |
| PUT | `/api/admin/users/{id}/role` | Rol değiştir |

### LLM Config
| Metod | Path | Açıklama |
|-------|------|----------|
| GET | `/api/llm/config` | Aktif LLM yapılandırması |
| PUT | `/api/llm/config` | Yapılandırma güncelle |

### Prompts
| Metod | Path | Açıklama |
|-------|------|----------|
| GET | `/api/prompts` | Prompt listesi |
| PUT | `/api/prompts/{id}` | Prompt güncelle |

---

## 9. Health — Sistem Sağlığı

### `GET /api/health`
Sistem durumunu döndürür.

### `GET /api/health/version`
Platform versiyonunu döndürür: `"3.3.0"`

---

## 10. WebSocket

### `WS /ws/{dialog_id}`
Real-time mesajlaşma.

**Gönderim:**
```json
{"type": "message", "content": "VPN sorunu var"}
```

**Alım:**
```json
{"type": "response", "content": "...", "sources": [...]}
```

**Enhancement Progress (🆕 v3.3.0):**
```json
{"type": "enhancement_progress", "current": 3, "total": 10, "percentage": 30, "status": "processing", "message": "Bölüm 3/10 iyileştiriliyor..."}
```

---

> 📌 Güvenlik detayları: [Güvenlik Modeli](security_model.md)
