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
        
        # 🆕 v2.57.0: Veritabanı sorgusu kontrolü (Hybrid Router)
        try:
            from app.services.hybrid_router import detect_db_intent
            db_intent_type = detect_db_intent(query)
            if db_intent_type is not None:
                return IntentResult(
                    intent_type=db_intent_type,
                    confidence=0.7,
                    suggested_n_results=10,
                    reasoning="Veritabanı sorgusu intent'i tespit edildi"
                )
        except ImportError:
            pass  # Hybrid router henüz yüklenmemişse atla
        
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
        v3.4.0: RAG chunk metadata'sından görselleri toplar.
        DRY helper — CatBoost BYPASS, Hybrid, LLM Sentez akışlarında ortak kullanılır.
        
        Returns:
            (image_ids: list, heading_image_map: dict)
        """
        heading_map = {}
        image_ids = []
        seen = set()
        primary_source = None
        best_score = 0.0
        
        for r in rag_results:
            s = r.get("score", 0)
            if s > best_score:
                best_score = s
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
                if isinstance(img_id, int) and img_id not in seen:
                    seen.add(img_id)
                    heading_map.setdefault(heading, []).append(img_id)
                    image_ids.append(img_id)
        
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
        
        # 🆕 v2.57.0: Hybrid Router — DB intent gelirse template SQL çalıştır
        # 🆕 v2.58.0: HYBRID intent → DB + RAG merge desteği
        if intent.intent_type in (IntentType.DATABASE_QUERY, IntentType.HYBRID) and category_index is None:
            try:
                from app.services.hybrid_router import HybridRouter
                router = HybridRouter()
                hybrid_result = router.route(query, user_id, intent)
                
                if hybrid_result and hybrid_result.db_results:
                    if intent.intent_type == IntentType.HYBRID:
                        # 🆕 v2.58.0: HYBRID — DB + RAG birleştir
                        rag_results = self.expanded_retrieval(query, intent, user_id)
                        synthesized = self._merge_hybrid_answer(
                            query, hybrid_result, rag_results, intent
                        )
                        sources = list(set(
                            [hybrid_result.source_db or ""] +
                            [r.get("source_file", "") for r in rag_results if r.get("source_file")]
                        ))
                        sources = [s for s in sources if s]  # Boşları kaldır
                    else:
                        # DATABASE_QUERY — sadece DB sentezle
                        synthesized = self._synthesize_hybrid(query, hybrid_result, intent)
                        sources = [hybrid_result.source_db] if hybrid_result.source_db else []
                    
                    elapsed_ms = (time.time() - start_time) * 1000
                    
                    # v3.4.0: HYBRID modda RAG sonuçlarından görselleri topla
                    _hybrid_img_ids, _hybrid_h_map = [], {}
                    if intent.intent_type == IntentType.HYBRID and rag_results:
                        _hybrid_img_ids, _hybrid_h_map = self._collect_images_from_rag(rag_results)
                    
                    result = DeepThinkResult(
                        synthesized_response=synthesized,
                        sources=sources,
                        intent=intent,
                        rag_result_count=len(hybrid_result.db_results),
                        processing_time_ms=elapsed_ms,
                        best_score=0.9,
                        image_ids=_hybrid_img_ids,
                        heading_images=_hybrid_h_map
                    )
                    
                    if cache_key is not None:
                        cache_service.deep_think.set(cache_key, result)
                    
                    log_system_event(
                        "INFO",
                        f"Hybrid Router: {intent.intent_type.value} başarılı — {len(hybrid_result.db_results)} satır, "
                        f"{elapsed_ms:.0f}ms | SQL: {hybrid_result.sql_executed[:80] if hybrid_result.sql_executed else ''}",
                        "deep_think"
                    )
                    
                    # 🆕 v2.58.0: SQL Audit Log
                    try:
                        from app.services.sql_audit_log import log_sql_execution
                        log_sql_execution(
                            user_id=user_id,
                            source_id=0,
                            source_name=hybrid_result.source_db or "",
                            sql_text=hybrid_result.sql_executed or "",
                            dialect="",
                            status="success" if not hybrid_result.db_error else "error",
                            row_count=len(hybrid_result.db_results),
                            elapsed_ms=hybrid_result.elapsed_ms,
                            error_msg=hybrid_result.db_error,
                        )
                    except Exception:
                        pass  # Audit log hatası ana akışı engellememeli
                    
                    return result
                else:
                    log_system_event(
                        "INFO",
                        "Hybrid Router: DB sonucu yok, RAG fallback",
                        "deep_think"
                    )
            except Exception as hybrid_err:
                log_warning(f"Hybrid Router hatası, RAG fallback: {hybrid_err}", "deep_think")
        
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
        
        # 🆕 v2.58.0: DB intent → Hybrid Router (streaming)
        if intent.intent_type in (IntentType.DATABASE_QUERY, IntentType.HYBRID):
            try:
                from app.services.hybrid_router import HybridRouter
                router = HybridRouter()
                hybrid_result = router.route(query, user_id, intent)
                
                if hybrid_result and hybrid_result.db_results:
                    # DB sonuçları geldi sinyali
                    yield {"type": "db_complete", "data": {
                        "intent": intent.intent_type.value,
                        "row_count": len(hybrid_result.db_results),
                        "source_db": hybrid_result.source_db or "",
                        "sql": hybrid_result.sql_executed or "",
                        "elapsed_ms": hybrid_result.elapsed_ms,
                    }}
                    
                    # HYBRID: DB + RAG birleştir
                    _stream_hybrid_imgs, _stream_hybrid_hmap = [], {}
                    if intent.intent_type == IntentType.HYBRID:
                        rag_results = self.expanded_retrieval(query, intent, user_id)
                        synthesized = self._merge_hybrid_answer(
                            query, hybrid_result, rag_results, intent
                        )
                        sources = list(set(
                            [hybrid_result.source_db or ""] +
                            [r.get("source_file", "") for r in rag_results if r.get("source_file")]
                        ))
                        sources = [s for s in sources if s]
                        # v3.4.0: HYBRID modda RAG sonuçlarından görselleri topla
                        _stream_hybrid_imgs, _stream_hybrid_hmap = self._collect_images_from_rag(rag_results)
                    else:
                        synthesized = self._synthesize_hybrid(query, hybrid_result, intent)
                        sources = [hybrid_result.source_db] if hybrid_result.source_db else []
                    
                    elapsed_ms = (time.time() - start_time) * 1000
                    
                    # Cache
                    if cache_key is not None:
                        result = DeepThinkResult(
                            synthesized_response=synthesized,
                            sources=sources,
                            intent=intent,
                            rag_result_count=len(hybrid_result.db_results),
                            processing_time_ms=elapsed_ms,
                            best_score=0.9,
                            image_ids=_stream_hybrid_imgs,
                            heading_images=_stream_hybrid_hmap
                        )
                        cache_service.deep_think.set(cache_key, result)
                    
                    yield {"type": "done", "data": {
                        "content": synthesized,
                        "metadata": {
                            "rag_result_count": len(hybrid_result.db_results),
                            "best_score": 0.9,
                            "deep_think": True,
                            "hybrid_db": True,
                            "sources": sources,
                            "sql_executed": hybrid_result.sql_executed or "",
                            "image_ids": _stream_hybrid_imgs,
                            "heading_images": _stream_hybrid_hmap
                        }
                    }}
                    
                    # 🆕 v2.58.0: SQL Audit Log (streaming)
                    try:
                        from app.services.sql_audit_log import log_sql_execution
                        log_sql_execution(
                            user_id=user_id,
                            source_id=0,
                            source_name=hybrid_result.source_db or "",
                            sql_text=hybrid_result.sql_executed or "",
                            dialect="",
                            status="success" if not hybrid_result.db_error else "error",
                            row_count=len(hybrid_result.db_results),
                            elapsed_ms=hybrid_result.elapsed_ms,
                            error_msg=hybrid_result.db_error,
                        )
                    except Exception:
                        pass
                    
                    return
                else:
                    log_system_event("INFO", "Stream: DB sonucu yok, RAG fallback", "deep_think")
            except Exception as hybrid_err:
                log_warning(f"Stream Hybrid Router hatası, RAG fallback: {hybrid_err}", "deep_think")
        
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
