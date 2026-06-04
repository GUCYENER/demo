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
