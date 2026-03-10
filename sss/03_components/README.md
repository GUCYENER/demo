# 🧩 Bileşen Dokümantasyonu

| Bilgi | Değer |
|-------|-------|
| **Versiyon** | v2.36.1 |
| **Son Güncelleme** | 2026-02-10 |
| **Durum** | ✅ Güncel |

---

## 📖 Bileşen Kataloğu

### Backend Bileşenleri (Python)

| # | Doküman | Modüller | Açıklama |
|---|---------|----------|----------|
| 1 | [Dialog Pipeline](backend/dialog_pipeline.md) | `dialog/processor.py`, `dialog/response_builder.py`, `dialog/messages.py`, `dialog/crud.py` | Soru → İşleme → Yanıt akışı |
| 2 | [RAG Pipeline](backend/rag_pipeline.md) | `rag/service.py`, `rag/embedding.py`, `rag/scoring.py` | Upload → Chunk → Embed → Search → Rerank |
| 3 | [Doküman İşleyiciler](backend/document_processors.md) | `document_processors/*.py` | Format-spesifik dosya çıkarma |
| 4 | [OCR Sistemi](backend/ocr_system.md) | `image_extractor.py`, `ocr_service.py` | EasyOCR ile metin çıkarma |
| 5 | [ML Eğitim](backend/ml_training.md) | `catboost_service.py`, `feature_extractor.py`, `ml_training/` | CatBoost reranking modeli |
| 6 | [Doküman İyileştirici](backend/document_enhancer.md) | `document_enhancer.py` | LLM tabanlı doküman zenginleştirme |
| 7 | [Olgunluk Analizi](backend/maturity_analyzer.md) | `maturity_analyzer.py` | Doküman kalite skorlama |

### Frontend Bileşenleri (JavaScript)

| # | Doküman | Modüller | Açıklama |
|---|---------|----------|----------|
| 1 | [Dialog Modülleri](frontend/dialog_modules.md) | `dialog_chat.js`, `dialog_chat_utils.js`, `dialog_voice.js`, `dialog_images.js` | Chat UI ve yardımcılar |
| 2 | [RAG Modülleri](frontend/rag_modules.md) | `rag_cards.js`, `rag_file_list.js`, `rag_org_modal.js`, `rag_file_org_edit.js` | Dosya yönetimi UI |
| 3 | [Ticket Modülleri](frontend/ticket_modules.md) | `ticket_handler.js`, `ticket_chat.js`, `ticket_formatter.js`, `ticket_llm_eval.js` | Ticket UI |
| 4 | [Admin Modülleri](frontend/admin_modules.md) | `llm_module.js`, `prompt_module.js`, `permissions_manager.js`, `ml_training.js` | Yönetim UI |
| 5 | [Yardımcı Modüller](frontend/utility_modules.md) | `rag_image_lightbox.js`, `rag_ocr_popup.js`, `sidebar_module.js` | Genel yardımcılar |
