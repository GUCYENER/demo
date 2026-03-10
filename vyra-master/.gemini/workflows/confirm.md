---
description: Finalizasyon ve code review ritüeli
---

# Finalization Ritual (/confirm)

Herhangi bir görevi tamamlandı olarak işaretlemeden ve versiyonlu commit/push yapmadan önce uygulanması zorunlu kontrol listesi.

## 1. Syntax & Import Validation
- **Python**:
  - Değiştirilen modüller için dry-run import: `python -c "import path.to.module"`.
  - **Portable Shell Pattern**: `python -c "import sys; sys.path.insert(0, r'd:\VYRA'); import module; print(module.VERSION)"`
  - Hedef: Circular dependency veya syntax hatası olmadığını doğrula.
- **Explicit Definitions**: Import edilen her fonksiyon/class'ın kaynakta tanımlı olduğunu doğrula.

## 2. Backend Review
- **Route Priority**: Statik route'lar dinamik path parametrelerinden ÖNCE tanımlı olmalı.
- **Resilience**: `try/except` blokları açıklayıcı hata loglaması ile çevrelenmiş olmalı.
- **Integrity**: Parameterized query, Pydantic validation, tutarlı API response formatı.

## 3. Frontend Review
- **Modularity**: Projenin modül pattern'ine uy.
- **Reliability**: API null-check, duplicate event listener önleme.
- **Forensic UX**: Toast/modal bildirimleri > raw console.log.

## 4. CSS & Style Review
- **Externalization**: Tüm stiller harici CSS dosyalarında. Inline `style="..."` YASAK (runtime hesaplamalar hariç).
- **Modern SaaS**: Tasarım sistemi ile uyum.
- **Responsiveness**: Mobil ve yüksek çözünürlüklü masaüstü.

## 5. Modular Structure
- **Decomposition**: 300+ satır dosyaları alt-modüllere böl.
- **Extraction**: Utility fonksiyonları shared bileşenlere taşı.

## 6. Database Maintenance
```powershell
$env:PGPASSWORD='postgres'; & 'D:\VYRA\pgsql\bin\psql.exe' -h localhost -p 5005 -U postgres -d vyra -c "REINDEX TABLE tablename; VACUUM ANALYZE tablename;"
```

## 7. Documentation & Versioning
- `README.md` veya `CHANGELOG.md` güncelle.
- `APP_VERSION` in `config.py` güncelle.
- UI'da versiyon string'inin eşleştiğini doğrula. `Ctrl+F5` ile cache temizle.

## 8. Temporary Cleanup
- `Gecici_Dosyalar_Sil` veya diğer bridge dizinlerindeki dosyaları sil.

## 9. Git Backup
- **Absolute Binary Path**: `C:\Users\EXT02D059293\AppData\Local\Programs\Git\cmd\git.exe`
- **Sequence**:
  1. `git add -A`
  2. `git commit -m "vX.Y.Z: [Module] Description"`
  3. `git push origin [branch]`
