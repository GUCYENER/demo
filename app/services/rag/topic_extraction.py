"""
VYRA L1 Support API - Topic Extraction Module
===============================================
Dosya yüklenirken chunk içeriklerinden otomatik topic keyword çıkarır.
CatBoost feature extractor'ın topic detection'ında kullanılır.

🆕 v2.34.0: Yeni modül
"""

from __future__ import annotations

import re
from collections import Counter
from typing import List, Dict, Any

from app.core.db import get_db_conn
from app.services.logging_service import log_system_event, log_error, log_warning


# Topic çıkarma için stop words (Türkçe + Genel)
STOP_WORDS = {
    'bir', 'bu', 've', 'ile', 'için', 'de', 'da', 'ne', 'nasıl', 'neden',
    'olan', 'olarak', 'ise', 'veya', 'gibi', 'kadar', 'ki', 'daha', 'en',
    'her', 'sonra', 'önce', 'aynı', 'diğer', 'yeni', 'eski', 'büyük', 'küçük',
    'ile', 'dan', 'den', 'ya', 'ya', 'hem', 'ama', 'fakat', 'ancak',
    'tüm', 'bütün', 'çok', 'az', 'var', 'yok', 'üzerinde', 'altında',
    'olan', 'olduğu', 'olur', 'olacak', 'edilir', 'yapılır', 'yapılacak',
    'kullanılır', 'kullanılacak', 'seçilir', 'seçilecek', 'tıklanır',
    'sayfa', 'ekran', 'alan', 'buton', 'butonu', 'tıklanır', 'açılır',
    'gösterilir', 'görünür', 'görüntülenir', 'listelenir', 'listelenecektir',
    'the', 'and', 'for', 'that', 'this', 'with', 'from', 'are', 'was', 'not',
}

# Minimum keyword uzunluğu
MIN_KEYWORD_LENGTH = 3

# Bir topic oluşturmak için minimum keyword frekansı
MIN_KEYWORD_FREQUENCY = 2


def extract_topics_from_chunks(
    chunks: List[Dict[str, Any]],
    file_name: str,
    file_id: int,
    max_topics: int = 10,
    max_keywords_per_topic: int = 15
) -> Dict[str, List[str]]:
    """
    Chunk içeriklerinden otomatik topic ve keyword çıkarır.
    
    Yöntem:
    1. Heading'lerden topic isimlerini çıkar (en güvenilir kaynak)
    2. Chunk metinlerinden sik tekrarlanan terimleri keyword olarak çıkar
    3. İlgili keyword'leri topic altında grupla
    
    Args:
        chunks: İşlenmiş chunk listesi
        file_name: Dosya adı
        file_id: Dosya ID
        max_topics: Maksimum topic sayısı
        max_keywords_per_topic: Topic başına maksimum keyword
    
    Returns:
        {topic_name: [keyword1, keyword2, ...], ...}
    """
    # 1. Heading'lerden topic isimleri çıkar
    heading_topics = _extract_topics_from_headings(chunks)
    
    # 2. Chunk metinlerinden keyword frekansları çıkar  
    all_text = " ".join(c.get("text", "") for c in chunks)
    keyword_freq = _extract_keyword_frequencies(all_text)
    
    # 3. Her topic için ilgili keyword'leri eşleştir
    topics = {}
    
    for topic_name, topic_headings in heading_topics.items():
        # Topic heading'lerindeki kelimeleri keyword olarak ekle
        topic_keywords = set()
        
        for heading in topic_headings:
            words = _tokenize(heading)
            for word in words:
                if word not in STOP_WORDS and len(word) >= MIN_KEYWORD_LENGTH:
                    topic_keywords.add(word)
        
        # İlgili chunk'lardaki en sık geçen terimleri ekle
        related_chunks = [
            c for c in chunks 
            if any(h.lower() in (c.get("metadata", {}).get("heading", "") or "").lower() 
                   for h in topic_headings)
        ]
        
        if related_chunks:
            related_text = " ".join(c.get("text", "") for c in related_chunks)
            related_freq = _extract_keyword_frequencies(related_text)
            
            # En sık 10 terimi ekle
            for term, freq in related_freq.most_common(10):
                if freq >= MIN_KEYWORD_FREQUENCY and term not in STOP_WORDS:
                    topic_keywords.add(term)
        
        if topic_keywords:
            topics[topic_name] = sorted(list(topic_keywords))[:max_keywords_per_topic]
    
    # 4. Heading'lere uymayan ama sık geçen terimleri "general_<filename>" topic'ine ekle
    file_stem = re.sub(r'[^a-zA-ZçÇğĞıİöÖşŞüÜ0-9]', '_', 
                       file_name.rsplit('.', 1)[0] if '.' in file_name else file_name)
    file_stem = file_stem[:30].lower().strip('_')
    
    uncategorized_keywords = set()
    for term, freq in keyword_freq.most_common(30):
        if freq >= MIN_KEYWORD_FREQUENCY and term not in STOP_WORDS:
            # Zaten bir topic'e atanmış mı?
            already_used = any(term in kws for kws in topics.values())
            if not already_used:
                uncategorized_keywords.add(term)
    
    if uncategorized_keywords:
        general_topic = f"doc_{file_stem}"
        topics[general_topic] = sorted(list(uncategorized_keywords))[:max_keywords_per_topic]
    
    # Max topic limiti
    if len(topics) > max_topics:
        # En fazla keyword'e sahip topic'leri tut
        sorted_topics = sorted(topics.items(), key=lambda x: len(x[1]), reverse=True)
        topics = dict(sorted_topics[:max_topics])
    
    return topics


def save_topics_to_db(
    topics: Dict[str, List[str]], 
    file_id: int
) -> int:
    """
    Çıkarılan topic'leri document_topics tablosuna kaydet.
    UPSERT: Aynı topic varsa keyword'leri birleştir.
    
    Returns:
        Kaydedilen/güncellenen topic sayısı
    """
    if not topics:
        return 0
    
    saved = 0
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                for topic_name, keywords in topics.items():
                    cur.execute("""
                        INSERT INTO document_topics (topic_name, keywords, source_file_ids, auto_generated)
                        VALUES (%s, %s, ARRAY[%s]::INTEGER[], TRUE)
                        ON CONFLICT (topic_name) DO UPDATE SET
                            keywords = (
                                SELECT array_agg(DISTINCT elem)
                                FROM unnest(
                                    document_topics.keywords || EXCLUDED.keywords
                                ) as elem
                            ),
                            source_file_ids = (
                                SELECT array_agg(DISTINCT elem)
                                FROM unnest(
                                    document_topics.source_file_ids || EXCLUDED.source_file_ids
                                ) as elem
                            ),
                            updated_at = NOW()
                    """, (topic_name, keywords, file_id))
                    saved += 1
                
                conn.commit()
        
        log_system_event(
            "INFO",
            f"Dosya {file_id} için {saved} topic kaydedildi: {list(topics.keys())}",
            "topic_extraction"
        )
        
    except Exception as e:
        log_error(f"Topic kaydetme hatası: {e}", "topic_extraction")
    
    return saved


def extract_and_save_topics(
    chunks: List[Dict[str, Any]],
    file_name: str,
    file_id: int
) -> int:
    """
    Chunk'lardan topic çıkar ve DB'ye kaydet (upload pipeline entegrasyonu).
    
    Returns:
        Kaydedilen topic sayısı
    """
    topics = extract_topics_from_chunks(chunks, file_name, file_id)
    
    if topics:
        saved = save_topics_to_db(topics, file_id)
        
        # Feature extractor cache'ini temizle (yeni topic'ler yüklensin)
        try:
            from app.services.feature_extractor import get_feature_extractor
            get_feature_extractor().clear_cache()
        except Exception as e:
            log_warning(f"Feature extractor cache temizleme hatası: {e}", "topic_extraction")
        
        return saved
    
    return 0


# ────────────────────────────────────────────────────
# Yardımcı Fonksiyonlar
# ────────────────────────────────────────────────────

def _tokenize(text: str) -> List[str]:
    """Metni küçük harfli kelimelere ayırır"""
    return [w.lower() for w in re.findall(r'\b\w+\b', text) if len(w) >= MIN_KEYWORD_LENGTH]


def _extract_topics_from_headings(chunks: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """
    Chunk heading'lerinden topic isimlerini çıkarır.
    Benzer heading'leri gruplar.
    """
    heading_counts = Counter()
    heading_map = {}  # normalized -> original headings
    
    for chunk in chunks:
        heading = (chunk.get("metadata", {}).get("heading", "") or "").strip()
        if not heading or len(heading) < 3:
            continue
        
        # Heading'i normalize et (numaralama kaldır, küçük harf)
        normalized = re.sub(r'^[\d\.\)\-\s]+', '', heading).strip()
        normalized = re.sub(r'\s+', ' ', normalized)
        
        if len(normalized) < 3:
            continue
        
        # Üst seviye heading'i topic ismi olarak kullan
        # "1. Stok Yeri Transfer İşlemleri" → "stok_yeri_transfer_islemleri"
        topic_key = _heading_to_topic_key(normalized)
        
        if topic_key:
            heading_counts[topic_key] += 1
            if topic_key not in heading_map:
                heading_map[topic_key] = []
            if heading not in heading_map[topic_key]:
                heading_map[topic_key].append(heading)
    
    # En az 2 chunk'ta geçen heading'leri topic olarak kabul et
    topics = {}
    for topic_key, count in heading_counts.most_common(20):
        if count >= 1:  # Tek heading bile değerli
            topics[topic_key] = heading_map.get(topic_key, [])
    
    return topics


def _heading_to_topic_key(heading: str) -> str:
    """Heading'i topic key'ine çevirir"""
    # Küçük harf
    key = heading.lower()
    
    # Özel karakterleri kaldır
    key = re.sub(r'[^a-zA-ZçÇğĞıİöÖşŞüÜ0-9\s]', '', key)
    
    # Boşlukları alt çizgiye çevir
    key = re.sub(r'\s+', '_', key.strip())
    
    # Çok uzunsa kırp
    if len(key) > 50:
        key = key[:50].rstrip('_')
    
    return key if len(key) >= 3 else ''


def _extract_keyword_frequencies(text: str) -> Counter:
    """Metinden keyword frekanslarını çıkarır (bigram dahil)"""
    words = _tokenize(text)
    
    # Unigram frekansları
    freq = Counter()
    for word in words:
        if word not in STOP_WORDS and len(word) >= MIN_KEYWORD_LENGTH:
            freq[word] += 1
    
    # Bigram frekansları (ör: "stok yeri", "iş emri")
    for i in range(len(words) - 1):
        w1, w2 = words[i], words[i + 1]
        if (w1 not in STOP_WORDS and w2 not in STOP_WORDS 
            and len(w1) >= MIN_KEYWORD_LENGTH and len(w2) >= MIN_KEYWORD_LENGTH):
            bigram = f"{w1} {w2}"
            freq[bigram] += 1
    
    return freq


# ────────────────────────────────────────────────────
# 🆕 v2.34.0: CatBoost Training → Topic Refinement
# ────────────────────────────────────────────────────

def refine_topics_from_training(training_data: List[Dict[str, Any]]) -> int:
    """
    CatBoost eğitim verilerinden topic keyword'leri iyileştirir.
    
    Her CL eğitim döngüsünde çağrılır:
    1. Başarılı eşleşmelerden (relevance=1) yeni keyword'ler çıkar
    2. Chunk'ın source_file'ına göre ilgili topic'i bul
    3. Sorgu keyword'lerini o topic'e ekle
    
    Args:
        training_data: CL pipeline'dan gelen eğitim verisi
            [{query, chunk_id, chunk_text, source_file, relevance_label, score}, ...]
    
    Returns:
        Güncellenen topic sayısı
    """
    if not training_data:
        return 0
    
    # Sadece başarılı (relevant) eşleşmeleri filtrele
    relevant_samples = [
        s for s in training_data 
        if s.get("relevance_label", 0) == 1 and s.get("score", 0) >= 0.5
    ]
    
    if not relevant_samples:
        return 0
    
    # Source file → yeni keyword'ler eşlemesi oluştur
    file_keywords: Dict[str, set] = {}
    
    for sample in relevant_samples:
        source_file = sample.get("source_file", "")
        query = sample.get("query", "")
        
        if not source_file or not query:
            continue
        
        # Sorgudan keyword'ler çıkar
        query_keywords = _tokenize(query)
        meaningful_keywords = [
            kw for kw in query_keywords 
            if kw not in STOP_WORDS and len(kw) >= MIN_KEYWORD_LENGTH
        ]
        
        if meaningful_keywords:
            if source_file not in file_keywords:
                file_keywords[source_file] = set()
            file_keywords[source_file].update(meaningful_keywords)
    
    if not file_keywords:
        return 0
    
    # DB'deki topic'leri oku ve eşle
    updated_count = 0
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                for source_file, new_keywords in file_keywords.items():
                    # Bu dosyaya ait topic'leri bul
                    cur.execute("""
                        SELECT id, topic_name, keywords, source_file_ids
                        FROM document_topics
                        WHERE source_file_ids IS NOT NULL
                    """)
                    all_topics = cur.fetchall()
                    
                    # Source file ID'sini bul
                    cur.execute(
                        "SELECT id FROM uploaded_files WHERE file_name = %s",
                        (source_file,)
                    )
                    file_row = cur.fetchone()
                    if not file_row:
                        continue
                    
                    file_id = file_row["id"]
                    
                    # Bu dosyaya ait topic'leri filtrele
                    matching_topics = [
                        t for t in all_topics 
                        if t["source_file_ids"] and file_id in t["source_file_ids"]
                    ]
                    
                    if not matching_topics:
                        # Dosyaya ait topic yoksa genel topic oluştur
                        file_stem = re.sub(
                            r'[^a-zA-ZçÇğĞıİöÖşŞüÜ0-9]', '_',
                            source_file.rsplit('.', 1)[0] if '.' in source_file else source_file
                        )[:30].lower().strip('_')
                        
                        general_topic = f"learned_{file_stem}"
                        new_kw_list = sorted(list(new_keywords))[:15]
                        
                        cur.execute("""
                            INSERT INTO document_topics (topic_name, keywords, source_file_ids, auto_generated)
                            VALUES (%s, %s, ARRAY[%s]::INTEGER[], TRUE)
                            ON CONFLICT (topic_name) DO UPDATE SET
                                keywords = (
                                    SELECT array_agg(DISTINCT elem)
                                    FROM unnest(document_topics.keywords || EXCLUDED.keywords) as elem
                                ),
                                updated_at = NOW()
                        """, (general_topic, new_kw_list, file_id))
                        updated_count += 1
                    else:
                        # En uygun topic'e keyword'leri ekle
                        # (En çok keyword örtüşmesi olan topic'i seç)
                        best_topic = None
                        best_overlap = -1
                        
                        for topic in matching_topics:
                            existing_kws = set(topic["keywords"] or [])
                            overlap = len(new_keywords & existing_kws)
                            if overlap > best_overlap:
                                best_overlap = overlap
                                best_topic = topic
                        
                        if best_topic:
                            new_kw_list = sorted(list(new_keywords))[:10]
                            cur.execute("""
                                UPDATE document_topics 
                                SET keywords = (
                                    SELECT array_agg(DISTINCT elem)
                                    FROM unnest(keywords || %s::TEXT[]) as elem
                                ),
                                updated_at = NOW()
                                WHERE id = %s
                            """, (new_kw_list, best_topic["id"]))
                            updated_count += 1
                
                conn.commit()
        
        if updated_count > 0:
            log_system_event(
                "INFO",
                f"CatBoost topic refinement: {updated_count} topic güncellendi "
                f"({len(relevant_samples)} başarılı eşleşmeden)",
                "topic_extraction"
            )
            
            # Feature extractor cache temizle
            try:
                from app.services.feature_extractor import get_feature_extractor
                get_feature_extractor().clear_cache()
            except Exception as e:
                log_warning(f"Feature extractor cache temizleme hatası (refinement): {e}", "topic_extraction")
    
    except Exception as e:
        log_error(f"Topic refinement hatası: {e}", "topic_extraction")
    
    return updated_count
