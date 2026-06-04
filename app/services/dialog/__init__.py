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
# === CORPIX & TICKET ===
from app.services.dialog.corpix import (
    ask_corpix,
    generate_ticket_summary,
)
from app.services.dialog.crud import (
    close_dialog,
    close_inactive_dialogs,
    create_dialog,
    get_active_dialog,
    get_dialog_history,
    get_or_create_active_dialog,
    list_user_dialogs,
)

# === MESSAGE CRUD ===
from app.services.dialog.messages import (
    add_message,
    add_message_feedback,
    get_dialog_messages,
    update_message_metadata,
)

# === AI PROCESSING ===
from app.services.dialog.processor import (
    process_quick_reply,
    process_user_message,
)

# === RESPONSE HELPERS (dahili kullanım için de export) ===
from app.services.dialog.response_builder import (
    check_user_has_accessible_documents,
    parse_chunk_details,
)

# Geriye dönük uyumluluk: Önceki _ prefix'li fonksiyon isimleri
_parse_chunk_details = parse_chunk_details
