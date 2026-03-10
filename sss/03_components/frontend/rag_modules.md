# RAG Modülleri — Frontend Bileşen Dokümantasyonu

| Bilgi | Değer |
|-------|-------|
| **Versiyon** | v2.36.1 |
| **Son Güncelleme** | 2026-02-10 |
| **Konum** | `frontend/assets/js/modules/rag_*.js`, `frontend/assets/js/rag_upload.js` |
| **Durum** | ✅ Güncel |

---

## 1. Modül Listesi

| Modül | Dosya | Amaç |
|-------|-------|------|
| **RAG Upload** | `rag_upload.js` | Dosya yükleme UI (drag & drop, progress) |
| **RAG Cards** | `rag_cards.js` | Dosya kartları render |
| **RAG File List** | `rag_file_list.js` | Dosya listesi ve filtreleme |
| **RAG Org Modal** | `rag_org_modal.js` | Organizasyon seçim modalı |
| **RAG File Org Edit** | `rag_file_org_edit.js` | Dosya-org düzenleme modalı |

---

## 2. `rag_upload.js` — Dosya Yükleme

### Ana Fonksiyonlar
| Fonksiyon | Açıklama |
|-----------|----------|
| `initUploadArea()` | Drag & drop alanı oluştur |
| `handleFileSelect(files)` | Dosya seçim sonrası validasyon |
| `uploadFile(file)` | API'ye POST (multipart/form-data) |
| `updateProgressBar(percent)` | Yükleme ilerleme çubuğu |

### Desteklenen Formatlar
`.docx`, `.pdf`, `.pptx`, `.xlsx`, `.txt`

### Drag & Drop
- Dosya sürükleme alanı
- Hover efekti
- Çoklu dosya desteği

---

## 3. `rag_cards.js` — Dosya Kartları

### Kart Yapısı
Her kart şu bilgileri gösterir:
| Öğe | Açıklama |
|-----|----------|
| 📄 İkon | Dosya tipine göre ikon |
| Dosya adı | Orijinal ad |
| Chunk sayısı | Kaç parçaya bölündüğü |
| Tarih | Yükleme zamanı |
| Org badge | Atanmış organizasyonlar |
| Aksiyon butonları | Detay, düzenle, sil |

### İşlem Butonları
| Buton | İkon | API Çağrısı |
|-------|------|-------------|
| Detay | 🔍 | Chunk listesi modalı |
| Org Düzenle | ✏️ | `rag_file_org_edit` modalı |
| Kalite | 📊 | Maturity score modalı |
| İyileştir | ✨ | Enhancement modalı |
| Sil | 🗑️ | DELETE /api/rag/files/{id} |

---

## 4. `rag_org_modal.js` — Organizasyon Seçimi

Yükleme sırasında organizasyon seçimini sağlar:
- Checkbox listesi ile çoklu org seçimi
- Arama/filtreleme
- "Tümünü Seç" / "Temizle" butonları

---

## 5. `rag_file_org_edit.js` — Org Düzenleme

Yüklenmiş dosyanın organizasyon atamasını düzenler:
- Mevcut atamaları göster
- Org ekle/çıkar
- Kaydet → DB güncelle
