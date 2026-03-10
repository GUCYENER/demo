# RAG Bilgi Bankası

| Bilgi | Değer |
|-------|-------|
| **Versiyon** | v2.36.1 |
| **Son Güncelleme** | 2026-02-10 |
| **Durum** | ✅ Güncel |

---

## 1. Genel Bakış

RAG (Retrieval-Augmented Generation) Bilgi Bankası, kurumsal dokümanlarınızı yükleyerek VYRA'nın bu dokümanlardan bilgi aramasını sağlar. Yüklenen dokümanlar otomatik olarak chunk'lara bölünür, vektör olarak indekslenir ve yapay zeka aramasında kullanılır.

---

## 2. Desteklenen Dosya Formatları

| Format | Uzantı | Açıklama |
|--------|--------|----------|
| Word | `.docx` | Microsoft Word belgeleri |
| PDF | `.pdf` | Portable Document Format |
| PowerPoint | `.pptx` | Microsoft PowerPoint sunumları |
| Excel | `.xlsx` | Microsoft Excel tabloları |
| Metin | `.txt` | Düz metin dosyaları |

---

## 3. Dosya Yükleme

### Adımlar
1. Sol menüden **RAG / Bilgi Bankası** bölümüne gidin
2. **"Dosya Yükle"** butonuna tıklayın
3. Dosya seçici açılır — dosyanızı seçin veya sürükle-bırak yapın
4. (Opsiyonel) **Organizasyon** seçin — dosya hangi birime ait
5. Yükleme başlar ve durum çubuğu gösterilir

### Yükleme Süreci
```
Dosya Seçimi → Upload → Chunk'lara Bölme → Embedding → İndeksleme → ✅ Hazır
```

### Yükleme Sonrası Otomatik İşlemler
| İşlem | Açıklama |
|-------|----------|
| **Chunk'lama** | Doküman anlamlı parçalara bölünür |
| **Embedding** | Her chunk vektör temsiline dönüştürülür |
| **OCR** | Görsellerdeki metinler otomatik çıkarılır |
| **Kalite Analizi** | Doküman kalite skoru hesaplanır |
| **Topic Çıkarma** | Dokümanın konusu otomatik belirlenir |

---

## 4. Dosya Listesi ve Yönetimi

### Dosya Kartları
Her yüklenen dosya bir kart olarak gösterilir:

| Bilgi | Açıklama |
|-------|----------|
| Dosya adı | Orijinal dosya adı |
| Format ikonu | 📄 PDF, 📊 Excel, 📝 Word vb. |
| Chunk sayısı | Kaç parçaya bölündüğü |
| Yükleme tarihi | Ne zaman yüklendiği |
| Organizasyon | Hangi birime ait |
| Kalite skoru | Olgunluk değerlendirmesi |

### İşlemler
| İşlem | Buton | Açıklama |
|-------|-------|----------|
| Detay Görüntüle | 🔍 | Chunk'ları ve metadata'yı incele |
| Organizasyon Düzenle | ✏️ | Dosyanın ait olduğu birimi değiştir |
| Kalite Analizi | 📊 | Doküman olgunluk skorunu görüntüle |
| İyileştirme | ✨ | LLM ile dokümanı zenginleştir |
| Sil | 🗑️ | Dosyayı ve indeksini kaldır |

---

## 5. Doküman Görselleri

### Görsel Çıkarma
Yüklenen DOCX, PDF ve PPTX dosyalarındaki görseller otomatik çıkarılır ve saklanır.

### Lightbox Görüntüleme
- Sohbet yanıtlarındaki görsellere **tıklayarak** büyütülmüş görünüm açabilirsiniz
- **ESC** tuşu veya **X** butonu ile kapatabilirsiniz

### OCR Metin Okuma
- Görselin üzerine geldiğinizde **"📝 Metin"** butonu görünür
- Tıkladığınızda görsel üzerindeki metin popup'ta gösterilir
- Bu özellik EasyOCR teknolojisi ile çalışır

---

## 6. Doküman İyileştirme (Enhance)

Yüklenen dokümanlarınızı LLM ile zenginleştirebilirsiniz:

### Adımlar
1. Dosya kartındaki **✨ İyileştir** butonuna tıklayın
2. İyileştirme modalı açılır
3. İyileştirme seçeneklerini belirleyin
4. **"İyileştir"** butonuna tıklayın
5. LLM dokümanı analiz eder ve geliştirilmiş versiyon oluşturur

### İyileştirme Çıktıları
- Eksik adımların tamamlanması
- Dil ve format düzeltmeleri
- Detay ekleme

---

## 7. Olgunluk Skoru (Maturity Analysis)

Her dokümanın kalitesi otomatik analiz edilir:

| Skor Aralığı | Seviye | Anlamı |
|---------------|--------|--------|
| 0-40 | 🔴 Düşük | Yetersiz içerik, iyileştirme gerekli |
| 41-70 | 🟡 Orta | Kullanılabilir ama geliştirilmeli |
| 71-100 | 🟢 Yüksek | İyi kalitede, güvenilir |

### Değerlendirme Kriterleri
- İçerik bütünlüğü
- Adım detayları
- Dil kalitesi
- Format uygunluğu

---

## 8. Organizasyon Bazlı Dosya Yönetimi

Dosyalar organizasyonlara atanabilir:
- Her dosya bir organizasyona ait olabilir
- Organizasyon filtresi ile sadece ilgili dosyaları görebilirsiniz
- Organizasyonu değiştirmek için dosya kartındaki ✏️ butonunu kullanın

---

> 📌 Sonraki adım: [Destek Talepleri](destek_talepleri.md)
