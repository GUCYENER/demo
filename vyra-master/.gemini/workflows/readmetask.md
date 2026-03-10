---
description: README dosyasını güncelleme ritüeli
---

# README Update Ritual (/readmetask)

README ve dokümantasyon güncelleme adımları.

## 1. Değişiklik Tespiti
// turbo
```powershell
& 'C:\Users\EXT02D059293\AppData\Local\Programs\Git\cmd\git.exe' log -5 --oneline
```

## 2. Mevcut Versiyon Oku
// turbo  
```powershell
python -c "import sys; sys.path.insert(0, r'd:\VYRA'); from app.core.config import APP_VERSION; print(f'APP_VERSION: {APP_VERSION}')"
```

## 3. README Güncelle
- `README.md` dosyasını aç
- En son değişiklikleri "Changelog" bölümüne ekle
- Versiyon numarasını güncelle
- Tarih ekle

## 4. SSS Dokümanları Güncelle
- Yeni endpoint → `sss/02_architecture/api_reference.md`
- Yeni tablo/sütun → `sss/02_architecture/database_schema.md`
- Yeni backend servisi → `sss/03_components/backend/`
- Yeni frontend modülü → `sss/03_components/frontend/`
- UI değişikliği → `sss/01_user_manual/`
- Her değişiklik → `sss/CHANGELOG.md` + `sss/INDEX.md` versiyonu

## 5. Doğrulama
- README ve SSS dosyalarının tutarlılığını kontrol et
- Versiyon numarasının her yerde aynı olduğunu doğrula
