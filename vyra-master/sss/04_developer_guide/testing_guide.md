# Test Rehberi — Geliştirici Rehberi

| Bilgi | Değer |
|-------|-------|
| **Versiyon** | v2.36.1 |
| **Son Güncelleme** | 2026-02-10 |
| **Framework** | pytest |
| **Konum** | `tests/` |
| **Durum** | ✅ Güncel |

---

## 1. Test Felsefesi

> **Kural:** Testi yazılmamış kod, yazılmamış sayılır.

### TDD Döngüsü
```
1. Test yaz (FAIL) → 2. Kodu yaz → 3. Test çalıştır (PASS) → 4. Regresyon çalıştır
```

---

## 2. Test Türleri

| Tür | Konum | Amaç | Coverage Hedefi |
|-----|-------|------|-----------------|
| **Unit** | `tests/test_*.py` | Model, helper, servis fonksiyonları | %80+ |
| **Integration** | `tests/test_*.py` | API endpoint'leri | %80+ |
| **Regression** | Tüm testler | Mevcut kodun bozulmadığını doğrulama | — |

---

## 3. Mevcut Test Dosyaları

| Test Dosyası | Test Sayısı | Kapsamı |
|-------------|-------------|---------|
| `test_image_extractor.py` | ~35 | OCR, görsel çıkarma, DB kayıt |
| `test_rag_images.py` | ~21 | Görsel API endpoint'leri |
| `test_response_builder_images.py` | ~8 | Görsel referans render |
| `test_catboost_service.py` | ~15 | ML feature extractor, CatBoost |
| `test_scoring.py` | ~20 | Cosine similarity, BM25, RRF |
| `test_dialog_service.py` | ~15 | Dialog pipeline |
| `test_auth.py` | ~10 | Login, register, JWT |

**Toplam:** 200+ test

---

## 4. Test Çalıştırma

### Tek Dosya
```powershell
python -m pytest tests/test_image_extractor.py -v
```

### Tüm Testler (Regresyon)
```powershell
python -m pytest tests/ -v --ignore=tests/test_ui.py --ignore=tests/integration/
```

### Coverage Raporu
```powershell
python -m pytest tests/ --cov=app --cov-report=term-missing
```

### Belirli Bir Test
```powershell
python -m pytest tests/test_image_extractor.py::TestExtractedImage::test_default_values -v
```

---

## 5. Test Yazım Kalıpları

### Unit Test Şablonu
```python
import pytest
from unittest.mock import MagicMock, patch

class TestMyFunction:
    """MyFunction test grubu."""
    
    def test_normal_case(self):
        """Normal durum testi."""
        result = my_function("valid_input")
        assert result == expected_output
    
    def test_edge_case_empty(self):
        """Boş input edge case."""
        result = my_function("")
        assert result == []
    
    def test_error_handling(self):
        """Hata durumu testi."""
        with pytest.raises(ValueError):
            my_function(None)
```

### Mock Kullanımı
```python
@patch('app.services.rag.service.get_db_connection')
def test_search_with_mock_db(self, mock_conn):
    """DB bağlantısı mock ile test."""
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        (1, "chunk text", [0.1, 0.2, ...])
    ]
    mock_conn.return_value.__enter__ = lambda s: mock_conn.return_value
    mock_conn.return_value.cursor.return_value = mock_cursor
    
    result = rag_service.search("VPN sorunu")
    assert len(result) > 0
```

### API Endpoint Testi
```python
from fastapi.testclient import TestClient

class TestMyEndpoint:
    def test_get_success(self):
        """GET isteği — başarılı."""
        with patch('app.api.routes.my_route.get_db_connection') as mock:
            mock_cur = MagicMock()
            mock_cur.fetchall.return_value = [...]
            mock.return_value.__enter__.return_value.cursor.return_value = mock_cur
            
            response = client.get("/api/my-endpoint", headers=auth_headers)
            assert response.status_code == 200
    
    def test_get_not_found(self):
        """GET isteği — kayıt bulunamadı."""
        with patch(...) as mock:
            mock_cur.fetchone.return_value = None
            response = client.get("/api/my-endpoint/999", headers=auth_headers)
            assert response.status_code == 404
```

---

## 6. Test Kapsamı Kuralları

| Kapsam | Oran | Açıklama |
|--------|------|----------|
| Proje geneli | %80+ | Minimum hedef |
| Kritik modüller | %95+ | auth, rag, dialog |
| Yeni özellikler | %100 | Her yeni feature test ile gelir |

---

## 7. Commit Öncesi Test Kontrol Listesi

- [ ] Unit testler yazıldı mı?
- [ ] Tüm testler geçti mi? (`pytest` çıktısı: 0 FAILED)
- [ ] Regresyon testleri geçti mi?
- [ ] Coverage hedefi karşılandı mı?

### ❌ Test Başarısızsa
1. **ASLA commit yapma**
2. Hatayı analiz et
3. Düzelt
4. Tekrar çalıştır
5. Geçtiğinde commit yap

---

## 8. Test Veritabanı

Testler gerçek DB'ye bağlanmaz. Tüm DB işlemleri **mock** ile yapılır:

```python
# ✅ DOĞRU — Mock DB
@patch('app.core.db.get_db_connection')
def test_with_mock(self, mock_conn):
    ...

# ❌ YANLIŞ — Gerçek DB
def test_with_real_db(self):
    conn = psycopg2.connect(...)  # ASLA yapma
```

---

## 9. Eksik Test Kapsamı (Known Gaps)

| Modül | Durum | Açıklama |
|-------|-------|----------|
| Frontend JavaScript | ❌ Otomatik test yok | Manuel test ile kapsanır |
| WebSocket | ❌ Otomatik test yok | Hand test ile kapsanır |
| UI/UX (Canvas, D&D) | ❌ Otomatik test yok | Manuel titiz test |
