"""
VYRA L1 Support API - RAG Router (Smart Pre-check)
====================================================
Sorguyu analiz eder ve RAG araması gerekip gerekmediğini belirler.
Keyword tabanlı hızlı ön kontrol (~10ms) yapar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Set, Optional
from app.core.db import get_db_conn
from app.services.logging_service import log_system_event


@dataclass
class RoutingDecision:
    """RAG routing kararı"""
    should_use_rag: bool
    reason: str
    matched_keywords: List[str] = None
    matched_files: List[str] = None


# Cache - dosya isimleri ve anahtar kelimeler
_file_keywords_cache: Optional[dict] = None
_cache_timestamp: float = 0


def _load_file_keywords() -> dict:
    """
    DB'den dosya isimlerini ve içeriklerinden anahtar kelimeleri çeker.
    Bu işlem ~10-50ms sürer.
    """
    global _file_keywords_cache, _cache_timestamp
    import time
    
    # Cache 5 dakika geçerliliğe sahip
    current_time = time.time()
    if _file_keywords_cache and (current_time - _cache_timestamp) < 300:
        return _file_keywords_cache
    
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        
        # Dosya isimlerini çek
        cur.execute("""
            SELECT DISTINCT file_name 
            FROM uploaded_files 
            WHERE chunk_count > 0
        """)
        files = [row['file_name'] for row in cur.fetchall()]
        
        # Her dosya için anahtar kelimeler çıkar
        keywords = set()
        for filename in files:
            # Dosya adından kelimeler
            name_parts = filename.lower().replace('.pdf', '').replace('.docx', '').replace('.txt', '')
            for word in name_parts.replace('_', ' ').replace('-', ' ').split():
                if len(word) > 2:
                    keywords.add(word)
        
        # İlk 100 chunk'tan anahtar kelimeleri çıkar (örnek için)
        cur.execute("""
            SELECT DISTINCT LEFT(chunk_text, 500) as sample
            FROM rag_chunks
            LIMIT 50
        """)
        
        for row in cur.fetchall():
            text = row['sample'].lower()
            # Önemli kelimeleri çıkar (basit yaklaşım)
            for word in ['mail', 'e-posta', 'outlook', 'şifre', 'parola', 'password', 
                        'vpn', 'ağ', 'network', 'internet', 'bağlantı', 'ldap', 
                        'active directory', 'ad ', 'kota', 'disk', 'depolama',
                        'yazıcı', 'printer', 'teams', 'office', 'onedrive']:
                if word in text:
                    keywords.add(word)
        
        conn.close()
        
        _file_keywords_cache = {
            'files': files,
            'keywords': keywords
        }
        _cache_timestamp = current_time
        
        log_system_event("INFO", f"RAG Router cache güncellendi: {len(files)} dosya, {len(keywords)} anahtar kelime", "rag_router")
        return _file_keywords_cache
        
    except Exception as e:
        log_system_event("WARNING", f"RAG Router cache hatası: {str(e)}", "rag_router")
        return {'files': [], 'keywords': set()}


def should_use_rag(query: str) -> RoutingDecision:
    """
    Sorguyu analiz eder ve RAG araması yapılmalı mı belirler.
    
    Mantık:
    1. Sorgu çok kısa ise -> RAG yok
    2. Sorguda bilgi tabanı anahtar kelimeleri varsa -> RAG kullan
    3. Aksi halde -> RAG yok, direkt LLM
    
    Args:
        query: Kullanıcı sorusu
        
    Returns:
        RoutingDecision
    """
    query_lower = query.lower()
    
    # 1. Çok kısa sorgular - direkt LLM
    if len(query) < 15:
        return RoutingDecision(
            should_use_rag=False,
            reason="Sorgu çok kısa, direkt LLM kullanılıyor"
        )
    
    # 2. Cache'den anahtar kelimeleri al
    cache = _load_file_keywords()
    
    # Bilgi tabanı boş
    if not cache['files']:
        return RoutingDecision(
            should_use_rag=False,
            reason="Bilgi tabanı boş, direkt LLM kullanılıyor"
        )
    
    # 3. Anahtar kelime eşleştirmesi
    matched_keywords = []
    for keyword in cache['keywords']:
        if keyword in query_lower:
            matched_keywords.append(keyword)
    
    # Dosya adlarıyla da eşleştir
    matched_files = []
    for filename in cache['files']:
        filename_lower = filename.lower()
        for word in query_lower.split():
            if len(word) > 3 and word in filename_lower:
                matched_files.append(filename)
                break
    
    # Karar
    if matched_keywords or matched_files:
        return RoutingDecision(
            should_use_rag=True,
            reason=f"Eşleşen anahtar kelimeler bulundu",
            matched_keywords=matched_keywords,
            matched_files=matched_files
        )
    
    # Genel BT terimleri - RAG'a bakmaya değer
    general_it_terms = ['sorun', 'hata', 'çalışmıyor', 'açılmıyor', 'bağlanamıyorum',
                       'nasıl', 'neden', 'yardım', 'destek']
    
    for term in general_it_terms:
        if term in query_lower:
            # Genel BT sorusu - RAG'a bak
            return RoutingDecision(
                should_use_rag=True,
                reason="Genel BT sorusu, bilgi tabanı kontrol edilecek",
                matched_keywords=[term]
            )
    
    # 4. Eşleşme yok - direkt LLM
    return RoutingDecision(
        should_use_rag=False,
        reason="İlgili anahtar kelime bulunamadı, direkt LLM kullanılıyor"
    )


def clear_cache():
    """Cache'i temizler (dosya yüklemesinden sonra çağrılmalı)"""
    global _file_keywords_cache, _cache_timestamp
    _file_keywords_cache = None
    _cache_timestamp = 0
    log_system_event("INFO", "RAG Router cache temizlendi", "rag_router")
