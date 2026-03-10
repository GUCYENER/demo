---
description: Test senaryosu hazırlığı ve analiz ritüeli
---

# Test Preparation Ritual (/testhazirlik)

Bu ritüel, tüm değişikliklerin analiz edilmesini ve uygun test senaryolarının geliştirilmesini sağlar.

## 1. Change Analysis
- **Scope Identification**: `C:\Users\EXT02D059293\AppData\Local\Programs\Git\cmd\git.exe diff` veya `git status` ile değişen dosyaları belirle.
- **Impact Assessment**: Değişikliklerden etkilenen modülleri ve bağımlı bileşenleri tespit et.

## 2. Test Scenario Development
- **ID & Description**: Benzersiz test tanımlayıcı.
- **Module & Priority**: Hedef dosya/fonksiyon ve kritiklik seviyesi.
- **Test Type**: Unit, Integration, E2E veya Manual.
- **Pre-conditions**: Gerekli ortam durumu.
- **Steps**: Mantıksal eylem sırası.
- **Expected Result**: Başarı kriterleri.
- **Test Data**: Girdi/çıktı örnekleri.

## 3. Scenario Categories
- ✅ **Happy Path**: Standart operasyonel akış.
- ⚠️ **Edge Cases**: Sınır koşulları ve olağandışı girdiler.
- ❌ **Error Cases**: Hata yönetimi ve toparlanma.
- 🔄 **Regression**: Mevcut işlevselliğin bozulmadığının doğrulanması.

## 4. Automation Alignment
- Test dosyalarını oluştur veya güncelle (örn: `tests/test_module.py`).
- Yeni vakaları mevcut test süitine entegre et.

## 5. Output Requirements
- Bir `test_scenarios.md` artefaktı sürdür.
- Kapsam ve kapsamı paydaş incelemesi için özetle.
