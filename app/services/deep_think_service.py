"""
VYRA L1 Support API - Deep Think Service
=========================================
RAG sonuçlarını LLM ile akıllıca sentezleyerek profesyonel yanıtlar üretir.

v3.1.0: Sorgu zamanı halüsinasyon doğrulaması eklendi

Özellikler:
- Intent Detection: Soru tipi analizi (liste, tekil, adım adım)
- Expanded Retrieval: Intent'e göre dinamik n_results
- LLM Synthesis: Tüm sonuçları profesyonel formatta birleştirme
- Citation: Kaynak dosya ve chunk referansları
- 🛡️ Hallucination Guard: Sentez cevaplarının kaynak sadakati doğrulaması
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional, Generator
import re

from app.core.config import settings
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
        user_id: int,
        skip_db_knowledge: bool = False
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
        
        # 🆕 v2.53.1: Kısa/anlamsız sorgularda eşik yükselt
        meaningful_chars = len(query.strip().replace('.', '').replace('?', '').replace(' ', ''))
        if meaningful_chars < 8:
            min_score = max(min_score, 0.45)
            log_system_event(
                "INFO",
                f"Deep Think: Kısa sorgu tespit ({meaningful_chars} harf) → min_score={min_score}",
                "deep_think"
            )
        
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
        
        results = []
        if rag_response.has_results:
            # Sonuçları dict listesine çevir
            for r in rag_response.results:
                results.append({
                    "content": r.content,
                    "source_file": r.source_file,
                    "score": r.score,
                    "metadata": r.metadata  # 🆕 v2.29.2: Sheet name vb.
                })
                
        # 🆕 DB Knowledge (Table ML) Araması
        # Sadece dökümanlardan değil, öğrenilen tablolardan da sonuç getirmesi için.
        # v3.6.0: RAG-only modunda buralar atlanır
        if not skip_db_knowledge:
            try:
                from app.services.ds_learning_service import search_db_knowledge
                db_knowledge_results = search_db_knowledge(query, min_score=max(0.35, min_score - 0.05), max_results=3)
                
                if db_knowledge_results:
                    for db_res in db_knowledge_results:
                        results.append({
                            "content": f"[Veritabanı / Tablo: {db_res['source_name']}]\n{db_res['content']}",
                            "source_file": db_res["source_name"],
                            "score": float(db_res["score"]),
                            "metadata": {"type": "db_knowledge", "content_type": db_res.get("content_type", "")}
                        })
                    log_system_event(
                        "INFO", 
                        f"Deep Think: DB Knowledge üzerinden {len(db_knowledge_results)} sonuç eklendi.", 
                        "deep_think"
                    )
            except Exception as e:
                from app.services.logging_service import log_warning
                log_warning(f"Deep Think DB Knowledge arama hatası: {e}", "deep_think")
            
            
        if not results:
            return []
            
        # Skorlara göre sırala (rag ve db_knowledge karışık)
        results.sort(key=lambda x: x["score"], reverse=True)
        
        # Limit the combined results
        results = results[:n_results]
        
        # Liste talebi ise aynı dosyadan gelen sonuçları grupla
        if intent.intent_type == IntentType.LIST_REQUEST:
            results = self._group_by_file(results)
        
        log_system_event(
            "INFO", 
            f"Deep Think: Toplam {len(results)} karma sonuç bulundu", 
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
    # 🆕 v2.57.0: Hybrid Synthesis
    # ========================================
    
    def _synthesize_hybrid(self, query: str, hybrid_result, intent: 'IntentResult') -> str:
        """
        DB sorgu sonuçlarını kullanıcı dostu yanıta dönüştürür.
        
        Basit sonuçlar (tek satır/tek sütun) doğrudan formatlanır.
        Karmaşık sonuçlar LLM ile sentezlenir.
        
        Args:
            query: Kullanıcı sorusu
            hybrid_result: HybridResult nesnesi
            intent: Intent analiz sonucu
            
        Returns:
            Formatlanmış yanıt metni
        """
        db_data = hybrid_result.db_results
        sql = hybrid_result.sql_executed or ""
        source_db = hybrid_result.source_db or "Veritabanı"
        
        if not db_data:
            if hybrid_result.db_error:
                return (
                    f"❌ Veritabanı sorgusunda bir hata oluştu:\n\n"
                    f"`{hybrid_result.db_error}`\n\n"
                    f"Farklı bir şekilde sormayı deneyebilirsiniz."
                )
            return "Bu sorgu için veritabanında sonuç bulunamadı."
        
        # Basit sonuç: tek satır, tek/az sütun
        if len(db_data) == 1 and len(db_data[0]) <= 3:
            row = db_data[0]
            parts = []
            for col, val in row.items():
                parts.append(f"**{col}**: {val}")
            
            return (
                f"📊 **{source_db}** veritabanından sorgu sonucu:\n\n"
                + "\n".join(parts)
                + f"\n\n`{sql}`"
            )
        
        # Çok satırlı sonuç: tablo formatında göster
        if len(db_data) <= 20:
            # Markdown tablo oluştur
            columns = list(db_data[0].keys())
            
            # Header
            header = "| " + " | ".join(str(c) for c in columns) + " |"
            separator = "| " + " | ".join("---" for _ in columns) + " |"
            
            rows_md = []
            for row in db_data:
                row_vals = []
                for c in columns:
                    val = row.get(c, "")
                    # Uzun değerleri kısalt
                    val_str = str(val) if val is not None else "-"
                    if len(val_str) > 50:
                        val_str = val_str[:47] + "..."
                    row_vals.append(val_str)
                rows_md.append("| " + " | ".join(row_vals) + " |")
            
            table_md = "\n".join([header, separator] + rows_md)
            
            result = (
                f"📊 **{source_db}** veritabanından **{len(db_data)}** kayıt:\n\n"
                f"{table_md}\n\n"
            )
            
            if hybrid_result.sql_executed:
                result += f"🔍 Çalıştırılan sorgu: `{sql}`"
            
            return result
        
        # 20+ satır: özet + LLM sentez
        try:
            import json
            context = json.dumps(db_data[:20], ensure_ascii=False, default=str)
            
            messages = [
                {"role": "system", "content": (
                    "Sen bir veritabanı analisti asistanısın. "
                    "Kullanıcının sorusuna, veritabanından dönen sonuçları "
                    "kullanarak kısa ve net bir yanıt üret. "
                    "Sayısal değerleri vurgula. Markdown formatı kullan."
                )},
                {"role": "user", "content": (
                    f"SORU: {query}\n\n"
                    f"VERİTABANI SONUÇLARI ({len(db_data)} satır, ilk 20 gösteriliyor):\n"
                    f"{context}\n\n"
                    f"SQL: {sql}"
                )},
            ]
            
            response = call_llm_api(messages)
            return response.strip()
            
        except Exception as e:
            log_warning(f"Hybrid LLM sentez hatası: {e}", "deep_think")
            # Fallback: ham veri göster
            return (
                f"📊 **{source_db}** veritabanından **{len(db_data)}** kayıt bulundu.\n\n"
                f"🔍 Çalıştırılan sorgu: `{sql}`"
            )

    # ========================================
    # 🆕 v2.58.0: Answer Merger (HYBRID intent)
    # ========================================
    
    def _merge_hybrid_answer(
        self, query: str, hybrid_result, rag_results: list, intent: 'IntentResult'
    ) -> str:
        """
        DB sorgu sonuçları ve RAG doküman sonuçlarını LLM ile birleştirir.
        
        HYBRID intent'te çağrılır — hem veritabanı verileri hem de 
        doküman bilgileri kullanılarak kapsamlı bir yanıt üretilir.
        
        Args:
            query: Kullanıcı sorusu
            hybrid_result: HybridResult nesnesi (DB verileri)
            rag_results: RAG doküman sonuçları
            intent: Intent analiz sonucu
            
        Returns:
            Birleştirilmiş yanıt metni
        """
        import json
        
        db_data = hybrid_result.db_results
        sql = hybrid_result.sql_executed or ""
        source_db = hybrid_result.source_db or "Veritabanı"
        
        # DB context hazırla
        db_context = json.dumps(
            db_data[:15], ensure_ascii=False, default=str
        ) if db_data else "Veri bulunamadı"
        
        # RAG context hazırla
        rag_context_parts = []
        for i, r in enumerate(rag_results[:5], 1):
            content = r.get("content", "")[:300]
            source = r.get("source_file", "")
            rag_context_parts.append(f"[{i}] {source}: {content}")
        rag_context = "\n".join(rag_context_parts) if rag_context_parts else "Doküman bulunamadı"
        
        # LLM ile birleştir
        try:
            messages = [
                {"role": "system", "content": (
                    "Sen bir bilgi asistanısın. Kullanıcının sorusuna iki kaynaktan gelen bilgileri "
                    "birleştirerek kapsamlı bir yanıt üret:\n"
                    "1. VERİTABANI: Canlı veriler (sayısal değerler, güncel kayıtlar)\n"
                    "2. DOKÜMAN: Prosedür, açıklama ve referans bilgileri\n\n"
                    "Her iki kaynağı da göz önünde bulundur. Sayısal verileri vurgula. "
                    "Markdown formatı kullan. Kaynakları belirt."
                )},
                {"role": "user", "content": (
                    f"SORU: {query}\n\n"
                    f"📊 VERİTABANI SONUÇLARI ({source_db}, {len(db_data)} kayıt):\n"
                    f"{db_context}\n"
                    f"SQL: {sql}\n\n"
                    f"📄 DOKÜMAN SONUÇLARI ({len(rag_results)} sonuç):\n"
                    f"{rag_context}"
                )},
            ]
            
            response = call_llm_api(messages)
            return response.strip()
            
        except Exception as e:
            log_warning(f"Answer Merger LLM hatası: {e}", "deep_think")
            # Fallback: DB sonuçlarını göster + RAG özetini ekle
            db_part = self._synthesize_hybrid(query, hybrid_result, intent)
            if rag_results:
                rag_part = f"\n\n📄 **İlişkili doküman bilgisi:**\n{rag_results[0].get('content', '')[:200]}..."
                return db_part + rag_part
            return db_part

    # ========================================
    # 🛡️ v3.1.0 → v3.4.0: Sorgu Zamanı Halüsinasyon Doğrulaması
    # ========================================
    # v3.4.0: Eşik sabitleri kaldırıldı — lenient=True parametresi kullanılıyor

    def _validate_synthesis(
        self,
        synthesized: str,
        rag_results: List[Dict],
        query: str,
        intent: 'IntentResult'
    ) -> str:
        """
        🛡️ v3.1.0: LLM sentez cevabını kaynak metne karşı doğrular.

        3 katmanlı kontrol:
        1. Uzunluk oranı (cevap/kaynak)
        2. Anahtar kelime temellendirme (grounding)
        3. Semantik sadakat (faithfulness)

        Başarısız olursa fallback cevap döner.

        Args:
            synthesized: LLM sentez cevabı
            rag_results: RAG kaynak sonuçları
            query: Kullanıcı sorusu
            intent: Intent analiz sonucu

        Returns:
            Doğrulanmış cevap veya fallback cevap
        """
        if not synthesized or not rag_results:
            return synthesized

        try:
            from app.services.learned_qa_service import get_learned_qa_service
            qa_service = get_learned_qa_service()

            # RAG kaynak metinlerini birleştir (doğrulama için)
            # v3.4.0 FIX: 400→2000 char — LLM tüm chunk'ı görüp sentezliyor
            source_texts = " ".join(
                r.get("content", "")[:2000] for r in rag_results[:3]
            )

            # v3.4.0 FIX: Eşik 500→1500 — kısa source'larda yanlış pozitif
            source_len = len(source_texts.strip())
            if source_len < 1500:
                log_system_event(
                    "DEBUG",
                    f"Hallucination check SKIPPED: source_len={source_len} < 1500",
                    "deep_think"
                )
                return synthesized

            # v3.4.0 FIX: Thread-unsafe eşik override kaldırıldı
            # lenient=True ile sorgu zamanı için düşük eşikler kullanılıyor
            validation = qa_service._validate_answer(
                answer=synthesized,
                source_text=source_texts,
                question=query,
                lenient=True
            )

            if not validation["passed"]:
                log_warning(
                    f"Deep Think HALLUCINATION blocked: "
                    f"reason={validation['reason']}, "
                    f"faithfulness={validation.get('faithfulness', 0):.2f}, "
                    f"grounding={validation.get('grounding', 0):.1%}, "
                    f"length_ratio={validation.get('length_ratio', 0):.1f}x | "
                    f"query='{query[:50]}'",
                    "deep_think"
                )
                # Fallback: RAG chunk'ını doğrudan göster
                return self._fallback_response(rag_results, intent)

            log_system_event(
                "DEBUG",
                f"Hallucination check PASSED: "
                f"grounding={validation.get('grounding', 0):.1%}, "
                f"faithfulness={validation.get('faithfulness', 0):.2f}",
                "deep_think"
            )
            return synthesized

        except Exception as e:
            log_system_event(
                "DEBUG",
                f"Hallucination check error (fail-open): {e}",
                "deep_think"
            )
            return synthesized  # Fail-open: hata durumunda cevabı engelleme

    # ========================================
    # 4. Main Pipeline
    # ========================================
    
    def _is_short_meaningless_query(self, query: str) -> bool:
        """
        🆕 v2.53.1: Kısa/anlamsız sorgu tespiti.
        Cache kontrolünden ÖNCE çağrılarak eski yanlış cache sonuçlarının
        dönmesi engellenir.
        
        Kriterler:
        - Tek kelimelik sorgular
        - Toplam anlamlı karakter sayısı < 10
        - Kesik kelime tespiti (nokta ile biten kısa parçalar: "bilg.", "yet.")
        """
        stripped = query.strip()
        
        # Noktalama temizle
        cleaned = stripped.rstrip('.?!,;:')
        
        # Kelimelere ayır (len >= 2)
        words = [w for w in cleaned.split() if len(w) >= 2]
        
        # Tek kelime veya kelime yok → anlamsız
        if len(words) < 2:
            return True
        
        # Toplam anlamlı karakter sayısı
        total_chars = sum(len(w) for w in words)
        if total_chars < 10:
            return True
        
        # Kesik kelime tespiti: orijinal metinde "." ile biten kelimeler
        # Örnek: "yeterli bilg." → "bilg." kesik kelime
        original_words = stripped.split()
        truncated_count = 0
        for w in original_words:
            # Nokta ile biten ama kısaltma olmayan kelime (2-5 harf + nokta)
            w_clean = w.rstrip('.?!,;:')
            if w.endswith('.') and 2 <= len(w_clean) <= 5 and w_clean.isalpha():
                # Kısaltma olabileceği durumları hariç tut (vb., vs., dr.)
                known_abbreviations = {'vb', 'vs', 'dr', 'mr', 'ms', 'st', 'ave', 'inc'}
                if w_clean.lower() not in known_abbreviations:
                    truncated_count += 1
        
        # Kesik kelime varsa → anlamsız
        if truncated_count > 0:
            return True
        
        return False
    
    def _enrich_learned_qa(self, qa_match: dict, user_id: int = None) -> dict:
        """
        🆕 v3.3.2: Learned QA cevabını kaynak ve görsel bilgisiyle zenginleştirir.
        
        1. source_file varsa → cevap metnine "_Kaynak: [dosya]_" satırı ekler
        2. source_file üzerinden document_images tablosundan görselleri çeker
        3. 🔒 user_id ile org bazlı filtreleme — multi-tenant izolasyon
        
        Returns:
            {"answer": str, "image_ids": list, "heading_images": dict}
        """
        answer = qa_match.get("answer", "")
        source_file = qa_match.get("source_file", "")
        image_ids = []
        heading_images = {}
        
        if source_file:
            # 1. Kaynak bilgisini cevap metnine ekle
            if source_file not in answer:
                answer += f"\n\n_Kaynak: [{source_file}]_"
            
            # 2. Kaynak dosyanın görsellerini DB'den çek (org filtreli)
            try:
                from app.core.db import get_db_context
                with get_db_context() as conn:
                    with conn.cursor() as cur:
                        if user_id:
                            # 🔒 Kullanıcının org'larına ait dosyalardan görselleri çek
                            cur.execute("""
                                SELECT di.id, di.context_heading
                                FROM document_images di
                                JOIN uploaded_files uf ON uf.id = di.file_id
                                WHERE uf.file_name = %s
                                AND (
                                    EXISTS (
                                        SELECT 1 FROM document_organizations doc_org
                                        JOIN user_organizations uo ON uo.org_id = doc_org.org_id
                                        WHERE doc_org.file_id = uf.id
                                        AND uo.user_id = %s
                                    )
                                    OR NOT EXISTS (
                                        SELECT 1 FROM document_organizations doc_org2
                                        WHERE doc_org2.file_id = uf.id
                                    )
                                )
                                ORDER BY di.context_chunk_index ASC
                                LIMIT 8
                            """, (source_file, user_id))
                        else:
                            cur.execute("""
                                SELECT di.id, di.context_heading
                                FROM document_images di
                                JOIN uploaded_files uf ON uf.id = di.file_id
                                WHERE uf.file_name = %s
                                ORDER BY di.context_chunk_index ASC
                                LIMIT 8
                            """, (source_file,))
                        rows = cur.fetchall()
                
                if rows:
                    seen = set()
                    for row in rows:
                        img_id = row["id"] if isinstance(row, dict) else row[0]
                        heading = (row["context_heading"] if isinstance(row, dict) else row[1]) or "__no_heading__"
                        heading = heading.strip() or "__no_heading__"
                        if img_id not in seen:
                            seen.add(img_id)
                            image_ids.append(img_id)
                            heading_images.setdefault(heading, []).append(img_id)
                    
                    log_system_event(
                        "DEBUG",
                        f"Learned QA görseller: {source_file} → {len(image_ids)} görsel (user={user_id})",
                        "deep_think"
                    )
            except Exception as e:
                log_warning(f"Learned QA görsel çekme hatası: {e}", "deep_think")
        
        return {
            "answer": answer,
            "image_ids": image_ids,
            "heading_images": heading_images
        }
    
    def _empty_result(self, query: str) -> DeepThinkResult:
        """Boş sonuç döndürür (anlamsız sorgular için)."""
        return DeepThinkResult(
            synthesized_response=(
                "🤔 Bu konuda bilgi tabanında ilgili bir kayıt bulunamadı.\n\n"
                "Farklı anahtar kelimeler kullanarak tekrar deneyebilir veya "
                "Vyra ile sohbet modunda sorabilirsiniz."
            ),
            sources=[],
            intent=self.analyze_intent(query),
            rag_result_count=0,
            processing_time_ms=0,
            best_score=0.0,
            image_ids=[],
            heading_images={}
        )
    
    def _collect_images_from_rag(self, rag_results: list, max_images: int = 8) -> tuple:
        """
        v3.4.7: RAG chunk metadata'sından görselleri toplar.
        DRY helper — CatBoost BYPASS, Hybrid, LLM Sentez akışlarında ortak kullanılır.
        
        v3.4.7 Issue 8: Sadece primary_source değil, en yüksek skorlu top 3 dosyadan
        görsel toplar — birden fazla dosyadan sonuç geldiğinde görseller kaybolmaz.
        
        Returns:
            (image_ids: list, heading_image_map: dict)
        """
        heading_map = {}
        image_ids = []
        seen = set()
        
        # v3.4.7: Top 3 dosyayı belirle (skor bazlı)
        source_best_score = {}  # source_file → best_score
        for r in rag_results:
            s = r.get("score", 0)
            src = r.get("source_file", "")
            if src and s > source_best_score.get(src, 0):
                source_best_score[src] = s
        
        # En yüksek skorlu top 3 dosya
        top_sources = sorted(source_best_score.keys(), key=lambda x: source_best_score[x], reverse=True)[:3]
        top_sources_set = set(top_sources)
        
        for r in rag_results:
            if r.get("source_file", "") not in top_sources_set:
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
                if isinstance(img_id, int) and img_id not in seen:
                    seen.add(img_id)
                    heading_map.setdefault(heading, []).append(img_id)
                    image_ids.append(img_id)
        # v3.4.8: Runtime fallback — chunk'ta image_ids yoksa
        # document_images tablosundan context_heading eşleşmesiyle getir
        if not image_ids and rag_results:
            _fb_conn = None
            try:
                from app.core.db import get_db_conn
                _fb_conn = get_db_conn()
                _fb_cur = _fb_conn.cursor()
                
                # Chunk'ların heading'lerini ve file_id'lerini topla
                _headings_to_search = []
                _file_ids = set()
                for r in rag_results:
                    if r.get("source_file", "") not in top_sources_set:
                        continue
                    meta = r.get("metadata")
                    if isinstance(meta, str):
                        try:
                            import json as _json2
                            meta = _json2.loads(meta)
                        except (ValueError, TypeError):
                            meta = {}
                    if isinstance(meta, dict):
                        h = (meta.get("heading", "") or "").strip()
                        if h and h not in _headings_to_search:
                            _headings_to_search.append(h)
                    # file_id'yi bul
                    _fid = r.get("file_id")
                    if _fid:
                        _file_ids.add(_fid)
                
                if _file_ids and _headings_to_search:
                    _fid_ph = ','.join(['%s'] * len(_file_ids))
                    _fb_cur.execute(
                        f"""SELECT id, context_heading, next_heading, page_number 
                        FROM document_images 
                        WHERE file_id IN ({_fid_ph}) 
                        ORDER BY image_index LIMIT 50""",
                        list(_file_ids)
                    )
                    _di_rows = _fb_cur.fetchall()
                    
                    for di in _di_rows:
                        di_heading = (di.get("context_heading", "") or "").strip().lower()
                        di_next = (di.get("next_heading", "") or "").strip().lower()
                        if not di_heading:
                            continue
                        for h in _headings_to_search:
                            h_lower = h.lower()
                            # heading_before veya heading_after eşleşmesi
                            matched = (
                                h_lower in di_heading or di_heading in h_lower or
                                (di_next and (h_lower in di_next or di_next in h_lower))
                            )
                            if matched:
                                img_id = di["id"]
                                if img_id not in seen:
                                    seen.add(img_id)
                                    heading_map.setdefault(h, []).append(img_id)
                                    image_ids.append(img_id)
                                break
                
                _fb_cur.close()
            except Exception:
                pass  # Fallback başarısız olursa sessizce devam et
            finally:
                if _fb_conn:
                    try:
                        _fb_conn.close()
                    except Exception:
                        pass
        
        return image_ids[:max_images], heading_map
    
    def process(self, query: str, user_id: int) -> DeepThinkResult:
        """
        Deep Think ana pipeline'ı.
        
        1. Intent Detection
        2. Expanded Retrieval
        3. LLM Synthesis
        
        🚀 v2.32.0: Response cache ile tekrar sorgularda ~%90 hız artışı
        """
        import time
        
        # 🆕 v2.53.1: Kısa/anlamsız sorgu koruması (cache'ten ÖNCE)
        if self._is_short_meaningless_query(query):
            log_system_event("INFO", f"Deep Think: Kısa sorgu reddedildi: '{query}'", "deep_think")
            return self._empty_result(query)
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
        # v3.4.1: RAG cross-validation ile yanlış eşleşme önleme
        _cv_intent = None  # Cross-validation'da hesaplanan intent (tekrar kullanım için)
        if category_index is None:
            try:
                from app.services.learned_qa_service import get_learned_qa_service
                qa_match = get_learned_qa_service().search(query, user_id)
                if qa_match:
                    qa_score = qa_match['score']
                    qa_question = qa_match.get('question', '')
                    
                    # v3.4.1: RAG Cross-Validation — Learned QA cevabı gerçekten doğru kaynaktan mı?
                    _qa_validated = True
                    try:
                        _cv_intent = self.analyze_intent(query)
                        _rag_check = self.expanded_retrieval(query, _cv_intent, user_id)
                        if _rag_check:
                            _top_rag = _rag_check[0]
                            _rag_text = _top_rag.get('content', '')
                            _rag_heading = ''
                            _meta = _top_rag.get('metadata')
                            if isinstance(_meta, dict):
                                _rag_heading = _meta.get('heading', '')
                            elif isinstance(_meta, str):
                                try:
                                    import json as _j
                                    _rag_heading = _j.loads(_meta).get('heading', '')
                                except Exception:
                                    pass
                            
                            # Soru kelimelerini RAG sonuç ile karşılaştır
                            _q_words = set(w.lower() for w in query.split() if len(w) >= 3)
                            _qa_words = set(w.lower() for w in qa_question.split() if len(w) >= 3)
                            _rag_words = set(w.lower() for w in (_rag_text[:500] + ' ' + _rag_heading).split() if len(w) >= 3)
                            
                            _q_in_rag = len(_q_words & _rag_words) / max(len(_q_words), 1)
                            _q_in_qa = len(_q_words & _qa_words) / max(len(_q_words), 1)
                            
                            if _q_in_rag > _q_in_qa and _q_in_qa < 0.6:
                                _qa_validated = False
                                log_system_event(
                                    "WARNING",
                                    f"Learned QA CROSS-VALIDATION FAIL: QA='{qa_question[:50]}' "
                                    f"(q_in_rag={_q_in_rag:.2f} > q_in_qa={_q_in_qa:.2f}), RAG'a devam",
                                    "deep_think"
                                )
                    except Exception as cv_err:
                        log_system_event("DEBUG", f"Learned QA cross-validation hatası: {cv_err}", "deep_think")
                    
                    if _qa_validated:
                        elapsed_ms = (time.time() - start_time) * 1000
                        log_system_event(
                            "INFO",
                            f"Learned QA HIT (validated): score={qa_score:.2f}, {elapsed_ms:.0f}ms",
                            "deep_think"
                        )
                        enriched = self._enrich_learned_qa(qa_match, user_id)
                        result = DeepThinkResult(
                            synthesized_response=enriched["answer"],
                            sources=[qa_match.get("source_file", "")] if qa_match.get("source_file") else [],
                            intent=_cv_intent or self.analyze_intent(query),
                            rag_result_count=1,
                            processing_time_ms=elapsed_ms,
                            best_score=qa_score,
                            image_ids=enriched["image_ids"],
                            heading_images=enriched["heading_images"]
                        )
                        if cache_key is not None:
                            cache_service.deep_think.set(cache_key, result)
                        return result
            except Exception as qa_err:
                log_system_event("DEBUG", f"Learned QA check hatası: {qa_err}", "deep_think")
        
        log_system_event("INFO", f"Deep Think: Pipeline başlatıldı - '{query[:50]}...'", "deep_think")
        
        # 1. Intent Detection (cross-validation'da hesaplandıysa tekrar kullan)
        intent = _cv_intent if _cv_intent else self.analyze_intent(query)
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
                # 🛡️ v3.1.0: Halüsinasyon doğrulaması
                synthesized = self._validate_synthesis(synthesized, rag_results, query, intent)
        elif category_index is not None:
            synthesized = self._next_category_response(rag_results, intent, category_index)
        else:
            synthesized = self.synthesize_response(query, rag_results, intent)
            # 🛡️ v3.1.0: Halüsinasyon doğrulaması
            synthesized = self._validate_synthesis(synthesized, rag_results, query, intent)
        
        # Kaynak dosyaları topla
        # 🔧 v2.33.2: Sonuç yokken boş sources döndür (sahte kaynak gösterimini önle)
        sources = list(set(r.get("source_file", "") for r in rag_results if r.get("source_file"))) if rag_results else []
        
        # v3.4.0: DRY helper ile görsel toplama (inline kod kaldırıldı)
        unique_image_ids, heading_image_map = self._collect_images_from_rag(rag_results) if rag_results else ([], {})
        best_score = max((r.get("score", 0) for r in rag_results), default=0.0) if rag_results else 0.0
        
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
        
        # 🆕 v2.53.1: Kısa/anlamsız sorgu koruması (cache'ten ÖNCE)
        if self._is_short_meaningless_query(query):
            log_system_event("INFO", f"Deep Think STREAM: Kısa sorgu reddedildi: '{query}'", "deep_think")
            yield {"type": "done", "data": {
                "content": (
                    "🤔 Bu konuda bilgi tabanında ilgili bir kayıt bulunamadı.\n\n"
                    "Farklı anahtar kelimeler kullanarak tekrar deneyebilir veya "
                    "Vyra ile sohbet modunda sorabilirsiniz."
                ),
                "metadata": {"rag_result_count": 0, "best_score": 0, "deep_think": True, "short_query_rejected": True}
            }}
            return
        
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
        # v3.4.1: RAG cross-validation ile yanlış eşleşme önleme
        _cv_intent = None  # Cross-validation'da hesaplanan intent (tekrar kullanım için)
        try:
            from app.services.learned_qa_service import get_learned_qa_service
            qa_match = get_learned_qa_service().search(query, user_id)
            if qa_match:
                qa_score = qa_match['score']
                qa_question = qa_match.get('question', '')
                
                # v3.4.1: RAG Cross-Validation
                _qa_validated = True
                try:
                    _cv_intent = self.analyze_intent(query)
                    _rag_check = self.expanded_retrieval(query, _cv_intent, user_id)
                    if _rag_check:
                        _top_rag = _rag_check[0]
                        _rag_text = _top_rag.get('content', '')
                        _rag_heading = ''
                        _meta = _top_rag.get('metadata')
                        if isinstance(_meta, dict):
                            _rag_heading = _meta.get('heading', '')
                        elif isinstance(_meta, str):
                            try:
                                import json as _j
                                _rag_heading = _j.loads(_meta).get('heading', '')
                            except Exception:
                                pass
                        
                        _q_words = set(w.lower() for w in query.split() if len(w) >= 3)
                        _qa_words = set(w.lower() for w in qa_question.split() if len(w) >= 3)
                        _rag_words = set(w.lower() for w in (_rag_text[:500] + ' ' + _rag_heading).split() if len(w) >= 3)
                        
                        _q_in_rag = len(_q_words & _rag_words) / max(len(_q_words), 1)
                        _q_in_qa = len(_q_words & _qa_words) / max(len(_q_words), 1)
                        
                        if _q_in_rag > _q_in_qa and _q_in_qa < 0.6:
                            _qa_validated = False
                            log_system_event(
                                "WARNING",
                                f"Learned QA CROSS-VALIDATION FAIL (stream): QA='{qa_question[:50]}' "
                                f"(q_in_rag={_q_in_rag:.2f} > q_in_qa={_q_in_qa:.2f})",
                                "deep_think"
                            )
                except Exception as cv_err:
                    log_system_event("DEBUG", f"Learned QA cross-validation hatası: {cv_err}", "deep_think")
                
                if _qa_validated:
                    elapsed_ms = (time.time() - start_time) * 1000
                    log_system_event(
                        "INFO",
                        f"Learned QA HIT (stream, validated): score={qa_score:.2f}, {elapsed_ms:.0f}ms",
                        "deep_think"
                    )
                    enriched = self._enrich_learned_qa(qa_match, user_id)
                    enriched_answer = enriched["answer"]
                    enriched_images = enriched["image_ids"]
                    enriched_heading = enriched["heading_images"]
                    
                    if cache_key is not None:
                        result = DeepThinkResult(
                            synthesized_response=enriched_answer,
                            sources=[qa_match.get("source_file", "")] if qa_match.get("source_file") else [],
                            intent=_cv_intent or self.analyze_intent(query),
                            rag_result_count=1,
                            processing_time_ms=elapsed_ms,
                            best_score=qa_score,
                            image_ids=enriched_images,
                            heading_images=enriched_heading
                        )
                        cache_service.deep_think.set(cache_key, result)
                    
                    yield {"type": "done", "data": {
                        "content": enriched_answer,
                        "metadata": {
                            "rag_result_count": 1,
                            "best_score": qa_score,
                            "deep_think": True,
                            "learned_qa": True,
                            "sources": [qa_match.get("source_file", "")] if qa_match.get("source_file") else [],
                            "image_ids": enriched_images,
                            "heading_images": enriched_heading
                        }
                    }}
                    return
        except Exception as qa_err:
            log_system_event("DEBUG", f"Learned QA check hatası: {qa_err}", "deep_think")
        
        log_system_event("INFO", f"Deep Think STREAM: Pipeline başlatıldı - '{query[:50]}...'", "deep_think")
        
        # 1. Intent Detection (cross-validation'da hesaplandıysa tekrar kullan)
        intent = _cv_intent if _cv_intent else self.analyze_intent(query)
        
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
            
            # v3.4.0 FIX: CatBoost BYPASS'ta da görselleri topla (DRY helper)
            bypass_image_ids, bypass_heading_map = self._collect_images_from_rag(rag_results)
            
            # Cache'e kaydet (mevcut cache_key kullan)
            if cache_key is not None:
                result = DeepThinkResult(
                    synthesized_response=final_content,
                    sources=sources,
                    intent=intent,
                    rag_result_count=len(rag_results),
                    processing_time_ms=(time.time() - start_time) * 1000,
                    best_score=best_combined,
                    image_ids=bypass_image_ids,
                    heading_images=bypass_heading_map
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
                    "sources": sources,
                    "image_ids": bypass_image_ids,
                    "heading_images": bypass_heading_map
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
                    yield {"type": "done", "data": {
                        "content": fallback,
                        "metadata": {"deep_think": True, "chunked_fallback": True}
                    }}
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
                "error": "Yanıt üretilirken bir hata oluştu."
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
        
        # Kaynak ve görsel bilgilerini topla
        sources = list(set(r.get("source_file", "") for r in rag_results if r.get("source_file"))) if rag_results else []
        
        # v3.4.0: DRY helper ile görsel toplama (inline kod kaldırıldı)
        unique_image_ids, heading_image_map = self._collect_images_from_rag(rag_results) if rag_results else ([], {})
        best_score = max((r.get("score", 0) for r in rag_results), default=0.0) if rag_results else 0.0
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

    # ========================================
    # 6. Mimariler Arası Yönlendirme
    # ========================================
    
    def process_stream_rag_only(self, query: str, user_id: int) -> Generator[Dict[str, Any], None, None]:
        """Sadece RAG pipeline çalıştırır, DB araması yapılmaz."""
        import time
        start_time = time.time()
        
        # 1. Intent Detection
        # Bilgi tabanında arama olduğu için IntentType.DATABASE_QUERY harici algılama yapılır
        intent = self.analyze_intent(query)
        # Eğer bir şekilde DATABASE_QUERY geldiyse GENERAL maskesi yap
        if intent.intent_type.value == "DATABASE_QUERY":
             intent = IntentResult(intent_type=IntentType.GENERAL, confidence=0.7, suggested_n_results=10, reasoning="RAG only mod - DB yönlendirmesi engellendi")
             
        log_system_event("INFO", f"Deep Think (RAG Only): {intent.intent_type.value} | Puan: {intent.confidence}", "deep_think")
        
        # 2. Expanded Retrieval
        # skip_db_knowledge parametresi ile ds_learning araması atlanır
        rag_results = self.expanded_retrieval(query, intent, user_id, skip_db_knowledge=True)
        
        yield {"type": "rag_complete", "data": {
            "intent": intent.intent_type.value,
            "result_count": len(rag_results),
            "elapsed_ms": (time.time() - start_time) * 1000
        }}

        if not rag_results:
             _no_result_msg = (
                 "🤔 Bu konuda bilgi tabanında ilgili bir kayıt bulunamadı.\n\n"
                 "Farklı anahtar kelimeler kullanarak tekrar deneyebilir veya "
                 "VYRA ile sohbet modunda sorabilirsiniz."
             )
             yield {"type": "done", "data": {
                "content": _no_result_msg,
                "metadata": {"rag_result_count": 0, "best_score": 0, "deep_think": True}
             }}
             return

        # 3. LLM Synthesis
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
             
             _token_buffer = []
             _buffer_limit = 15
             _buffer_flushed = False
             
             stream_gen = call_llm_api_stream(messages)
             for token in stream_gen:
                 full_response += token
                 if not _buffer_flushed:
                     _token_buffer.append(token)
                     buffered_text = "".join(_token_buffer)
                     
                     if "[NO_MATCH]" in buffered_text:
                         for remaining in stream_gen:
                             full_response += remaining
                         break
                     
                     if len(_token_buffer) >= _buffer_limit:
                         for t in _token_buffer:
                             yield {"type": "token", "data": t}
                         _token_buffer = []
                         _buffer_flushed = True
                 else:
                     yield {"type": "token", "data": token}
             
             # Post-process
             cleaned = self._clean_prompt_leak(full_response.strip())
             cleaned = self._postprocess_llm_response(cleaned, intent)
             
             # No Match check
             if "[NO_MATCH]" in cleaned:
                  from app.services.dialog.response_builder import get_dialog_response_builder
                  return get_dialog_response_builder().generate_no_result_response(query)
                
             # İmaj vs.
             sources = list(set(r.get("source_file", "") for r in rag_results if r.get("source_file")))
             bypass_image_ids, bypass_heading_map = self._collect_images_from_rag(rag_results)
             
             yield {"type": "done", "data": {
                 "content": cleaned,
                 "metadata": {
                     "rag_result_count": len(rag_results),
                     "best_score":  rag_results[0].get("score", 0) if rag_results else 0,
                     "deep_think": True,
                     "original_query": query,
                     "sources": sources,
                     "image_ids": bypass_image_ids,
                     "heading_images": bypass_heading_map
                 }
             }}
        except Exception as e:
            log_error(f"RAG Only stream hatası: {e}", "deep_think")
            yield {"type": "done", "data": {
                "content": self._fallback_response(rag_results, intent),
                "metadata": {"deep_think": True, "error": True}
            }}


    def _maybe_chitchat_reply(self, query: str) -> Optional[str]:
        """
        v3.13.1: Kısa selamlama/sohbet mesajları için Text-to-SQL bypass.
        Eşleşirse dostane Türkçe yanıt döner, eşleşmezse None.
        """
        if not query:
            return None
        import re as _re
        q = (query or "").strip().lower()
        # Noktalama temizle (basit)
        q_clean = _re.sub(r"[?!.,;:'\"\-]+", " ", q).strip()
        q_clean = _re.sub(r"\s+", " ", q_clean)
        if not q_clean or len(q_clean) > 80:
            return None

        # Tam eşleşmeli kısa selamlama setleri
        greetings = {
            "merhaba", "selam", "sa", "selamun aleykum", "selamünaleyküm",
            "iyi günler", "iyi aksamlar", "iyi akşamlar", "iyi geceler",
            "günaydın", "gunaydin", "hi", "hello", "hey", "naber", "nbr",
        }
        thanks = {
            "tesekkurler", "teşekkürler", "tesekkur ederim", "teşekkür ederim",
            "sagol", "sağol", "sagolun", "sağolun", "eyvallah",
            "thanks", "thank you", "thx",
        }
        howareyou = {
            "nasilsin", "nasılsın", "naber", "ne haber", "nasıl gidiyor",
            "how are you",
        }
        whoareyou = {
            "kimsin", "sen kimsin", "adın ne", "adin ne", "ne yapabilirsin",
            "neler yapabilirsin", "ne yapiyorsun", "ne yapıyorsun",
        }
        bye = {
            "gorusuruz", "görüşürüz", "hosca kal", "hoşça kal", "bye", "goodbye",
        }

        if q_clean in greetings:
            return "Merhaba! 👋 Veritabanınız üzerinde size nasıl yardımcı olabilirim? Örneğin: *“geçen ayki toplam satışları göster”*."
        if q_clean in thanks:
            return "Rica ederim! 🙌 Başka bir veri sorgusu için buradayım."
        if q_clean in howareyou:
            return "İyiyim, teşekkürler! 🙂 Hangi veriyi getirmemi istersiniz?"
        if q_clean in whoareyou:
            return ("Ben **VYRA** — şirket verilerinize doğal dilde sorular sorabilmenizi sağlayan asistanınızım. "
                    "Veritabanı sorgularınızı SQL'e çevirip sonuçları tablo/özet olarak gösteririm.")
        if q_clean in bye:
            return "Görüşmek üzere! 👋"
        return None


    def process_stream_db_only(self, query: str, user_id: int, company_id: int = None, confirm_mode: bool = False, schema_hint: str = None, report_template: str = None, follow_up_context: Optional[Dict[str, Any]] = None, source_id: int = None) -> Generator[Dict[str, Any], None, None]:
        """
        v3.10.0: DB-only pipeline — Firma bazlı DB kaynağı filtresi + Schema Pruning + Error Sanitization.
        + FAQ/Query Cache + Confirm before execute + Self-Healing.

        Akış:
        0. **FAQ Cache:** Aynı soru+firma için cached SQL/sonuç kontrolü
        1. Kullanıcının **firmasına ait** (company_id) aktif DB kaynağını bul
        2. ML öğrenme verisiyle (search_db_knowledge) ilgili tabloyu tespit et
        3. Schema context'i al (get_schema_context)
        4. **Schema Pruning:** ML match'e göre sadece ilgili tabloları context'e al
        5. ML bağlamı + budanmış şema ile LLM Text-to-SQL üret
        5b. **Confirm Mode:** SQL'i kullanıcıya göster, onay bekle
        6. SafeSQLExecutor ile güvenli çalıştır + Self-Healing retry
        7. Sonuçları markdown tablo olarak formatla
        8. **Error Sanitization:** Fortify uyumu — hata detaylarını kullanıcıya gösterme
        9. **Cache:** Başarılı sonucu cache'e yaz
        """
        import time
        start_time = time.time()

        # ── 0a. Selamlama / sohbet bypass (v3.13.1) ────────────────────
        # "merhaba", "nasılsın", "teşekkür", "sa", "selam" gibi mesajlar
        # SQL pipeline'ına girmemeli — kısa, dostane yanıt döner.
        _bypass_text = self._maybe_chitchat_reply(query)
        if _bypass_text is not None:
            log_system_event(
                "INFO",
                f"DB-Only: Chitchat bypass — '{query[:60]}'",
                "deep_think", user_id
            )
            yield {"type": "done", "data": {
                "content": _bypass_text,
                "metadata": {"deep_think": True, "intent": "chitchat", "source_type": "db", "bypass": True}
            }}
            return

        try:
            # ── 0. FAQ/Query Cache kontrolü ────────────────────────────
            # v3.16.0: Follow-up modunda cache ve Golden SQL atlanır — kullanıcı
            # zaten önceki sorguyu MODIFIYE etmek istiyor; cache hit ya da Golden
            # match aynı eski sorguyu döndürürse "değişiklik isteği" görmezden
            # gelinmiş olur.
            cache_key = _make_cache_key(query, company_id)
            cached = _SQL_QUERY_CACHE.get(cache_key) if not follow_up_context else None
            if cached and not confirm_mode:
                log_system_event(
                    "INFO",
                    f"DB-Only: Cache HIT — '{query[:50]}' (company={company_id})",
                    "deep_think", user_id
                )
                # Cached SQL'i tekrar çalıştır (veri güncelliği için)
                # Ama LLM çağrısını atla
                yield {"type": "status", "data": "📦 Önceki sorgu sonuçları kullanılıyor..."}

            # ── 1. Kullanıcının firmasına ait DB kaynağını bul ──────────────
            from app.core.db import get_db_conn
            sources = []
            conn = get_db_conn()
            try:
                cur = conn.cursor()

                # v3.20.0 Faz 1c: source_id verilmişse o kaynağa kilitlen
                if source_id is not None:
                    cur.execute("""
                        SELECT ds.id, ds.name, ds.db_type, ds.host, ds.port,
                               ds.db_name, ds.db_user, ds.db_password_encrypted
                        FROM data_sources ds
                        WHERE ds.id = %s
                          AND ds.source_type = 'database'
                          AND ds.is_active = TRUE
                        LIMIT 1
                    """, (source_id,))
                # v3.8.0: company_id filtresi — kullanıcının firmasına ait kaynaklar
                elif company_id:
                    cur.execute("""
                        SELECT ds.id, ds.name, ds.db_type, ds.host, ds.port,
                               ds.db_name, ds.db_user, ds.db_password_encrypted
                        FROM data_sources ds
                        WHERE ds.source_type = 'database'
                          AND ds.is_active = TRUE
                          AND ds.company_id = %s
                          AND EXISTS (
                              SELECT 1 FROM ds_db_objects dbo
                              WHERE dbo.source_id = ds.id
                          )
                        ORDER BY ds.name
                        LIMIT 1
                    """, (company_id,))
                else:
                    # Fallback: company_id yoksa tüm aktif kaynaklar (geriye uyumluluk)
                    log_warning(
                        "DB-Only: company_id parametresi yok, tüm kaynaklar aranıyor (güvenlik riski!)",
                        "deep_think"
                    )
                    cur.execute("""
                        SELECT ds.id, ds.name, ds.db_type, ds.host, ds.port,
                               ds.db_name, ds.db_user, ds.db_password_encrypted
                        FROM data_sources ds
                        WHERE ds.source_type = 'database'
                          AND ds.is_active = TRUE
                          AND EXISTS (
                              SELECT 1 FROM ds_db_objects dbo
                              WHERE dbo.source_id = ds.id
                          )
                        ORDER BY ds.name
                        LIMIT 1
                    """)

                for row in cur.fetchall():
                    sources.append({
                        "id": row["id"], "name": row["name"],
                        "db_type": row["db_type"], "host": row["host"],
                        "port": row["port"], "db_name": row["db_name"],
                        "db_user": row["db_user"],
                        "db_password_encrypted": row["db_password_encrypted"],
                    })
            finally:
                conn.close()

            if not sources:
                try:
                    from app.services.user_service import get_user_by_id
                    user = get_user_by_id(user_id)
                    is_admin = user and user.get("role") == "admin"
                except Exception:
                    is_admin = False
                msg = (
                    "📊 Firmanıza tanımlı bir veritabanı kaynağı bulunamadı. "
                    "Parametreler → Kaynaklar sekmesinden bir veritabanı bağlantısı ekleyin."
                    if is_admin else
                    "📊 Bu özellik henüz kullanımda değildir."
                )
                yield {"type": "done", "data": {"content": msg, "metadata": {"db_only": True}}}
                return

            # ── 1b. Golden SQL kontrolü — doğrulanmış sorgu varsa direkt kullan ──
            # v3.16.0: Follow-up modunda Golden SQL atlanır (yukarıdaki cache açıklamasıyla aynı sebep).
            golden_hit = None
            golden_examples = []
            try:
                from app.services.text_to_sql import search_golden_sql
                if sources and not follow_up_context:
                    golden_results = search_golden_sql(
                        query, sources[0]["id"], company_id, min_score=0.80, max_results=3
                    )
                    if golden_results:
                        best = golden_results[0]
                        if best["score"] >= 0.95:
                            # Direkt çalıştır — LLM bypass
                            golden_hit = best
                            log_system_event(
                                "INFO",
                                f"DB-Only: Golden SQL hit (score={best['score']}): {best['question_text'][:60]}",
                                "deep_think", user_id
                            )
                        else:
                            # Few-shot örnek olarak kullan
                            golden_examples = golden_results
                            log_system_event(
                                "INFO",
                                f"DB-Only: {len(golden_results)} Golden SQL few-shot örneği bulundu",
                                "deep_think", user_id
                            )
            except Exception as gs_err:
                log_warning(f"DB-Only Golden SQL hatası: {gs_err}", "deep_think")

            # ── 2. ML öğrenilmiş şema bilgisini getir (schema_record) ──────
            ml_context = ""
            ml_matched_tables = []
            try:
                from app.services.ds_learning_service import search_db_knowledge
                # v3.20.0 Faz 1c: DB-only path source_id verilmişse RLS-scope edilir
                ml_results = search_db_knowledge(query, company_id=company_id, min_score=0.25, max_results=3, source_id=source_id)
                if ml_results:
                    schema_parts = []
                    for r in ml_results:
                        content = r.get("content", "")
                        meta = r.get("metadata") or {}
                        full_table = meta.get("full_table") or meta.get("table_name", "")
                        if full_table:
                            ml_matched_tables.append(full_table)
                        # schema_record içeriği zaten yapılandırılmış şema metni
                        schema_parts.append(content)

                    ml_context = "\n\n---\n\n".join(schema_parts)
                    log_system_event(
                        "INFO",
                        f"DB-Only: {len(ml_results)} schema_record bulundu: {ml_matched_tables}",
                        "deep_think", user_id
                    )
                else:
                    log_warning(
                        "DB-Only: ML'de eslesme bulunamadi (min_score=0.25)",
                        "deep_think"
                    )
            except Exception as ml_err:
                log_warning(f"DB-Only ML arama hatasi: {ml_err}", "deep_think")


            # ── 3. Schema context'i al ────────────────────────────────────
            from app.services.text_to_sql import get_schema_context

            # v3.14.0: Entity Resolution — ML'den önce deterministik eşleştirme
            entity_matched_tables = []
            try:
                from app.services.text_to_sql import resolve_entities, get_schema_context as _get_ctx
                # Hızlı entity resolution için enriched tabloları çek
                for s in sources:
                    try:
                        er_ctx = _get_ctx(s["id"], enriched_only=True)
                        if er_ctx and er_ctx.get("tables"):
                            entity_matched_tables = resolve_entities(query, er_ctx["tables"])
                            if entity_matched_tables:
                                log_system_event(
                                    "INFO",
                                    f"DB-Only Entity Resolution: {len(entity_matched_tables)} tablo eşleşti: "
                                    f"{entity_matched_tables[:5]}",
                                    "deep_think", user_id
                                )
                            break
                    except Exception:
                        pass
            except Exception as er_err:
                log_warning(f"DB-Only Entity Resolution hatası: {er_err}", "deep_think")

            # ML + Entity Resolution sonuçlarını birleştir
            combined_matched = list(set(ml_matched_tables + entity_matched_tables))

            # v3.28.9: Follow-up modunda önceki SQL'in FROM tablosunu çıpa olarak
            # combined_matched'e MUTLAKA enjekte et. Aksi halde yeni sorudaki entity
            # resolution farklı tabloya kayar ve pruner önceki tabloyu schema'dan
            # düşürür → LLM tabloyu görmez ve halüsinasyon eder.
            followup_anchor_tables: list = []
            if follow_up_context and follow_up_context.get("prev_sql"):
                try:
                    import re as _re
                    _prev_sql = follow_up_context.get("prev_sql", "")
                    # FROM ... ve JOIN ... klozlarındaki tüm referansları yakala
                    _refs = _re.findall(
                        r'\b(?:FROM|JOIN)\s+("?[\w\.]+"?)',
                        _prev_sql,
                        flags=_re.IGNORECASE,
                    )
                    for _r in _refs:
                        _r = _r.strip().strip('"').lower()
                        if _r and _r not in followup_anchor_tables:
                            followup_anchor_tables.append(_r)
                    if followup_anchor_tables:
                        for _at in followup_anchor_tables:
                            if _at not in [m.lower() for m in combined_matched]:
                                combined_matched.append(_at)
                        log_system_event(
                            "INFO",
                            f"DB-Only Follow-up: prev_sql çıpa tabloları enjekte edildi → {followup_anchor_tables}",
                            "deep_think", user_id
                        )
                except Exception as _fua_err:
                    log_warning(f"DB-Only: Follow-up anchor extraction hatası: {_fua_err}", "deep_think")

            # v3.14.0: ML eşleşme varsa tüm tabloları al (pruning yapılacak),
            # ML eşleşme yoksa sadece enriched tabloları al (gereksiz tabloları LLM'e gönderme)
            # v3.28.9: Follow-up modunda çıpa zaten matched'e eklendi — pruning aktif kalsın.
            use_enriched_only = not combined_matched
            schema_ctx = None
            source = None
            for s in sources:
                try:
                    ctx = get_schema_context(s["id"], enriched_only=use_enriched_only)
                    if ctx and ctx.get("tables"):
                        schema_ctx = ctx
                        source = s
                        break
                except Exception as schema_err:
                    log_warning(f"DB-Only: Kaynak '{s['name']}' şema yüklenemedi: {schema_err}", "deep_think")

            # v3.14.0: enriched_only ile tablo bulunamazsa, tüm tablolarla tekrar dene (fallback)
            if not schema_ctx and use_enriched_only:
                log_warning("DB-Only: Enriched tablo bulunamadı, tüm tablolarla deneniyor", "deep_think")
                for s in sources:
                    try:
                        ctx = get_schema_context(s["id"], enriched_only=False)
                        if ctx and ctx.get("tables"):
                            schema_ctx = ctx
                            source = s
                            break
                    except Exception:
                        pass

            if not schema_ctx:
                yield {"type": "done", "data": {
                    "content": "⚠️ Veritabanı şeması yüklenemedi. Lütfen veri kaynağının aktif olduğunu kontrol edin.",
                    "metadata": {"db_only": True, "error": True}
                }}
                return

            # ── 4. Schema Pruning: ML match'e göre sadece ilgili tabloları al ──
            schema_ctx_with_ml = dict(schema_ctx)
            if ml_context:
                schema_ctx_with_ml["extra_context"] = ml_context

            if combined_matched and schema_ctx_with_ml.get("tables"):
                pruned_tables = _prune_schema_tables(
                    all_tables=schema_ctx_with_ml["tables"],
                    matched_tables=combined_matched,
                    relationships=schema_ctx_with_ml.get("relationships", []),
                )
                if pruned_tables:
                    log_system_event(
                        "INFO",
                        f"DB-Only Schema Pruning: {len(schema_ctx_with_ml['tables'])} → {len(pruned_tables)} tablo "
                        f"(ML: {ml_matched_tables}, Entity: {entity_matched_tables[:5]})",
                        "deep_think", user_id
                    )
                    schema_ctx_with_ml["tables"] = pruned_tables
                else:
                    # v3.14.0: Pruning eşleşme bulamadı — enriched tablolara fallback
                    enriched_fallback = [
                        t for t in schema_ctx_with_ml["tables"]
                        if t.get("business_name_tr") or t.get("category")
                    ]
                    if enriched_fallback:
                        log_system_event(
                            "INFO",
                            f"DB-Only: Pruning eşleşme bulamadı, enriched fallback: "
                            f"{len(schema_ctx_with_ml['tables'])} → {len(enriched_fallback)} tablo",
                            "deep_think", user_id
                        )
                        schema_ctx_with_ml["tables"] = enriched_fallback
                    else:
                        log_warning(
                            "DB-Only: Pruning ve enriched fallback boş — tüm tablolar kullanılacak",
                            "deep_think"
                        )
            elif use_enriched_only and schema_ctx_with_ml.get("tables"):
                log_system_event(
                    "INFO",
                    f"DB-Only: ML eşleşme yok, sadece enriched tablolar kullanılıyor: "
                    f"{len(schema_ctx_with_ml['tables'])} tablo",
                    "deep_think", user_id
                )

            # ── 4b. v4.0: schema_hint ile tablo önceliklendirme ───────────
            if schema_hint:
                from app.services.text_to_sql import filter_tables_by_schema_hint
                filtered = filter_tables_by_schema_hint(
                    schema_ctx_with_ml.get("tables", []), schema_hint
                )
                schema_ctx_with_ml = dict(schema_ctx_with_ml)
                schema_ctx_with_ml["tables"] = filtered
                log_system_event(
                    "INFO",
                    f"DB-Only: schema_hint='{schema_hint}' uygulandı, "
                    f"{len(filtered)} tablo kaldı",
                    "deep_think", user_id
                )

            # ── 4c. v4.0: Disambiguation — aynı isimde çoklu tablo kontrolü ──
            if not schema_hint:
                from app.services.text_to_sql import detect_ambiguous_tables
                ambiguous = detect_ambiguous_tables(schema_ctx_with_ml.get("tables", []))
                if ambiguous:
                    candidates = []
                    for base_name, group in ambiguous.items():
                        for t in group:
                            candidates.append({
                                "schema": t.get("schema", ""),
                                "table_name": t["name"],
                                "full_name": f"{t.get('schema', '')}.{t['name']}",
                                "business_name_tr": (
                                    t.get("admin_label_tr") or t.get("business_name_tr") or t["name"]
                                ),
                                "description_tr": t.get("description_tr", ""),
                                "row_estimate": t.get("row_estimate", 0),
                                "base_name": base_name,
                            })
                    log_system_event(
                        "INFO",
                        f"DB-Only: Disambiguation tetiklendi — {len(candidates)} aday tablo",
                        "deep_think", user_id
                    )
                    yield {"type": "clarification", "data": {
                        "candidates": candidates,
                        "query": query,
                        "message": "Aynı isimde birden fazla tablo bulundu. Hangisini kastettiğinizi seçin:",
                    }}
                    return

            # ── 4d. v4.0: DB Intent Tespiti + Rapor Şablonu Önerisi ─────────
            if not report_template:
                db_intent = _detect_db_intent(query)
                if db_intent == "DB_REPORT":
                    templates = _generate_report_templates(query, schema_ctx_with_ml)
                    if templates:
                        log_system_event(
                            "INFO",
                            f"DB-Only: DB_REPORT intent — {len(templates)} şablon önerildi",
                            "deep_think", user_id
                        )
                        yield {"type": "suggestions", "data": {
                            "intent": "DB_REPORT",
                            "message": "Bu analiz için birkaç yaklaşım hazırladım. Hangisiyle ilerleyelim?",
                            "templates": templates,
                        }}
                        return
            else:
                # Kullanıcı rapor şablonu seçti — şablonu sorguya ekle.
                # v3.33.0: Önceden `[Rapor Yaklaşımı: ...]` etiketi sorgunun
                # SONUNA eklenirdi; LLM/SQL generator sıklıkla bu suffix'i
                # decorative kabul edip orijinal kısa sorguyu (örn. "sipariş
                # trendini listele") basit zaman serisi olarak yorumluyor,
                # şablondaki tablo JOIN'leri (ABONELIKLER, KAMPANYALAR vs.)
                # ihmal ediliyordu. Şablonu ÖN PLANA çekiyoruz ve açık
                # "ZORUNLU YAKLAŞIM" tag'ı veriyoruz — generator bunu
                # spec olarak yorumlar.
                _rt = str(report_template).strip()
                query = (
                    "ZORUNLU ANALİZ YAKLAŞIMI — kullanıcı bu şablonu seçti,"
                    " SQL bu yaklaşımı birebir uygulamalı (içinde geçen TÜM"
                    " tablo adları ve JOIN/segmentasyon talimatları"
                    " kullanılmalı):\n"
                    f"  → {_rt}\n\n"
                    f"Kullanıcının orijinal isteği: {query}"
                )

            # ── 4e. v3.14.0: Value Retrieval — soruda geçen spesifik değerleri tespit et ──
            try:
                from app.services.text_to_sql import value_retrieval
                value_hints = value_retrieval(query, source["id"], schema_ctx_with_ml.get("tables", []))
                if value_hints:
                    vr_block = "\nDEĞER İPUÇLARI (kullanıcının bahsettiği spesifik değerler):\n"
                    for vh in value_hints[:5]:
                        vr_block += f"- '{vh['value']}' → {vh['schema']}.{vh['table']}.{vh['column']} kolonunda aranabilir\n"
                    if schema_ctx_with_ml.get("extra_context"):
                        schema_ctx_with_ml["extra_context"] += vr_block
                    else:
                        schema_ctx_with_ml["extra_context"] = vr_block
            except Exception:
                pass

            # ── 5. LLM Text-to-SQL üret (ML bağlamı + şema) ─────────────
            from app.services.text_to_sql import generate_sql, generate_sql_with_retry
            from app.services.safe_sql_executor import SafeSQLExecutor, SQLResult

            dialect = schema_ctx.get("dialect", "mssql")

            executor = SafeSQLExecutor()
            allowed_tables = executor.get_allowed_tables(source["id"])

            # v3.10.0: Cache'den SQL kullan (LLM çağrısını atla)
            if cached and cached.get("sql") and not confirm_mode:
                sql_result = {
                    "success": True,
                    "sql": cached["sql"],
                    "explanation": "Önceki sorgununuz tekrar kullanılıyor.",
                    "error": None,
                    "from_cache": True,
                }
                log_system_event("INFO", f"DB-Only: Cache'den SQL kullanılıyor: {cached['sql'][:80]}", "deep_think", user_id)
            elif golden_hit:
                # v3.14.0: Golden SQL hit — LLM bypass, doğrulanmış SQL direkt kullan
                sql_result = {
                    "success": True,
                    "sql": golden_hit["sql_query"],
                    "explanation": f"Önceki doğrulanmış sorgu kullanılıyor (benzerlik: {golden_hit['score']}).",
                    "error": None,
                    "from_golden": True,
                }
                log_system_event("INFO", f"DB-Only: Golden SQL kullanılıyor: {golden_hit['sql_query'][:80]}", "deep_think", user_id)
            else:
                # v3.14.0: Golden SQL few-shot örneklerini schema context'e ekle
                if golden_examples:
                    gs_block = "\n\nÖNCEKİ DOĞRULANMIŞ SORGULAR (referans olarak kullan):\n"
                    for ge in golden_examples[:3]:
                        gs_block += f"Soru: {ge['question_text']}\n```sql\n{ge['sql_query']}\n```\n\n"
                    if schema_ctx_with_ml.get("extra_context"):
                        schema_ctx_with_ml["extra_context"] += gs_block
                    else:
                        schema_ctx_with_ml["extra_context"] = gs_block

                sql_result = generate_sql(
                    query=query,
                    schema_context=schema_ctx_with_ml,
                    allowed_tables=allowed_tables,
                    schema_hint=schema_hint,
                    follow_up_context=follow_up_context,  # v3.16.0: önceki SQL modifikasyonu
                )

            if not sql_result.get("success"):
                _sql_err = sql_result.get("error", "Bilinmeyen SQL hatasi")
                log_warning(f"DB-Only: SQL uretimi basarisiz: {_sql_err}", "deep_think")
                
                # v3.8.0 Error Sanitization: Teknik detayları kullanıcıya gösterme
                # v3.19.2: Yanlış anlaşılmaması için "problem yaşandı" başlığı kaldırıldı
                content_msg = (
                    f"**Yapay Zeka Notu:**\n_{_sanitize_error_for_user(_sql_err)}_\n\n"
                    "Lütfen farklı bir şekilde sormayı deneyin."
                )
                
                yield {"type": "done", "data": {
                    "content": content_msg,
                    "metadata": {"db_only": True, "error": True}
                }}
                return

            sql = sql_result["sql"]
            retry_count = 0
            from_cache = sql_result.get("from_cache", False)

            # ── 5a.5: v3.28.2 G3 — Sample Data Preview hint ─────────────
            # Frontend'e seçilen birincil tabloyu duyur; consumer
            # /api/data-sources/{id}/samples'tan cached örnek satırları çeker.
            # Hata olursa graceful: event yayma.
            #
            # v3.33.0 — DB-Only akışındaki ranker pick regression fix:
            # Önceden `pruned_tables[0]` / `combined_matched[0]` yayılıyordu;
            # bu, LLM'in ürettiği SQL farklı tabloyu hedeflese bile (örn. JOIN'lerde
            # MUSTERILER ⋈ SIPARISLER) yanlış tabloyu ("Aday Tablo — ABONELIKLER")
            # gösteriyordu. v3.32.0 `pick_preview_table_validated` fixi yalnızca
            # `agentic_query_api.py`'a uygulanmıştı; aynı kuralı burada da uyguluyoruz:
            #   - SQL'de ≥2 tablo varsa preview atlanır (multi-table yanıltıcı).
            #   - SQL'de 1 tablo varsa SQL'deki tablo kullanılır.
            #   - SQL parse edilemezse (CTE/subquery dialect issues) ranker pick'e fallback.
            try:
                from app.services.pipeline.nodes.sample_data_preview import (
                    extract_all_tables_from_sql,
                )
                _preview_table = None
                _preview_schema = None
                _sql_tables = extract_all_tables_from_sql(sql) if sql else []
                if len(_sql_tables) == 1:
                    _only = _sql_tables[0]
                    _preview_table = _only.get("table")
                    _preview_schema = _only.get("schema")
                elif not _sql_tables:
                    # SQL parse edilemedi → eski davranış (ranker pick) ile fallback.
                    _pt = locals().get("pruned_tables")
                    if isinstance(_pt, list) and _pt:
                        _first = _pt[0]
                        if isinstance(_first, dict):
                            _preview_table = (
                                _first.get("table_name") or _first.get("name") or _first.get("table")
                            )
                            _preview_schema = _first.get("schema") or _first.get("schema_name")
                    if not _preview_table:
                        _cm = locals().get("combined_matched")
                        if isinstance(_cm, list) and _cm:
                            _first2 = _cm[0]
                            if isinstance(_first2, dict):
                                _preview_table = (
                                    _first2.get("table_name") or _first2.get("name") or _first2.get("table")
                                )
                                _preview_schema = _first2.get("schema") or _first2.get("schema_name")
                # len >= 2 → preview emit edilmez (multi-table JOIN)
                if _preview_table and source and source.get("id"):
                    yield {"type": "selected_table_for_preview", "data": {
                        "source_id": int(source["id"]),
                        "schema": _preview_schema,
                        "table": _preview_table,
                    }}
            except Exception:
                pass

            # ── 5b. Confirm Mode: SQL'i göster, çalıştırma ──────────────
            if confirm_mode:
                yield {"type": "done", "data": {
                    "content": (
                        "📋 **Oluşturulan SQL sorgusu:**\n\n"
                        f"```sql\n{sql}\n```\n\n"
                        "Bu sorguyu çalıştırmak ister misiniz?"
                    ),
                    "metadata": {
                        "db_only": True,
                        "confirm_pending": True,
                        "pending_sql": sql,
                        "source_id": source["id"],
                        "source_name": source["name"],
                        "dialect": dialect,
                    }
                }}
                return

            # ── 6. SQL'i güvenli çalıştır (Progressive Timeout) ──────────

            # v3.14.0: Tahmini süre hesapla ve kullanıcıya göster
            time_estimate = executor.estimate_query_time(schema_ctx_with_ml, sql)
            yield {"type": "status", "data": f"🔍 Sorgu çalıştırılıyor... ({time_estimate['reason']}, ~{time_estimate['estimate_seconds']}sn)"}

            # v3.14.0: Non-blocking execution — sorguyu arka planda çalıştır
            # v3.15.0: cancel_event ile iptal mekanizması + job_id ile registry
            MAX_WAIT = int(getattr(settings, "DB_QUERY_MAX_WAIT_SECONDS", 900))
            result_holder, result_event, exec_thread, cancel_event = executor.execute_async(
                sql=sql, source=source, dialect=dialect, allowed_tables=allowed_tables,
                timeout=MAX_WAIT,
            )

            # v3.15.0: Job'u registry'e kaydet — iptal endpoint'i bunu kullanır
            # try/finally ile sarılı: GeneratorExit / herhangi bir exception'da bile
            # registry'den temizlenir (memory leak engellenir — TYCHE bulgusu).
            import uuid as _uuid
            from app.services.safe_sql_executor import register_sql_job, unregister_sql_job
            job_id = _uuid.uuid4().hex
            try:
                register_sql_job(job_id, cancel_event, owner_user_id=user_id)
            except Exception:
                pass

            INITIAL_WAIT = 5
            elapsed_so_far = INITIAL_WAIT
            user_cancelled = False
            try:
                # v3.14.5: İlk bekleme periyodu (5sn) — kısa, çabuk feedback
                got_result = result_event.wait(timeout=INITIAL_WAIT)

                if not got_result and not cancel_event.is_set():
                    # İlk timeout uyarısı — job_id artık frontend'e gönderilir (İptal butonu için)
                    # v3.15.6: sql payload'a eklendi — kullanıcı beklerken üretilen SQL'i
                    # gözden geçirebilsin (doğru sorgu mu oluşmuş kontrolü için).
                    yield {"type": "timeout_warning", "data": {
                        "message": "⏳ Sorgu devam ediyor, büyük tablolarda biraz daha zaman alabilir...",
                        "elapsed": elapsed_so_far,
                        "estimate": time_estimate["estimate_seconds"],
                        "max_wait": MAX_WAIT,
                        "job_id": job_id,
                        "sql": sql,
                    }}

                    # v3.14.5: Her 10 saniyede bir progress_tick — SSE keep-alive sağlar,
                    # ara katman (Nginx/proxy/AV) idle timeout'unu tetiklemez.
                    # v3.15.0: MAX_WAIT settings'ten gelir (varsayılan 900sn = 15dk).
                    #          cancel_event.is_set() ise döngüden çık.
                    TICK_INTERVAL = 10
                    while elapsed_so_far < MAX_WAIT:
                        if cancel_event.is_set():
                            user_cancelled = True
                            break
                        remaining = MAX_WAIT - elapsed_so_far
                        wait_for = min(TICK_INTERVAL, remaining)
                        got_result = result_event.wait(timeout=wait_for)
                        elapsed_so_far += wait_for
                        if got_result:
                            break
                        if cancel_event.is_set():
                            user_cancelled = True
                            break
                        yield {"type": "progress_tick", "data": {
                            "elapsed": elapsed_so_far,
                            "max_wait": MAX_WAIT,
                            "job_id": job_id,
                            "message": f"⏳ {elapsed_so_far}sn — sorgu devam ediyor...",
                        }}
            finally:
                # v3.15.0: GeneratorExit (istemci disconnect) dahil her exit yolu
                # registry'den siler — TYCHE-D fix.
                try:
                    unregister_sql_job(job_id)
                except Exception:
                    pass

            exec_result = result_holder.get("result")
            if user_cancelled and exec_result is None:
                # Kullanıcı iptal etti, daha sonuç gelmedi
                exec_result = SQLResult(
                    success=False,
                    error="Sorgu kullanıcı tarafından iptal edildi",
                    sql_executed=sql[:200],
                    cancelled=True,
                )
            elif exec_result is None:
                # v3.15.0: Gerçek wait-loop timeout — SQL hala backend'de çalışıyor olabilir
                # ancak SSE bağlantısını sonsuz açık tutmuyoruz. timeout=True flag'ı
                # Self-Healing'in tetiklenmesini engeller (sorun süre, SQL değil).
                _max_wait_min = max(1, MAX_WAIT // 60)
                exec_result = SQLResult(
                    success=False,
                    error=f"Sorgu {_max_wait_min} dakika ({MAX_WAIT} saniye) içinde tamamlanamadı",
                    sql_executed=sql[:200],
                    timeout=True,
                )

            # v3.9.0: Self-Healing — execution hatası varsa LLM ile düzeltme
            # v3.15.0: Timeout durumunda Self-Healing'i tetikleme — SQL yanlış değil, sadece uzun sürdü.
            if not exec_result.success and exec_result.error and not getattr(exec_result, "timeout", False):
                log_system_event(
                    "INFO",
                    f"DB-Only: SQL Self-Healing tetikleniyor: {exec_result.error[:100]}",
                    "deep_think", user_id
                )
                retry_result = generate_sql_with_retry(
                    query=query,
                    schema_context=schema_ctx_with_ml,
                    allowed_tables=allowed_tables,
                    execution_error=exec_result.error,
                    failed_sql=exec_result.sql_executed or sql,
                    max_retries=3,
                )

                if retry_result.get("success"):
                    retry_count = retry_result.get("retry_count", 0)
                    sql = retry_result["sql"]
                    # Düzeltilmiş SQL'i tekrar çalıştır
                    exec_result = executor.execute(
                        sql=sql,
                        source=source,
                        dialect=dialect,
                        allowed_tables=allowed_tables,
                    )
                    log_system_event(
                        "INFO",
                        f"DB-Only: Self-Healing retry #{retry_count} → "
                        f"{'BAŞARILI' if exec_result.success else 'BAŞARISIZ'}",
                        "deep_think", user_id
                    )

            elapsed_ms = (time.time() - start_time) * 1000

            # SQL Audit Log
            try:
                from app.services.sql_audit_log import log_sql_execution
                log_sql_execution(
                    user_id=user_id,
                    source_id=source["id"],
                    source_name=source["name"],
                    sql_text=exec_result.sql_executed or sql,
                    dialect=dialect,
                    status="success" if exec_result.success else "error",
                    row_count=exec_result.row_count if exec_result.success else 0,
                    elapsed_ms=elapsed_ms,
                    error_msg=exec_result.error if not exec_result.success else None,
                    company_id=company_id,
                )
            except Exception:
                pass

            # v3.14.0: Başarılı sorguyuGolden SQL'e kaydet (arka planda)
            if exec_result.success and not sql_result.get("from_cache") and not sql_result.get("from_golden"):
                try:
                    from app.services.text_to_sql import save_golden_sql
                    import threading
                    threading.Thread(
                        target=save_golden_sql,
                        args=(source["id"], company_id, query, sql, None, dialect, user_id),
                        daemon=True
                    ).start()
                except Exception:
                    pass

            if not exec_result.success:
                # v3.8.0 Error Sanitization: DB hata detaylarını loglayıp kullanıcıya genel mesaj göster
                log_warning(f"DB-Only: SQL çalıştırma hatası (retry={retry_count}): {exec_result.error}", "deep_think")

                # v3.15.0: Timeout durumunda kullanıcıya özgün mesaj — sorunun "SQL yanlış" değil
                # "süre aşıldı" olduğunu net söylüyoruz; tekrar denemesi için yönlendiriyoruz.
                if getattr(exec_result, "timeout", False):
                    _max_wait_min = max(1, MAX_WAIT // 60)
                    content_msg = (
                        f"⏱️ Sorgu **{_max_wait_min} dakika** içinde tamamlanamadı.\n\n"
                        f"Sorgunuz veritabanında hâlâ çalışıyor olabilir ancak bağlantı süresi doldu. "
                        f"Daha dar bir tarih aralığı veya filtre ile tekrar deneyebilir, "
                        f"ya da sorguyu daha sade bir şekilde ifade edebilirsiniz."
                    )
                    error_kind = "timeout"
                elif getattr(exec_result, "cancelled", False):
                    content_msg = "🛑 Sorgu kullanıcı tarafından iptal edildi."
                    error_kind = "cancelled"
                else:
                    content_msg = (
                        "❌ Sorgu çalıştırılırken bir hata oluştu.\n\n"
                        "Lütfen sorunuzu farklı şekilde ifade ederek tekrar deneyin. "
                        "Sorun devam ederse sistem yöneticinize başvurun."
                    )
                    error_kind = "exec_error"

                # v3.15.1: SQL'i hata yanıtına da ekle — kullanıcı "SQL" butonuyla
                # hangi sorgunun çalıştığını/denendiğini görebilsin (troubleshooting).
                _failed_sql = (exec_result.sql_executed or sql or "").strip()

                yield {"type": "done", "data": {
                    "content": content_msg,
                    "metadata": {
                        "db_only": True,
                        "error": True,
                        "error_kind": error_kind,
                        "retry_count": retry_count,
                        "elapsed_sec": int(elapsed_so_far) if 'elapsed_so_far' in locals() else None,
                        "sql_executed": _failed_sql,
                    }
                }}
                return

            # ── 7. Sonuçları LLM ile Sentezle ve Stream Et ───────────────────────
            db_data = exec_result.data or []
            sql_executed = exec_result.sql_executed or sql
            source_name = schema_ctx.get("source_name", source["name"])

            # ── 7a. Boş sonuç erken dönüşü (LLM'e gereksiz yere gitme) ──────────
            if not db_data:
                empty_msg = (
                    f"📭 Sorgunuz çalıştırıldı ancak **hiç kayıt bulunamadı**.\n\n"
                    f"Arama kriterlerinizi değiştirerek tekrar deneyebilirsiniz."
                )
                yield {"type": "token", "data": empty_msg}
                yield {"type": "done", "data": {
                    "content": empty_msg,
                    "metadata": {
                        "db_only": True, "sql": sql_executed, "sql_executed": sql_executed,
                        "row_count": 0, "source_db": source_name,
                        "ml_context_used": bool(ml_context),
                        "processing_time_ms": elapsed_ms,
                        "company_id": company_id,
                        "retry_count": retry_count,
                        "columns": [], "raw_data": [],
                    }
                }}
                return

            import json

            # ── 7b. Büyük sonuç setlerini sınırla (LLM token taşması önleme) ─────
            MAX_LLM_ROWS = 50
            MAX_JSON_CHARS = 8000
            data_for_llm = db_data[:MAX_LLM_ROWS]
            data_json = json.dumps(data_for_llm, ensure_ascii=False, default=str)
            truncated = len(db_data) > MAX_LLM_ROWS or len(data_json) > MAX_JSON_CHARS

            if len(data_json) > MAX_JSON_CHARS:
                # Karakter sınırı aşılmışsa satır sayısını da azalt
                data_for_llm = data_for_llm[:10]
                data_json = json.dumps(data_for_llm, ensure_ascii=False, default=str)
                truncated = True

            truncation_note = (
                f"\n[NOT: Toplam {len(db_data)} satırdan ilk {len(data_for_llm)} tanesi gösterilmektedir.]"
                if truncated else ""
            )

            # v3.9.0: Tablo formatı desteği — az veri (≤15 satır, ≤6 sütun) → markdown tablo, aksi halde madde
            row_count = len(data_for_llm)
            col_count = len(data_for_llm[0]) if data_for_llm and isinstance(data_for_llm[0], dict) else 0
            use_table_format = (row_count <= 15 and col_count <= 6)

            if use_table_format:
                format_instruction = (
                    "3. Verileri **Markdown tablo** formatında göster. Tablo başlıklarını Türkçe iş ismiyle yaz (varsa).\n"
                    "   Örnek: | Ad | Soyad | E-posta |\n"
                    "4. Tablo altına kısa bir özet cümlesi ekle (kaç kayıt bulundu vb.)."
                )
            else:
                format_instruction = (
                    "3. Verileri HER ZAMAN temiz, okunaklı, maddeler (bullet points -) veya numaralı liste (1.) halinde sun.\n"
                    "4. Her sonuç için: `- **(Sütun Adı)**: (Değer)` şeklinde madde oluştur.\n"
                    "5. Sonuçlar çok fazlaysa, özet tablo ve kilit bilgilere odaklan."
                )

            system_prompt = (
                "Sen kıdemli bir veri asistanı ve raporlama uzmanısın. Kullanıcının sorusuna, "
                "veritabanından dönen aşağıdaki JSON sonuçlarına göre doğal, profesyonel ve modern "
                "(SaaS hissi veren UX) bir formatta yanıt vereceksin.\n\n"
                "KURALLAR:\n"
                "1. Çok önemli: Veri boşsa ([]), sonucun bulunamadığını kibarca belirt ve tahmin yürütme.\n"
                "2. Yanıtına hoş bir girişle başla (Örn: 'İşte aradığınız veriler:', 'Sorgunuza ait sonuçları listeledim:' vb.).\n"
                f"{format_instruction}\n"
                "6. YALNIZCA aşağıdaki JSON verisindeki sütun ve değerleri kullan. Kendi bilgini KESİNLİKLE ekleme!\n\n"
                f"Sorgulanan Kaynak: {source_name}{truncation_note}\n"
                f"Veritabanı SQL Sonucu (JSON):\n{data_json}"
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ]

            full_content = ""
            try:
                from app.core.llm import call_llm_api_stream
                stream_gen = call_llm_api_stream(messages)

                for token in stream_gen:
                    full_content += token
                    yield {"type": "token", "data": token}

                # SQL footer artık frontend'de buton olarak gösterilir (metadata.sql_executed)
                # İnline metin olarak eklenmez — temiz yanıt akışı

            except Exception as llm_err:
                log_warning(f"DB-Only Yanıt Sentezi Hatası: {llm_err}", "deep_think")
                full_content = (
                    f"✅ Sorgu başarıyla çalıştırıldı: **{len(db_data)} kayıt** bulundu.\n\n"
                    f"*(Yanıt formatlanırken hata oluştu.)*\n\nSQL: `{sql_executed}`"
                )
                yield {"type": "token", "data": full_content}

            log_system_event(
                "INFO",
                f"DB-Only: {len(db_data)} satır, {elapsed_ms:.0f}ms | SQL: {sql_executed[:80]}",
                "deep_think", user_id
            )

            # ── 9. Cache: Başarılı sonucu cache'e yaz ────────────────────
            if not from_cache:
                _cache_set(cache_key, {
                    "sql": sql_executed,
                    "source_id": source["id"],
                    "dialect": dialect,
                })

            # Export için ham veri — JSON-safe'e çevir (Oracle Decimal/date/LOB vb. için)
            try:
                safe_raw_data = json.loads(json.dumps(db_data[:100], ensure_ascii=False, default=str))
            except Exception:
                safe_raw_data = []

            yield {"type": "done", "data": {
                "content": full_content,
                "metadata": {
                    "db_only": True,
                    "deep_think": True,
                    "db_routing": True,
                    "sql": sql_executed,
                    "sql_executed": sql_executed,
                    "row_count": len(db_data),
                    "rows_shown": len(data_for_llm),
                    "source_db": source_name,
                    "ml_context_used": bool(ml_context),
                    "processing_time_ms": elapsed_ms,
                    "company_id": company_id,
                    "retry_count": retry_count,
                    "from_cache": from_cache,
                    "columns": exec_result.columns or [],
                    "raw_data": safe_raw_data,  # Export için ham veri (JSON-safe)
                }
            }}

            # ── 10. v4.0: Follow-up Önerileri ───────────────────────────────
            # v3.28.8: sql_executed iletilir — fonksiyon FROM tablosunu çıkarıp
            # gerçek kolonlardan öneri üretsin (aggregate result alias'ları değil).
            try:
                followups = _generate_followup_suggestions(query, db_data, schema_ctx, sql_executed)
                if followups:
                    yield {"type": "followup", "data": {"suggestions": followups}}
            except Exception as _fu_err:
                log_warning(f"DB-Only: Follow-up üretim hatası: {_fu_err}", "deep_think")

        except Exception as e:
            import traceback as _tb
            _detail = _tb.format_exc()
            log_error(f"DB Only stream hatasi: {e}", "deep_think", error_detail=_detail)
            # v3.8.0 Error Sanitization: Kullanıcıya teknik detay gösterme
            yield {"type": "done", "data": {
                "content": (
                    "Sorgu çalıştırılırken beklenmeyen bir hata oluştu.\n\n"
                    "Lütfen birkaç dakika sonra tekrar deneyin. "
                    "Sorun devam ederse sistem yöneticinize başvurun."
                ),
                "metadata": {"db_only": True, "error": True, "error_type": type(e).__name__}
            }}

# =====================================================
# FAQ/Query Cache (v3.10.0)
# =====================================================

from collections import OrderedDict
import hashlib as _hashlib
import re as _re_cache
import threading as _threading

_SQL_QUERY_CACHE_MAX = 128  # Max cache entry sayısı
_SQL_QUERY_CACHE: OrderedDict = OrderedDict()
_SQL_CACHE_LOCK = _threading.Lock()


def _make_cache_key(query: str, company_id: int = None) -> str:
    """
    Sorgu + firma ID'sinden cache key üretir.
    Normalize: küçük harf, fazla boşluk temizle, Türkçe karakter düzleştirme.
    """
    normalized = query.strip().lower()
    normalized = _re_cache.sub(r'\s+', ' ', normalized)
    raw = f"{normalized}|company={company_id or 0}"
    return _hashlib.md5(raw.encode("utf-8")).hexdigest()


def _cache_set(key: str, value: dict):
    """LRU cache'e yaz. Max boyuta ulaşınca en eski entry'yi sil. Thread-safe."""
    with _SQL_CACHE_LOCK:
        if key in _SQL_QUERY_CACHE:
            _SQL_QUERY_CACHE.move_to_end(key)
        _SQL_QUERY_CACHE[key] = value
        while len(_SQL_QUERY_CACHE) > _SQL_QUERY_CACHE_MAX:
            _SQL_QUERY_CACHE.popitem(last=False)


def invalidate_sql_cache(company_id: int = None, source_id: int = None):
    """
    Cache'i temizler. company_id veya source_id verilirse sadece ilgili entry'leri siler.
    Schema değişikliği veya admin onay sonrası çağrılır. Thread-safe.
    """
    with _SQL_CACHE_LOCK:
        if company_id is None and source_id is None:
            _SQL_QUERY_CACHE.clear()
            return

        keys_to_delete = []
        for k, v in list(_SQL_QUERY_CACHE.items()):
            if source_id and v.get("source_id") == source_id:
                keys_to_delete.append(k)
                continue
            if company_id and v.get("company_id") == company_id:
                keys_to_delete.append(k)
        for k in keys_to_delete:
            del _SQL_QUERY_CACHE[k]


# =====================================================
# FKGraph & Schema Pruning Helpers (v3.14.0)
# =====================================================

class FKGraph:
    """
    v3.14.0: FK ilişkilerinden bidirectional graf oluşturur.
    Multi-hop BFS ile seed tablolardan N-derinliğe kadar bağlı tabloları bulur.
    Steiner tree yaklaşımıyla birden fazla seed tabloyu birleştiren ara tabloları keşfeder.
    """

    def __init__(self, relationships: list):
        from collections import defaultdict
        self.adj = defaultdict(set)          # table -> {neighbor_tables}
        self.adj_full = defaultdict(set)      # schema.table -> {schema.neighbor_tables}
        self.edge_details = {}                # (from_table, to_table) -> FK detail

        for rel in relationships:
            from_parts = rel.get("from", "").lower().split(".")
            to_parts = rel.get("to", "").lower().split(".")

            from_table = from_parts[1] if len(from_parts) >= 2 else from_parts[0]
            to_table = to_parts[1] if len(to_parts) >= 2 else to_parts[0]
            from_full = f"{from_parts[0]}.{from_table}" if len(from_parts) >= 2 else from_table
            to_full = f"{to_parts[0]}.{to_table}" if len(to_parts) >= 2 else to_table

            # Bidirectional edges (short name)
            self.adj[from_table].add(to_table)
            self.adj[to_table].add(from_table)
            # Bidirectional edges (full name)
            self.adj_full[from_full].add(to_full)
            self.adj_full[to_full].add(from_full)
            # Edge details
            self.edge_details[(from_table, to_table)] = rel
            self.edge_details[(to_table, from_table)] = rel

    def bfs_expand(self, seed_tables: set, max_depth: int = 3) -> set:
        """
        Seed tablolardan BFS ile max_depth hop'a kadar bağlı tabloları bulur.

        Args:
            seed_tables: Başlangıç tabloları (short veya full name)
            max_depth: Maksimum derinlik (default: 3)

        Returns:
            Seed + komşu tabloların seti
        """
        # Normalize seed tables
        normalized_seeds = set()
        for s in seed_tables:
            s_lower = s.lower().strip()
            normalized_seeds.add(s_lower)
            if "." in s_lower:
                normalized_seeds.add(s_lower.split(".")[-1])

        visited = set(normalized_seeds)
        queue = [(t, 0) for t in normalized_seeds]

        while queue:
            table, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            # Short name neighbors
            for neighbor in self.adj.get(table, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))
            # Full name neighbors
            for neighbor in self.adj_full.get(table, set()):
                n_short = neighbor.split(".")[-1] if "." in neighbor else neighbor
                if n_short not in visited and neighbor not in visited:
                    visited.add(n_short)
                    visited.add(neighbor)
                    queue.append((n_short, depth + 1))

        return visited

    def find_join_path(self, table_a: str, table_b: str, max_depth: int = 5) -> list:
        """
        İki tablo arasındaki en kısa FK yolunu bulur (BFS shortest path).

        Returns:
            [table_a, intermediate1, intermediate2, table_b] veya [] (yol yoksa)
        """
        a = table_a.lower().split(".")[-1] if "." in table_a else table_a.lower()
        b = table_b.lower().split(".")[-1] if "." in table_b else table_b.lower()

        if a == b:
            return [a]

        visited = {a}
        queue = [(a, [a])]

        while queue:
            current, path = queue.pop(0)
            if len(path) > max_depth:
                continue
            for neighbor in self.adj.get(current, set()):
                if neighbor == b:
                    return path + [b]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return []

    def steiner_tree(self, required_tables: list, max_depth: int = 5) -> set:
        """
        Birden fazla seed tabloyu birleştiren minimum tablo seti (Steiner tree approximation).
        Gerekli tüm tabloları FK path'leri üzerinden bağlar.

        Returns:
            Tüm gerekli tablolar + ara tablolar
        """
        if len(required_tables) <= 1:
            return set(t.lower().split(".")[-1] for t in required_tables)

        # Normalize
        tables = [t.lower().split(".")[-1] if "." in t else t.lower() for t in required_tables]
        result = set(tables)

        # Her ardışık çift arasında yol bul, ara tabloları ekle
        for i in range(len(tables) - 1):
            path = self.find_join_path(tables[i], tables[i + 1], max_depth)
            result.update(path)

        return result


def _prune_schema_tables(
    all_tables: list,
    matched_tables: list,
    relationships: list,
    max_depth: int = 3,
) -> list:
    """
    v3.14.0: Multi-hop BFS ile şema tablosu listesini budar.

    Sadece eşleşen tabloları VE FK ilişkisi olan N-hop komşu tabloları döndürür.
    Eski 1-hop yaklaşım yerine FKGraph ile derinlemesine bağlantı keşfi yapar.

    Args:
        all_tables: Tüm keşfedilmiş tablolar
        matched_tables: ML'den eşleşen tablo isimleri (schema.table veya table)
        relationships: FK ilişki listesi [{from: "s.t.c", to: "s.t.c"}, ...]
        max_depth: Maksimum FK hop derinliği (default: 3)

    Returns:
        Budanmış tablo listesi
    """
    if not matched_tables or not all_tables:
        return all_tables

    # FKGraph oluştur ve multi-hop BFS uygula
    fk_graph = FKGraph(relationships)

    # Steiner tree ile tüm matched tabloları birbirine bağla (ara tabloları da dahil et)
    steiner_set = fk_graph.steiner_tree(matched_tables)

    # BFS ile her seed'den max_depth hop'a kadar genişlet
    bfs_set = fk_graph.bfs_expand(set(matched_tables), max_depth=max_depth)

    # İki seti birleştir
    allowed_set = steiner_set | bfs_set

    # İlgili tabloları filtrele
    pruned = []
    for t in all_tables:
        table_name = (t.get("name") or "").lower()
        schema_name = (t.get("schema") or "").lower()
        full_name = f"{schema_name}.{table_name}" if schema_name else table_name

        if table_name in allowed_set or full_name in allowed_set:
            pruned.append(t)

    if not pruned:
        log_warning(
            f"Schema pruning: {len(matched_tables)} ML match ile {len(all_tables)} tablo arasında "
            f"eşleşme bulunamadı (depth={max_depth}). Match: {matched_tables}",
            "deep_think"
        )
        return []

    return pruned


def _sanitize_error_for_user(error_msg: str) -> str:
    """
    v3.8.0 Fortify uyumu: SQL/DB hata mesajlarındaki teknik detayları
    temizleyerek kullanıcıya güvenli bir mesaj döndürür.
    
    - Tablo/kolon adları, SQL fragmanları → kaldırılır
    - Connection string, host/port bilgileri → kaldırılır
    - DIAGNOSTIC mesajları (LLM'in can't generate açıklaması) → korunur
    """
    import re

    if not error_msg:
        return "Bilinmeyen bir hata oluştu."

    # DIAGNOSTIC mesajları kullanıcıya gösterilebilir (LLM'in "bu soru şemada yok" açıklaması)
    if error_msg.startswith("DIAGNOSTIC") or "şemada" in error_msg.lower() or "tablo" in error_msg.lower():
        # Teknik SQL referanslarını temizle ama anlamı koru
        cleaned = re.sub(r'`[^`]+`', '', error_msg)
        cleaned = re.sub(r'"[^"]*"\."[^"]*"', '', cleaned)
        cleaned = re.sub(r'\[.*?\]\.\[.*?\]', '', cleaned)
        return cleaned.strip() or error_msg

    # Güvenlik: Teknik detay içerebilecek mesajları genel mesajla değiştir
    sensitive_patterns = [
        r'(?i)(column|relation|table)\s+"?\w+"?\s+(does not exist|not found)',
        r'(?i)syntax error',
        r'(?i)permission denied',
        r'(?i)connection refused',
        r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',  # IP adresleri
        r'(?i)(host|port|password|user)\s*=',  # Connection string parçaları
    ]

    for pattern in sensitive_patterns:
        if re.search(pattern, error_msg):
            return "Sorgunuz işlenirken teknik bir sorun oluştu. Lütfen farklı bir şekilde sormayı deneyin."

    # Uzun hata mesajlarını kes (max 200 karakter)
    if len(error_msg) > 200:
        return error_msg[:200] + "..."

    return error_msg


# =====================================================
# v4.0: DB Intent, Rapor Şablonu ve Follow-up Helpers
# =====================================================

_DB_INTENT_REPORT_KW = (
    "rapor", "analiz", "özet", "özet rapor", "istatistik", "dağılım",
    "trend", "performans", "karşılaştır", "kıyasla",
    "analiz et", "incele", "değerlendir", "breakdown", "summary", "report",
)
_DB_INTENT_AGGREGATE_KW = (
    "kaç", "toplam", "ortalama", "en fazla", "en az", "en çok", "sayısı",
    "count", "sum", "avg", "max", "min", "total", "average",
)
_DB_INTENT_TIME_KW = (
    "bu ay", "geçen ay", "bu hafta", "geçen hafta", "bu yıl", "tarih aralığı",
    "son 30 gün", "son 7 gün", "bugün", "dün", "aylık", "yıllık", "haftalık",
)
_DB_INTENT_COUNT_KW = ("kaç tane", "kaç adet", "kaç kişi", "kaç satır", "toplam kaç")


def _detect_db_intent(query: str) -> str:
    """
    Kullanıcı sorgusundan DB intent tipini tespit eder.

    Returns:
        'DB_REPORT' | 'DB_AGGREGATE' | 'DB_TIME_SERIES' | 'DB_COUNT' | 'DB_LOOKUP'
    """
    q = query.lower()
    if any(kw in q for kw in _DB_INTENT_COUNT_KW):
        return "DB_COUNT"
    if any(kw in q for kw in _DB_INTENT_TIME_KW):
        return "DB_TIME_SERIES"
    if any(kw in q for kw in _DB_INTENT_AGGREGATE_KW):
        return "DB_AGGREGATE"
    if any(kw in q for kw in _DB_INTENT_REPORT_KW):
        return "DB_REPORT"
    return "DB_LOOKUP"


def _generate_report_templates(query: str, schema_ctx: dict) -> list:
    """
    DB_REPORT intent için 2-3 rapor yaklaşımı üretir.
    Önce hızlı kural bazlı yaklaşım dener, başarısız olursa LLM kullanır.

    Returns:
        [{"title": "...", "description": "...", "hint": "..."}, ...]
    """
    tables = schema_ctx.get("tables", [])
    if not tables:
        return []

    q_lower = query.lower()

    # ── Hızlı kural bazlı şablonlar (LLM'siz, anlık) ───────────────────────
    heuristic = []

    # Zaman bazlı analiz tespiti
    time_kw = any(w in q_lower for w in ("aylık", "haftalık", "günlük", "yıllık", "tarih", "dönem", "periyot", "trend"))
    # Müşteri/kullanıcı bazlı
    customer_kw = any(w in q_lower for w in ("müşteri", "kullanıcı", "üye", "kişi", "kişisel", "bireysel"))
    # Ürün/sipariş bazlı
    order_kw = any(w in q_lower for w in ("sipariş", "fatura", "satış", "ödeme", "gelir", "ciro"))
    # İstatistik/özet
    stat_kw = any(w in q_lower for w in ("istatistik", "analiz", "özet", "performans", "kıyasla", "karşılaştır", "dağılım"))

    if time_kw or order_kw:
        heuristic.append({
            "title": "📅 Zaman Bazlı Analiz",
            "description": "Verileri aylık/günlük periyotlarla grupla ve trendi göster",
            "hint": "aylık gruplama ile toplam ve ortalama değerleri hesapla"
        })
    if customer_kw or stat_kw:
        heuristic.append({
            "title": "👥 Detaylı Özet Tablo",
            "description": "Tüm kayıtları özet halinde, sayı ve yüzdelerle listele",
            "hint": "toplam sayı, ortalama ve yüzde dağılımlarını göster"
        })
    if order_kw or stat_kw:
        heuristic.append({
            "title": "🏆 En Yüksek / En Düşük",
            "description": "Değer bazında sıralama ve en kritik kayıtları öne çıkar",
            "hint": "değere göre azalan sırada ilk 20 kaydı getir"
        })

    # Genel fallback — her zaman en az 1 şablon sun
    if not heuristic:
        heuristic = [
            {
                "title": "📊 Genel Özet",
                "description": "Tüm verileri özetleyen genel bakış tablosu",
                "hint": "toplam kayıt sayısı ve temel metrikleri göster"
            },
            {
                "title": "📋 Detaylı Liste",
                "description": "Tüm kayıtları filtresiz, tam detaylarıyla getir",
                "hint": "son 100 kaydı tüm sütunlarıyla listele"
            },
            {
                "title": "📈 Trend Analizi",
                "description": "Zaman içindeki değişim ve eğilimleri incele",
                "hint": "tarihe göre grupla, artış/azalış trendini göster"
            },
        ]

    if len(heuristic) >= 3:
        return heuristic[:3]

    # ── LLM ile zenginleştir (opsiyonel, kural bazlı şablonlar yetersizse) ──
    try:
        from app.core.llm import call_llm_api
        import json as _json
        import threading as _thr

        table_summary = "; ".join(
            f"{t.get('schema','')}.{t['name']} [{t.get('business_name_tr') or t['name']}]"
            for t in tables[:5]
        )

        prompt_messages = [
            {
                "role": "system",
                "content": (
                    "Sen bir veri analiz uzmanısın. Kullanıcının rapor isteğine göre "
                    "3 farklı analiz yaklaşımı öner. YANIT FORMATI — JSON array:\n"
                    '[{"title":"...","description":"...","hint":"..."},...]\n'
                    "Sadece JSON döndür, başka açıklama ekleme."
                ),
            },
            {
                "role": "user",
                "content": f"Kullanıcı isteği: {query}\nMevcut tablolar: {table_summary}",
            },
        ]

        result = {"raw": None}
        done_event = _thr.Event()

        def _llm_call():
            try:
                result["raw"] = call_llm_api(prompt_messages, temperature=0.4)
            except Exception:
                pass
            finally:
                done_event.set()  # Her durumda sinyali gönder (race condition yok)

        t = _thr.Thread(target=_llm_call, daemon=False)
        t.start()
        done_event.wait(timeout=8)  # Event tabanlı bekleme — güvenli senkronizasyon

        if result["raw"]:
            # Non-greedy: ilk tam JSON array bloğunu yakala, açgözlü \[.*\] yerine
            match = re.search(r'\[\s*\{.*?\}\s*\]', result["raw"], re.DOTALL)
            if match:
                try:
                    llm_templates = _json.loads(match.group(0))
                    # Schema doğrulama: her şablon title/description/hint içermeli
                    validated = [
                        t for t in llm_templates
                        if isinstance(t, dict)
                        and "title" in t and "description" in t and "hint" in t
                        and isinstance(t["title"], str) and isinstance(t["hint"], str)
                    ]
                    if validated:
                        return validated[:3]
                except (_json.JSONDecodeError, Exception):
                    pass  # LLM JSON formatı bozuk → heuristic'e dön

    except Exception as e:
        log_warning(f"_generate_report_templates LLM hata: {e}", "deep_think")

    return heuristic[:3]


def _generate_followup_suggestions(query: str, db_data: list, schema_ctx: dict, sql_executed: str = "") -> list:
    """
    v3.14.0: Sorgu sonrasında kullanıcıya konuya uygun en az 3 follow-up önerisi üretir.

    Strateji:
    1. Kural bazlı öneriler (gerçek tablo kolonlarından — tarih, sayı, status)
    2. Şema bazlı öneriler (ilişkili tablolardan derinleştirme)
    3. Kural + şema yeterli değilse LLM ile tamamla

    v3.28.8:
      - Aggregate sonuç kolonları (alias'lar) yerine asıl FROM tablosunun
        gerçek kolonları kullanılır. Tablo, sql_executed'in FROM clause'undan
        regex ile çıkarılır; bulunamazsa eski heuristic (col_names ∩ schema)
        devreye girer.
      - LLM önerilerinde raw SQL döndürme filtresi: query alanı SELECT/INSERT
        gibi anahtarla başlıyorsa öneri atılır (canlıda LLM bazen SQL üretip
        pipeline'ı kilitliyordu).

    Returns:
        [{"text": "...", "query": "..."}, ...]  — min 3, max 5 öneri
    """
    from app.core.llm import call_llm_api

    if not db_data:
        return []

    row_count = len(db_data)
    first_row = db_data[0] if db_data else {}
    col_names = list(first_row.keys()) if isinstance(first_row, dict) else []

    suggestions = []

    # v3.28.8: önce SQL'den tablo adını çıkarıp schema_ctx'te eşle.
    # Aggregate sorgularda (COUNT/AVG/SUM) result kolonları alias olur
    # ve gerçek tablo kolonu değildir — bu nedenle FROM-tablosunu bulup
    # onun columns_json içindeki gerçek kolonları kullanmamız şart.
    matched_table: dict | None = None
    try:
        if sql_executed and schema_ctx:
            _tables_ctx_sql = schema_ctx.get("tables", []) or []
            _m = re.search(r'\bFROM\s+("?[\w\.]+"?)', sql_executed, re.IGNORECASE)
            if _m:
                _ref = _m.group(1).strip().strip('"').lower()
                _ref_tbl = _ref.split(".")[-1]
                for _t in _tables_ctx_sql:
                    if (_t.get("name") or "").lower() == _ref_tbl:
                        matched_table = _t
                        break
    except Exception:
        matched_table = None

    # v3.28.7: Öneri text/query'lerinde kullanılacak ana tablo etiketini
    # (admin_label_tr / business_name_tr / name) bir kez çöz — kural-bazlı
    # öneriler de LLM dalı gibi tablo bağlamına bağlansın.
    tbl_label: str | None = None
    if matched_table:
        tbl_label = (matched_table.get("admin_label_tr")
                     or matched_table.get("business_name_tr")
                     or matched_table.get("name"))
    try:
        if not tbl_label and schema_ctx and col_names:
            _tables_ctx = schema_ctx.get("tables", []) or []
            _col_lc = {c.lower() for c in col_names}
            _matched: list[tuple[int, dict]] = []
            for _t in _tables_ctx:
                _t_cols = {(c.get("name") or "").lower() for c in (_t.get("columns") or [])}
                _hits = len(_col_lc & _t_cols)
                if _hits:
                    _matched.append((_hits, _t))
            if _matched:
                _matched.sort(key=lambda x: x[0], reverse=True)
                matched_table = matched_table or _matched[0][1]
                _lbl = (_matched[0][1].get("admin_label_tr")
                        or _matched[0][1].get("business_name_tr")
                        or _matched[0][1].get("name"))
                if _lbl:
                    tbl_label = _lbl
    except Exception:
        pass

    # ── 1. Kural bazlı öneriler ────────────────────────────────────────
    # v3.28.8: önce gerçek tablonun kolonları (matched_table.columns) üzerinden
    # tespit yap. Bulunamadıysa eski fallback (result-set first_row.keys()).
    _id_like = ("id", "code", "no", "kod", "year", "yil", "yıl")

    real_cols: list[dict] = []
    if matched_table:
        real_cols = matched_table.get("columns") or []

    if real_cols:
        # tip + isim heuristic'i — type bilgisi varsa onu önce kullan
        _numeric_types = ("int", "float", "numeric", "decimal", "double", "real", "bigint", "smallint", "money")
        _date_types = ("date", "time", "timestamp", "datetime")
        date_cols = []
        numeric_cols = []
        status_cols = []
        for _c in real_cols:
            _cname = _c.get("name") or ""
            _ctype = str(_c.get("type") or "").lower()
            if not _cname:
                continue
            _cl = _cname.lower()
            if any(t in _ctype for t in _date_types) or any(kw in _cl for kw in (
                "tarih", "date", "time", "created", "updated", "zaman", "period"
            )):
                date_cols.append(_cname)
            elif any(t in _ctype for t in _numeric_types) and not any(kw in _cl for kw in _id_like):
                numeric_cols.append(_cname)
            if any(kw in _cl for kw in (
                "status", "durum", "stat", "state", "tip", "type", "kategori", "category"
            )):
                status_cols.append(_cname)
    else:
        # Fallback: aggregate sonuç kolonlarından heuristic (eski davranış)
        date_cols = [c for c in col_names if any(
            kw in c.lower() for kw in ("tarih", "date", "time", "created", "updated", "zaman", "period")
        )]
        numeric_cols = [
            c for c in col_names
            if isinstance(first_row, dict) and isinstance(first_row.get(c), (int, float))
            and not any(kw in c.lower() for kw in _id_like)
        ]
        status_cols = [c for c in col_names if any(
            kw in c.lower() for kw in ("status", "durum", "stat", "state", "tip", "type", "kategori", "category")
        )]

    # v3.27.1: Önerileri tablo şemasına bağla — metin ve query gerçek kolon adlarını içersin.
    # v3.28.7: Tablo etiketi de hem text hem query'ye enjekte edilir (alakasız öneri bug-fix).
    _tbl_text_pref = f"{tbl_label} — " if tbl_label else ""
    _tbl_query_pref = f"{tbl_label} tablosunda " if tbl_label else f"{query} — "

    if date_cols:
        dc = date_cols[0]
        suggestions.append({
            "text": f"📈 {_tbl_text_pref}{dc} alanına göre aylık trend",
            "query": f"{_tbl_query_pref}{dc} alanını aylık grupla, trend olarak göster"
        })

    if numeric_cols:
        nc = numeric_cols[0]
        suggestions.append({
            "text": f"📊 {_tbl_text_pref}{nc} için toplam ve ortalama",
            "query": f"{_tbl_query_pref}{nc} alanının toplam, ortalama, min ve max değerlerini hesapla"
        })

    if status_cols:
        status_col = status_cols[0]
        suggestions.append({
            "text": f"📋 {_tbl_text_pref}{status_col} bazında dağılım",
            "query": f"{_tbl_query_pref}{status_col} kolonuna göre grupla ve sayıları göster"
        })

    if row_count >= 10 and numeric_cols:
        nc = numeric_cols[0]
        suggestions.append({
            "text": f"🔝 {_tbl_text_pref}{nc} alanına göre en yüksek 10 kayıt",
            "query": f"{_tbl_query_pref}{nc} alanına göre azalan sırala ve ilk 10'u göster"
        })

    if date_cols and numeric_cols:
        dc = date_cols[0]
        suggestions.append({
            "text": f"📅 {_tbl_text_pref}{dc} ile son 7 gün karşılaştırma",
            "query": f"{_tbl_query_pref}{dc} alanı üzerinden son 7 günle önceki 7 günü karşılaştır"
        })

    # ── 2. Şema bazlı öneriler (ilişkili tablolardan) ──────────────────
    if schema_ctx and len(suggestions) < 4:
        tables = schema_ctx.get("tables", [])
        rels = schema_ctx.get("relationships", [])

        # Kullanılan tablo isimlerini tespit et.
        # v3.32.0: Aggregate sorgularda (COUNT/AVG/SUM) col_names = ['TOPLAM_MUSTERI']
        # gibi alias'lar olur ve hiçbir tablonun gerçek kolonuyla eşleşmez → eskiden
        # used_tables boş kalıyor, FK komşusu önerileri hiç üretilmiyordu. Önce
        # FROM-tablosundan resolve edilmiş matched_table varsa onu doğrudan seed et;
        # ardından col_names heuristic'i ek tabloları bulmaya devam etsin.
        used_tables = set()
        if matched_table:
            _mt_name = (matched_table.get("name") or "").lower()
            if _mt_name:
                # v3.32.0 M3 fix: matched_table.name şema ön-eki içerebilir
                # (örn. "HR.EMPLOYEES"), ama FK rel'lerde sadece tablo adıyla
                # compare edilir → schema'sız son segmenti de ekle.
                used_tables.add(_mt_name)
                if "." in _mt_name:
                    used_tables.add(_mt_name.rsplit(".", 1)[-1])
        for t in tables:
            t_name = (t.get("name") or "").lower()
            for col in col_names:
                if col.lower() in [c.get("name", "").lower() for c in t.get("columns", [])]:
                    used_tables.add(t_name)
                    break

        # FK komşuları üzerinden derinleştirme önerisi
        for rel in rels[:20]:
            from_parts = rel.get("from", "").lower().split(".")
            to_parts = rel.get("to", "").lower().split(".")
            from_table = from_parts[1] if len(from_parts) >= 2 else from_parts[0]
            to_table = to_parts[1] if len(to_parts) >= 2 else to_parts[0]

            related_table = None
            if from_table in used_tables and to_table not in used_tables:
                related_table = to_table
            elif to_table in used_tables and from_table not in used_tables:
                related_table = from_table

            if related_table:
                # İlişkili tablonun iş adını bul
                bname = related_table
                for t in tables:
                    if (t.get("name") or "").lower() == related_table:
                        bname = t.get("admin_label_tr") or t.get("business_name_tr") or related_table
                        break
                suggestions.append({
                    "text": f"🔗 {_tbl_text_pref}{bname} detayıyla birleştir",
                    "query": f"{_tbl_query_pref}{bname} tablosu ile JOIN yaparak detay ekle"
                })
                if len(suggestions) >= 5:
                    break

    # ── 3. LLM ile tamamla (min 3'e ulaşamadıysa veya tablo etiketi çözülemediyse) ─
    # v3.28.7: tbl_label None ise kural-bazlı öneriler tablo bağlamından yoksun olur;
    # LLM yedek zenginleştirme her zaman tetiklensin.
    if len(suggestions) < 3 or not tbl_label:
        try:
            # v3.28.8: LLM'e GERÇEK tablo kolonlarını ver — aggregate alias değil.
            if real_cols:
                _real_col_str = ", ".join(
                    f"{(c.get('name') or '')}({(c.get('type') or '?')})" for c in real_cols[:20]
                )
            else:
                _real_col_str = ", ".join(col_names[:8])
            col_sample = _real_col_str
            used_tables_list: list[str] = []
            try:
                if tbl_label:
                    used_tables_list = [tbl_label]
                elif schema_ctx:
                    tables = schema_ctx.get("tables", []) or []
                    used_set = set()
                    for t in tables:
                        t_cols = {(c.get("name") or "").lower() for c in t.get("columns", [])}
                        if any(cn.lower() in t_cols for cn in col_names):
                            label = t.get("admin_label_tr") or t.get("business_name_tr") or t.get("name")
                            if label:
                                used_set.add(label)
                    used_tables_list = sorted(used_set)[:3]
            except Exception:
                used_tables_list = []
            tables_hint = ", ".join(used_tables_list) if used_tables_list else "(belirtilmedi)"
            sample_row_str = ""
            try:
                if isinstance(first_row, dict):
                    items = list(first_row.items())[:6]
                    sample_row_str = ", ".join(f"{k}={v}" for k, v in items)
            except Exception:
                pass
            # v3.28.7: hedef öneri sayısı — tbl_label çözülemediyse de en az 2 öneri iste
            _llm_need = max(2, 3 - len(suggestions))
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Sen bir veri analisti asistansın. Kullanıcının veritabanı sorgusuna "
                        f"ilişkin {_llm_need} adet kısa follow-up soru öner. "
                        "Sorular kullanıcının SORGULADIĞI TABLO/KOLON adlarına doğrudan referans "
                        "vermeli; generic 'trend göster' gibi değil, hem TABLO ADI hem kolon adı "
                        "içermeli. Türkçe.\n\n"
                        "ÖNEMLİ KURALLAR:\n"
                        "1) ASLA SQL ifadesi (SELECT/INSERT/UPDATE/DELETE/FROM/WHERE/JOIN) YAZMA. "
                        "Sadece doğal dilde Türkçe soru/komut yaz.\n"
                        "2) 'Dönen veri kolonları' aggregate alias olabilir (örn. 'problem_kayit_sayisi') — "
                        "bunları KULLANMA. Yalnızca aşağıdaki GERÇEK TABLO KOLONLARI listesinden "
                        "kolon adı seç.\n"
                        "3) Tablo adı ve kolon adı GERÇEK olmalı, uydurma — listede yoksa kullanma.\n\n"
                        "YANIT FORMATI — JSON array:\n"
                        '[{"text":"📋 Kısa buton etiketi (tablo + gerçek kolon, max 8 kelime)","query":"Doğal dilde Türkçe sorgu metni — tablo adıyla"},...]\n'
                        "Sadece JSON döndür."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Kullanıcının sorusu: {query}\n"
                        f"İlgili tablo etiketi: {tables_hint}\n"
                        f"GERÇEK TABLO KOLONLARI (öneride bunları kullan): {col_sample}\n"
                        f"Örnek satır (yalnız bağlam için): {sample_row_str or '(boş)'}\n"
                        f"Satır sayısı: {row_count}"
                    ),
                },
            ]
            raw = call_llm_api(messages, temperature=0.3)
            if raw:
                import json as _json
                match = re.search(r'\[.*\]', raw, re.DOTALL)
                if match:
                    llm_suggestions = _json.loads(match.group(0))
                    # v3.28.8: raw SQL içerikli önerileri filtrele — LLM bazen
                    # query alanına "SELECT MIN(tarih)..." gibi SQL döküyordu;
                    # pipeline'a girince intent-extraction fail edip cevap üretmez.
                    _sql_kw = re.compile(
                        r'^\s*(SELECT|INSERT|UPDATE|DELETE|WITH|MERGE|TRUNCATE|DROP|CREATE)\b',
                        re.IGNORECASE,
                    )
                    _filtered: list = []
                    for _s in llm_suggestions:
                        if not isinstance(_s, dict):
                            continue
                        _q = (_s.get("query") or "").strip()
                        _t = (_s.get("text") or "").strip()
                        if not _q or not _t:
                            continue
                        if _sql_kw.match(_q) or _sql_kw.match(_t):
                            log_warning(
                                f"_generate_followup_suggestions: SQL içerikli öneri atıldı: {_q[:80]}",
                                "deep_think",
                            )
                            continue
                        _filtered.append(_s)
                    suggestions.extend(_filtered[:_llm_need])
        except Exception as e:
            log_warning(f"_generate_followup_suggestions LLM hata: {e}", "deep_think")

    # v3.28.8: Final filtre — kural/şema dallarında da raw-SQL geçmesin
    _sql_kw_final = re.compile(
        r'^\s*(SELECT|INSERT|UPDATE|DELETE|WITH|MERGE|TRUNCATE|DROP|CREATE)\b',
        re.IGNORECASE,
    )
    suggestions = [
        s for s in suggestions
        if isinstance(s, dict)
           and s.get("text") and s.get("query")
           and not _sql_kw_final.match((s.get("query") or "").strip())
           and not _sql_kw_final.match((s.get("text") or "").strip())
    ]

    # Deduplicate ve sınırla
    seen = set()
    unique = []
    for s in suggestions:
        key = s.get("text", "")
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique[:5]


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
