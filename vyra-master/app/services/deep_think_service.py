"""
VYRA L1 Support API - Deep Think Service
=========================================
RAG sonuçlarını LLM ile akıllıca sentezleyerek profesyonel yanıtlar üretir.

v2.28.0: Initial implementation

Özellikler:
- Intent Detection: Soru tipi analizi (liste, tekil, adım adım)
- Expanded Retrieval: Intent'e göre dinamik n_results
- LLM Synthesis: Tüm sonuçları profesyonel formatta birleştirme
- Citation: Kaynak dosya ve chunk referansları
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional
import re

from app.core.db import get_db_conn
from app.core.llm import call_llm_api, LLMConnectionError, LLMConfigError
from app.services.logging_service import log_system_event, log_error, log_warning
from app.services.deep_think.types import IntentType, IntentResult, DeepThinkResult
from app.services.deep_think import DeepThinkFormattingMixin, DeepThinkFallbackMixin


# ============================================
# Deep Think Service
# ============================================

class DeepThinkService(DeepThinkFormattingMixin, DeepThinkFallbackMixin):
    """
    RAG sonuçlarını akıllıca sentezleyen servis.
    
    Pipeline:
    1. Intent Detection → Soru tipini belirle
    2. Expanded Retrieval → Daha fazla sonuç getir (liste için)
    3. LLM Synthesis → Sonuçları birleştir ve formatla
    """
    
    # Liste talep eden kalıplar
    LIST_PATTERNS = [
        r'\bnelerdir\b', r'\blistele\b', r'\btüm\b', r'\bhepsi\b',
        r'\bkaç tane\b', r'\bhangileri\b', r'\bsayar mısın\b',
        r'\bkomutlar[ıi]?\b', r'\bseçenekler\b', r'\byöntemler\b',
        r'\badımlar\b', r'\bçeşitler\b', r'\btürler\b'
    ]
    
    # Tekil cevap kalıpları
    SINGLE_PATTERNS = [
        r'\bnedir\b', r'\bne işe yarar\b', r'\bne demek\b',
        r'\bnasıl çalışır\b', r'\bne anlama gelir\b'
    ]
    
    # Adım adım çözüm kalıpları
    HOWTO_PATTERNS = [
        r'\bnasıl\b', r'\badım adım\b', r'\byapılır\b',
        r'\bkurulum\b', r'\bayarla\b', r'\byap\b'
    ]
    
    # Sorun giderme kalıpları
    TROUBLESHOOT_PATTERNS = [
        r'\bçalışmıyor\b', r'\bhata\b', r'\bsorun\b', r'\bproblem\b',
        r'\bbozuk\b', r'\baçılmıyor\b', r'\bdonuyor\b'
    ]
    
    def __init__(self):
        self._synthesis_prompt = None  # Lazy load - DB bağlantısı geciktirildi
    
    @property
    def synthesis_prompt(self) -> str:
        """Lazy load: İlk kullanımda DB'den prompt çeker."""
        if self._synthesis_prompt is None:
            self._synthesis_prompt = self._load_synthesis_prompt()
        return self._synthesis_prompt
    
    def _load_synthesis_prompt(self) -> str:
        """DB'den Deep Think promptunu çeker, yoksa fallback kullanır."""
        try:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT content FROM prompt_templates 
                WHERE category = 'deep_think' AND is_active = TRUE 
                LIMIT 1
            """)
            row = cur.fetchone()
            conn.close()
            
            if row:
                return row["content"]
        except Exception as e:
            log_warning(f"Deep Think prompt çekilemedi: {e}", "deep_think")
        
        return DEEP_THINK_FALLBACK_PROMPT
    
    # ========================================
    # 1. Intent Detection
    # ========================================
    
    def _detect_target_category(self, keywords: List[str]) -> Optional[str]:
        """
        🆕 v2.29.3: Kullanıcının hangi kategoriyi sorduğunu tespit eder.
        
        Args:
            keywords: Intent'ten gelen anahtar kelimeler
            
        Returns:
            Kategori adı veya None
        """
        query_lower = " ".join(keywords).lower() if keywords else ""
        
        category_priority = [
            ("cisco switch", "Cisco Switch Komutları"),
            ("huawei switch", "Huawei Switch Komutları"),
            ("cisco", "Cisco Switch Komutları"),
            ("huawei", "Huawei Switch Komutları"),
            ("ape", "APE Komutları"),
            ("upe", "UPE Komutları"),
            ("mdu", "MDU Switch Komutları"),
        ]
        
        for keyword, cat_name in category_priority:
            if keyword in query_lower:
                return cat_name
        
        return None
    
    def analyze_intent(self, query: str) -> IntentResult:
        """
        Kullanıcı sorusunun tipini analiz eder.
        
        Returns:
            IntentResult: Soru tipi, güven skoru ve önerilen n_results
        """
        query_lower = query.lower()
        
        # Liste talebi kontrolü
        list_matches = sum(1 for p in self.LIST_PATTERNS if re.search(p, query_lower))
        if list_matches >= 1:
            keywords = [m.group() for p in self.LIST_PATTERNS 
                       for m in [re.search(p, query_lower)] if m]
            return IntentResult(
                intent_type=IntentType.LIST_REQUEST,
                confidence=min(0.5 + list_matches * 0.2, 1.0),
                suggested_n_results=30,  # Liste için çok daha fazla sonuç
                keywords=keywords,
                reasoning="Liste talep eden anahtar kelimeler tespit edildi"
            )
        
        # Adım adım çözüm kontrolü
        howto_matches = sum(1 for p in self.HOWTO_PATTERNS if re.search(p, query_lower))
        if howto_matches >= 1:
            return IntentResult(
                intent_type=IntentType.HOW_TO,
                confidence=min(0.5 + howto_matches * 0.2, 1.0),
                suggested_n_results=10,
                reasoning="Adım adım çözüm talep edildi"
            )
        
        # Sorun giderme kontrolü
        trouble_matches = sum(1 for p in self.TROUBLESHOOT_PATTERNS if re.search(p, query_lower))
        if trouble_matches >= 1:
            return IntentResult(
                intent_type=IntentType.TROUBLESHOOT,
                confidence=min(0.5 + trouble_matches * 0.2, 1.0),
                suggested_n_results=15,
                reasoning="Sorun giderme talebi tespit edildi"
            )
        
        # Tekil cevap kontrolü
        single_matches = sum(1 for p in self.SINGLE_PATTERNS if re.search(p, query_lower))
        if single_matches >= 1:
            return IntentResult(
                intent_type=IntentType.SINGLE_ANSWER,
                confidence=min(0.5 + single_matches * 0.2, 1.0),
                suggested_n_results=5,
                reasoning="Tekil cevap talebi tespit edildi"
            )
        
        # Genel sorgu
        return IntentResult(
            intent_type=IntentType.GENERAL,
            confidence=0.5,
            suggested_n_results=10,
            reasoning="Genel sorgu - varsayılan ayarlar kullanılıyor"
        )
    
    # ========================================
    # 2. Expanded Retrieval
    # ========================================
    
    def expanded_retrieval(
        self, 
        query: str, 
        intent: IntentResult, 
        user_id: int
    ) -> List[Dict[str, Any]]:
        """
        Intent'e göre genişletilmiş RAG araması yapar.
        
        Liste talepleri için daha fazla sonuç getirir ve
        aynı dosyadan gelen sonuçları gruplar.
        """
        from app.core.rag import search_knowledge_base
        
        n_results = intent.suggested_n_results
        # 🔧 v2.33.2: Eşikler düşürüldü - PDF dokümanları için embedding kalitesi daha düşük olabiliyor
        min_score = 0.25 if intent.intent_type == IntentType.LIST_REQUEST else 0.30
        
        # 🆕 v2.28.0: Liste sorguları için diversity filter'ı kaldır
        max_per_file = None if intent.intent_type == IntentType.LIST_REQUEST else 2
        
        log_system_event(
            "INFO", 
            f"Deep Think: Expanded retrieval - n={n_results}, min_score={min_score}, max_per_file={max_per_file}", 
            "deep_think"
        )
        
        # RAG araması
        rag_response = search_knowledge_base(
            query, 
            n_results=n_results, 
            min_score=min_score, 
            user_id=user_id,
            max_per_file=max_per_file
        )
        
        if not rag_response.has_results:
            return []
        
        # Sonuçları dict listesine çevir
        results = []
        for r in rag_response.results:
            results.append({
                "content": r.content,
                "source_file": r.source_file,
                "score": r.score,
                "metadata": r.metadata  # 🆕 v2.29.2: Sheet name vb.
            })
        
        # Liste talebi ise aynı dosyadan gelen sonuçları grupla
        if intent.intent_type == IntentType.LIST_REQUEST:
            results = self._group_by_file(results)
        
        log_system_event(
            "INFO", 
            f"Deep Think: {len(results)} sonuç bulundu", 
            "deep_think"
        )
        
        return results
    
    def _group_by_file(self, results: List[Dict]) -> List[Dict]:
        """Aynı dosyadan gelen sonuçları gruplar ve sıralar."""
        # Dosya bazlı gruplama
        file_groups: Dict[str, List[Dict]] = {}
        
        for r in results:
            source = r.get("source_file", "unknown")
            if source not in file_groups:
                file_groups[source] = []
            file_groups[source].append(r)
        
        # Her grup içinde skor'a göre sırala
        for source in file_groups:
            file_groups[source].sort(key=lambda x: x.get("score", 0), reverse=True)
        
        # Grupları birleştir (en çok sonuç olan dosya önce)
        sorted_groups = sorted(
            file_groups.items(), 
            key=lambda x: len(x[1]), 
            reverse=True
        )
        
        grouped_results = []
        for source, group in sorted_groups:
            grouped_results.extend(group)
        
        return grouped_results
    
    # ========================================
    # 3. LLM Synthesis
    # ========================================
    
    # Maximum context karakter sayısı — üzerinde chunked synthesis devreye girer
    MAX_CONTEXT_CHARS = 12000  # ~3000 token (güvenli sınır)
    
    def synthesize_response(
        self, 
        query: str, 
        rag_results: List[Dict], 
        intent: IntentResult
    ) -> str:
        """
        RAG sonuçlarını LLM ile sentezler.
        
        Intent tipine göre farklı formatlar kullanır:
        - LIST_REQUEST: Numaralı liste
        - HOW_TO: Adım adım talimatlar
        - SINGLE_ANSWER: Kısa ve öz cevap
        - TROUBLESHOOT: Sorun-Çözüm formatı
        
        v2.38.0: Uzun context için parçalı LLM sorgulama desteği.
        """
        if not rag_results:
            return "Üzgünüm, bilgi tabanında bu konuyla ilgili bilgi bulunamadı."
        
        # RAG içeriklerini hazırla
        context = self._prepare_context(rag_results, intent)
        
        # Context uzunluğuna göre tek veya parçalı synthesis
        if len(context) <= self.MAX_CONTEXT_CHARS:
            return self._single_synthesis(query, context, len(rag_results), intent, rag_results)
        else:
            log_system_event(
                "INFO", 
                f"Deep Think: Context çok uzun ({len(context)} karakter), parçalı synthesis", 
                "deep_think"
            )
            return self._chunked_synthesis(query, context, len(rag_results), intent, rag_results)
    
    def _single_synthesis(
        self, query: str, context: str, result_count: int, intent: IntentResult,
        rag_results: List[Dict] = None
    ) -> str:
        """Tek LLM çağrısı ile synthesis yapar."""
        format_instruction = self._get_format_instruction(intent)
        system_prompt = self.synthesis_prompt
        
        user_message = f"""SORU:
{query}

---
BİLGİ TABANI İÇERİĞİ ({result_count} sonuç):
{context}
---

{format_instruction}"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        try:
            response = call_llm_api(messages)
            log_system_event("INFO", "Deep Think: LLM synthesis tamamlandı", "deep_think")
            cleaned = self._clean_prompt_leak(response.strip())
            return self._postprocess_llm_response(cleaned, intent)
        except (LLMConnectionError, LLMConfigError) as e:
            log_error(f"Deep Think LLM hatası: {e}", "deep_think")
            return self._fallback_response(rag_results or [], intent)
    
    def _chunked_synthesis(
        self, query: str, context: str, result_count: int, intent: IntentResult,
        rag_results: List[Dict] = None
    ) -> str:
        """
        Uzun context için parçalı LLM synthesis.
        
        1. Context'i MAX_CONTEXT_CHARS boyutunda parçalara böl
        2. Her parça için ayrı LLM çağrısı yap
        3. Parça yanıtlarını birleştirme LLM çağrısı ile sentezle
        """
        # Context'i satır bazında böl (chunk ortasından kesmemek için)
        lines = context.split("\n")
        chunks = []
        current_chunk = []
        current_len = 0
        
        for line in lines:
            line_len = len(line) + 1  # +1 for newline
            if current_len + line_len > self.MAX_CONTEXT_CHARS and current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_len = line_len
            else:
                current_chunk.append(line)
                current_len += line_len
        
        if current_chunk:
            chunks.append("\n".join(current_chunk))
        
        # Her chunk için LLM çağrısı
        partial_responses = []
        for idx, chunk in enumerate(chunks):
            try:
                part_msg = f"""SORU:
{query}

---
BİLGİ TABANI İÇERİĞİ (Parça {idx + 1}/{len(chunks)}):
{chunk}
---

Bu parçadaki bilgileri kullanarak soruyu yanıtla. Birden fazla parça olduğu için sadece bu parça ile ilgili bilgileri ver."""

                messages = [
                    {"role": "system", "content": self.synthesis_prompt},
                    {"role": "user", "content": part_msg}
                ]
                response = call_llm_api(messages)
                if response and response.strip():
                    partial_responses.append(response.strip())
            except (LLMConnectionError, LLMConfigError) as e:
                log_error(f"Deep Think chunk {idx + 1} hatası: {e}", "deep_think")
        
        if not partial_responses:
            return self._fallback_response(rag_results or [], intent)
        
        # Tek parça döndüyse birleştirme gerekmez
        if len(partial_responses) == 1:
            cleaned = self._clean_prompt_leak(partial_responses[0])
            return self._postprocess_llm_response(cleaned, intent)
        
        # Birleştirme LLM çağrısı
        format_instruction = self._get_format_instruction(intent)
        combined = "\n\n---\n\n".join(
            f"[Parça {i+1}]\n{resp}" for i, resp in enumerate(partial_responses)
        )
        
        merge_msg = f"""SORU:
{query}

Aşağıda aynı soruya farklı bilgi parçalarından verilen yanıtlar var. 
Bunları TEK, TUTARLI ve KAPSAMLI bir yanıt olarak birleştir. 
Tekrarları kaldır ama hiçbir bilgiyi kaybetme.

{combined}

{format_instruction}"""

        try:
            messages = [
                {"role": "system", "content": self.synthesis_prompt},
                {"role": "user", "content": merge_msg}
            ]
            merged = call_llm_api(messages)
            log_system_event(
                "INFO", 
                f"Deep Think: Parçalı synthesis tamamlandı ({len(chunks)} parça birleştirildi)", 
                "deep_think"
            )
            cleaned = self._clean_prompt_leak(merged.strip())
            return self._postprocess_llm_response(cleaned, intent)
        except (LLMConnectionError, LLMConfigError) as e:
            log_error(f"Deep Think merge hatası: {e}", "deep_think")
            # Merge başarısız olursa ilk parça yanıtını döndür
            cleaned = self._clean_prompt_leak(partial_responses[0])
            return self._postprocess_llm_response(cleaned, intent)
    
    def _prepare_context(self, results: List[Dict], intent: IntentResult) -> str:
        """RAG sonuçlarını LLM için hazırlar (heading bilgisi dahil)."""
        context_parts = []
        
        for i, r in enumerate(results, 1):
            source = r.get("source_file", "Bilinmeyen Kaynak")
            content = r.get("content", "").strip()
            score = r.get("score", 0)
            
            # Metadata'dan heading bilgisini çıkar
            meta = r.get("metadata", {})
            if isinstance(meta, str):
                try:
                    import json as _j
                    meta = _j.loads(meta)
                except (ValueError, TypeError):
                    meta = {}
            heading = meta.get("heading", "") if isinstance(meta, dict) else ""
            
            # Heading bilgisini LLM context'e dahil et
            header = f"[{i}] Kaynak: {source}"
            if heading:
                header += f" | Bölüm: {heading}"
            header += f" (Skor: {score:.2f})"
            
            context_parts.append(header)
            context_parts.append(content)
            context_parts.append("")
        
        return "\n".join(context_parts)
    
    # ========================================
    # Format & Postprocess → deep_think/formatting.py (v2.30.1)
    # ========================================
    # Mixin'den gelir: _get_format_instruction, _postprocess_llm_response, _parse_rag_results

    
    # ========================================
    # Fallback → deep_think/fallback.py (v2.30.1)
    # ========================================
    # Mixin'den gelir: _fallback_response, _score_to_bar, _next_category_response

    
    # ========================================
    # 4. Main Pipeline
    # ========================================
    
    def process(self, query: str, user_id: int) -> DeepThinkResult:
        """
        Deep Think ana pipeline'ı.
        
        1. Intent Detection
        2. Expanded Retrieval
        3. LLM Synthesis
        
        🚀 v2.32.0: Response cache ile tekrar sorgularda ~%90 hız artışı
        """
        import time
        import re as regex_mod
        import hashlib
        start_time = time.time()
        
        # 🆕 v2.29.13: "Sonraki kategori[N]:" prefix kontrolü
        next_category_match = regex_mod.match(r'sonraki kategori\[(\d+)\]:\s*(.+)', query, regex_mod.IGNORECASE)
        category_index = None
        if next_category_match:
            category_index = int(next_category_match.group(1))
            query = next_category_match.group(2).strip()
        
        # 🚀 v2.32.0: Deep Think Response Cache
        # Sonraki kategori sorguları cache'lenmez (her seferinde farklı sonuç)
        from app.core.cache import cache_service
        cache_key = None
        if category_index is None:
            cache_key = f"dt:{hashlib.md5(f'{query.lower().strip()}:{user_id}'.encode()).hexdigest()}"
            cached = cache_service.deep_think.get(cache_key)
            if cached is not None:
                elapsed_ms = (time.time() - start_time) * 1000
                log_system_event(
                    "DEBUG", 
                    f"Deep Think CACHE HIT: '{query[:30]}' - {elapsed_ms:.0f}ms", 
                    "deep_think"
                )
                return cached
        
        # 🆕 v2.51.0: Tier 1 — Learned Q&A (semantik eşleşme, ~100ms)
        if category_index is None:
            try:
                from app.services.learned_qa_service import get_learned_qa_service
                qa_match = get_learned_qa_service().search(query, user_id)
                if qa_match:
                    elapsed_ms = (time.time() - start_time) * 1000
                    log_system_event(
                        "INFO",
                        f"Learned QA HIT: score={qa_match['score']:.2f}, {elapsed_ms:.0f}ms",
                        "deep_think"
                    )
                    result = DeepThinkResult(
                        synthesized_response=qa_match["answer"],
                        sources=[qa_match.get("source_file", "")] if qa_match.get("source_file") else [],
                        intent=self.analyze_intent(query),
                        rag_result_count=1,
                        processing_time_ms=elapsed_ms,
                        best_score=qa_match["score"],
                        image_ids=[],
                        heading_images={}
                    )
                    # Cache'e de kaydet (sonraki sorguda Tier 0'dan gelsin)
                    if cache_key is not None:
                        cache_service.deep_think.set(cache_key, result)
                    return result
            except Exception as qa_err:
                log_system_event("DEBUG", f"Learned QA check hatası: {qa_err}", "deep_think")
        
        log_system_event("INFO", f"Deep Think: Pipeline başlatıldı - '{query[:50]}...'", "deep_think")
        
        # 1. Intent Detection
        intent = self.analyze_intent(query)
        log_system_event(
            "INFO", 
            f"Deep Think: Intent={intent.intent_type.value}, n_results={intent.suggested_n_results}", 
            "deep_think"
        )
        
        # 2. Expanded Retrieval
        rag_results = self.expanded_retrieval(query, intent, user_id)
        
        # 🆕 v2.50.0: CatBoost Direct Answer — Yüksek güvenirlikte LLM bypass
        if rag_results and category_index is None:
            best = rag_results[0]
            best_combined = best.get("combined_score", best.get("score", 0))
            best_content = best.get("content", "")
            if best_combined >= 0.75 and len(best_content) >= 80:
                log_system_event(
                    "INFO",
                    f"CatBoost BYPASS: score={best_combined:.2f}, LLM atlandı",
                    "deep_think"
                )
                synthesized = best_content
            else:
                synthesized = self.synthesize_response(query, rag_results, intent)
        elif category_index is not None:
            synthesized = self._next_category_response(rag_results, intent, category_index)
        else:
            synthesized = self.synthesize_response(query, rag_results, intent)
        
        # Kaynak dosyaları topla
        # 🔧 v2.33.2: Sonuç yokken boş sources döndür (sahte kaynak gösterimini önle)
        sources = list(set(r.get("source_file", "") for r in rag_results if r.get("source_file"))) if rag_results else []
        
        # 🆕 v2.45.1: Görsel ID'lerini kaynak dosya ilişkisine dayalı topla
        # ────────────────────────────────────────────────────────────
        # DB İlişkisi: rag_chunks.file_id → uploaded_files ← document_images.file_id
        # Sadece cevabı veren asıl (primary) kaynak dosyanın görsellerini al.
        # ────────────────────────────────────────────────────────────
        heading_image_map = {}  # heading → [image_id, ...]
        all_image_ids = []
        seen_ids = set()
        
        # 1) En yüksek skorlu kaynak dosyayı belirle (primary source)
        primary_source = None
        best_score = 0.0
        for r in rag_results:
            score = r.get("score", 0)
            if score > best_score:
                best_score = score
                primary_source = r.get("source_file", "")
        
        for r in rag_results:
            # 🔧 v2.45.1: Sadece primary source dosyasından görsel al
            if r.get("source_file", "") != primary_source:
                continue
            
            meta = r.get("metadata")
            if isinstance(meta, str):
                try:
                    import json as _json
                    meta = _json.loads(meta)
                except (ValueError, TypeError):
                    meta = {}
            
            if not isinstance(meta, dict):
                continue
            
            ids = meta.get("image_ids", [])
            if not ids or not isinstance(ids, list):
                continue
            
            heading = meta.get("heading", "").strip()
            if not heading:
                heading = "__no_heading__"
            
            for img_id in ids:
                if isinstance(img_id, int) and img_id not in seen_ids:
                    seen_ids.add(img_id)
                    heading_image_map.setdefault(heading, []).append(img_id)
                    all_image_ids.append(img_id)
        
        if primary_source:
            log_system_event(
                "DEBUG",
                f"Deep Think: Görseller primary source'tan alındı: '{primary_source}' "
                f"(skor: {best_score:.2f}, {len(all_image_ids)} görsel)",
                "deep_think"
            )
        
        # Max 8 görsel limiti (heading bazlı sırayla)
        unique_image_ids = all_image_ids[:8]
        
        elapsed_ms = (time.time() - start_time) * 1000
        log_system_event(
            "INFO", 
            f"Deep Think: Pipeline tamamlandı - {elapsed_ms:.0f}ms, {len(rag_results)} sonuç, {len(unique_image_ids)} görsel", 
            "deep_think"
        )
        
        result = DeepThinkResult(
            synthesized_response=synthesized,
            sources=sources,
            intent=intent,
            rag_result_count=len(rag_results),
            processing_time_ms=elapsed_ms,
            best_score=best_score,  # 🆕 v2.49.0: En iyi RAG skoru
            image_ids=unique_image_ids,
            heading_images=heading_image_map  # 🆕 v2.37.1: Heading → image_ids
        )
        
        # 🚀 v2.32.0: Sonucu cache'e kaydet (TTL: 3600 sn = 1 saat)
        if cache_key is not None:
            cache_service.deep_think.set(cache_key, result)
            log_system_event("DEBUG", f"Deep Think CACHE SET: '{query[:30]}'", "deep_think")
        
        return result
    
    # ========================================
    # 5. Streaming Pipeline (v2.50.0)
    # ========================================
    
    def process_stream(self, query: str, user_id: int):
        """
        🆕 v2.50.0: Deep Think streaming pipeline.
        
        Phase 1: RAG + CatBoost (~3s) — batch olarak yapılır
        Phase 2: LLM Synthesis — token token yield edilir
        
        Yields:
            dict: {
                "type": "rag_complete" | "token" | "status" | "cached" | "done",
                "data": ...
            }
        """
        import time
        import hashlib
        start_time = time.time()
        
        # Cache kontrolü — cache hit varsa streaming gereksiz
        from app.core.cache import cache_service
        cache_key = f"dt:{hashlib.md5(f'{query.lower().strip()}:{user_id}'.encode()).hexdigest()}"
        cached = cache_service.deep_think.get(cache_key)
        if cached is not None:
            log_system_event(
                "DEBUG", 
                f"Deep Think STREAM CACHE HIT: '{query[:30]}' - {(time.time() - start_time) * 1000:.0f}ms", 
                "deep_think"
            )
            yield {"type": "cached", "data": {
                "content": cached.synthesized_response,
                "intent": cached.intent.intent_type.value,
                "sources": cached.sources,
                "best_score": getattr(cached, 'best_score', 0.0),
                "image_ids": getattr(cached, 'image_ids', []),
                "heading_images": getattr(cached, 'heading_images', {}),
                "rag_result_count": cached.rag_result_count,
                "processing_time_ms": (time.time() - start_time) * 1000
            }}
            return
        
        # 🆕 v2.51.0: Tier 1 — Learned Q&A (semantik eşleşme, ~100ms)
        try:
            from app.services.learned_qa_service import get_learned_qa_service
            qa_match = get_learned_qa_service().search(query, user_id)
            if qa_match:
                elapsed_ms = (time.time() - start_time) * 1000
                log_system_event(
                    "INFO",
                    f"Learned QA HIT (stream): score={qa_match['score']:.2f}, {elapsed_ms:.0f}ms",
                    "deep_think"
                )
                # Cache'e kaydet (mevcut cache_key kullan)
                if cache_key is not None:
                    result = DeepThinkResult(
                        synthesized_response=qa_match["answer"],
                        sources=[qa_match.get("source_file", "")] if qa_match.get("source_file") else [],
                        intent=self.analyze_intent(query),
                        rag_result_count=1,
                        processing_time_ms=elapsed_ms,
                        best_score=qa_match["score"],
                        image_ids=[],
                        heading_images={}
                    )
                    cache_service.deep_think.set(cache_key, result)
                
                yield {"type": "done", "data": {
                    "content": qa_match["answer"],
                    "metadata": {
                        "rag_result_count": 1,
                        "best_score": qa_match["score"],
                        "deep_think": True,
                        "learned_qa": True,
                        "sources": [qa_match.get("source_file", "")] if qa_match.get("source_file") else []
                    }
                }}
                return
        except Exception as qa_err:
            log_system_event("DEBUG", f"Learned QA check hatası: {qa_err}", "deep_think")
        
        log_system_event("INFO", f"Deep Think STREAM: Pipeline başlatıldı - '{query[:50]}...'", "deep_think")
        
        # 1. Intent Detection (anlık)
        intent = self.analyze_intent(query)
        
        # 2. Expanded Retrieval — RAG + CatBoost (batch, ~3s)
        rag_results = self.expanded_retrieval(query, intent, user_id)
        
        # RAG tamamlandı sinyali gönder
        yield {"type": "rag_complete", "data": {
            "intent": intent.intent_type.value,
            "result_count": len(rag_results),
            "elapsed_ms": (time.time() - start_time) * 1000
        }}
        
        if not rag_results:
            yield {"type": "done", "data": {
                "content": "Üzgünüm, bilgi tabanında bu konuyla ilgili bilgi bulunamadı.",
                "metadata": {"rag_result_count": 0, "best_score": 0, "deep_think": True}
            }}
            return
        
        # 🆕 v2.50.0: CatBoost Direct Answer — Yüksek güvenirlikte LLM bypass
        # v2.52.1: Minimum içerik uzunluğu 80 → 300 karakter.
        # Kısa chunk'lar (Excel komut tabloları, 94-116 char) kullanıcıya yeterli
        # bilgi sağlamıyor. Bu durumda LLM sentezleme yapılmalı.
        best = rag_results[0]
        best_combined = best.get("combined_score", best.get("score", 0))
        best_content = best.get("content", "")
        if best_combined >= 0.75 and len(best_content) >= 300:
            log_system_event(
                "INFO",
                f"CatBoost BYPASS (stream): score={best_combined:.2f}, len={len(best_content)}, LLM atlandı",
                "deep_think"
            )
            sources = list(set(r.get("source_file", "") for r in rag_results if r.get("source_file")))
            # Post-process uygula
            final_content = self._postprocess_llm_response(best_content, intent)
            final_content = self._clean_prompt_leak(final_content)
            
            # Cache'e kaydet (mevcut cache_key kullan)
            if cache_key is not None:
                result = DeepThinkResult(
                    synthesized_response=final_content,
                    sources=sources,
                    intent=intent,
                    rag_result_count=len(rag_results),
                    processing_time_ms=(time.time() - start_time) * 1000,
                    best_score=best_combined,
                    image_ids=[],
                    heading_images={}
                )
                cache_service.deep_think.set(cache_key, result)
            
            yield {"type": "done", "data": {
                "content": final_content,
                "metadata": {
                    "rag_result_count": len(rag_results),
                    "best_score": best_combined,
                    "deep_think": True,
                    "catboost_bypass": True,
                    "can_enhance": True,
                    "original_query": query,
                    "sources": sources
                }
            }}
            return
        
        # 3. LLM Synthesis — STREAMING
        context = self._prepare_context(rag_results, intent)
        format_instruction = self._get_format_instruction(intent)
        system_prompt = self.synthesis_prompt
        
        user_message = f"""SORU:
{query}

---
BİLGİ TABANI İÇERİĞİ ({len(rag_results)} sonuç):
{context}
---

{format_instruction}"""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        full_response = ""
        try:
            from app.core.llm import call_llm_api_stream
            
            # Context uzunluğuna göre tek veya parçalı streaming
            if len(context) <= self.MAX_CONTEXT_CHARS:
                # TEK PARÇA — doğrudan stream
                # v2.52.1: İlk token'ları buffer'la — [NO_MATCH] kontrolü
                # LLM cevabın başına [NO_MATCH] yazarsa streaming'i durdur
                _token_buffer = []
                _buffer_limit = 15  # İlk 15 token yeterli (~"[NO_MATCH] ...")
                _buffer_flushed = False
                
                stream_gen = call_llm_api_stream(messages)
                for token in stream_gen:
                    full_response += token
                    
                    if not _buffer_flushed:
                        _token_buffer.append(token)
                        buffered_text = "".join(_token_buffer)
                        
                        # [NO_MATCH] tespit edildi → streaming'i durdur
                        if "[NO_MATCH]" in buffered_text:
                            # Kalan token'ları da aynı generator'dan topla
                            for remaining in stream_gen:
                                full_response += remaining
                            break
                        
                        # Buffer doldu, [NO_MATCH] yok → birikmiş token'ları gönder
                        if len(_token_buffer) >= _buffer_limit:
                            for t in _token_buffer:
                                yield {"type": "token", "data": t}
                            _token_buffer = []
                            _buffer_flushed = True
                    else:
                        yield {"type": "token", "data": token}
            else:
                # PARÇALI (CHUNKED) STREAMING
                yield {"type": "status", "data": "Kapsamlı içerik tespit edildi, parçalar halinde işleniyor..."}
                
                lines = context.split("\n")
                chunks = []
                current_chunk = []
                current_len = 0
                for ln in lines:
                    ln_len = len(ln) + 1
                    if current_len + ln_len > self.MAX_CONTEXT_CHARS and current_chunk:
                        chunks.append("\n".join(current_chunk))
                        current_chunk = [ln]
                        current_len = ln_len
                    else:
                        current_chunk.append(ln)
                        current_len += ln_len
                if current_chunk:
                    chunks.append("\n".join(current_chunk))
                
                # Her chunk için batch LLM
                partial_responses = []
                for idx, chunk in enumerate(chunks):
                    yield {"type": "status", "data": f"Parça {idx+1}/{len(chunks)} işleniyor..."}
                    part_msg = f"""SORU:\n{query}\n\n---\nBİLGİ TABANI İÇERİĞİ (Parça {idx+1}/{len(chunks)}):\n{chunk}\n---\n\nBu parçadaki bilgileri kullanarak soruyu yanıtla."""
                    try:
                        resp = call_llm_api(messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": part_msg}
                        ])
                        if resp and resp.strip():
                            partial_responses.append(resp.strip())
                    except Exception:
                        pass
                
                if not partial_responses:
                    fallback = self._fallback_response(rag_results, intent)
                    yield {"type": "done", "data": {"content": fallback}}
                    return
                
                if len(partial_responses) == 1:
                    # Tek parça yeterli — char-by-char stream olarak gönder
                    for char in partial_responses[0]:
                        full_response += char
                        yield {"type": "token", "data": char}
                else:
                    # BİRLEŞTİRME LLM — streaming olarak
                    yield {"type": "status", "data": "Parçalar birleştiriliyor..."}
                    combined = "\n\n---\n\n".join(
                        f"[Parça {i+1}]\n{resp}" for i, resp in enumerate(partial_responses)
                    )
                    merge_msg = f"""SORU:\n{query}\n\nAşağıda aynı soruya farklı bilgi parçalarından verilen yanıtlar var.\nBunları TEK, TUTARLI ve KAPSAMLI bir yanıt olarak birleştir.\nTekrarları kaldır ama hiçbir bilgiyi kaybetme.\n\n{combined}\n\n{format_instruction}"""
                    
                    merge_messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": merge_msg}
                    ]
                    for token in call_llm_api_stream(merge_messages):
                        full_response += token
                        yield {"type": "token", "data": token}
                        
        except Exception as e:
            log_error(f"Deep Think stream LLM hatası: {e}", "deep_think")
            fallback = self._fallback_response(rag_results, intent)
            yield {"type": "done", "data": {
                "content": fallback,
                "error": str(e)
            }}
            return
        
        # Post-processing
        cleaned = self._clean_prompt_leak(full_response.strip())
        final_content = self._postprocess_llm_response(cleaned, intent)
        
        # v2.52.1: İlgisizlik kontrolü — [NO_MATCH] token tabanlı (güvenilir)
        # LLM prompt'unda "bilgi yoksa cevabın başına [NO_MATCH] yaz" direktifi var.
        # Önce token kontrol, sonra marker yedek olarak.
        is_irrelevant = "[NO_MATCH]" in final_content
        
        # Token bulunamadıysa marker-based yedek kontrol (eski uyumluluk)
        if not is_irrelevant:
            _irrelevance_markers = [
                "ilişkili değildir", "ilgili değildir", "doğrudan ilişkili değil",
                "ilgili bilgi bulunamadı", "bu konuda bilgi bulunamadı",
                "yer almamaktadır", "açıklayamıyoruz", "açıklayamamaktayız",
                "yanıt veremiyoruz", "bilgi veremiyoruz",
                "bilgi sağlanamamaktadır", "mevcut değildir",
            ]
            content_lower = final_content.lower()
            is_irrelevant = any(marker in content_lower for marker in _irrelevance_markers)
        
        # [NO_MATCH] tokenini final içerikten temizle (kullanıcıya görünmesin)
        if is_irrelevant:
            final_content = final_content.replace("[NO_MATCH]", "").strip()
        
        # Kaynak ve görsel bilgilerini topla (process() mantığının aynısı)
        sources = list(set(r.get("source_file", "") for r in rag_results if r.get("source_file"))) if rag_results else []
        
        heading_image_map = {}
        all_image_ids = []
        seen_ids = set()
        primary_source = None
        best_score = 0.0
        for r in rag_results:
            score = r.get("score", 0)
            if score > best_score:
                best_score = score
                primary_source = r.get("source_file", "")
        
        for r in rag_results:
            if r.get("source_file", "") != primary_source:
                continue
            meta = r.get("metadata")
            if isinstance(meta, str):
                try:
                    import json as _json
                    meta = _json.loads(meta)
                except (ValueError, TypeError):
                    meta = {}
            if not isinstance(meta, dict):
                continue
            ids = meta.get("image_ids", [])
            if not ids or not isinstance(ids, list):
                continue
            heading = meta.get("heading", "").strip()
            if not heading:
                heading = "__no_heading__"
            for img_id in ids:
                if isinstance(img_id, int) and img_id not in seen_ids:
                    seen_ids.add(img_id)
                    heading_image_map.setdefault(heading, []).append(img_id)
                    all_image_ids.append(img_id)
        
        unique_image_ids = all_image_ids[:8]
        elapsed_ms = (time.time() - start_time) * 1000
        
        # v2.52.1: İlgisiz sonuç ise mesajı değiştir
        if is_irrelevant:
            log_system_event(
                "INFO",
                f"Deep Think: İLGİSİZ SONUÇ tespit edildi, best_score={best_score:.2f}",
                "deep_think"
            )
            final_content = (
                "🤔 Bu konuda bilgi tabanında ilgili bir kayıt bulunamadı.\n\n"
                "Farklı anahtar kelimeler kullanarak tekrar deneyebilir veya "
                "Vyra ile sohbet modunda sorabilirsiniz."
            )
        
        # Cache'e kaydet
        result = DeepThinkResult(
            synthesized_response=final_content,
            sources=sources,
            intent=intent,
            rag_result_count=len(rag_results),
            processing_time_ms=elapsed_ms,
            best_score=best_score,
            image_ids=unique_image_ids,
            heading_images=heading_image_map
        )
        cache_service.deep_think.set(cache_key, result)
        
        log_system_event(
            "INFO", 
            f"Deep Think STREAM: Pipeline tamamlandı - {elapsed_ms:.0f}ms, {len(rag_results)} sonuç", 
            "deep_think"
        )
        
        # Done sinyali — final metadata
        yield {"type": "done", "data": {
            "content": final_content,
            "metadata": {
                "intent": intent.intent_type.value,
                "sources": sources,
                "best_score": best_score,
                "rag_result_count": len(rag_results),
                "image_ids": unique_image_ids,
                "heading_images": heading_image_map,
                "deep_think": True,
                "processing_time_ms": elapsed_ms,
                "no_relevant_result": is_irrelevant,
                "original_query": query
            }
        }}



# ============================================
# Fallback Prompt
# ============================================

DEEP_THINK_FALLBACK_PROMPT = """Sen VYRA Deep Think, akıllı bilgi sentezleme asistanısın.

GÖREV:
Sana verilen RAG (bilgi tabanı) sonuçlarını analiz et ve kullanıcının sorusuna profesyonel bir yanıt hazırla.

KURALLAR:
1. SADECE verilen bilgi tabanı içeriğini kullan - BİLGİ UYDURMADAN yanıtla
2. Liste istenmişse TÜM öğeleri numaralı listele
3. Adım adım çözüm istenmişse net ve DETAYLI talimatlar ver
4. Alakasız sonuçları filtrele, sadece ilgili olanları kullan
5. Kaynak dosya adlarını belirt
6. Türkçe ve profesyonel bir dil kullan
7. Bu talimatları ASLA yanıtına dahil etme - sadece içeriği ver
8. Cevapların YETERLI UZUNLUKTA ve DETAYLI olmasını sağla — bilgi kaybına izin verme
9. Bilgi tabanından gelen içeriği özetlerken anlam bütünlüğünü koru
10. "Bölüm:" bilgisi verilmişse yanıtı ilgili başlıklar altında organize et
11. **KRİTİK:** Eğer verilen bilgi tabanı içerikleri kullanıcının sorusuyla İLGİLİ DEĞİLSE veya soruya yanıt verecek bilgi YOKSA, cevabının EN BAŞINA [NO_MATCH] yaz. Bilgi yoksa uydurma, sadece [NO_MATCH] yaz.

ÇIKTI FORMATI:
📋 YANIT
[Sentezlenmiş, profesyonel ve DETAYLI yanıt]

📚 KAYNAKLAR
• [Dosya adı] - [Kısa açıklama]"""


# ============================================
# Singleton Instance
# ============================================

_deep_think_service: Optional[DeepThinkService] = None

def get_deep_think_service() -> DeepThinkService:
    """Deep Think servis singleton'ı döndürür."""
    global _deep_think_service
    if _deep_think_service is None:
        _deep_think_service = DeepThinkService()
    return _deep_think_service
