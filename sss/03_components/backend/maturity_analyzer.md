# Olgunluk Analizi — Backend Bileşen Dokümantasyonu

| Bilgi | Değer |
|-------|-------|
| **Versiyon** | v2.36.1 |
| **Son Güncelleme** | 2026-02-10 |
| **Konum** | `app/services/maturity_analyzer.py` |
| **Durum** | ✅ Güncel |

---

## 1. Amaç

Yüklenen dokümanların kalitesini otomatik analiz ederek 0-100 arası olgunluk skoru hesaplama.

---

## 2. `MaturityAnalyzer.analyze(file_id)`

**Input:**
| Parametre | Tip | Açıklama |
|-----------|-----|----------|
| `file_id` | `int` | uploaded_files ID |

**Output:** `Dict`
```python
{
    "score": 75,
    "level": "Orta",
    "details": {
        "content_completeness": 80,
        "step_quality": 70,
        "language_clarity": 85,
        "format_compliance": 65
    },
    "recommendations": ["Adım 4 eksik", "Tablo formatı önerilir"]
}
```

---

## 3. Skor Seviyeleri

| Aralık | Seviye | Renk | Anlamı |
|--------|--------|------|--------|
| 0-40 | Düşük | 🔴 | Yetersiz, iyileştirme şart |
| 41-70 | Orta | 🟡 | Kullanılabilir, geliştirilebilir |
| 71-100 | Yüksek | 🟢 | İyi kalite |

---

## 4. Değerlendirme Kriterleri

| Kriter | Ağırlık | Açıklama |
|--------|---------|----------|
| İçerik bütünlüğü | %30 | Konunun tam ele alınması |
| Adım detayları | %25 | Adımların netliği ve eksiksizliği |
| Dil kalitesi | %25 | Yazım, gramer, anlaşılırlık |
| Format uygunluğu | %20 | Başlık, liste, tablo kullanımı |
