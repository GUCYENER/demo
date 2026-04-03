"""
VYRA L1 Support API - Content Anchor Service
==============================================
LLM iyileştirme öncesi kritik veri noktalarını çıkarır,
placeholder ile değiştirir ve iyileştirme sonrası geri yerleştirir.

"Extract-Protect-Reinject" Pattern:
1. extract_anchors(): Sayılar, tarihler, URL'ler, kodları placeholder'a çevirir
2. reinject_anchors(): Placeholder'ları orijinal değerlerle geri doldurur
3. recover_missing(): LLM'in sildiği anchor'ları otomatik geri ekler

Author: VYRA AI Team
Version: 1.0.0 (v3.3.3)
"""

import re
from typing import Dict, List, Tuple
from dataclasses import dataclass, field

from app.services.logging_service import log_system_event


# ============================================
# Anchor Result
# ============================================

@dataclass
class AnchorResult:
    """Anchor extraction sonucu"""
    sanitized_text: str                           # Placeholder'lı metin
    anchor_registry: Dict[str, str] = field(default_factory=dict)  # {ANCHOR_ID: original_value}
    anchor_count: int = 0                         # Toplam anchor sayısı
    anchor_types: Dict[str, int] = field(default_factory=dict)     # {tip: adet}


# ============================================
# Regex Patterns — Kritik veri tespiti
# ============================================

# Para birimi + sayılar (öncelikli — daha spesifik)
_CURRENCY_PATTERN = re.compile(
    r'(?:[$€₺]|TL|USD|EUR)\s?\d[\d.,]*'   # $1.234 veya 1.234 TL
    r'|\d[\d.,]*\s?(?:TL|USD|EUR|₺)',       # 1.234,56 TL
    re.UNICODE
)

# Yüzde ifadeleri
_PERCENT_PATTERN = re.compile(
    r'%\s?\d[\d.,]*'        # %95,5
    r'|\d[\d.,]*\s?%',      # 95,5%
    re.UNICODE
)

# Genel sayılar (2+ hane — anlamsız tek hane hariç)
_NUMBER_PATTERN = re.compile(
    r'(?<!\w)'
    r'\d[\d.,]{1,}'          # En az 2 karakter (ör: 12, 1.5, 3.500)
    r'(?!\w)',
    re.UNICODE
)

# Tarihler (çeşitli formatlar)
_DATE_PATTERN = re.compile(
    r'\b\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}\b'     # DD/MM/YYYY, DD.MM.YYYY
    r'|\b\d{4}[./\-]\d{1,2}[./\-]\d{1,2}\b'       # YYYY-MM-DD
    r'|\b\d{1,2}\s+(?:Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık)\s+\d{4}\b'
)

# Saat formatları
_TIME_PATTERN = re.compile(
    r'\b\d{1,2}[.:]\d{2}(?:[.:]\d{2})?\b'   # 12:15, 08.30, 14:30:00
)

# URL/Email
_URL_PATTERN = re.compile(
    r'https?://[^\s<>"]+|www\.[^\s<>"]+|\b[\w.+-]+@[\w-]+\.[\w.-]+\b'
)

# Kod/komut blokları
_CODE_PATTERN = re.compile(r'`[^`]+`')

# Teknik kısaltmalar (2+ büyük harf)
_ACRONYM_PATTERN = re.compile(
    r'\b[A-ZÇĞİÖŞÜ]{2,}(?:/[A-ZÇĞİÖŞÜ]{2,})*\b'
)

# Telefon numaraları
_PHONE_PATTERN = re.compile(
    r'\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{2}[-.\s]?\d{2}\b'
)


# ============================================
# Content Anchor Service
# ============================================

class ContentAnchorService:
    """
    LLM'e gönderilecek içerikten kritik verileri çıkarıp placeholder ile korur.

    Kullanım:
        service = ContentAnchorService()
        result = service.extract_anchors(original_text)
        # result.sanitized_text → LLM'e gönder
        # LLM yanıtı gelince:
        final = service.reinject_anchors(llm_output, result.anchor_registry)
        final, recovered = service.recover_missing(final, result.anchor_registry, original_text)
    """

    # Anchor format: ‹‹ANC_001›› — LLM'in silme veya değiştirme riski düşük Unicode ayraçlar
    ANCHOR_PREFIX = "‹‹ANC_"
    ANCHOR_SUFFIX = "››"

    def extract_anchors(self, text: str) -> AnchorResult:
        """
        Metindeki tüm kritik veri noktalarını tespit edip placeholder ile değiştirir.

        Çıkarma sırası önemli — daha spesifik pattern'ler önce:
        1. URL/Email (en spesifik)
        2. Tarihler
        3. Saatler
        4. Para birimi + sayılar
        5. Yüzde ifadeleri
        6. Telefon numaraları
        7. Kod blokları
        8. Genel sayılar (en genel — en son)

        Returns:
            AnchorResult
        """
        if not text or len(text.strip()) < 10:
            return AnchorResult(sanitized_text=text, anchor_count=0)

        registry = {}
        type_counts = {}
        counter = 0
        working_text = text

        # Çıkarma sırası: spesifikten genele
        extraction_order = [
            ("url", _URL_PATTERN),
            ("date", _DATE_PATTERN),
            ("time", _TIME_PATTERN),
            ("phone", _PHONE_PATTERN),
            ("currency", _CURRENCY_PATTERN),
            ("percent", _PERCENT_PATTERN),
            ("code", _CODE_PATTERN),
            ("number", _NUMBER_PATTERN),
        ]

        for anchor_type, pattern in extraction_order:
            matches = list(pattern.finditer(working_text))
            if not matches:
                continue

            # Reverse order — sondan başa değiştir (index kayması önlenir)
            for match in reversed(matches):
                original_value = match.group(0).strip()

                # Boş veya çok kısa değerleri atla
                if not original_value or len(original_value) < 2:
                    continue

                # Zaten bir anchor mı? (iç içe eşleşme önle)
                if self.ANCHOR_PREFIX in original_value:
                    continue

                counter += 1
                anchor_id = f"{self.ANCHOR_PREFIX}{counter:03d}{self.ANCHOR_SUFFIX}"

                registry[anchor_id] = original_value
                type_counts[anchor_type] = type_counts.get(anchor_type, 0) + 1

                # Metinde değiştir
                start, end = match.start(), match.end()
                working_text = working_text[:start] + anchor_id + working_text[end:]

        if counter > 0:
            log_system_event(
                "DEBUG",
                f"Anchor extraction: {counter} anchor çıkarıldı — {type_counts}",
                "anchor"
            )

        return AnchorResult(
            sanitized_text=working_text,
            anchor_registry=registry,
            anchor_count=counter,
            anchor_types=type_counts
        )

    def reinject_anchors(
        self, enhanced_text: str, registry: Dict[str, str]
    ) -> str:
        """
        LLM çıktısındaki placeholder'ları orijinal değerlerle geri doldurur.

        Returns:
            Anchor'ları geri yerleştirilmiş metin
        """
        if not registry or not enhanced_text:
            return enhanced_text

        result = enhanced_text
        injected = 0

        for anchor_id, original_value in registry.items():
            if anchor_id in result:
                result = result.replace(anchor_id, original_value)
                injected += 1

        if injected > 0:
            log_system_event(
                "DEBUG",
                f"Anchor re-injection: {injected}/{len(registry)} anchor geri yerleştirildi",
                "anchor"
            )

        return result

    def recover_missing(
        self,
        enhanced_text: str,
        registry: Dict[str, str],
        original_text: str
    ) -> Tuple[str, List[str]]:
        """
        LLM'in sildiği anchor'ları tespit edip otomatik geri ekler.

        Strateji:
        1. Enhanced text'te olmayan anchor'ları bul
        2. Orijinal metinde anchor'ın bağlamını (önceki/sonraki kelimeler) bul
        3. Enhanced text'te aynı bağlamı ara → orada ekle
        4. Bağlam bulunamazsa → bölüm sonuna ekle

        Returns:
            (düzeltilmiş metin, kurtarılan anchor listesi)
        """
        if not registry:
            return enhanced_text, []

        recovered = []
        result = enhanced_text

        for anchor_id, original_value in registry.items():
            # Anchor placeholder hala var mı? (reinject yapılmamışsa)
            if anchor_id in result:
                continue

            # Orijinal değer zaten enhanced text'te var mı?
            if original_value in result:
                continue

            # Kayıp! → Kurtarma
            # Orijinal metinde bu değerin bağlamını bul
            context_inserted = self._context_based_recovery(
                result, original_value, original_text
            )

            if context_inserted is not None:
                result = context_inserted
                recovered.append(f"[bağlam] {original_value}")
            else:
                # Fallback: bölüm sonuna ekle
                result = result.rstrip() + f"\n{original_value}"
                recovered.append(f"[sonuna] {original_value}")

        if recovered:
            log_system_event(
                "WARNING",
                f"Anchor recovery: {len(recovered)} kayıp veri kurtarıldı: "
                f"{', '.join(recovered[:5])}",
                "anchor"
            )

        return result, recovered

    def _context_based_recovery(
        self, enhanced_text: str, lost_value: str, original_text: str
    ) -> str | None:
        """
        Kayıp değeri orijinal bağlamına bakarak enhanced text'te doğru yere ekler.

        Returns:
            Düzeltilmiş metin veya None (bağlam bulunamazsa)
        """
        # Orijinal metinde lost_value'nun konumunu bul
        pos = original_text.find(lost_value)
        if pos < 0:
            return None

        # Önceki ve sonraki kelime gruplarını çıkar (bağlam)
        before_context = original_text[max(0, pos - 60):pos].strip()

        # Önceki bağlamın son 3-4 kelimesini al
        before_words = before_context.split()[-4:] if before_context else []
        before_phrase = " ".join(before_words) if before_words else ""

        # Enhanced text'te bu bağlamı ara
        if before_phrase and len(before_phrase) > 5:
            ctx_pos = enhanced_text.find(before_phrase)
            if ctx_pos >= 0:
                insert_pos = ctx_pos + len(before_phrase)
                # Değeri orijinal bağlamıyla birlikte ekle
                return (
                    enhanced_text[:insert_pos]
                    + " " + lost_value + " "
                    + enhanced_text[insert_pos:]
                )

        return None

    def get_anchor_summary(self, registry: Dict[str, str]) -> str:
        """LLM prompt'una eklenecek anchor özeti — hangi placeholder ne anlama geliyor."""
        if not registry:
            return ""

        lines = ["⛔ KRİTİK VERİ KORUMA — Aşağıdaki placeholder'lar gerçek değerleri temsil eder, AYNEN KORU:"]
        for anchor_id, value in list(registry.items())[:20]:  # Max 20 göster
            lines.append(f"  {anchor_id} = (korunan veri)")

        return "\n".join(lines)


# ============================================
# Singleton instance
# ============================================

_anchor_service_instance = None


def get_anchor_service() -> ContentAnchorService:
    """Singleton anchor service instance"""
    global _anchor_service_instance
    if _anchor_service_instance is None:
        _anchor_service_instance = ContentAnchorService()
    return _anchor_service_instance
