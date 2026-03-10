"""
VYRA ML Training - SyntheticDataGenerator Grounding Tests
=========================================================
_stem_match, _estimate_grounding ve _validate_question_relevance
fonksiyonlarının Türkçe çekim eki toleransı testleri.

v2.52.0: Kök eşleştirme (stem matching) düzeltmesi doğrulaması.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def generator():
    """SyntheticDataGenerator instance — DB bağlantısı gerekmez."""
    from app.services.ml_training.synthetic_data import SyntheticDataGenerator
    return SyntheticDataGenerator(max_chunks=10, use_llm=False)


# =============================================================================
# TEST: _stem_match — Türkçe Çekim Eki Toleransı
# =============================================================================

class TestStemMatch:
    """Kök eşleştirme fonksiyonunun Türkçe ek toleransını test eder."""

    def test_exact_match(self, generator):
        """Tam kelime eşleşmesi True döndürmeli."""
        assert generator._stem_match("sorgulama", "sorgulama ekranı açılır") is True

    def test_stem_match_suffix_tolerance(self, generator):
        """'sipariş' kelimesi 'siparişi' içeren metinde eşleşmeli."""
        assert generator._stem_match("sipariş", "bu siparişi kontrol edin") is True

    def test_stem_match_verb_conjugation(self, generator):
        """'sorgulama' kelimesi 'sorgula' içeren metinde eşleşmeli."""
        assert generator._stem_match("sorgulama", "sistemi sorgula butonuna tıklayın") is True

    def test_stem_match_numara_suffix(self, generator):
        """'numarası' kelimesi 'numarayı' içeren metinde eşleşmeli (kök: numer → numar)."""
        assert generator._stem_match("numarası", "numarayı girin") is True

    def test_stem_match_short_word_exact(self, generator):
        """3 karakterlik kelime sadece tam eşleşme olmalı."""
        assert generator._stem_match("vpn", "vpn bağlantısı kurun") is True

    def test_stem_match_no_match(self, generator):
        """İlişkisiz kelime eşleşmemeli."""
        assert generator._stem_match("yazıcı", "vpn bağlantısı kurun") is False

    def test_stem_match_long_word_5char_stem(self, generator):
        """7+ karakterlik kelimede 5 char kök kullanılmalı."""
        # 'değiştirilir' (12 char) → kök 'değiş' (5 char) → 'değişiklik' de eşleşir
        assert generator._stem_match("değiştirilir", "değişiklik yapıldı") is True


# =============================================================================
# TEST: _estimate_grounding — Grounding Skoru
# =============================================================================

class TestEstimateGrounding:
    """Grounding skoru hesaplamasının Türkçe çekim ekleriyle çalışmasını test eder."""

    def test_high_grounding_turkish(self, generator):
        """Türkçe çekim ekleriyle yüksek grounding (kök eşleştirme)."""
        query = "Satın alma sipariş numarası nasıl girilir?"
        chunk = "Satın alma modülünde siparişi oluşturun. Numara alanına değer girin."
        score = generator._estimate_grounding(query, chunk)
        # 'satın', 'alma', 'sipariş' → 'siparişi', 'numarası' → 'numara', 'girilir' → 'girin'
        assert score >= 0.15, f"Grounding skoru çok düşük: {score}"

    def test_low_grounding_unrelated(self, generator):
        """İlişkisiz soru-chunk çiftinde düşük grounding."""
        query = "VPN nasıl bağlanılır?"
        chunk = "Excel formatında rapor oluşturmak için menüden dışa aktar seçeneğini kullanın."
        score = generator._estimate_grounding(query, chunk)
        assert score < 0.15, f"Grounding skoru çok yüksek: {score}"

    def test_grounding_empty_inputs(self, generator):
        """Boş girişlerde 0.0 döndürmeli."""
        assert generator._estimate_grounding("", "metin") == 0.0
        assert generator._estimate_grounding("soru", "") == 0.0

    def test_grounding_stopwords_only(self, generator):
        """Sadece stop words varsa 1.0 döndürmeli."""
        assert generator._estimate_grounding("bu ne", "herhangi bir metin") == 1.0


# =============================================================================
# TEST: _validate_question_relevance — Eşik ve Kök Eşleştirme
# =============================================================================

class TestValidateQuestionRelevance:
    """Validasyon eşiğinin %25 ile düzgün çalıştığını test eder."""

    def test_relevant_turkish_question(self, generator):
        """Türkçe çekim ekli geçerli soru True döndürmeli."""
        query = "Parça kodu nasıl değiştirilir?"
        chunk_lower = "parça kodu ekranından kodun değiştirilmesi işlemi yapılır"
        assert generator._validate_question_relevance(query, chunk_lower) is True

    def test_irrelevant_question(self, generator):
        """İlgisiz soru False döndürmeli."""
        query = "Yazıcı kurulumu nasıl yapılır?"
        chunk_lower = "vpn bağlantısı için aşağıdaki adımları izleyin server adresi girin"
        assert generator._validate_question_relevance(query, chunk_lower) is False

    def test_short_question_rejected(self, generator):
        """5 karakterden kısa soru False döndürmeli."""
        assert generator._validate_question_relevance("abc", "metin") is False

    def test_empty_inputs(self, generator):
        """Boş girişlerde False döndürmeli."""
        assert generator._validate_question_relevance("", "metin") is False
        assert generator._validate_question_relevance("soru", "") is False
