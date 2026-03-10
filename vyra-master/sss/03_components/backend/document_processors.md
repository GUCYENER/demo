# Doküman İşleyiciler — Backend Bileşen Dokümantasyonu

| Bilgi | Değer |
|-------|-------|
| **Versiyon** | v2.43.0 |
| **Son Güncelleme** | 2026-02-16 |
| **Konum** | `app/services/document_processors/` |
| **Durum** | ✅ Güncel |

---

## 1. Amaç

Her dosya formatı için özelleştirilmiş metin ve metadata çıkarma. Polimorfik yapıda — `BaseProcessor` abstract class'ından türetilir.

---

## 2. Desteklenen Formatlar

| Format | Processor | Uzantı |
|--------|-----------|--------|
| Word | `DocxProcessor` | `.docx` |
| PDF | `PdfProcessor` | `.pdf` |
| PowerPoint | `PptxProcessor` | `.pptx` |
| Excel | `ExcelProcessor` | `.xlsx` |
| Metin | `TxtProcessor` | `.txt` |

---

## 3. Base Processor (Abstract)

| Özellik | Değer |
|---------|-------|
| **Dosya** | `app/services/document_processors/base.py` |
| **Tip** | Abstract Base Class |

#### `BaseProcessor.process(file_content, file_name)`

**Input:**
| Parametre | Tip | Açıklama |
|-----------|-----|----------|
| `file_content` | `bytes` | Dosya binary içeriği |
| `file_name` | `str` | Dosya adı (uzantı dahil) |

**Output:** `List[Dict]`
```python
[
    {
        "chunk_text": "VPN bağlantısı için...",
        "chunk_index": 0,
        "metadata": {
            "page": 1,
            "heading": "Giriş",
            "source_file": "vpn_guide.pdf"
        }
    },
    ...
]
```

---

## 4. Format-Spesifik İşleyiciler

### 4.1 `DocxProcessor`
- **python-docx** kütüphanesi kullanır
- Paragraf, tablo ve başlık bilgisi çıkarır
- Heading yapısını korur
- 🆕 **v2.43.0:** `heading_level`, `heading_path` breadcrumb metadata
- 🆕 **v2.43.0:** Tablo yapısal metadata (`table_id`, `column_headers`, `row_count`)
- 🆕 **v2.43.0 Faz 4:** Görsel-chunk eşleme (XML namespace heading-image map)
- Görsel referansları metadata'ya ekler

### 4.2 `PdfProcessor`
- 🆕 **v2.43.0:** **PyMuPDF (fitz)** ile font-aware heading detection (font size, bold, italic)
- Fallback: **pypdf** metin çıkarma
- OCR fallback: **EasyOCR** (taranmış PDF'ler)
- 🆕 **v2.43.0:** `heading_level`, `heading_path` breadcrumb
- 🆕 **v2.43.0:** Header/footer temizleme (`_clean_header_footer_blocks`)
- 🆕 **v2.43.0:** TOC tespiti (`_detect_toc_section`)
- 🆕 **v2.43.0 Faz 4:** Görsel-chunk eşleme (`_extract_image_positions_fitz` + `image_refs` metadata)
- Sayfa numarası metadata'da

### 4.3 `PptxProcessor`
- **python-pptx** kullanır
- Slayt bazlı chunk'lama
- Shape içindeki metinleri birleştirir
- Slayt numarası metadata'da

### 4.4 `ExcelProcessor`
- **openpyxl** kullanır
- Sheet bazlı chunk'lama
- Satır-sütun yapısını metin formatında korur
- Sheet adı metadata'da

### 4.5 `TxtProcessor`
- Düz metin dosyaları
- Satır/paragraf bazlı bölme
- UTF-8 encoding

---

## 5. Routing Mantığı

```python
# __init__.py'de otomatik routing
def get_processor(file_type: str) -> BaseProcessor:
    processors = {
        ".docx": DocxProcessor,
        ".pdf":  PdfProcessor,
        ".pptx": PptxProcessor,
        ".xlsx": ExcelProcessor,
        ".txt":  TxtProcessor,
    }
    return processors.get(file_type.lower())
```

**Desteklenmeyen format:** `None` döner → upload reddedilir

---

## 6. Hata Yönetimi

| Durum | Davranış |
|-------|----------|
| Bozuk dosya | Hata loglanır, boş chunk listesi döner |
| Boş dosya | Boş liste döner |
| Encoding hatası | UTF-8 fallback denenir |
| Şifreli PDF | Hata mesajı, chunk üretilemez |
