"""
Test: _insert_images_by_heading ve _calculate_quality_score
===========================================================
Yeni eklenen fonksiyonların edge case'leri dahil doğrulaması.
"""


# ─── _insert_images_by_heading Tests ────────────────────────────


class TestInsertImagesByHeading:
    """_insert_images_by_heading fonksiyonu testleri"""
    
    def _get_fn(self):
        from app.services.dialog.processor import _insert_images_by_heading
        return _insert_images_by_heading
    
    def test_empty_heading_images(self):
        """heading_images boş → içerik değişmez"""
        fn = self._get_fn()
        content = "Merhaba dünya"
        result = fn(content, {})
        assert result == content
    
    def test_no_heading_only(self):
        """Sadece __no_heading__ görseller → sona eklenir"""
        fn = self._get_fn()
        content = "Test içerik"
        result = fn(content, {"__no_heading__": [1, 2]})
        assert "İlgili Görseller" in result
        assert 'data-image-id="1"' in result
        assert 'data-image-id="2"' in result
    
    def test_heading_match(self):
        """Başlık eşleşmesi — görseller ilgili başlık altına yerleştirilir"""
        fn = self._get_fn()
        content = (
            "## Giriş\n\n"
            "Açıklama metni.\n\n"
            "**Depo Sayım İşlemleri**\n\n"
            "Sayım detayları burada.\n\n"
            "**Diğer Bölüm**\n\n"
            "Son paragraf."
        )
        heading_images = {
            "DEPO SAYIM İŞLEMLERİ": [10, 11],
            "Diğer Bölüm": [20],
        }
        result = fn(content, heading_images)
        
        # Her iki başlık için görseller olmalı
        assert 'data-image-id="10"' in result
        assert 'data-image-id="20"' in result
        # "Depo Sayım" görseli "Diğer Bölüm" başlığından ÖNCE olmalı
        img10_pos = result.find('data-image-id="10"')
        diger_pos = result.find("Diğer Bölüm")
        assert img10_pos < diger_pos, "Depo Sayım görseli, Diğer Bölüm başlığından önce olmalı"
    
    def test_unmatched_headings_appended(self):
        """Eşleşmeyen heading görselleri sona eklenir"""
        fn = self._get_fn()
        content = "**Giriş**\n\nMeseleler"
        heading_images = {
            "BU_BASLIK_YOK_ICERIKTE": [99],
        }
        result = fn(content, heading_images)
        assert 'data-image-id="99"' in result
    
    def test_max_4_images_per_heading(self):
        """Her başlık altında max 4 görsel"""
        fn = self._get_fn()
        content = "**Test Başlık**\n\nİçerik"
        heading_images = {
            "Test Başlık": [1, 2, 3, 4, 5, 6],
        }
        result = fn(content, heading_images)
        assert 'data-image-id="4"' in result
        assert 'data-image-id="5"' not in result
    
    def test_false_positive_prevention(self):
        """Kısa satırlar heading olarak eşleşmemeli"""
        fn = self._get_fn()
        content = "Bu uzun bir paragraf cümlesi.\n---\nDevam eden metin."
        heading_images = {
            "Bu uzun bir paragraf cümlesi": [50],
        }
        result = fn(content, heading_images)
        # Paragraf satırı ** veya # ile başlamıyor → heading olarak eşleşmemeli
        # Görseller unmatched olarak sona eklenecek
        assert 'data-image-id="50"' in result
    
    def test_turkish_normalization(self):
        """Türkçe karakter normalizasyonu"""
        fn = self._get_fn()
        content = "**DEPO SAYIM İŞLEMLERİ**\n\nSayım detayları."
        heading_images = {
            "Depo Sayım İşlemleri": [20],
        }
        result = fn(content, heading_images)
        assert 'data-image-id="20"' in result


# ─── _calculate_quality_score Tests ─────────────────────────────


class TestCalculateQualityScore:
    """Quality score hesaplama doğrulaması"""
    
    def _get_service(self):
        from app.services.rag.service import RAGService
        svc = RAGService.__new__(RAGService)
        return svc
    
    def test_short_text_low_score(self):
        """Çok kısa metin → düşük skor"""
        svc = self._get_service()
        score = svc._calculate_quality_score("abc", {})
        assert score < 0.3
    
    def test_ideal_length_high_score(self):
        """İdeal uzunluk (500 karakter) → yüksek skor"""
        svc = self._get_service()
        text = "A" * 500 + "."  # 500 char + nokta (cümle bütünlüğü)
        score = svc._calculate_quality_score(text, {"heading": "Test", "type": "paragraph"})
        assert score >= 0.6
    
    def test_heading_boost(self):
        """Heading varsa skor artmalı"""
        svc = self._get_service()
        text = "X" * 300
        score_no_heading = svc._calculate_quality_score(text, {})
        score_with_heading = svc._calculate_quality_score(text, {"heading": "Başlık"})
        assert score_with_heading > score_no_heading
    
    def test_sentence_completeness_boost(self):
        """Nokta ile biten metin → skor artmalı"""
        svc = self._get_service()
        text_no_dot = "X" * 300
        text_dot = "X" * 299 + "."
        s1 = svc._calculate_quality_score(text_no_dot, {})
        s2 = svc._calculate_quality_score(text_dot, {})
        assert s2 > s1
    
    def test_table_bonus(self):
        """Tablo satırı → bonus"""
        svc = self._get_service()
        text = "X" * 300
        s1 = svc._calculate_quality_score(text, {"type": "paragraph"})
        s2 = svc._calculate_quality_score(text, {"type": "table_row"})
        assert s2 > s1
    
    def test_score_range(self):
        """Skor her zaman 0.1-1.0 arasında"""
        svc = self._get_service()
        # Minimum
        score_min = svc._calculate_quality_score("", {})
        assert 0.1 <= score_min <= 1.0
        
        # Maximum
        text = "A" * 1500 + "."
        score_max = svc._calculate_quality_score(
            text, {"heading": "H", "type": "table_row"}
        )
        assert 0.1 <= score_max <= 1.0
    
    def test_metadata_none_handling(self):
        """metadata None/string olabilir → hata vermemeli"""
        svc = self._get_service()
        score = svc._calculate_quality_score("Test metin.", None)
        assert isinstance(score, float)
        score2 = svc._calculate_quality_score("Test metin.", "invalid")
        assert isinstance(score2, float)
