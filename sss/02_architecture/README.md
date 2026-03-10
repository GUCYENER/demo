# 🏗️ Mimari Tasarım

| Bilgi | Değer |
|-------|-------|
| **Versiyon** | v2.36.1 |
| **Son Güncelleme** | 2026-02-10 |
| **Durum** | ✅ Güncel |

---

## 📖 İçindekiler

| # | Doküman | Açıklama |
|---|---------|----------|
| 1 | [Sistem Mimarisi](system_overview.md) | Katmanlar, veri akışı, teknoloji yığını |
| 2 | [Veritabanı Şeması](database_schema.md) | Tablolar, ilişkiler, indeksler |
| 3 | [API Referansı](api_reference.md) | Tüm endpoint'ler, input/output |
| 4 | [Güvenlik Modeli](security_model.md) | JWT, RBAC, rate limiting |

---

## Genel Mimari

```mermaid
graph TB
    subgraph Frontend
        HTML["HTML5 + JS Modülleri"]
        CSS["Vanilla CSS"]
    end
    
    subgraph Backend["FastAPI Backend (Python)"]
        API["API Routes"]
        Services["Service Layer"]
        Core["Core (DB, Config, LLM)"]
    end
    
    subgraph Storage
        PG["PostgreSQL"]
        FS["File System (Logs)"]
    end
    
    subgraph External
        LLM["Google Gemini AI"]
        OCR["EasyOCR"]
        EMB["SentenceTransformers"]
    end
    
    HTML --> API
    API --> Services
    Services --> Core
    Core --> PG
    Core --> LLM
    Services --> OCR
    Services --> EMB
```

> 📌 Detaylı katman açıklamaları için [Sistem Mimarisi](system_overview.md) dokümanına bakınız.
