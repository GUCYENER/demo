# P20 — DB Smart Wizard AST Editor Manuel Smoke Testi

**Sürüm:** v3.30.0 — FAZ 3 / P20 (A+B+C+D)
**Kapsam:** DB Smart Wizard 5 adım + Step 4 AST düzenleyici (DnD, klavye, undo/redo, filtre modali, maliyet rozeti, /ast/diff toast, ağ hata simülasyonu, A11y)
**Ön koşul:** Demo şirket + en az 1 PostgreSQL veri kaynağı bağlı; `feature_key=aki_kesif` izni açık.

> Her satıra **[ ]** kutucuğu — testin geçtiyse `[x]`, kaldıysa `[F]` + ek not.

---

## 0 · Hazırlık

- [ ] Tarayıcıyı temizle (Ctrl+Shift+Del) ve sayfayı sert yenile (Ctrl+F5)
- [ ] DevTools → Network sekmesini aç, "Disable cache" işaretle
- [ ] DevTools → Console sekmesini aç (uyarı/hata için)
- [ ] DevTools → Application → Local Storage → `access_token` mevcut
- [ ] Ekran okuyucu aç (NVDA / JAWS / VoiceOver) — opsiyonel ama A11y satırları için gerekli

---

## 1 · Wizard Açılışı

- [ ] Ana sayfada **"Akıllı Veri Keşfi"** butonu görünür
- [ ] Butona tıkla → wizard paneli açılır (`#dbSmartWizardPanel` görünür)
- [ ] Stepper'da 5 sekme görünür: **1·Tablo · 2·İlişkiler · 3·Metrik · 4·Filtre · 5·Önizleme**
- [ ] "Adım 1 / 5" metni progress alanında görünür
- [ ] Önceki/İleri butonları doğru disable durumda (Önceki disabled, İleri tabloya kadar disabled)
- [ ] Console'da kritik hata yok

---

## 2 · Adım 1 — Tablo Seç

- [ ] Veri kaynağı dropdown otomatik dolar
- [ ] Bir kaynak seç → arama kutusuna örn. `siparis` yaz → **Ara** tıkla
- [ ] Aranıyor... mesajı kısaca görünür, sonra sonuç listesi gelir
- [ ] Bir sonuç kartına tıkla → "Seçildi: ..." toast'u görünür, kart turuncu kenarlı olur
- [ ] **İleri** butonu aktif olur

### Klavye

- [ ] Tab ile sonuç kartlarına odaklan → Enter veya Space ile seçim yapılabilir
- [ ] aria-selected="true" odaklı kartta

---

## 3 · Adım 2 — İlişkiler (FK Graph)

- [ ] İleri → otomatik FK ilişki listesi yüklenir
- [ ] "FK ile bağlı N tablo bulundu (X bağlantı tablosu)" hint metni görünür
- [ ] Bağlantı tabloları "bağlantı tablosu" etiketiyle işaretlenmiş
- [ ] Hata olmadan tamamlanır

---

## 4 · Adım 3 — Metrik

- [ ] İleri → metrik kütüphanesi yüklenir, kategoriler ayrı ayrı gruplanmış
- [ ] Bir metriğe tıkla → "Metrik seçildi: ..." toast'u, kart turuncu kenarlı
- [ ] Klavyeyle (Tab + Enter/Space) seçim çalışır
- [ ] Metrik seçimi atlanabilir (opsiyonel) — yine İleri'ye basılabilir

---

## 5 · Adım 4 — Filtre (Kolonlar)

- [ ] İleri → seçili tablonun kolon listesi yüklenir
- [ ] Kolonlar "isim · tür · semantic" formatında listelenir
- [ ] Hint metninde "N kolon" doğru sayı

---

## 6 · Adım 5 — Önizleme + AST Düzenleyici (Step 4 / P20-D)

### Mount

- [ ] İleri → `#dswStep4Hint` "SQL üretiliyor..." yazar
- [ ] DevTools Network: `POST /api/db-smart/sessions/{uid}/preview` başarılı (200)
- [ ] Hint metni güncellenir: "Önizleme · dialect: postgresql · maliyet: X.XX · akış: tek istek"
- [ ] `#dswAstEditor` görünür hale gelir (hidden attribute kalkar)
- [ ] **`#dswLegacyPreview` GİZLİDİR** (`hidden` attr ile)
- [ ] AST editor içinde 3 bölüm görünür: **SELECT · ORDER BY · WHERE**
- [ ] Sağ üstte **Geri Al / Yinele** toolbar butonları (başlangıçta disabled)
- [ ] Sağ alt köşede **Maliyet rozeti** — başlangıçta gri (`cost-unknown`) veya `cost-green` (sunucu cevap verdiyse)
- [ ] DevTools Network: `POST /sessions/{uid}/explain` çağrısı görünür

### Drag-and-Drop — Kolon reorder

- [ ] SELECT listesinde 2+ kolon varsa, ilki tutup ikincinin üstüne sürükle
- [ ] Drop indicator (mavi çizgi) görünür
- [ ] Bırak → liste yeni sırayla render olur
- [ ] DevTools Network: `POST /sessions/{uid}/ast/patch` `reorder_columns` op ile gönderilir (debounced 250ms)
- [ ] Server canonical AST döner — UI güncellenir
- [ ] aria-live "Bırakıldı." duyurur (eğer klavyeyle yapıldıysa)

### Drag-and-Drop — Sıralama reorder

- [ ] ORDER BY listesinde 2+ öğe varsa benzer reorder işlemi
- [ ] `reorder_order` op gönderilir
- [ ] DESC/ASC togglesi sağdaki butonla değişir (`modify_order_dir` op)

### Klavye Reorder

- [ ] SELECT'teki bir kolona Tab ile odaklan
- [ ] **Space** → "Tutuldu. Ok tuşlarıyla taşıyın, Enter ile bırakın, Esc ile iptal." duyurusu
- [ ] **ArrowDown** → öğe bir aşağı kayar (her ok tuşu bir patch gönderir)
- [ ] **Enter** → konum kilitlenir, "Bırakıldı." duyurusu
- [ ] **Esc** → grab iptal, "İptal edildi." duyurusu
- [ ] **Delete** → öğe listeden silinir (`remove_column` patch)

### Filtre Modali

- [ ] WHERE bölümünde **"+ Ekle"** chip'ine tıkla
- [ ] `DbSmartFilterModal` modali açılır (kolon dropdown + operatör + değer alanı)
- [ ] Bir kolon seç, operatör `=`, değer yaz → **Ekle** butonu
- [ ] Modal kapanır, yeni filtre chip'i WHERE bölümünde görünür
- [ ] `add_filter` patch gönderilir, cost rozeti güncellenir
- [ ] Chip'e tıkla → filtre kaldırılır (`remove_filter`)

### Cost Badge Transition

- [ ] Başlangıç: gri (`cost-unknown` `?`)
- [ ] İlk EXPLAIN sonrası: maliyet < 10K → **yeşil** (`cost-green`)
- [ ] Pahalı bir filtre/kolon ekledikten sonra: maliyet > 10K → **sarı** (`cost-yellow`)
- [ ] Çok büyük tablo full-scan → maliyet > 1M → **kırmızı** (`cost-red`)
- [ ] Önbellekten gelen değerde "cached" rozet stili (CSS class `cached`)

### /ast/diff Toast (TR summary)

- [ ] Undo (Ctrl+Z) yap → bir patch geri alınır
- [ ] DevTools Network: `POST /ast/diff` çağrısı görünür
- [ ] Toast (üst sağ) "Değişti: kolonlar" veya "Değişti: sıralama, filtreler" gibi TR özetler
- [ ] Redo (Ctrl+Y veya Ctrl+Shift+Z) → benzer toast

### Undo / Redo

- [ ] Bir kolonu kaldır → toolbar **Geri Al** aktif olur
- [ ] **Ctrl+Z** → kolon geri gelir, **Yinele** aktif olur
- [ ] **Ctrl+Y** veya **Ctrl+Shift+Z** → kolon yine kaldırılır
- [ ] Toolbar Geri Al/Yinele butonlarına fareyle tıklamak da aynı sonucu verir
- [ ] DevTools Network: `replace_ast` op'lu patch gönderilir (server canonical resync)

### Ağ Hata Simülasyonu

- [ ] DevTools Network → throttle: **Offline**
- [ ] Bir kolonu kaldır → UI optimistik olarak kaldırır
- [ ] Patch başarısız olur → UI **rollback** (kolon geri gelir)
- [ ] Toast Türkçe hata: "AST yaması başarısız" / "Geçersiz işlem." / "Oturum bulunamadı." gibi
- [ ] Network → Online yap → tekrar dene, başarılı

### Adım Geçişi — Mount/Unmount Yaşam Döngüsü

- [ ] Adım 5'teyken DevTools Console: `window.DbSmartAstEditor.getAst()` bir AST objesi döner
- [ ] **Geri** butonuyla Adım 4'e dön
- [ ] DevTools Network: önceki `patch`/`explain` fetch'leri **abort** edilmiş (status: canceled)
- [ ] `#dswAstEditor` slot'u boşaldı (innerHTML = '')
- [ ] `window.DbSmartAstEditor.getAst()` artık `null`
- [ ] **İleri** ile Adım 5'e tekrar dön → editor yeniden mount edilir
- [ ] Önceki AST snapshot'ı (`_state.currentAst`) korunmuş, editor onunla başlar

### Wizard Kapatma

- [ ] Esc tuşu → wizard kapanır, AST editor unmount edilir
- [ ] DevTools Network: in-flight fetch'ler abort
- [ ] Wizard'ı tekrar aç → temiz başlangıç

---

## 7 · A11y — Ekran Okuyucu

- [ ] AST editor `<region aria-label="AST düzenleyici">` olarak duyurulur
- [ ] Her bölüm h4 başlığıyla okunur (SELECT, ORDER BY, WHERE)
- [ ] Liste öğeleri "Kolon X, sürükle veya boşluk tuşu ile taşı" olarak duyurulur
- [ ] Maliyet rozeti "Tahmini maliyet X" duyurulur (önbellekteyse "önbellekten" eklenir)
- [ ] Toolbar butonlarında `aria-keyshortcuts` mevcut (Ctrl+Z, Ctrl+Y)
- [ ] aria-live (`#dswAstLive`) duyuruları kesintisiz çalışır
- [ ] Tab odak sırası mantıklı (stepper → panel → kolon listeleri → toolbar → cost badge)
- [ ] `prefers-reduced-motion: reduce` aktifken sürükleme animasyonları sönükleşir (CSS kontrolü)

---

## 8 · Genel Kontrol

- [ ] Console'da kırmızı (error) yok, sadece bilgi/uyarı kabul edilebilir
- [ ] Tüm fetch çağrıları doğru `Authorization: Bearer ...` header'ı içerir
- [ ] CSS bundle yüklenmiş, AST editor stilleri uygulanmış (chip, list, drop-indicator)
- [ ] Mobil görünümde (responsive) editor okunabilir kalıyor
- [ ] Türkçe karakter ç, ğ, ı, ö, ş, ü doğru render ediliyor

---

## Sonuç

- Test eden: ____________________
- Tarih: ____________________
- Tarayıcı / OS: ____________________
- Genel sonuç: [ ] PASS  [ ] FAIL  [ ] PASS (with notes)
- Notlar / bulgular:
