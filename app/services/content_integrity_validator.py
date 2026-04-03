"""
VYRA L1 Support API - Content Integrity Validator
===================================================
LLM iyileştirme sonrası içerik bütünlüğü doğrulama.

Kontroller:
1. İçerik Kaybı: Sayılar, tarihler, özel terimler korunuyor mu?
2. Halüsinasyon: Orijinalde olmayan yeni bilgi eklenmiş mi?
3. Uzunluk Oranı: Çok fazla kısaltma veya şişirme var mı?
4. Yapısal Bütünlük: Tablo satır sayısı, anahtar kelime bütünlüğü

Author: VYRA AI Team
Version: 1.0.0 (v3.2.1)
"""

import re
from typing import Dict, Any, List, Tuple, Set
from dataclasses import dataclass, field

from app.services.logging_service import log_system_event, log_warning


# ============================================
# Validation Result
# ============================================

@dataclass
class IntegrityResult:
    """Bütünlük doğrulama sonucu"""
    is_valid: bool                          # Geçti mi?
    score: float                            # 0.0–1.0 (1.0 = mükemmel bütünlük)
    issues: List[str] = field(default_factory=list)     # Tespit edilen sorunlar
    warnings: List[str] = field(default_factory=list)   # Uyarılar (geçer ama dikkat)
    lost_entities: List[str] = field(default_factory=list)       # Kaybolan varlıklar
    hallucinated_entities: List[str] = field(default_factory=list)  # Halüsinasyon şüphesi
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "score": round(self.score, 3),
            "issues": self.issues,
            "warnings": self.warnings,
            "lost_entities": self.lost_entities[:10],  # Max 10 göster
            "hallucinated_entities": self.hallucinated_entities[:10]
        }


# ============================================
# Regex Patterns — Önemli veri tespiti
# ============================================

# Sayılar (ondalık, yüzde, para birimi)
_NUM_PATTERN = re.compile(
    r'(?<!\w)'                  # Kelime başı
    r'(?:\$|€|₺|TL|USD)?'      # Opsiyonel para birimi
    r'\s?'
    r'\d[\d.,]*'                # Sayı (1.234,56 formatı dahil)
    r'(?:\s?%)?'                # Opsiyonel yüzde
    r'(?!\w)',                  # Kelime sonu
    re.UNICODE
)

# Tarihler (çeşitli formatlar)
_DATE_PATTERN = re.compile(
    r'\b\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}\b'   # DD/MM/YYYY, DD.MM.YYYY
    r'|\b\d{4}[./\-]\d{1,2}[./\-]\d{1,2}\b'     # YYYY-MM-DD
    r'|\b\d{1,2}\s+(?:Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık)\s+\d{4}\b'  # 15 Ocak 2024
)

# Özel isimler, teknik terimler (büyük harfle başlayan 2+ kelime)
_PROPER_NOUN_PATTERN = re.compile(
    r'\b[A-ZÇĞİÖŞÜ][a-zçğıöşü]+(?:\s+[A-ZÇĞİÖŞÜ][a-zçğıöşü]+)+\b'
)

# Tablo satırları (pipe separator veya tab-separated)
_TABLE_ROW_PATTERN = re.compile(r'^.*\|.*\|.*$', re.MULTILINE)

# URL/Email
_URL_PATTERN = re.compile(
    r'https?://[^\s<>"]+|www\.[^\s<>"]+|\b[\w.+-]+@[\w-]+\.[\w.-]+\b'
)

# Kod/komut blokları (backtick veya teknik terimler)
_CODE_PATTERN = re.compile(r'`[^`]+`|\b(?:SELECT|INSERT|UPDATE|DELETE|FROM|WHERE)\b', re.IGNORECASE)


# ============================================
# Content Integrity Validator
# ============================================

class ContentIntegrityValidator:
    """
    LLM iyileştirme sonrası içerik bütünlüğü doğrulayıcı.
    
    Kullanım:
        validator = ContentIntegrityValidator()
        result = validator.validate(original_text, enhanced_text, file_type)
        if not result.is_valid:
            # Orijinal metni koru, iyileştirmeyi reddet
    """
    
    # ─── Eşik Değerler ───
    # Uzunluk oranı: enhanced / original
    MIN_LENGTH_RATIO = 0.60    # %40'tan fazla küçülmemeli
    MAX_LENGTH_RATIO = 2.0     # 2 kattan fazla büyümemeli
    
    # Entity koruma oranı
    MIN_NUMBER_RETENTION = 0.90   # Sayıların %90'ı korunmalı
    MIN_DATE_RETENTION = 1.0     # Tarihlerin %100'ü korunmalı  
    MIN_URL_RETENTION = 1.0      # URL'lerin %100'ü korunmalı
    MIN_KEYWORD_RETENTION = 0.80 # Anahtar kelimelerin %80'i korunmalı
    
    # Halüsinasyon eşiği
    MAX_NEW_NUMBER_RATIO = 0.15  # Yeni sayılar orijinalin %15'inden fazla olmamalı
    MAX_NEW_PROPER_RATIO = 0.10  # Yeni özel isimler %10'u geçmemeli
    
    # Bütünlük skoru eşiği
    MIN_INTEGRITY_SCORE = 0.70   # Bu skorun altı = RED
    
    def validate(
        self,
        original: str,
        enhanced: str,
        file_type: str = "",
        weakness_types: List[str] = None
    ) -> IntegrityResult:
        """
        Orijinal ve iyileştirilmiş metin arasında bütünlük doğrulaması.
        
        Args:
            original: Orijinal metin
            enhanced: LLM tarafından iyileştirilmiş metin
            file_type: Dosya tipi (XLSX, DOCX vb.)
            weakness_types: Bilinen zayıflık tipleri (bazı kontrolleri gevşetir)
            
        Returns:
            IntegrityResult
        """
        if not original or not enhanced:
            return IntegrityResult(is_valid=False, score=0.0, issues=["Boş içerik"])
        
        weakness_types = weakness_types or []
        issues = []
        warnings = []
        lost_entities = []
        hallucinated_entities = []
        scores = []  # Her kontrolün skoru
        
        # ─── 1. Uzunluk Oranı Kontrolü ───
        length_score, length_issues = self._check_length_ratio(
            original, enhanced, weakness_types
        )
        scores.append(("length", length_score, 0.15))
        issues.extend(length_issues)
        
        # ─── 2. Sayı Korunma Kontrolü ───
        num_score, num_issues, num_lost = self._check_number_retention(
            original, enhanced
        )
        scores.append(("numbers", num_score, 0.25))
        issues.extend(num_issues)
        lost_entities.extend(num_lost)
        
        # ─── 3. Tarih Korunma Kontrolü ───
        date_score, date_issues, date_lost = self._check_date_retention(
            original, enhanced
        )
        scores.append(("dates", date_score, 0.20))
        issues.extend(date_issues)
        lost_entities.extend(date_lost)
        
        # ─── 4. URL/Email Korunma Kontrolü ───
        url_score, url_issues, url_lost = self._check_url_retention(
            original, enhanced
        )
        scores.append(("urls", url_score, 0.15))
        issues.extend(url_issues)
        lost_entities.extend(url_lost)
        
        # ─── 5. Anahtar Kelime Korunma ───
        kw_score, kw_issues, kw_lost = self._check_keyword_retention(
            original, enhanced, file_type
        )
        scores.append(("keywords", kw_score, 0.15))
        if kw_issues:
            warnings.extend(kw_issues)
        lost_entities.extend(kw_lost)
        
        # ─── 6. Halüsinasyon Kontrolü ───
        hal_score, hal_warnings, hal_entities = self._check_hallucination(
            original, enhanced
        )
        scores.append(("hallucination", hal_score, 0.10))
        warnings.extend(hal_warnings)
        hallucinated_entities.extend(hal_entities)
        
        # ─── 7. Tablo Bütünlüğü (Excel/tablo içeriği) ───
        if file_type in ("XLSX", "XLS", "CSV") or "|" in original:
            table_score, table_issues = self._check_table_integrity(
                original, enhanced
            )
            scores.append(("table", table_score, 0.20))
            issues.extend(table_issues)
        
        # ─── Final Skor Hesaplama (ağırlıklı) ───
        total_weight = sum(w for _, _, w in scores)
        final_score = sum(s * w for _, s, w in scores) / total_weight if total_weight > 0 else 0.0
        
        is_valid = final_score >= self.MIN_INTEGRITY_SCORE and not any(
            "[KRİTİK]" in i for i in issues
        )
        
        # Loglama
        log_system_event(
            "INFO" if is_valid else "WARNING",
            f"Bütünlük doğrulama: skor={final_score:.3f}, geçerli={is_valid}, "
            f"sorun={len(issues)}, kayıp={len(lost_entities)}, "
            f"halüsinasyon={len(hallucinated_entities)}",
            "integrity"
        )
        
        return IntegrityResult(
            is_valid=is_valid,
            score=final_score,
            issues=issues,
            warnings=warnings,
            lost_entities=lost_entities,
            hallucinated_entities=hallucinated_entities
        )
    
    # ─────────────────────────────────────────
    #  Kontrol Fonksiyonları
    # ─────────────────────────────────────────
    
    def _check_length_ratio(
        self, original: str, enhanced: str, weakness_types: List[str]
    ) -> Tuple[float, List[str]]:
        """Uzunluk oranı kontrolü"""
        issues = []
        orig_len = len(original.strip())
        enh_len = len(enhanced.strip())
        
        if orig_len == 0:
            return (1.0, [])
        
        ratio = enh_len / orig_len
        
        # Weakness'e göre eşikleri ayarla
        min_ratio = self.MIN_LENGTH_RATIO
        max_ratio = self.MAX_LENGTH_RATIO
        
        # redundant_content veya empty_gaps varsa daha fazla küçülme kabul
        if any(wt in weakness_types for wt in ("redundant_content", "empty_gaps", "excess_whitespace")):
            min_ratio = 0.40
        
        # content_too_short varsa daha fazla büyüme kabul
        if "content_too_short" in weakness_types:
            max_ratio = 3.0
        
        if ratio < min_ratio:
            issues.append(
                f"[KRİTİK] İçerik aşırı kısaltılmış (oran: {ratio:.1%}). "
                f"Orijinal: {orig_len} → İyileştirilmiş: {enh_len} karakter"
            )
            return (0.0, issues)
        
        if ratio > max_ratio:
            issues.append(
                f"[KRİTİK] İçerik aşırı şişirilmiş (oran: {ratio:.1%}). "
                f"Halüsinasyon riski yüksek."
            )
            return (0.2, issues)
        
        # Normal aralıkta — 0.8-1.2 arası ideal
        if 0.80 <= ratio <= 1.30:
            return (1.0, [])
        else:
            score = max(0.5, 1.0 - abs(ratio - 1.0) * 0.5)
            return (score, [])
    
    def _check_number_retention(
        self, original: str, enhanced: str
    ) -> Tuple[float, List[str], List[str]]:
        """Sayıların korunma oranı"""
        orig_numbers = set(_NUM_PATTERN.findall(original))
        enh_numbers = set(_NUM_PATTERN.findall(enhanced))
        
        if not orig_numbers:
            return (1.0, [], [])
        
        # Korunan sayılar
        retained = orig_numbers & enh_numbers
        lost = orig_numbers - enh_numbers
        
        # Anlamsız sayıları filtrele (tek haneli sayılar, 0, 1 gibi)
        significant_lost = [n for n in lost if len(n.strip()) > 1 and n.strip() not in ("0", "1", "2")]
        
        retention_rate = len(retained) / len(orig_numbers) if orig_numbers else 1.0
        
        issues = []
        if retention_rate < self.MIN_NUMBER_RETENTION and significant_lost:
            issues.append(
                f"[KRİTİK] Sayısal veri kaybı tespit edildi. "
                f"Korunma: {retention_rate:.0%} ({len(lost)} sayı kayıp)"
            )
        
        # Skor: retention rate ile doğru orantılı
        score = min(1.0, retention_rate / self.MIN_NUMBER_RETENTION)
        
        return (score, issues, [f"SAYI: {n}" for n in significant_lost[:5]])
    
    def _check_date_retention(
        self, original: str, enhanced: str
    ) -> Tuple[float, List[str], List[str]]:
        """Tarihlerin %100 korunma kontrolü"""
        orig_dates = set(_DATE_PATTERN.findall(original))
        enh_dates = set(_DATE_PATTERN.findall(enhanced))
        
        if not orig_dates:
            return (1.0, [], [])
        
        lost = orig_dates - enh_dates
        
        issues = []
        if lost:
            issues.append(
                f"[KRİTİK] Tarih verisi kaybolmuş: {', '.join(list(lost)[:3])}"
            )
            score = len(enh_dates & orig_dates) / len(orig_dates) if orig_dates else 1.0
            return (score, issues, [f"TARİH: {d}" for d in lost])
        
        return (1.0, [], [])
    
    def _check_url_retention(
        self, original: str, enhanced: str
    ) -> Tuple[float, List[str], List[str]]:
        """URL/Email korunma kontrolü"""
        orig_urls = set(_URL_PATTERN.findall(original))
        enh_urls = set(_URL_PATTERN.findall(enhanced))
        
        if not orig_urls:
            return (1.0, [], [])
        
        lost = orig_urls - enh_urls
        
        issues = []
        if lost:
            issues.append(
                f"[KRİTİK] URL/Email kaybolmuş: {', '.join(list(lost)[:2])}"
            )
            score = len(enh_urls & orig_urls) / len(orig_urls) if orig_urls else 1.0
            return (score, issues, [f"URL: {u[:50]}" for u in lost])
        
        return (1.0, [], [])
    
    def _check_keyword_retention(
        self, original: str, enhanced: str, file_type: str
    ) -> Tuple[float, List[str], List[str]]:
        """Anahtar kelime korunma kontrolü (TF tabanlı)"""
        # Kelime frekans analizi
        orig_words = self._extract_significant_words(original)
        enh_words = self._extract_significant_words(enhanced)
        
        if not orig_words:
            return (1.0, [], [])
        
        # Orijinaldeki en sık kelimeler (top N)
        top_n = min(30, len(orig_words))
        orig_top = set(list(orig_words.keys())[:top_n])
        
        # Kaç tanesi iyileştirilmişte var?
        retained = orig_top & set(enh_words.keys())
        lost = orig_top - set(enh_words.keys())
        
        retention_rate = len(retained) / len(orig_top) if orig_top else 1.0
        
        issues = []
        if retention_rate < self.MIN_KEYWORD_RETENTION:
            issues.append(
                f"Anahtar kelime kaybı: {retention_rate:.0%} korunma. "
                f"Kayıp: {', '.join(list(lost)[:5])}"
            )
        
        score = min(1.0, retention_rate / self.MIN_KEYWORD_RETENTION)
        
        return (score, issues, [f"KELIME: {w}" for w in list(lost)[:5]])
    
    def _check_hallucination(
        self, original: str, enhanced: str
    ) -> Tuple[float, List[str], List[str]]:
        """Halüsinasyon tespiti — orijinalde olmayan yeni bilgi eklendi mi?"""
        warnings = []
        entities = []
        
        # Yeni sayılar
        orig_nums = set(_NUM_PATTERN.findall(original))
        enh_nums = set(_NUM_PATTERN.findall(enhanced))
        new_nums = enh_nums - orig_nums
        
        # Anlamsız yeni sayıları filtrele
        significant_new = [n for n in new_nums if len(n.strip()) > 1 and n.strip() not in ("0", "1", "2")]
        
        if orig_nums and significant_new:
            new_ratio = len(significant_new) / max(len(orig_nums), 1)
            if new_ratio > self.MAX_NEW_NUMBER_RATIO:
                warnings.append(
                    f"⚠ Halüsinasyon şüphesi: {len(significant_new)} yeni sayı eklendi "
                    f"(orijinalin %{new_ratio:.0%})"
                )
                entities.extend([f"YENİ SAYI: {n}" for n in significant_new[:3]])
        
        # Yeni özel isimler
        orig_proper = set(_PROPER_NOUN_PATTERN.findall(original))
        enh_proper = set(_PROPER_NOUN_PATTERN.findall(enhanced))
        new_proper = enh_proper - orig_proper
        
        if orig_proper and new_proper:
            new_ratio = len(new_proper) / max(len(orig_proper), 1)
            if new_ratio > self.MAX_NEW_PROPER_RATIO:
                warnings.append(
                    f"⚠ Halüsinasyon şüphesi: {len(new_proper)} yeni özel isim eklendi"
                )
                entities.extend([f"YENİ İSİM: {n}" for n in list(new_proper)[:3]])
        
        # Yeni URL'ler
        orig_urls = set(_URL_PATTERN.findall(original))
        enh_urls = set(_URL_PATTERN.findall(enhanced))
        new_urls = enh_urls - orig_urls
        if new_urls:
            warnings.append(
                f"⚠ Halüsinasyon şüphesi: {len(new_urls)} yeni URL eklendi"
            )
            entities.extend([f"YENİ URL: {u[:50]}" for u in new_urls])
        
        # Skor: uyarı sayısına göre
        if not warnings:
            return (1.0, [], [])
        elif len(warnings) == 1:
            return (0.7, warnings, entities)
        else:
            return (0.4, warnings, entities)
    
    def _check_table_integrity(
        self, original: str, enhanced: str
    ) -> Tuple[float, List[str]]:
        """Tablo bütünlüğü — satır sayısı korunuyor mu?"""
        orig_rows = _TABLE_ROW_PATTERN.findall(original)
        enh_rows = _TABLE_ROW_PATTERN.findall(enhanced)
        
        if not orig_rows:
            # Pipe separator yoksa tab/comma satırlarını say
            orig_lines = [l for l in original.split('\n') if l.strip() and '\t' in l]
            enh_lines = [l for l in enhanced.split('\n') if l.strip() and '\t' in l]
            
            if not orig_lines:
                return (1.0, [])
            
            orig_rows = orig_lines
            enh_rows = enh_lines
        
        if not orig_rows:
            return (1.0, [])
        
        # Satır sayısı farkı
        orig_count = len(orig_rows)
        enh_count = len(enh_rows)
        
        issues = []
        if enh_count < orig_count * 0.80:
            issues.append(
                f"[KRİTİK] Tablo satır kaybı: {orig_count} → {enh_count} satır "
                f"({(1 - enh_count/orig_count):.0%} kayıp)"
            )
            return (enh_count / orig_count, issues)
        
        if enh_count > orig_count * 1.50:
            issues.append(
                f"Tabloya fazla satır eklenmiş: {orig_count} → {enh_count}"
            )
            return (0.7, issues)
        
        return (1.0, [])
    
    # ─────────────────────────────────────────
    #  Yardımcı Fonksiyonlar
    # ─────────────────────────────────────────
    
    def _extract_significant_words(
        self, text: str, min_length: int = 4
    ) -> Dict[str, int]:
        """Metinden anlamlı kelimeleri çıkar (frekans sıralı)"""
        # Stop words (Türkçe)
        stop_words = {
            "ve", "veya", "ile", "bir", "bu", "şu", "için", "gibi", "ama",
            "ancak", "fakat", "daha", "çok", "her", "tüm", "olan", "olarak",
            "sonra", "önce", "kadar", "arasında", "üzerinde", "içinde",
            "tarafından", "nedeniyle", "dolayı", "yapılan", "edilir", "yapılır",
            "the", "and", "for", "with", "from", "this", "that", "are", "was",
            "were", "been", "have", "has", "had", "not", "but", "can", "will", "none"
        }
        
        # Kelimeleri çıkar
        words = re.findall(r'\b[a-zA-ZçğıöşüÇĞİÖŞÜ]{' + str(min_length) + r',}\b', text.lower())
        
        # Frekans say
        freq = {}
        for w in words:
            if w not in stop_words:
                freq[w] = freq.get(w, 0) + 1
        
        # Frekansa göre sırala
        sorted_freq = dict(sorted(freq.items(), key=lambda x: -x[1]))
        
        return sorted_freq


# ============================================
# Singleton instance
# ============================================

_validator_instance = None

def get_integrity_validator() -> ContentIntegrityValidator:
    """Singleton validator instance"""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = ContentIntegrityValidator()
    return _validator_instance
