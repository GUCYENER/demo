# Giriş ve Kurulum

| Bilgi | Değer |
|-------|-------|
| **Versiyon** | v2.36.1 |
| **Son Güncelleme** | 2026-02-10 |
| **Durum** | ✅ Güncel |

---

## 1. Sisteme Erişim

VYRA uygulamasına tarayıcınız üzerinden erişebilirsiniz:
- **URL:** `http://<sunucu-adresi>:8002`
- **Desteklenen Tarayıcılar:** Chrome, Firefox, Edge (güncel sürümler)

---

## 2. Giriş Yapma (Login)

### Adımlar
1. VYRA giriş sayfasını açın
2. **Kullanıcı Adı** alanına kullanıcı adınızı girin
3. **Şifre** alanına şifrenizi girin
4. (Opsiyonel) **"Beni Hatırla"** kutucuğunu işaretleyin
5. **"Giriş Yap"** butonuna tıklayın

### Önemli Bilgiler
| Özellik | Açıklama |
|---------|----------|
| Şifre göster/gizle | 👁️ ikonuna tıklayarak şifrenizi görebilirsiniz |
| Beni Hatırla | İşaretlerseniz sonraki girişlerde otomatik doldurulur |
| Hatalı giriş | Yanlış bilgi girilirse kırmızı hata mesajı görünür |

### Hata Durumları
| Hata | Sebep | Çözüm |
|------|-------|-------|
| "Kullanıcı adı veya şifre hatalı" | Yanlış bilgi girildi | Bilgileri kontrol edin |
| "Hesabınız henüz onaylanmamış" | Admin onayı bekleniyor | Yöneticinize başvurun |

---

## 3. Kayıt Olma (Register)

Sisteme ilk kez katılıyorsanız kayıt olmanız gerekir.

### Gerekli Bilgiler
| Alan | Format | Zorunlu | Açıklama |
|------|--------|---------|----------|
| Ad Soyad | Metin | ✅ | Tam adınız |
| Kullanıcı Adı | Metin | ✅ | Giriş için kullanılacak |
| E-posta | ornek@email.com | ✅ | Geçerli e-posta adresi |
| Telefon | 5XX XXX XXXX | ✅ | 10 haneli (başında 0 olmadan) |
| Şifre | Min 8 karakter | ✅ | Güçlü şifre |
| Şifre Tekrar | Min 8 karakter | ✅ | Şifre ile aynı olmalı |

### Adımlar
1. Giriş sayfasında **"Kayıt Ol"** sekmesine tıklayın
2. Tüm alanları doldurun
3. **"Kayıt Ol"** butonuna tıklayın
4. Başarılı kayıt mesajı alacaksınız
5. ⚠️ **Admin onayı** gerekir — onaylandıktan sonra giriş yapabilirsiniz

### Validasyon Kuralları
- **Telefon:** Sadece rakam, 10 hane (5XX XXX XXXX)
- **Şifre:** Minimum 8 karakter
- **Şifre Tekrar:** Şifre alanıyla birebir eşleşmeli
- **E-posta:** Geçerli e-posta formatı

---

## 4. Oturum Yönetimi

### JWT Token Sistemi
VYRA, güvenli oturum yönetimi için JWT (JSON Web Token) kullanır:

| Token | Süre | Kullanım |
|-------|------|----------|
| Access Token | 12 saat | API isteklerinde kullanılır |
| Refresh Token | 7 gün | Access token yenilemek için |

### Otomatik Yenileme
- Access token süresi dolduğunda refresh token ile otomatik yenilenir
- Refresh token süresi dolduğunda login sayfasına yönlendirilirsiniz

### Çıkış Yapma
- Sol menüden (sidebar) **çıkış** butonuna tıklayın
- Token'lar temizlenir ve giriş sayfasına yönlendirilirsiniz

---

## 5. Ana Sayfa Yapısı

Giriş yaptıktan sonra ana sayfa açılır. Ana sayfa şu bölümlerden oluşur:

```
┌──────────────────────────────────────────────┐
│  [Logo]     Başlık     [🔔 Bildirimler]      │
├──────────────────────────────────────────────┤
│  📋 Sidebar  │  🤖 VYRA'ya Sor  |  Geçmiş   │
│  ─────────── │  ─────────────────────────── │
│  • Dialog    │                               │
│  • RAG       │     [Ana İçerik Alanı]        │
│  • Tickets   │                               │
│  • Admin     │                               │
│  • Çıkış     │                               │
└──────────────────────────────────────────────┘
```

### Sekmeler
| Sekme | İkon | Açıklama |
|-------|------|----------|
| VYRA'ya Sor | 🤖 | AI chatbot ile soru-cevap |
| Geçmiş Çözümler | 📋 | Önceki destek geçmişi |

### Sidebar Menü (Sol Panel)
Sidebar'dan tüm modüllere erişebilirsiniz. Detayları ilgili dokümanlardan inceleyebilirsiniz:
- [Soru Sorma ve Dialog](soru_sorma_ve_dialog.md)
- [RAG Bilgi Bankası](rag_bilgi_bankasi.md)
- [Destek Talepleri](destek_talepleri.md)
- [Admin Paneli](admin_paneli.md) (yetki gerekir)

---

## 6. Bildirimler

Sağ üst köşedeki 🔔 ikonu üzerinden sistem bildirimlerini takip edebilirsiniz:
- Yeni ticket güncellemeleri
- Admin mesajları
- Sistem duyuruları

---

> 📌 Sonraki adım: [Soru Sorma ve Dialog](soru_sorma_ve_dialog.md)
