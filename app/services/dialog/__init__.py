"""
VYRA L1 Support API - Dialog Service Package
==============================================
Modüler dialog servisi public API.

Tüm tüketici modüller bu __init__.py üzerinden import yapmalıdır.
Bu sayede dahili modül yapısı değiştiğinde tüketici kodlar etkilenmez.

Refactored from monolithic dialog_service.py (v2.29.14)

Modül Yapısı:
  dialog/
  ├── __init__.py          # Public API (bu dosya)
  ├── crud.py              # Dialog CRUD işlemleri 
  ├── messages.py          # Mesaj CRUD & feedback
  ├── processor.py         # AI processing orchestrator
  ├── response_builder.py  # Yanıt formatlama & chunk parsing
  ├── ai_evaluation.py     # LLM değerlendirme
  └── corpix.py            # Corpix fallback & ticket özeti
"""

# === DIALOG CRUD ===
from app.services.dialog.crud import (
    create_dialog,
    get_active_dialog,
    get_or_create_active_dialog,
    close_dialog,
    close_inactive_dialogs,
    list_user_dialogs,
    get_dialog_history,
)

# === MESSAGE CRUD ===
from app.services.dialog.messages import (
    add_message,
    update_message_metadata,
    get_dialog_messages,
    add_message_feedback,
)

# === AI PROCESSING ===
from app.services.dialog.processor import (
    process_user_message,
    process_quick_reply,
)

# === CORPIX & TICKET ===
from app.services.dialog.corpix import (
    ask_corpix,
    generate_ticket_summary,
)

# === RESPONSE HELPERS (dahili kullanım için de export) ===
from app.services.dialog.response_builder import (
    parse_chunk_details,
    check_user_has_accessible_documents,
)

# Geriye dönük uyumluluk: Önceki _ prefix'li fonksiyon isimleri
_parse_chunk_details = parse_chunk_details
