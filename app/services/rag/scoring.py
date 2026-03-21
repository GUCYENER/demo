"""
VYRA L1 Support API - RAG Scoring Functions
=============================================
Hybrid search skorlama fonksiyonları:
- Cosine Similarity
- BM25 Keyword Scoring
- Reciprocal Rank Fusion (RRF)
- Min-Max Normalizasyon
- Exact Match & Fuzzy Matching
"""

from __future__ import annotations

import re
from typing import List, Dict


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """İki vektör arasındaki cosine similarity hesaplar"""
    import numpy as np
    a = np.array(vec1)
    b = np.array(vec2)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def cosine_similarity_batch(query_vec: List[float], doc_vecs: List[List[float]]) -> List[float]:
    """
    🚀 v2.32.0: NumPy vectorized batch cosine similarity.
    Tüm doküman vektörlerini tek seferde hesaplar - ~100x hız artışı.
    
    Args:
        query_vec: Sorgu vektörü (1D)
        doc_vecs: Doküman vektörleri listesi (2D)
        
    Returns:
        Her doküman için cosine similarity skoru listesi
    """
    import numpy as np
    
    if not doc_vecs:
        return []
    
    q = np.array(query_vec, dtype=np.float32)
    D = np.array(doc_vecs, dtype=np.float32)
    
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        return [0.0] * len(doc_vecs)
    
    # Batch norm hesaplama
    d_norms = np.linalg.norm(D, axis=1)
    # Sıfır vektörleri koru (division by zero önle)
    d_norms = np.where(d_norms == 0, 1e-10, d_norms)
    
    # Tek matris çarpımı ile tüm similarity'leri hesapla
    similarities = D @ q / (d_norms * q_norm)
    
    return similarities.tolist()


def bm25_score(query: str, document: str, avg_doc_len: float = 500, k1: float = 1.5, b: float = 0.75) -> float:
    """
    🆕 v2.25.0: BM25 keyword scoring
    Best practice: Hybrid search için keyword-based skor
    
    Args:
        query: Arama sorgusu
        document: Chunk metni
        avg_doc_len: Ortalama doküman uzunluğu
        k1: Term frequency saturation parametresi
        b: Length normalization parametresi
    
    Returns:
        BM25 skoru (0-1 normalize edilmiş)
    """
    # Tokenize
    query_terms = set(re.findall(r'\w+', query.lower()))
    doc_terms = re.findall(r'\w+', document.lower())
    doc_len = len(doc_terms)
    
    if not query_terms or not doc_terms:
        return 0.0
    
    # Term frequency hesapla
    term_freq = {}
    for term in doc_terms:
        term_freq[term] = term_freq.get(term, 0) + 1
    
    # BM25 formülü
    score = 0.0
    for term in query_terms:
        if term in term_freq:
            tf = term_freq[term]
            # IDF basitleştirilmiş (corpus bazlı değil, tek doküman)
            idf = 1.0  # Basitleştirme: tüm terimlere eşit ağırlık
            
            # BM25 numerator ve denominator
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * (doc_len / avg_doc_len))
            score += idf * (numerator / denominator)
    
    # Normalize (0-1 arası)
    max_possible = len(query_terms) * (k1 + 1)
    return min(1.0, score / max_possible) if max_possible > 0 else 0.0


def reciprocal_rank_fusion(rankings: List[List[Dict]], k: int = 60) -> List[Dict]:
    """
    🆕 v2.25.0: Reciprocal Rank Fusion (RRF)
    Best practice: Multiple ranking'leri birleştir
    
    Args:
        rankings: [[{id, score}, ...], ...] şeklinde birden fazla ranking
        k: RRF konstant (genellikle 60)
    
    Returns:
        Birleştirilmiş ve sıralanmış sonuçlar
    """
    rrf_scores = {}
    item_data = {}
    
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            item_id = item.get("id")
            if item_id:
                rrf_scores[item_id] = rrf_scores.get(item_id, 0) + (1.0 / (k + rank))
                item_data[item_id] = item  # Son veriyi sakla
    
    # RRF skorunu ekle ve sırala
    results = []
    for item_id, rrf_score in rrf_scores.items():
        item = item_data[item_id].copy()
        item["rrf_score"] = rrf_score
        results.append(item)
    
    results.sort(key=lambda x: x["rrf_score"], reverse=True)
    return results


def normalize_scores(results: List[Dict], score_key: str = "score") -> List[Dict]:
    """
    v2.53.1: Akıllı normalizasyon — sonuç sayısına göre strateji seçer.
    
    Sorun: Min-Max normalizasyon tek sonuçta otomatik 1.0 verir,
    bu da düşük kaliteli eşleşmeleri "mükemmel" gibi gösterir.
    
    Çözüm:
    - 1 sonuç: Ham skor korunur (normalizasyon yok)
    - 2 sonuç: Oransal normalizasyon (ham skora göre 0.0-ham_skor arası)
    - 3+ sonuç: Min-Max normalizasyon + ham skor alt sınır koruması
    
    Her sonuca `original_raw_score` eklenir → debug ve UI için kullanılabilir.
    """
    if not results:
        return results
    
    # Her sonuca ham skoru kaydet (her zaman korunsun)
    for r in results:
        r["original_raw_score"] = r.get(score_key, 0)
    
    scores = [r.get(score_key, 0) for r in results]
    min_s = min(scores)
    max_s = max(scores)
    
    if len(results) == 1:
        # ✅ Tek sonuç: Normalizasyon YOK — ham skor direkt kullanılır
        # Bu, düşük kaliteli eşleşmelerin 1.0 olarak gösterilmesini engeller
        r = results[0]
        r[f"{score_key}_normalized"] = r.get(score_key, 0)
        return results
    
    if max_s == min_s:
        # Tüm skorlar eşit — ham skoru koru
        for r in results:
            r[f"{score_key}_normalized"] = r.get(score_key, 0)
        return results
    
    if len(results) == 2:
        # 2 sonuç: Oransal — max skoru referans al, min'i ham oranına göre düşür
        for r in results:
            raw = r.get(score_key, 0)
            # max_s'a yakınsa yüksek normalized skor, uzaksa düşük
            r[f"{score_key}_normalized"] = raw / max_s if max_s > 0 else 0
        return results
    
    # 3+ sonuç: Min-Max normalizasyon + ham skor alt sınır koruması
    for r in results:
        raw = r.get(score_key, 0)
        normalized = (raw - min_s) / (max_s - min_s)
        # Alt sınır: normalize edilmiş skor, ham skorun altına düşmesin
        # Bu, düşük ham skorlu sonuçların normalize ile şişmesini engeller
        r[f"{score_key}_normalized"] = min(normalized, max(raw, normalized))
    
    return results


def extract_keywords(text: str) -> List[str]:
    """Metinden anahtar kelimeleri çıkarır"""
    # Türkçe stopwords
    stopwords = {'ve', 'veya', 'bir', 'bu', 'şu', 'için', 'ile', 'de', 'da', 'mi', 'mı', 'mu', 'mü', 
                 'nasıl', 'ne', 'neden', 'kim', 'hangi', 'kaç', 'benim', 'var', 'yok', 'olarak'}
    
    words = text.lower().split()
    keywords = [w for w in words if len(w) > 2 and w not in stopwords]
    return keywords[:10]  # Max 10 keyword


def is_technical_term(term: str) -> bool:
    """
    Teknik terim mi kontrol et.
    Örnek: SC_380_KURUMSAL_MUSTERILER_VRFTSOL_READWRITE
    """
    # Teknik terim pattern'leri
    patterns = [
        r'^[A-Z][A-Z0-9_]{5,}$',     # SC_380_KURUMSAL... (büyük harf + alt çizgi)
        r'^\d+[A-Z_]+',               # 380KURUMSAL...
        r'[A-Z]{3,}_[A-Z]+',          # ABC_DEF formatı
        r'_READWRITE$|_READ$|_WRITE$',  # Yetki suffix'leri
        r'VRFTSOL|TSOLVRF',            # Bilinen teknik kodlar
    ]
    
    term_upper = term.upper()
    return any(re.search(p, term_upper) for p in patterns)


def has_exact_query_match(query: str, chunk_text: str) -> bool:
    """
    🆕 v2.29.1: Sorgunun chunk'ta tam eşleşip eşleşmediğini kontrol eder.
    
    Özellikle teknik komutlar için optimize edilmiş:
    - 'show vlan' → chunk'ta 'show vlan' geçiyor mu?
    - 'dis cur' → chunk'ta 'dis cur' geçiyor mu?
    
    Returns:
        True eğer sorgunun teknik komut kısmı chunk'ta bulunuyorsa
    """
    query_lower = query.lower()
    chunk_lower = chunk_text.lower()
    
    # 1️⃣ Teknik komut pattern'leri çıkar (show xxx, dis xxx, ping xxx vb.)
    command_patterns = [
        r'\b(show\s+\w+)',       # show vlan, show run, show ip int brief
        r'\b(dis\s+\w+)',        # dis cur, dis vlan
        r'\b(ping\s+[\w\-\.]+)', # ping -vpn-instance
        r'\b(conf\s+\w+)',       # conf t
        r'\b(no\s+\w+)',         # no shutdown
    ]
    
    for pattern in command_patterns:
        matches = re.findall(pattern, query_lower)
        for cmd in matches:
            if cmd in chunk_lower:
                return True
    
    # 2️⃣ Fallback: En az 3+ karakterli 2 kelime eşleşmeli
    query_terms = [w for w in query_lower.split() if len(w) >= 3]
    if not query_terms:
        return False
    
    match_count = sum(1 for term in query_terms if term in chunk_lower)
    return match_count >= 2 and match_count >= len(query_terms) / 3


def calculate_exact_match_bonus(query: str, chunk_text: str) -> float:
    """
    Sorgu terimi chunk'ta tam geçiyorsa bonus ver.
    Teknik terimler için ekstra bonus.
    
    🔧 v2.20.7: Teknik terim bonusları artırıldı
    - 3 harfli kısaltmalar (APE, VPN, DNS): 0.4 bonus
    - Diğer teknik terimler: 0.3 bonus
    - Teknik match ekstra boost: 0.15
    
    Returns:
        0.0 - 0.7 arası bonus değeri
    """
    query_terms = query.split()
    chunk_lower = chunk_text.lower()
    
    total_bonus = 0.0
    technical_match = False
    short_acronym_match = False  # 3 harfli kısaltma eşleşmesi
    
    for term in query_terms:
        term_lower = term.lower()
        
        # Çok kısa terimler için kontrol - AMA teknik kısaltmalar hariç
        # APE, VPN, DNS, NTP, BGP gibi 3 harfli kısaltmalar teknik terim sayılır
        if len(term) < 3:
            continue  # 2 ve altı karakterli terimler atla
        
        # 3 karakterli terimler: Büyük harfle yazılmış VEYA küçük harf ama chunk'ta büyük harf var
        is_short_acronym = len(term) == 3 and (term.isupper() or term.upper() in chunk_text)
        
        if len(term) == 3 and not is_short_acronym:
            continue  # "bir", "için" gibi 3 harfli normal kelimeler atla
        
        # Tam eşleşme kontrolü (case insensitive)
        if term_lower in chunk_lower:
            # 3 harfli teknik kısaltma mı? (APE, VPN, DNS vb.)
            if is_short_acronym:
                total_bonus += 0.4  # 🔥 3 harfli kısaltma için YÜKSEK bonus
                technical_match = True
                short_acronym_match = True
            # Diğer teknik terim mi?
            elif is_technical_term(term):
                total_bonus += 0.3  # Teknik terim için bonus
                technical_match = True
            else:
                total_bonus += 0.1  # Normal terim için bonus
    
    # Teknik terim eşleşmesi varsa ekstra boost
    if technical_match:
        total_bonus += 0.15
    
    # 3 harfli kısaltma eşleşmesi için ekstra boost (APE, VPN gibi kritik terimler)
    if short_acronym_match:
        total_bonus += 0.1
    
    # Maksimum 0.7 bonus (artırıldı)
    return min(0.7, total_bonus)


def calculate_fuzzy_boost(query_keywords: List[str], chunk_text: str) -> float:
    """
    Fuzzy string matching ile bonus skor hesaplar.
    'şfre' vs 'şifre' gibi eksik harf durumlarını tespit eder.
    
    Returns:
        0.0 - 0.3 arası boost değeri
    """
    if not query_keywords:
        return 0.0
    
    try:
        from rapidfuzz import fuzz
        
        chunk_lower = chunk_text.lower()
        total_boost = 0.0
        match_count = 0
        
        for keyword in query_keywords:
            # Exact match varsa küçük boost
            if keyword in chunk_lower:
                total_boost += 0.05
                match_count += 1
                continue
            
            # Fuzzy match dene - partial ratio kullan
            # Bu "şifre" ile "şfre" arasındaki benzerliği bulur
            words_in_chunk = chunk_lower.split()
            
            best_ratio = 0
            for chunk_word in words_in_chunk:
                if len(chunk_word) < 3:
                    continue
                
                # Partial ratio - kısmi eşleşme
                ratio = fuzz.ratio(keyword, chunk_word)
                
                # %80+ benzerlik varsa match say
                if ratio > 80:
                    best_ratio = max(best_ratio, ratio)
            
            if best_ratio > 80:
                # Oran bazlı boost: 80% -> 0.05, 90% -> 0.10, 100% -> 0.15
                boost = (best_ratio - 80) / 100 * 0.5
                total_boost += boost
                match_count += 1
        
        # Normalize et - max 0.3 boost
        if match_count > 0:
            return min(0.3, total_boost)
        return 0.0
        
    except ImportError as e:
        # rapidfuzz yüklü değilse boost yok
        import sys
        print(f"[Scoring] rapidfuzz import hatası, fuzzy boost devre dışı: {e}", file=sys.stderr)
        return 0.0
