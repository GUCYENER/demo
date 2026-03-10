# Admin Modülleri — Frontend Bileşen Dokümantasyonu

| Bilgi | Değer |
|-------|-------|
| **Versiyon** | v2.36.1 |
| **Son Güncelleme** | 2026-02-10 |
| **Konum** | `frontend/assets/js/modules/` |
| **Yetki** | ⚠️ Admin rolü gerektirir |
| **Durum** | ✅ Güncel |

---

## 1. Modül Listesi

| Modül | Dosya | Amaç |
|-------|-------|------|
| **LLM Module** | `llm_module.js` | LLM yapılandırma UI |
| **Prompt Module** | `prompt_module.js` | Prompt şablon düzenleyici |
| **Permissions Manager** | `permissions_manager.js` | RBAC izin yönetimi |
| **ML Training** | `ml_training.js` | CatBoost eğitim yönetimi |
| **Param Tabs** | `param_tabs.js` | Admin tab navigasyonu |

---

## 2. `llm_module.js`

### Ana Fonksiyonlar
| Fonksiyon | Açıklama |
|-----------|----------|
| `initLLMModule()` | LLM ayarları panelini başlat |
| `loadConfig()` | Mevcut yapılandırmayı getir |
| `saveConfig(data)` | Yapılandırmayı kaydet |
| `testConnection()` | LLM bağlantısını test et |

### UI Elemanları
| Eleman | Tip | Açıklama |
|--------|-----|----------|
| Model seçici | Select | Model adı |
| Provider | Select | Google AI, OpenAI vb. |
| Temperature | Range (0-1) | Yanıt çeşitliliği |
| Max Tokens | Input | Maksimum token sayısı |
| API URL | Input | Endpoint adresi |
| Test butonu | Button | Bağlantı testi |

---

## 3. `prompt_module.js`

### Ana Fonksiyonlar
| Fonksiyon | Açıklama |
|-----------|----------|
| `initPromptModule()` | Prompt editörünü başlat |
| `loadPrompts()` | Prompt listesini getir |
| `savePrompt(id, content)` | Prompt'u kaydet |
| `resetPrompt(id)` | Varsayılana dön |

### Prompt Kategorileri
| Kategori | Açıklama |
|----------|----------|
| `system` | VYRA temel davranış |
| `rag_search` | Arama yanıt formatı |
| `enhancement` | Doküman iyileştirme |

---

## 4. `permissions_manager.js`

### Modül/Rol İzin Matrisi
Admin panelinden hangi modüllerin hangi rollere açık olduğunu yönetir.

| Fonksiyon | Açıklama |
|-----------|----------|
| `loadPermissions()` | Mevcut izin matrisini getir |
| `togglePermission(module, role)` | İzni aç/kapat |
| `savePermissions()` | Değişiklikleri kaydet |

---

## 5. `ml_training.js`

### Ana Fonksiyonlar
| Fonksiyon | Açıklama |
|-----------|----------|
| `initMLTraining()` | Eğitim panelini başlat |
| `startTraining()` | Yeni model eğitimi başlat |
| `loadHistory()` | Eğitim geçmişini getir |
| `showModelInfo()` | Aktif model bilgisi |
| `showTrainingSamples()` | Eğitim verilerini incele |
