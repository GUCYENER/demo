"""
VYRA L1 Support API - CatBoost Prioritizer
=============================================
CatBoost ile chunk kalite tahmini + heuristic priority + zayıflık tespiti.

Author: VYRA AI Team
Version: 1.0.0 (v3.3.3)
"""

from typing import Dict, Any, List

from app.services.logging_service import log_system_event, log_warning


class CatBoostPrioritizer:
    """
    CatBoost ML modeli ile bölüm kalitesini tahmin eder.
    Model yoksa heuristic (kural tabanlı) fallback kullanılır.

    Kullanım:
        prioritizer = CatBoostPrioritizer()
        result = prioritizer.catboost_prioritize(sections, file_type, violations)
    """

    def __init__(self):
        self._catboost_service = None
        self._feature_extractor = None

    def _get_catboost(self):
        """CatBoost servisini lazy load et"""
        if self._catboost_service is None:
            try:
                from app.services.catboost_service import get_catboost_service
                self._catboost_service = get_catboost_service()
            except Exception as e:
                log_warning(f"CatBoost yüklenemedi: {e}", "enhancer")
        return self._catboost_service

    def _get_feature_extractor(self):
        """Feature extractor'ı lazy load et"""
        if self._feature_extractor is None:
            try:
                from app.services.feature_extractor import get_feature_extractor
                self._feature_extractor = get_feature_extractor()
            except Exception as e:
                log_warning(f"FeatureExtractor yüklenemedi: {e}", "enhancer")
        return self._feature_extractor

    def catboost_prioritize(
        self,
        sections: List[Dict[str, Any]],
        file_type: str,
        violations: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        CatBoost ile her bölümün RAG kalitesini tahmin et.
        Model yoksa maturity violation'lara göre basit scoring.
        """

        catboost = self._get_catboost()
        fe = self._get_feature_extractor()

        section_priorities = []
        has_catboost = catboost is not None and catboost.is_ready() and fe is not None

        # Violation → section eşleştirme
        violation_names = [v.get("name", "") for v in violations]

        # v3.2.1: Debug — hangi violation'lar tespit edildi
        log_system_event("DEBUG",
            f"CatBoost prioritize: {len(sections)} section, "
            f"violations={violation_names}, catboost={has_catboost}",
            "enhancer")

        for section in sections:
            content = section.get("content", "")
            heading = section.get("heading", "")
            word_count = len(content.split())

            if has_catboost:
                # CatBoost ile kalite tahmini
                try:
                    # Fake RAG result oluştur (feature extractor'ın beklediği format)
                    fake_result = {
                        "chunk_id": 0,
                        "content": content,
                        "chunk_text": content,
                        "score": 0.5,
                        "quality_score": 0.5,
                        "metadata": {
                            "heading": heading,
                            "file_type": f".{file_type.lower()}"
                        },
                        "file_type": f".{file_type.lower()}"
                    }

                    feature_matrix, _ = fe.build_feature_matrix(
                        results=[fake_result],
                        user_id=None,
                        query=heading or "doküman kalite analizi"
                    )

                    if feature_matrix is not None and len(feature_matrix) > 0:
                        scores = catboost.predict(feature_matrix)
                        priority = 1.0 - float(scores[0])  # Düşük skor = yüksek iyileştirme önceliği
                    else:
                        priority = self._heuristic_priority(content, heading, violation_names)
                except Exception as e:
                    log_warning(f"CatBoost prediction hatası: {e}", "enhancer")
                    priority = self._heuristic_priority(content, heading, violation_names)
            else:
                # CatBoost yoksa heuristic
                priority = self._heuristic_priority(content, heading, violation_names)

            weakness_types = self.detect_weaknesses(content, heading, violation_names)

            section_priorities.append({
                "index": section["index"],
                "heading": heading,
                "priority": round(priority, 3),
                "weakness_types": weakness_types,
                "word_count": word_count,
                "catboost_used": has_catboost
            })

        # Özet
        avg_priority = sum(s["priority"] for s in section_priorities) / max(len(section_priorities), 1)
        high_priority_count = sum(1 for s in section_priorities if s["priority"] > 0.5)

        return {
            "sections": section_priorities,
            "summary": {
                "total_sections": len(section_priorities),
                "high_priority_count": high_priority_count,
                "average_priority": round(avg_priority, 3),
                "catboost_available": has_catboost,
                "violation_count": len(violations)
            }
        }

    def _heuristic_priority(
        self,
        content: str,
        heading: str,
        violation_names: List[str]
    ) -> float:
        """
        CatBoost yoksa heuristic ile priority hesapla — tüm dosya türleri.
        v3.3.0 [C3]: Min-max normalizasyon — CatBoost ile tutarlı 0-1 dağılım.
        """
        raw_score = 0.0  # Ham skor (normalize edilecek)

        word_count = len(content.split())

        # Çok kısa içerik → yüksek priority
        if word_count < 20:
            raw_score += 3.0
        elif word_count < 50:
            raw_score += 1.5

        # Heading yoksa veya Generic ise
        if not heading or heading in ("Genel", "Giriş"):
            raw_score += 2.0

        # Violation eşleştirme — PDF/DOCX/TXT
        if "Başlık Hiyerarşisi" in violation_names or "Word Stilleri" in violation_names:
            raw_score += 1.5
        if "Metin Yoğunluğu" in violation_names or "Metin İçeriği" in violation_names:
            raw_score += 1.0
        if "Tablo Formatı" in violation_names:
            raw_score += 1.0
        if "Türkçe Karakter" in violation_names:
            raw_score += 1.0
        if "Gereksiz İçerik" in violation_names or "Gereksiz Boşluklar" in violation_names:
            raw_score += 1.0

        # v3.2.1: Excel'e özel ihlal boost
        if "İlk Satır Başlık" in violation_names:
            raw_score += 1.5
        if "Merge Hücreler" in violation_names:
            raw_score += 1.0
        if "Açıklama Satırları" in violation_names:
            raw_score += 1.0
        if "Boş Satır/Sütun" in violation_names:
            raw_score += 1.0
        if "Formül vs Değer" in violation_names:
            raw_score += 1.0
        if "Tutarlı Veri Tipi" in violation_names:
            raw_score += 0.5
        if "Gizli Sheet" in violation_names:
            raw_score += 0.5

        # DOCX özel
        if "Metin Kutusu" in violation_names:
            raw_score += 1.5
        if "Liste Formatı" in violation_names:
            raw_score += 0.5

        # PPTX özel (v3.3.0: yeni kurallar)
        if "Slayt Başlıkları" in violation_names:
            raw_score += 1.0
        if "Speaker Notes" in violation_names:
            raw_score += 0.8
        if "Görsel/Metin Oranı" in violation_names:
            raw_score += 0.8
        if "Slayt Sayısı" in violation_names:
            raw_score += 0.5

        # v3.3.0 [C3]: Min-max normalizasyon
        # Olası max ham skor ≈ 15 (tüm violation'lar + kısa metin + heading yok)
        MAX_RAW_SCORE = 15.0
        normalized = min(raw_score / MAX_RAW_SCORE, 1.0)

        # Minimum 0.1 floor (tamamen sorunsuz bile olsa bir baseline sağlar)
        return max(round(normalized, 3), 0.1)

    def detect_weaknesses(
        self,
        content: str,
        heading: str,
        violation_names: List[str]
    ) -> List[str]:
        """Bölüm bazında zayıflıkları tespit et — tüm dosya türleri desteklenir."""
        weaknesses = []

        word_count = len(content.split())

        if not heading or heading in ("Genel", "Giriş"):
            weaknesses.append("heading_missing")

        if word_count < 20:
            weaknesses.append("content_too_short")

        # Tablo kontrol
        if "|" in content and content.count("|") > 5:
            if "Tablo Formatı" in violation_names:
                weaknesses.append("table_format_issue")

        # Türkçe karakter
        if "Türkçe Karakter" in violation_names:
            bad_chars = ['Ã¼', 'Ã§', 'Ã¶', 'Ä±', 'ÅŸ']
            if any(bc in content for bc in bad_chars):
                weaknesses.append("encoding_issue")

        # PDF / DOCX / TXT yapısal sorunlar
        if "Başlık Hiyerarşisi" in violation_names:
            weaknesses.append("structure_weak")
        if "Metin Yoğunluğu" in violation_names:
            weaknesses.append("low_density")
        if "Gereksiz İçerik" in violation_names:
            weaknesses.append("redundant_content")
        if "Gereksiz Boşluklar" in violation_names:
            weaknesses.append("excess_whitespace")

        # DOCX özel
        if "Word Stilleri" in violation_names:
            weaknesses.append("structure_weak")
        if "Metin Kutusu" in violation_names:
            weaknesses.append("textbox_issue")
        if "Liste Formatı" in violation_names:
            weaknesses.append("list_format_issue")

        # v3.2.1: Excel'e özel ihlal eşleştirmesi
        if "İlk Satır Başlık" in violation_names:
            weaknesses.append("header_row_missing")
        if "Merge Hücreler" in violation_names:
            weaknesses.append("merged_cells")
        if "Açıklama Satırları" in violation_names:
            weaknesses.append("description_rows")
        if "Boş Satır/Sütun" in violation_names:
            weaknesses.append("empty_gaps")
        if "Tutarlı Veri Tipi" in violation_names:
            weaknesses.append("inconsistent_types")
        if "Formül vs Değer" in violation_names:
            weaknesses.append("formula_issue")
        if "Gizli Sheet" in violation_names:
            weaknesses.append("hidden_sheets")

        # PPTX özel
        if "Metin İçeriği" in violation_names:
            weaknesses.append("low_density")
        if "Slayt Başlıkları" in violation_names:
            weaknesses.append("heading_missing")

        return weaknesses
