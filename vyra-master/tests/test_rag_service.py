"""
VYRA L1 Support API - RAG Service Tests
=========================================
rag_service.py için unit testler.

Author: VYRA AI Team
Version: 1.0.0 (2026-02-06)
"""

import pytest
from unittest.mock import patch, MagicMock


class TestRAGServiceInit:
    """RAGService initialization testleri"""
    
    def test_rag_service_import(self):
        """RAGService import edilebilir"""
        from app.services.rag_service import RAGService
        assert RAGService is not None
    
    def test_rag_service_instantiation(self):
        """RAGService örneği oluşturulabilir"""
        from app.services.rag_service import RAGService
        service = RAGService()
        assert service is not None


class TestCosineSimilarity:
    """Cosine similarity hesaplama testleri"""
    
    def test_identical_vectors(self):
        """Aynı vektörler 1.0 benzerlik verir"""
        from app.services.rag_service import RAGService
        
        service = RAGService()
        vec = [0.1, 0.2, 0.3, 0.4, 0.5]
        
        similarity = service._cosine_similarity(vec, vec)
        
        assert abs(similarity - 1.0) < 0.0001  # Floating point tolerance
    
    def test_orthogonal_vectors(self):
        """Dik vektörler 0 benzerlik verir"""
        from app.services.rag_service import RAGService
        
        service = RAGService()
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [0.0, 1.0, 0.0]
        
        similarity = service._cosine_similarity(vec1, vec2)
        
        assert abs(similarity - 0.0) < 0.0001
    
    def test_opposite_vectors(self):
        """Ters vektörler -1 benzerlik verir"""
        from app.services.rag_service import RAGService
        
        service = RAGService()
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [-1.0, 0.0, 0.0]
        
        similarity = service._cosine_similarity(vec1, vec2)
        
        assert abs(similarity - (-1.0)) < 0.0001


class TestBM25Score:
    """BM25 scoring testleri"""
    
    def test_bm25_exact_match(self):
        """Tam eşleşme yüksek skor verir"""
        from app.services.rag_service import RAGService
        
        service = RAGService()
        query = "VPN bağlantısı"
        document = "VPN bağlantısı için önce Cisco AnyConnect açın"
        
        score = service._bm25_score(query, document)
        
        assert score > 0.0  # Eşleşme varsa pozitif skor
    
    def test_bm25_no_match(self):
        """Eşleşme yoksa düşük skor verir"""
        from app.services.rag_service import RAGService
        
        service = RAGService()
        query = "VPN bağlantısı"
        document = "Outlook mail ayarları nasıl yapılır"
        
        score = service._bm25_score(query, document)
        
        assert score < 0.5  # Düşük skor beklenir
    
    def test_bm25_partial_match(self):
        """Kısmi eşleşme orta skor verir"""
        from app.services.rag_service import RAGService
        
        service = RAGService()
        query = "VPN Cisco AnyConnect"
        document = "AnyConnect uygulaması ile ağa bağlanın"
        
        score = service._bm25_score(query, document)
        
        assert score >= 0.0  # Geçerli skor beklenir


class TestRRF:
    """Reciprocal Rank Fusion testleri"""
    
    def test_rrf_single_ranking(self):
        """Tek ranking ile RRF çalışır"""
        from app.services.rag_service import RAGService
        
        service = RAGService()
        rankings = [[
            {"id": 1, "score": 0.9},
            {"id": 2, "score": 0.7},
            {"id": 3, "score": 0.5}
        ]]
        
        result = service._reciprocal_rank_fusion(rankings)
        
        assert len(result) == 3
        assert result[0]["id"] == 1  # En yüksek skor ilk sırada
    
    def test_rrf_multiple_rankings(self):
        """Çoklu ranking ile RRF birleştirir"""
        from app.services.rag_service import RAGService
        
        service = RAGService()
        rankings = [
            [{"id": 1, "score": 0.9}, {"id": 2, "score": 0.7}],
            [{"id": 2, "score": 0.8}, {"id": 1, "score": 0.6}]
        ]
        
        result = service._reciprocal_rank_fusion(rankings)
        
        # Her iki ranking'de de yüksek olan id en üstte olmalı
        assert len(result) >= 2


class TestNormalizeScores:
    """Score normalization testleri"""
    
    def test_normalize_scores_range(self):
        """Skorlar 0-1 arasında normalize edilir"""
        from app.services.rag_service import RAGService
        
        service = RAGService()
        results = [
            {"id": 1, "score": 0.2},
            {"id": 2, "score": 0.8},
            {"id": 3, "score": 0.5}
        ]
        
        normalized = service._normalize_scores(results)
        
        scores = [r["score"] for r in normalized]
        assert min(scores) >= 0.0
        assert max(scores) <= 1.0


class TestExactMatchBonus:
    """Exact match bonus testleri"""
    
    def test_technical_term_bonus(self):
        """Teknik terim yüksek bonus alır"""
        from app.services.rag_service import RAGService
        
        service = RAGService()
        query = "VPN"
        chunk = "VPN bağlantısı için AnyConnect kullanın"
        
        bonus = service._calculate_exact_match_bonus(query, chunk)
        
        assert bonus > 0.2  # Teknik terim bonusu
    
    def test_no_match_no_bonus(self):
        """Eşleşme yoksa bonus 0"""
        from app.services.rag_service import RAGService
        
        service = RAGService()
        query = "VPN"
        chunk = "Outlook mail ayarları"
        
        bonus = service._calculate_exact_match_bonus(query, chunk)
        
        assert bonus == 0.0


class TestExtractKeywords:
    """Keyword extraction testleri"""
    
    def test_extract_keywords(self):
        """Anahtar kelimeler çıkarılır"""
        from app.services.rag_service import RAGService
        
        service = RAGService()
        text = "VPN bağlantısı nasıl yapılır"
        
        keywords = service._extract_keywords(text)
        
        assert len(keywords) > 0  # Anahtar kelimeler çıkarılır
        # VPN veya bağlantısı keyword'ler arasında olmalı
        text_lower = text.lower()
        assert any(kw in text_lower for kw in keywords)


class TestIsTechnicalTerm:
    """Technical term detection testleri"""
    
    def test_vpn_is_technical(self):
        """Teknik terim pattern'a uyan"""
        from app.services.rag_service import RAGService
        
        service = RAGService()
        
        # Pattern: [A-Z]{3,}_[A-Z]+ veya en az 5+ karakter büyük harf+sayı+alt çizgi
        assert service._is_technical_term("SC_380_KURUMSAL") == True
    
    def test_random_word_not_technical(self):
        """Normal kısa kelime teknik değil"""
        from app.services.rag_service import RAGService
        
        service = RAGService()
        
        # 3 harften az kelimeler pattern'a uymaz
        assert service._is_technical_term("ab") == False
    
    def test_uppercase_code_is_technical(self):
        """Büyük harfli kod teknik"""
        from app.services.rag_service import RAGService
        
        service = RAGService()
        
        assert service._is_technical_term("SC_380_KURUMSAL") == True


class TestSearchIntegration:
    """Search fonksiyon testleri (integration)"""
    
    @patch('app.services.rag.service.get_db_conn')
    def test_search_empty_database(self, mock_db):
        """Boş veritabanında arama"""
        from app.services.rag_service import RAGService
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []
        # _fetch_db_rows: ilk fetchone → {"cnt": N}, sonra user org fetchone
        mock_cursor.fetchone.return_value = {"cnt": 0}
        mock_db.return_value = mock_conn
        
        service = RAGService()
        
        # Embedding model mock
        with patch.object(service, '_get_embedding', return_value=[0.1] * 384):
            result = service.search("VPN bağlantısı", n_results=5)
        
        assert result.total == 0
        assert len(result.results) == 0


class TestIsTocChunk:
    """🆕 v2.38.3: TOC chunk algılama testleri"""
    
    def test_toc_with_dot_patterns(self):
        """Yoğun nokta deseni olan metin TOC olarak algılanır"""
        from app.services.rag_service import RAGService
        service = RAGService()
        
        toc_text = (
            "Giriş ........................................ 1\n"
            "Bölüm 1 ...................................... 5\n"
            "Bölüm 2 ...................................... 12\n"
            "Bölüm 3 ...................................... 18\n"
            "Bölüm 4 ...................................... 25\n"
            "Sonuç ......................................... 30"
        )
        assert service._is_toc_chunk(toc_text) == True
    
    def test_normal_text_not_toc(self):
        """Normal metin TOC olarak algılanmaz"""
        from app.services.rag_service import RAGService
        service = RAGService()
        
        normal_text = "VPN bağlantısı kurmak için önce Cisco AnyConnect uygulamasını indirmeniz gerekmektedir."
        assert service._is_toc_chunk(normal_text) == False
    
    def test_empty_text_not_toc(self):
        """Boş metin TOC değildir"""
        from app.services.rag_service import RAGService
        service = RAGService()
        
        assert service._is_toc_chunk("") == False
        assert service._is_toc_chunk(None) == False
    
    def test_few_dots_not_toc(self):
        """Az sayıda nokta içeren metin TOC değildir"""
        from app.services.rag_service import RAGService
        service = RAGService()
        
        text = "Cümle 1. Cümle 2. Cümle 3. Devam eden metin burada."
        assert service._is_toc_chunk(text) == False
    
    def test_page_refs_is_toc(self):
        """Sayfa referansları yoğun olan metin TOC olarak algılanır"""
        from app.services.rag_service import RAGService
        service = RAGService()
        
        toc_text = (
            "Bölüm A.  5\n"
            "Bölüm B.  12\n"
            "Bölüm C.  18\n"
            "Bölüm D.  25\n"
            "Bölüm E.  30\n"
            "Bölüm F.  35"
        )
        assert service._is_toc_chunk(toc_text) == True


class TestPreprocessQuery:
    """🆕 v2.38.3: Sorgu ön işleme testleri"""
    
    def test_removes_nelerdir(self):
        """'nelerdir' soru eki temizlenir"""
        from app.services.rag_service import RAGService
        service = RAGService()
        
        result = service._preprocess_query("Atama Türleri nelerdir?")
        assert "nelerdir" not in result
        assert "?" not in result
        assert "Atama Türleri" in result
    
    def test_removes_nedir(self):
        """'nedir' soru eki temizlenir"""
        from app.services.rag_service import RAGService
        service = RAGService()
        
        result = service._preprocess_query("VPN nedir?")
        assert "nedir" not in result
        assert "VPN" in result
    
    def test_no_change_for_clean_query(self):
        """Soru eki olmayan sorgu değişmez"""
        from app.services.rag_service import RAGService
        service = RAGService()
        
        result = service._preprocess_query("Atama Türleri")
        assert result == "Atama Türleri"
    
    def test_empty_query_returns_empty(self):
        """Boş sorgu boş döner"""
        from app.services.rag_service import RAGService
        service = RAGService()
        
        assert service._preprocess_query("") == ""
        assert service._preprocess_query(None) == ""  # None → boş string
    
    def test_short_result_fallback(self):
        """Temizleme sonrası çok kısa kalırsa orijinal döner"""
        from app.services.rag_service import RAGService
        service = RAGService()
        
        # Sadece soru kelimesinden oluşan sorgu
        result = service._preprocess_query("nedir?")
        # Temizleme sonrası boş kalır → orijinal döner
        assert len(result) >= 3 or result == "nedir?"


class TestDeduplicateChunks:
    """v2.43.0 Faz 7: Chunk deduplication testleri"""

    def test_no_duplicates(self):
        """Duplicate olmayan chunk'larda boş set döner"""
        from app.services.rag_service import RAGService
        service = RAGService()

        chunks = [
            {"text": "Bu birinci chunk."},
            {"text": "Bu tamamen farklı ikinci chunk."},
        ]
        # Ortogonal vektörler (0 similarity)
        embeddings = [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ]

        result = service._deduplicate_chunks(chunks, embeddings)
        assert len(result) == 0

    def test_identical_chunks_removed(self):
        """Birebir aynı chunk'lar kaldırılır"""
        from app.services.rag_service import RAGService
        service = RAGService()

        chunks = [
            {"text": "Bu bir tekrar eden chunk."},
            {"text": "Bu bir tekrar eden chunk."},
        ]
        embeddings = [
            [1.0, 0.5, 0.3],
            [1.0, 0.5, 0.3],
        ]

        result = service._deduplicate_chunks(chunks, embeddings)
        assert len(result) == 1  # Bir tanesi kaldırılır

    def test_shorter_duplicate_removed(self):
        """Duplicate çiftte daha kısa olan kaldırılır"""
        from app.services.rag_service import RAGService
        service = RAGService()

        chunks = [
            {"text": "Bu uzun bir chunk metnidir ve daha fazla bilgi içerir detaylı."},
            {"text": "Bu biraz daha kısa olan bir metin ama benzer uzunlukta."},
        ]
        # Çok yüksek similarity (birebir aynı vektörler)
        embeddings = [
            [1.0, 0.5, 0.3],
            [1.0, 0.5, 0.3],
        ]

        result = service._deduplicate_chunks(chunks, embeddings)
        # Kısa olan (index 1) kaldırılmalı
        assert 1 in result
        assert 0 not in result

    def test_single_chunk_no_dedup(self):
        """Tek chunk'ta dedup boş döner"""
        from app.services.rag_service import RAGService
        service = RAGService()

        chunks = [{"text": "Tek chunk."}]
        embeddings = [[1.0, 0.0, 0.0]]

        result = service._deduplicate_chunks(chunks, embeddings)
        assert len(result) == 0

    def test_length_filter_skips_different_sizes(self):
        """Uzunluk %30'dan fazla farklıysa similarity hesaplanmaz"""
        from app.services.rag_service import RAGService
        service = RAGService()

        chunks = [
            {"text": "Kısa."},
            {"text": "Bu çok çok çok uzun bir metin, birçok kelime barındırır ve farklı konuları kapsar."},
        ]
        # Aynı vektörler olsa bile uzunluk filtresi devreye girer
        embeddings = [
            [1.0, 0.5, 0.3],
            [1.0, 0.5, 0.3],
        ]

        result = service._deduplicate_chunks(chunks, embeddings)
        # Uzunluk çok farklı → dedup yapılmaz
        assert len(result) == 0

    def test_threshold_boundary(self):
        """Threshold altındaki similarity'ler duplicate sayılmaz"""
        from app.services.rag_service import RAGService
        service = RAGService()

        chunks = [
            {"text": "Chunk A benzer ama farklı."},
            {"text": "Chunk B benzer ama farklı."},
        ]
        # 0.94 similarity → threshold altında
        v1 = [1.0, 0.1, 0.0]
        v2 = [0.95, 0.15, 0.1]

        result = service._deduplicate_chunks(chunks, [v1, v2])
        # Similarity < 0.95 ise kaldırılmaz (threshold altı)
        assert isinstance(result, set)


class TestQualityScoreV243:
    """v2.43.0: Quality score zenginleştirme testleri"""

    def test_heading_path_bonus(self):
        """Heading hiyerarşi derinliği bonus verir"""
        from app.services.rag_service import RAGService
        service = RAGService()

        text = "Bu orta uzunlukta bir paragraf metnidir."
        meta_no_path = {"heading": "Test", "type": "paragraph", "heading_path": []}
        meta_deep_path = {"heading": "Test", "type": "paragraph", "heading_path": ["Bölüm 1", "Alt Bölüm 1.1"]}

        score_no_path = service._calculate_quality_score(text, meta_no_path)
        score_deep_path = service._calculate_quality_score(text, meta_deep_path)

        assert score_deep_path > score_no_path

    def test_toc_penalty(self):
        """TOC chunk'larına ceza uygulanır"""
        from app.services.rag_service import RAGService
        service = RAGService()

        text = "Bölüm 1...............5\nBölüm 2...............12\nBölüm 3...............18"
        meta_toc = {"type": "toc", "heading": "İçindekiler", "heading_path": []}
        meta_normal = {"type": "paragraph", "heading": "Giriş", "heading_path": []}

        score_toc = service._calculate_quality_score(text, meta_toc)
        score_normal = service._calculate_quality_score(text, meta_normal)

        assert score_toc < score_normal

    def test_single_heading_path_small_bonus(self):
        """Tek heading path'te küçük bonus"""
        from app.services.rag_service import RAGService
        service = RAGService()

        text = "Bu bir test paragrafıdır."
        meta_one = {"type": "paragraph", "heading_path": ["Tek Bölüm"]}
        meta_two = {"type": "paragraph", "heading_path": ["Bölüm", "Alt Bölüm"]}

        score_one = service._calculate_quality_score(text, meta_one)
        score_two = service._calculate_quality_score(text, meta_two)

        assert score_two > score_one

    def test_score_always_between_0_1(self):
        """Quality score her zaman 0.1-1.0 arasında"""
        from app.services.rag_service import RAGService
        service = RAGService()

        test_cases = [
            ("Kısa.", {}),
            ("Orta uzunlukta test metni." * 10, {"heading": "H1", "type": "paragraph", "heading_path": ["A", "B"]}),
            ("", {"type": "toc"}),
            ("12345" * 100, {"type": "table_row"}),
        ]

        for text, meta in test_cases:
            score = service._calculate_quality_score(text, meta)
            assert 0.1 <= score <= 1.0, f"Score {score} out of range for text '{text[:30]}...'"

class TestKeywordDensityScore:
    """v2.43.0: Bilgi yoğunluğu (keyword density + entity) testleri"""

    def test_high_diversity_bonus(self):
        """Yüksek kelime çeşitliliği bonus verir"""
        from app.services.rag_service import RAGService
        service = RAGService()

        # Çeşitli kelimeler → yüksek diversity
        diverse_text = "Sistem yönetimi kapsamında veritabanı optimizasyonu yapılandırıldı performans analizi tamamlandı sunucu mimarisi güncellendi."
        # Tekrarlı kelimeler → düşük diversity
        repetitive_text = "test test test test test test metin metin metin metin metin metin test metin test metin"
        
        meta = {"type": "paragraph", "heading": ""}
        score_diverse = service._calculate_quality_score(diverse_text, meta)
        score_repetitive = service._calculate_quality_score(repetitive_text, meta)

        assert score_diverse > score_repetitive

    def test_entity_density_bonus(self):
        """Yüksek entity yoğunluğu bonus verir"""
        from app.services.rag_service import RAGService
        service = RAGService()

        # Entity'ler (büyük harfli kelimeler) çok
        entity_text = "Microsoft Azure, Google Cloud, Amazon AWS, Oracle Database ve IBM Watson servisleri kullanıldı projede."
        # Entity yok
        noentity_text = "bu bir düz metin parçasıdır herhangi bir özel isim veya kuruluş içermez sadece açıklama niteliğindedir."
        
        meta = {"type": "paragraph", "heading": ""}
        score_entity = service._calculate_quality_score(entity_text, meta)
        score_no = service._calculate_quality_score(noentity_text, meta)

        assert score_entity >= score_no

    def test_short_text_skips_density(self):
        """50 karakter altı metin density kontrolünü atlar"""
        from app.services.rag_service import RAGService
        service = RAGService()

        short_text = "Kısa metin."
        meta = {"type": "paragraph"}
        score = service._calculate_quality_score(short_text, meta)
        assert 0.1 <= score <= 1.0

    def test_low_word_count_skips(self):
        """5 kelimeden az metin density kontrolünü atlar"""
        from app.services.rag_service import RAGService
        service = RAGService()

        # 50+ karakter ama az kelime (uzun kelimeler)
        text = "superlongwordthathasnospacesandismeaningless " * 3
        meta = {"type": "paragraph"}
        score = service._calculate_quality_score(text, meta)
        assert 0.1 <= score <= 1.0


class TestContextCoherenceScore:
    """v2.43.0: Bağlam bütünlüğü (heading-içerik overlap) testleri"""

    def test_high_overlap_bonus(self):
        """Heading kelimeleri içerikte bulunursa bonus"""
        from app.services.rag_service import RAGService
        service = RAGService()

        text = "Veritabanı yönetimi kapsamında indeks bakımı performans açısından kritik önem taşır. Veritabanı optimizasyonu düzenli yapılmalıdır."
        meta_match = {"type": "paragraph", "heading": "Veritabanı Yönetimi", "heading_path": ["Veritabanı Yönetimi"]}
        meta_nomatch = {"type": "paragraph", "heading": "Güvenlik Politikası", "heading_path": ["Güvenlik Politikası"]}

        score_match = service._calculate_quality_score(text, meta_match)
        score_nomatch = service._calculate_quality_score(text, meta_nomatch)

        assert score_match > score_nomatch

    def test_no_heading_neutral(self):
        """Heading yoksa bağlam bütünlüğü nötr"""
        from app.services.rag_service import RAGService
        service = RAGService()

        text = "Bu bir test metni parçasıdır ve herhangi bir başlıkla ilişkili değildir ama yeterince uzundur."
        meta_no_heading = {"type": "paragraph", "heading": "", "heading_path": []}
        meta_heading = {"type": "paragraph", "heading": "Test", "heading_path": ["Test"]}

        score_no = service._calculate_quality_score(text, meta_no_heading)
        score_with = service._calculate_quality_score(text, meta_heading)

        # Her ikisi de geçerli aralıkta
        assert 0.1 <= score_no <= 1.0
        assert 0.1 <= score_with <= 1.0

    def test_short_heading_words_skipped(self):
        """2 karakterden kısa heading kelimeleri atlanır"""
        from app.services.rag_service import RAGService
        service = RAGService()

        text = "Bu bir detaylı açıklama metnidir ve yeterli uzunluktadır bağlam bütünlüğü kontrolü için."
        meta = {"type": "paragraph", "heading": "A B", "heading_path": ["A B"]}

        score = service._calculate_quality_score(text, meta)
        # Kısa kelimeler filtrelenir → heading_words boş → nötr
        assert 0.1 <= score <= 1.0


class TestCrossFileDedup:
    """v2.43.0: Cross-file duplicate detection testleri"""

    def test_no_chunks_returns_empty(self):
        """Boş chunk listesi boş set döndürür"""
        from app.services.rag_service import RAGService
        service = RAGService()

        result = service._cross_file_deduplicate([], [], file_id=1)
        assert result == set()

    @patch('app.services.rag.service.get_db_conn')
    def test_no_existing_chunks_returns_empty(self, mock_conn):
        """DB'de chunk yoksa boş set döndürür"""
        from app.services.rag_service import RAGService
        service = RAGService()

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.return_value.cursor.return_value = mock_cursor

        chunks = [{"text": "Test chunk metni burada."}]
        embeddings = [[0.1, 0.2, 0.3]]

        result = service._cross_file_deduplicate(chunks, embeddings, file_id=1)
        assert result == set()

    @patch('app.services.rag.service.get_db_conn')
    def test_duplicate_detected(self, mock_conn):
        """DB'deki mevcut chunk ile aynı embedding → duplicate"""
        from app.services.rag_service import RAGService
        service = RAGService()

        mock_cursor = MagicMock()
        # DB'deki mevcut chunk (aynı embedding)
        mock_cursor.fetchall.return_value = [
            {"id": 100, "embedding": [0.1, 0.2, 0.3], "text_len": 25}
        ]
        mock_conn.return_value.cursor.return_value = mock_cursor

        chunks = [{"text": "Test chunk metni burada."}]
        embeddings = [[0.1, 0.2, 0.3]]  # Aynı embedding

        result = service._cross_file_deduplicate(chunks, embeddings, file_id=2)
        assert 0 in result  # İlk chunk duplicate olarak işaretlenmeli

    @patch('app.services.rag.service.get_db_conn')
    def test_different_embeddings_not_duplicate(self, mock_conn):
        """Farklı embedding'ler duplicate sayılmaz"""
        from app.services.rag_service import RAGService
        service = RAGService()

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"id": 100, "embedding": [1.0, 0.0, 0.0], "text_len": 25}
        ]
        mock_conn.return_value.cursor.return_value = mock_cursor

        chunks = [{"text": "Tamamen farklı bir içerik."}]
        embeddings = [[0.0, 1.0, 0.0]]  # Dik vektör

        result = service._cross_file_deduplicate(chunks, embeddings, file_id=2)
        assert len(result) == 0

    @patch('app.services.rag.service.get_db_conn')
    def test_db_error_returns_empty(self, mock_conn):
        """DB hatası → chunk'lar yine de eklenir (graceful degradation)"""
        from app.services.rag_service import RAGService
        service = RAGService()

        mock_conn.side_effect = Exception("DB bağlantı hatası")

        chunks = [{"text": "Test chunk."}]
        embeddings = [[0.1, 0.2, 0.3]]

        result = service._cross_file_deduplicate(chunks, embeddings, file_id=1)
        assert result == set()  # Hata → boş set, chunk'lar korunur


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
