# Admin Paneli

| Bilgi | Değer |
|-------|-------|
| **Versiyon** | v2.36.1 |
| **Son Güncelleme** | 2026-02-10 |
| **Yetki** | ⚠️ Admin rolü gerektirir |
| **Durum** | ✅ Güncel |

---

## 1. Erişim

Admin paneline sadece **admin** rolüne sahip kullanıcılar erişebilir. Sol menüde (sidebar) admin bölümleri yalnızca yetkili kullanıcılara görünür.

---

## 2. Organizasyon Yönetimi

### İşlevler
| İşlem | Açıklama |
|-------|----------|
| Org Listele | Tüm organizasyonları görüntüle |
| Org Ekle | Yeni organizasyon oluştur |
| Org Düzenle | Organizasyon bilgilerini güncelle |
| Org Sil | Organizasyonu kaldır |

### Organizasyon Bilgileri
| Alan | Tip | Açıklama |
|------|-----|----------|
| Adı | Metin | Organizasyon adı |
| Açıklama | Metin | Opsiyonel açıklama |
| Durum | Aktif/Pasif | Kullanılabilirlik |

---

## 3. Kullanıcı Yönetimi

### Kullanıcı İşlemleri
| İşlem | Açıklama |
|-------|----------|
| Kullanıcı Listele | Tüm kayıtlı kullanıcıları gör |
| Onaylama | Yeni kayıtları onaya al |
| Rol Değiştirme | Kullanıcının rolünü güncelle |
| Durum Değiştirme | Aktif / Pasif |
| Organizasyon Atama | Kullanıcıyı bir org'a ata |

### Roller
| Rol | Yetki | Açıklama |
|-----|-------|----------|
| `user` | Standart | Soru sorma, ticket oluşturma |
| `admin` | Tam | Tüm yönetim işlemleri |

### Kullanıcı Bilgileri
| Alan | Açıklama |
|------|----------|
| Ad Soyad | Tam isim |
| Kullanıcı Adı | Login bilgisi |
| E-posta | İletişim |
| Telefon | İletişim |
| Rol | user / admin |
| Organizasyon | Ait olduğu birim |
| Onay Durumu | Onaylı / Beklemede |
| Kayıt Tarihi | İlk kayıt zamanı |

---

## 4. LLM Konfigürasyonu

VYRA'nın kullandığı yapay zeka modelini yapılandırabilirsiniz.

### Ayarlanabilir Parametreler
| Parametre | Açıklama | Varsayılan |
|-----------|----------|------------|
| Model | Kullanılacak LLM modeli | gemini-2.0-flash |
| Temperature | Yanıt çeşitliliği (0-1) | 0.3 |
| Max Tokens | Maksimum yanıt uzunluğu | 4096 |
| Top-P | Nucleus sampling | 0.9 |
| Provider | Servis sağlayıcı | Google AI |

### Adımlar
1. Sidebar'dan **LLM Ayarları** bölümüne gidin
2. Model ve parametreleri düzenleyin
3. **"Kaydet"** butonuna tıklayın
4. Değişiklikler anında uygulanır

---

## 5. Prompt Yönetimi

Sistem promptlarını yönetebilirsiniz:

### Prompt Tipleri
| Tip | Açıklama |
|-----|----------|
| System Prompt | VYRA'nın temel davranış talimatları |
| RAG Prompt | Doküman araması yanıt formatı |
| Enhancement Prompt | Doküman iyileştirme talimatları |

### İşlemler
| İşlem | Açıklama |
|-------|----------|
| Görüntüle | Mevcut prompt'u oku |
| Düzenle | İçeriği değiştir |
| Reset | Varsayılana dön |

---

## 6. İzin Yönetimi (RBAC)

Modül bazında erişim izinlerini yapılandırabilirsiniz:

### İzin Matrisi
| Modül | User | Admin |
|-------|------|-------|
| Dialog (VYRA'ya Sor) | ✅ | ✅ |
| Ticket Geçmişi | ✅ | ✅ |
| RAG Dosya Yükleme | ⚙️ | ✅ |
| Kullanıcı Yönetimi | ❌ | ✅ |
| LLM Ayarları | ❌ | ✅ |
| Prompt Yönetimi | ❌ | ✅ |
| Organizasyon Yönetimi | ❌ | ✅ |

⚙️ = Yapılandırılabilir (admin tarafından açılıp kapatılabilir)

---

## 7. ML Eğitim Yönetimi

CatBoost modelini yönetebilirsiniz:

### İşlevler
| İşlem | Açıklama |
|-------|----------|
| Eğitim Başlat | Yeni CatBoost modeli eğit |
| Eğitim Geçmişi | Önceki eğitimleri görüntüle |
| Model Bilgisi | Aktif model detayları |
| Eğitim Örnekleri | Modelin öğrendiği verileri gör |

### Eğitim Süreci
1. Sol menüden **ML Eğitim** bölümüne gidin
2. **"Eğitim Başlat"** butonuna tıklayın
3. Eğitim arka planda çalışır
4. Tamamlandığında bildirim alırsınız
5. Eğitim geçmişinden sonuçları inceleyin

---

## 8. Sistem Sağlığı

### Health Check
| Endpoint | Açıklama |
|----------|----------|
| `/api/health` | Genel sistem durumu |
| `/api/health/version` | Platform versiyonu |

---

> 📌 Teknik detaylar için: [Mimari Tasarım](../02_architecture/README.md)
