"""
VYRA L1 Support API - Dialog Service (Backward-Compatible Shim)
================================================================
Bu dosya geriye dönük uyumluluk (backward compatibility) için korunmuştur.

Tüm iş mantığı app/services/dialog/ paketine taşınmıştır.
Yeni kod bu dosyadan DEĞİL, doğrudan dialog paketinden import etmelidir:

    from app.services.dialog import create_dialog, process_user_message, ...

Bu shim dosyası mevcut import'ların bozulmamasını sağlar.

Version: 2.30.0 (Modular Refactor)
"""

# Re-export everything from the dialog package
from app.services.dialog import *  # noqa: F401, F403

# Private function backward compatibility
from app.services.dialog.response_builder import (
    parse_chunk_details as _parse_chunk_details,
    build_response as _build_response,
    format_single_result as _format_single_result,
    format_multiple_choices as _format_multiple_choices,
    format_confirmed_solution as _format_confirmed_solution,
    format_multi_solution as _format_multi_solution,
    get_short_label as _get_short_label,
    create_error_response as _create_error_response,
    check_user_has_accessible_documents,
)

from app.services.dialog.processor import (
    perform_rag_search as _perform_rag_search,
    extract_ocr_texts as _extract_ocr_texts,
    _legacy_process,
)

from app.services.dialog.messages import (
    get_last_assistant_with_quick_reply as _get_last_assistant_with_quick_reply,
    get_message_by_id as _get_message_by_id,
    find_rag_results_in_history as _find_rag_results_in_history,
    get_original_query as _get_original_query,
)

from app.services.dialog.ai_evaluation import (
    evaluate_with_llm as _evaluate_with_llm,
)
