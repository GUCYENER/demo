"""
VYRA ML Training - LearnedQAService Tests
==========================================
Intent-bazlı format talimatı, post-processing ve cevap üretim
pipeline testleri.

v2.52.0: Yeni per-question mimarisi doğrulaması.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def service():
    """LearnedQAService instance — DB bağlantısı gerekmez (sadece static metodlar test edilir)."""
    from app.services.learned_qa_service import LearnedQAService
    return LearnedQAService()


# =============================================================================
# TEST: _get_qa_format_instruction — Intent Bazlı Format
# =============================================================================

class TestGetQAFormatInstruction:
    """Her intent tipi için doğru format talimatı döndüğünü test eder."""

    def test_howto_has_steps(self, service):
        """HOW_TO intent'i adım adım format içermeli."""
        result = service._get_qa_format_instruction("HOW_TO")
        assert "ADIM ADIM" in result
        assert "1️⃣" in result
        assert "2️⃣" in result

    def test_troubleshoot_has_problem_solution(self, service):
        """TROUBLESHOOT intent'i sorun-çözüm yapısı içermeli."""
        result = service._get_qa_format_instruction("TROUBLESHOOT")
        assert "Sorun" in result
        assert "Çözüm" in result
        assert "Olası Nedenler" in result

    def test_list_request_has_numbered_items(self, service):
        """LIST_REQUEST intent'i numaralı liste formatı içermeli."""
        result = service._get_qa_format_instruction("LIST_REQUEST")
        assert "1." in result
        assert "2." in result
        assert "LİSTE" in result

    def test_single_answer_has_definition(self, service):
        """SINGLE_ANSWER intent'i tanım + kullanım formatı içermeli."""
        result = service._get_qa_format_instruction("SINGLE_ANSWER")
        assert "Tanım" in result
        assert "Kullanım" in result

    def test_general_fallback(self, service):
        """Bilinmeyen intent'te genel format döndürmeli."""
        result = service._get_qa_format_instruction("UNKNOWN_TYPE")
        assert "GENEL" in result
        assert "Özet" in result

    def test_case_sensitive(self, service):
        """Intent büyük harfle verilmeli."""
        result_upper = service._get_qa_format_instruction("HOW_TO")
        result_lower = service._get_qa_format_instruction("how_to")
        # Küçük harf eşleşmez, fallback döner
        assert "ADIM ADIM" in result_upper
        assert "GENEL" in result_lower


# =============================================================================
# TEST: _postprocess_qa_answer — Prompt Leak Temizleme
# =============================================================================

class TestPostprocessQAAnswer:
    """Post-processing fonksiyonunun prompt sızıntılarını temizlediğini test eder."""

    def test_cleans_prompt_leak(self, service):
        """Prompt sızıntısı içeren satırlar temizlenmeli."""
        answer = """1️⃣ **İlk adım:** Sisteme giriş yapın.
SADECE kaynak içerikteki bilgilere dayalı cevap verin.
2️⃣ **İkinci adım:** Menüden seçin."""
        
        result = service._postprocess_qa_answer(answer, "HOW_TO")
        assert "SADECE kaynak içerikteki" not in result
        assert "İlk adım" in result
        assert "İkinci adım" in result

    def test_cleans_format_instruction_leak(self, service):
        """FORMAT TALİMATI sızıntısı temizlenmeli."""
        answer = """📖 **VPN Bağlantısı**
FORMAT TALİMATI (TEKİL CEVAP):
VPN, sanal özel ağ anlamına gelir."""
        
        result = service._postprocess_qa_answer(answer, "SINGLE_ANSWER")
        assert "FORMAT TALİMATI" not in result
        assert "VPN" in result

    def test_cleans_excessive_newlines(self, service):
        """3+ ardışık boş satır 2'ye düşürülmeli."""
        answer = "Birinci bölüm.\n\n\n\n\nİkinci bölüm."
        result = service._postprocess_qa_answer(answer, "GENERAL")
        assert "\n\n\n" not in result
        assert "Birinci bölüm" in result
        assert "İkinci bölüm" in result

    def test_preserves_valid_content(self, service):
        """Geçerli içerik korunmalı."""
        answer = """🎯 **Amaç:** Sisteme giriş yapmak

📌 **Adımlar:**
  1️⃣ **Tarayıcıyı açın**
     ↳ Chrome veya Edge tercih edin
  2️⃣ **URL'yi girin**
     ↳ portal.example.com adresine gidin"""
        
        result = service._postprocess_qa_answer(answer, "HOW_TO")
        assert "Amaç" in result
        assert "1️⃣" in result
        assert "portal.example.com" in result


# =============================================================================
# TEST: chunk_text[:2000] — Tam Context
# =============================================================================

class TestChunkContext:
    """Chunk context'in 2000 char olarak korunduğunu doğrular."""

    def test_long_chunk_preserved(self, service):
        """2000 char'a kadar olan context korunmalı."""
        # _generate_single_answer fonksiyonu chunk_text[:2000] kullanır
        # Bu test fonksiyonun prompt'unda [:2000] kullandığını doğrular
        import inspect
        source = inspect.getsource(service._generate_single_answer)
        assert "chunk_text[:2000]" in source or "[:2000]" in source

    def test_old_600_limit_removed(self, service):
        """Eski 600 char limiti artık olmamalı."""
        import inspect
        source = inspect.getsource(service._generate_answers_batch)
        assert "[:600]" not in source


# =============================================================================
# TEST: _compute_answer_quality_score — UPSERT Kalite Skoru
# =============================================================================

class TestComputeAnswerQualityScore:
    """Kalite skoru fonksiyonunun doğru çalıştığını test eder."""

    def test_empty_answer_zero(self, service):
        """Boş veya çok kısa cevap 0 döndürmeli."""
        assert service._compute_answer_quality_score("") == 0.0
        assert service._compute_answer_quality_score("kısa") == 0.0

    def test_plain_text_low_score(self, service):
        """Düz metin düşük skor almalı (format yok, adım yok)."""
        answer = "VPN bağlantısı kurmak için sisteme giriş yapmanız gerekir."
        score = service._compute_answer_quality_score(answer)
        assert 0 < score < 40, f"Düz metin skoru çok yüksek: {score}"

    def test_formatted_answer_high_score(self, service):
        """Formatlı, adım adım cevap yüksek skor almalı."""
        answer = """🎯 **Amaç:** VPN bağlantısı kurmak

📌 **Adımlar:**

1️⃣ **Tarayıcıyı açın**
   ↳ Chrome veya Edge tercih edin

2️⃣ **Portal adresini girin**
   ↳ vpn.example.com adresine gidin

3️⃣ **Kimlik bilgilerinizi girin**
   ↳ Kurumsal e-posta ve şifreniz ile giriş yapın

💡 **İpucu:** Bağlantı kopması durumunda tekrar deneyin.
⚠️ **Dikkat:** VPN sadece şirket ağında çalışır."""
        score = service._compute_answer_quality_score(answer)
        assert score > 60, f"Formatlı cevap skoru çok düşük: {score}"

    def test_quality_comparison_new_better(self, service):
        """Yeni kaliteli cevap > eski basit cevap."""
        old = "VPN bağlantısı yapın."
        new = """🎯 **Amaç:** VPN bağlantısı

1️⃣ **Tarayıcıyı açın**
   ↳ Chrome kullanın

2️⃣ **Giriş yapın**
   ↳ portal.example.com

💡 **İpucu:** Sorun olursa IT'ye başvurun."""

        old_score = service._compute_answer_quality_score(old)
        new_score = service._compute_answer_quality_score(new)
        assert new_score > old_score, f"Yeni ({new_score}) > Eski ({old_score}) olmalı"

    def test_quality_comparison_old_better(self, service):
        """Eski detaylı cevap > yeni kısa cevap."""
        old = """🎯 **Amaç:** Parça kodu değiştirme

📌 **Adımlar:**

1️⃣ **SAP'ye girin**
   ↳ Transaction MM02 kullanın

2️⃣ **Parça numarasını girin**

3️⃣ **Kaydet butonuna basın**

⚠️ **Dikkat:** Onay gerektirir."""
        new = "Parça kodunu SAP'den değiştirin."

        old_score = service._compute_answer_quality_score(old)
        new_score = service._compute_answer_quality_score(new)
        assert old_score > new_score, f"Eski ({old_score}) > Yeni ({new_score}) olmalı"
