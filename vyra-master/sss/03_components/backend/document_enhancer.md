# Doküman İyileştirici — Backend Bileşen Dokümantasyonu

| Bilgi | Değer |
|-------|-------|
| **Versiyon** | v2.36.1 |
| **Son Güncelleme** | 2026-02-10 |
| **Konum** | `app/services/document_enhancer.py` |
| **Durum** | ✅ Güncel |

---

## 1. Amaç

Yüklenen dokümanları LLM (Google Gemini) ile analiz ederek içerik kalitesini artırma — eksik adımları tamamlama, dili düzeltme, format iyileştirme.

---

## 2. `DocumentEnhancer.enhance(file_id)`

**Input:**
| Parametre | Tip | Açıklama |
|-----------|-----|----------|
| `file_id` | `int` | uploaded_files ID |

**Output:** `Dict`
```python
{
    "success": True,
    "sections": [
        EnhancedSection(title="Giriş", original="...", enhanced="...", changes=["Eklendi: adım 3"])
    ],
    "file_path": "/tmp/enhanced_vpn_guide.pdf"
}
```

---

## 3. İyileştirme Süreci

1. DB'den dosya chunk'larını al
2. Her chunk'ı LLM'e gönder
3. Analiz sonucunu `EnhancedSection` olarak formatla
4. İyileştirilmiş dokümanı geçici dosya olarak kaydet
5. İndirme linki döndür

---

## 4. Temizlik

`cleanup_enhanced_file(file_path)` — Geçici dosyaları siler.
