"""
VYRA L1 Support API - LLM Enhancement Module
===============================================
LLM ile bölüm iyileştirme, corrective retry, anchor protection.

İçerik:
- LLM ile düşük kaliteli bölümleri iyileştirme
- Corrective retry mekanizması (max 2 retry)
- Content Anchor extraction + re-injection
- Fix instruction builder + LLM response parser

Author: VYRA AI Team
Version: 1.0.0 (v3.3.3)
"""

import re
import json
from typing import Dict, Any, List

from app.services.logging_service import log_system_event, log_warning
from app.services.content_integrity_validator import get_integrity_validator


class LLMEnhancer:
    """
    LLM ile bölüm iyileştirme servisi.

    Özellikler:
    - Anchor extraction (kritik veri koruma)
    - Integrity validation (bütünlük doğrulama)
    - Corrective retry (düzeltici prompt ile tekrar deneme)

    Kullanım:
        enhancer = LLMEnhancer()
        sections = enhancer.llm_enhance(sections, violations, file_type, catboost_analysis)
    """

    def llm_enhance(
        self,
        sections: List[Dict[str, Any]],
        violations: List[Dict[str, Any]],
        file_type: str,
        catboost_analysis: Dict[str, Any],
        progress_callback=None
    ) -> list:
        """LLM ile düşük kaliteli bölümleri iyileştir"""
        from app.services.document_enhancer import EnhancedSection

        enhanced_sections = []
        cb_sections = catboost_analysis.get("sections", [])

        for section in sections:
            idx = section["index"]
            heading = section.get("heading", "")
            content = section.get("content", "")

            # CatBoost priority bul
            cb_info = next((s for s in cb_sections if s["index"] == idx), None)
            priority = cb_info["priority"] if cb_info else 0.5
            weakness_types = cb_info.get("weakness_types", []) if cb_info else []

            # v3.2.1: Debug loglama — karar sürecini izlemek için
            log_system_event("DEBUG",
                f"Bölüm [{idx}] '{heading[:30]}': priority={priority:.3f}, "
                f"weaknesses={weakness_types}, catboost={cb_info is not None}",
                "enhancer")

            # Priority düşükse (yani kalite yüksek) VE zayıflık yoksa değiştirme
            # v3.2.1: weakness_types varsa priority ne olursa olsun LLM'e gönder
            if priority < 0.4 and not weakness_types:
                log_system_event("DEBUG",
                    f"Bölüm [{idx}] → SKIP (priority={priority:.3f}, no weaknesses)",
                    "enhancer")
                enhanced_sections.append(EnhancedSection(
                    section_index=idx,
                    heading=heading,
                    original_text=content,
                    enhanced_text=content,
                    change_type="no_change",
                    explanation="Bu bölüm yeterli kalitede.",
                    priority=priority
                ))
                # v3.3.0 [C5]: Progress callback — "Bölüm X/Y atlandı"
                if progress_callback:
                    try:
                        progress_callback(idx + 1, len(sections), heading, "skipped")
                    except Exception:
                        pass
                continue

            # v3.3.0 [C5]: Progress callback — "Bölüm X/Y iyileştiriliyor..."
            if progress_callback:
                try:
                    progress_callback(idx + 1, len(sections), heading, "processing")
                except Exception:
                    pass

            # LLM ile iyileştir — v3.3.3 [Faz 2]: max 2 retry desteği
            MAX_ENHANCEMENT_RETRIES = 2
            try:
                llm_result = self._call_llm_for_enhancement(
                    heading=heading,
                    content=content,
                    weakness_types=weakness_types,
                    violations=violations,
                    file_type=file_type
                )

                enhanced_text = llm_result.get("enhanced_text", content)

                # ─── Content Integrity Validation ───
                validator = get_integrity_validator()
                integrity = validator.validate(
                    original=content,
                    enhanced=enhanced_text,
                    file_type=file_type,
                    weakness_types=weakness_types
                )

                # 🛡️ v3.3.3 [Faz 2]: Retry with Corrective Prompt
                # Bütünlük başarısızsa → düzeltici prompt ile tekrar dene
                retry_attempt = 0
                while not integrity.is_valid and retry_attempt < MAX_ENHANCEMENT_RETRIES:
                    retry_attempt += 1
                    log_system_event(
                        "INFO",
                        f"Bölüm [{idx}] integrity fail (skor={integrity.score:.3f}), "
                        f"retry {retry_attempt}/{MAX_ENHANCEMENT_RETRIES}...",
                        "enhancer"
                    )

                    # Progress callback: retrying durumu
                    if progress_callback:
                        try:
                            progress_callback(
                                idx + 1, len(sections), heading,
                                f"retrying_{retry_attempt}"
                            )
                        except Exception:
                            pass

                    # Düzeltici prompt ile LLM'i tekrar çağır
                    corrective_result = self._call_llm_corrective(
                        heading=heading,
                        content=content,
                        failed_enhanced_text=enhanced_text,
                        integrity_issues=integrity.issues,
                        lost_entities=integrity.lost_entities,
                        hallucinated_entities=integrity.hallucinated_entities,
                        weakness_types=weakness_types,
                        violations=violations,
                        file_type=file_type
                    )
                    enhanced_text = corrective_result.get("enhanced_text", content)
                    llm_result = corrective_result  # heading vb. güncellemesi için

                    # Yeniden validate et
                    integrity = validator.validate(
                        original=content,
                        enhanced=enhanced_text,
                        file_type=file_type,
                        weakness_types=weakness_types
                    )

                if not integrity.is_valid:
                    # Tüm denemeler başarısız → Orijinali koru
                    total_attempts = retry_attempt + 1
                    log_warning(
                        f"Bölüm [{idx}] {total_attempts} denemede de bütünlük BAŞARISIZ "
                        f"(skor={integrity.score:.3f}): {'; '.join(integrity.issues[:2])}",
                        "enhancer"
                    )
                    enhanced_sections.append(EnhancedSection(
                        section_index=idx,
                        heading=heading,  # Orijinal başlık koru
                        original_text=content,
                        enhanced_text=content,  # ORİJİNALİ KORU
                        change_type="integrity_failed",
                        explanation=(
                            f"İyileştirme reddedildi ({total_attempts} deneme) — "
                            f"{'; '.join(integrity.issues[:2])}. "
                            f"Bütünlük skoru: {integrity.score:.0%}"
                        ),
                        priority=priority,
                        violations=weakness_types,
                        integrity_score=integrity.score,
                        integrity_issues=integrity.issues + integrity.warnings
                    ))
                    if progress_callback:
                        try:
                            progress_callback(idx + 1, len(sections), heading, "error")
                        except Exception:
                            pass
                    continue

                # Bütünlük OK — iyileştirmeyi kabul et
                if retry_attempt > 0:
                    log_system_event(
                        "INFO",
                        f"Bölüm [{idx}] retry {retry_attempt} sonrası integrity BAŞARILI "
                        f"(skor={integrity.score:.3f})",
                        "enhancer"
                    )

                enhanced_sections.append(EnhancedSection(
                    section_index=idx,
                    heading=llm_result.get("heading", heading),
                    original_text=content,
                    enhanced_text=enhanced_text,
                    change_type=llm_result.get("change_type", "content_restructured"),
                    explanation=(
                        llm_result.get("explanation", "LLM ile iyileştirildi.")
                        + (f" (retry {retry_attempt} sonrası başarılı)" if retry_attempt > 0 else "")
                    ),
                    priority=priority,
                    violations=weakness_types,
                    integrity_score=integrity.score,
                    integrity_issues=integrity.warnings  # Sadece uyarılar
                ))
                if progress_callback:
                    try:
                        progress_callback(idx + 1, len(sections), heading, "processing")
                    except Exception:
                        pass

            except Exception as e:
                log_warning(f"LLM enhancement hatası (bölüm {idx}): {e}", "enhancer")
                # v3.2.1: LLM hatası kullanıcıya gösterilmeli — no_change yerine llm_error
                error_msg = str(e)[:150]
                if "Failed to resolve" in error_msg or "getaddrinfo" in error_msg:
                    user_msg = "LLM API sunucusuna bağlanılamadı (DNS hatası). Ağ bağlantınızı kontrol edin."
                elif "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
                    user_msg = "LLM API yanıt zaman aşımı. Lütfen tekrar deneyin."
                elif "401" in error_msg or "403" in error_msg:
                    user_msg = "LLM API yetkilendirme hatası. API anahtarını kontrol edin."
                else:
                    user_msg = "LLM iyileştirme sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin."

                enhanced_sections.append(EnhancedSection(
                    section_index=idx,
                    heading=heading,
                    original_text=content,
                    enhanced_text=content,
                    change_type="llm_error",
                    explanation=user_msg,
                    priority=priority,
                    violations=weakness_types
                ))
                # v3.3.0 [C5]: Progress callback — hata sonrası da bildirim
                if progress_callback:
                    try:
                        progress_callback(idx + 1, len(sections), heading, "error")
                    except Exception:
                        pass

        return enhanced_sections

    def _call_llm_for_enhancement(
        self,
        heading: str,
        content: str,
        weakness_types: List[str],
        violations: List[Dict[str, Any]],
        file_type: str
    ) -> Dict[str, Any]:
        """Tek bir bölüm için LLM'e iyileştirme isteği gönder"""
        from app.core.llm import call_llm_api

        # v3.3.0: Akıllı kırpma — heading/ayıraç bazlı kesim noktası
        max_content_chars = 6000
        remaining_text = ""
        context_overlap = ""  # LLM'e bağlam olarak gönderilecek kırpılan kısmın son 300 karakteri

        if len(content) > max_content_chars:
            # Öncelik 1: Heading veya bölüm ayracından kes
            heading_cut_patterns = [
                r'\n\d+[\.\\)]\s+\S',       # 1. veya 1) ile başlayan satır
                r'\n[A-ZÇĞİÖŞÜ]{4,}',     # TAMAMEN BÜYÜK HARF satır
                r'\n---+',                   # --- ayıraç
                r'\n#{1,3}\s',              # Markdown heading
                r'\n(?:BÖLÜM|MADDE|KISIM)\s', # Türkçe bölüm kelimeleri
            ]

            best_cut = -1
            # max_content_chars aralığında heading ara (son %30'luk dilimde)
            search_start = int(max_content_chars * 0.7)
            search_end = max_content_chars

            for pattern in heading_cut_patterns:
                matches = list(re.finditer(pattern, content[search_start:search_end]))
                if matches:
                    # En son eşleşmeyi al (mümkün olduğunca fazla içerik gönder)
                    best_cut = search_start + matches[-1].start()
                    break

            # Öncelik 2: Paragraf sınırından kes
            if best_cut < 0:
                cut_point = content.rfind("\n\n", 0, max_content_chars)
                if cut_point > max_content_chars // 2:
                    best_cut = cut_point

            # Öncelik 3: Tek satır sonundan kes
            if best_cut < 0:
                cut_point = content.rfind("\n", 0, max_content_chars)
                if cut_point > max_content_chars // 2:
                    best_cut = cut_point

            # Son çare: karakter limitinden kes
            if best_cut < 0:
                best_cut = max_content_chars

            truncated = content[:best_cut]
            remaining_text = content[best_cut:]

            # v3.3.0: Kalan kısmın ilk 300 karakterini LLM'e context olarak gönder
            # Bu sayede LLM paragrafı yarıda bırakmaz
            context_overlap = remaining_text[:300].strip()

            log_system_event(
                "INFO",
                f"İçerik kırpıldı: {len(content)} → {len(truncated)} karakter "
                f"(heading/ayıraç bazlı kesim, kalan {len(remaining_text)} karakter orijinal korunacak)",
                "enhancer"
            )
        else:
            truncated = content

        # 🛡️ v3.3.3: Anchor Extraction — kritik verileri placeholder ile koru
        from app.services.content_anchor_service import get_anchor_service
        anchor_svc = get_anchor_service()
        anchor_result = anchor_svc.extract_anchors(truncated)
        anchored_text = anchor_result.sanitized_text
        anchor_registry = anchor_result.anchor_registry

        if anchor_result.anchor_count > 0:
            log_system_event(
                "INFO",
                f"Anchor extraction: {anchor_result.anchor_count} kritik veri korundu — {anchor_result.anchor_types}",
                "enhancer"
            )

        # Weakness'e göre talimat oluştur
        instructions = self._build_fix_instructions(weakness_types)

        violation_list = "\n".join(
            f"- {v.get('name', '')}: {v.get('detail', '')}"
            for v in violations if v.get("status") in ("fail", "warning")
        ) or "Belirgin ihlal yok."

        # v3.3.0: Context overlap bilgisini prompt'a ekle
        context_note = ""
        if context_overlap:
            context_note = f"\n\n**NOT:** Bu bölümün devamı aşağıdaki gibidir (sadece bağlam için, iyileştirmeye DAHİL ETMEYİN):\n{context_overlap}...\n"

        # 🛡️ v3.3.3 [Faz 3]: Structured Prompt — Fenced Critical Blocks
        anchor_note = ""
        if anchor_registry:
            # Anchor ID'lerini listele — LLM hangi placeholder'ların dokunulmaz olduğunu bilsin
            anchor_ids_display = "  ".join(anchor_registry.keys())
            anchor_type_summary = ", ".join(
                f"{atype}: {count}" for atype, count in anchor_result.anchor_types.items()
            )
            anchor_note = (
                f"\n\n**⛔ DOKUNMA BÖLGESİ — FROZEN DATA ({anchor_result.anchor_count} adet, {anchor_type_summary}):**\n"
                "---FROZEN_START---\n"
                f"{anchor_ids_display}\n"
                "---FROZEN_END---\n\n"
                "**KURALLAR:**\n"
                "- Yukarıdaki ‹‹ANC_XXX›› placeholder'lar gerçek verileri (sayı, tarih, URL vb.) temsil eder.\n"
                "- Bu placeholder'ları AYNEN KORU — SİLME, DEĞİŞTİRME, YERİNİ DEĞİŞTİRME.\n"
                "- Placeholder'ın etrafındaki bağlam cümlesini değiştirirsen bile placeholder'ı KORU.\n"
            )

        prompt = f"""Sen bir doküman optimize uzmanısın. Aşağıdaki doküman bölümünü RAG (Retrieval-Augmented Generation) sistemi için optimize et.

**Dosya Tipi:** {file_type}
**Bölüm Başlığı:** {heading or '(Başlık yok)'}
**Tespit Edilen Sorunlar:** {', '.join(weakness_types) if weakness_types else 'Genel kalite iyileştirmesi'}

**İyileştirme Talimatları:**
{instructions}

**Maturity İhlalleri:**
{violation_list}{anchor_note}

**Orijinal İçerik:**
{anchored_text}{context_note}

**Yanıt Formatı (JSON):**
{{
    "heading": "İyileştirilmiş başlık (yoksa uygun bir başlık öner)",
    "enhanced_text": "İyileştirilmiş metin (orijinal yapıyı koru, sadece sorunları düzelt)",
    "change_type": "heading_added|content_restructured|table_fixed|encoding_fixed|formatting_improved",
    "explanation": "Yapılan değişikliklerin kısa açıklaması (Türkçe)"
}}

**KRİTİK KURALLAR:**
- Orijinal metnin ANLAMINI ve İÇERİĞİNİ koru
- Yapısal iyileştirme yap: başlık ekleme, paragraf düzenleme, format düzeltme, bölümlendirme
- İçerik iyileştirme yap: yazım/imla düzeltme, cümle netliği artırma, tutarsızlıkları giderme
- ASLA kendi yorumunu, açıklamanı veya ek bilgi EKLEME
- ASLA "Not:", "Açıklama:", "Yorum:", "Dipnot:" gibi meta-tekstler ekleme
- ASLA orijinal bilgiyi silme — sadece daha iyi ifade et
- Yanıtı SADECE JSON formatında ver, başka hiçbir metin ekleme"""

        messages = [
            {"role": "system", "content": "Sen doküman optimizasyon uzmanısın. Yanıtlarını SADECE JSON formatında ver."},
            {"role": "user", "content": prompt}
        ]

        response = call_llm_api(messages)

        # JSON parse
        result = self._parse_llm_response(response, heading, content)

        # 🛡️ v3.3.3: Anchor Re-injection + Recovery
        if anchor_registry:
            enhanced_text = result.get("enhanced_text", "")
            # Adım 1: Placeholder'ları orijinal değerlerle değiştir
            enhanced_text = anchor_svc.reinject_anchors(enhanced_text, anchor_registry)
            # Adım 2: LLM'in sildiği anchor'ları kurtarıp geri ekle
            enhanced_text, recovered = anchor_svc.recover_missing(
                enhanced_text, anchor_registry, truncated
            )
            result["enhanced_text"] = enhanced_text

            if recovered:
                result["explanation"] = (
                    result.get("explanation", "") +
                    f" (⚠ {len(recovered)} kayıp veri otomatik kurtarıldı)"
                )

        # v3.3.0: Kırpılan içeriği enhanced text'e ekle — yumuşak geçiş
        if remaining_text:
            enhanced_part = result.get("enhanced_text", "")
            # Birleşim noktasında çift newline ile temiz geçiş sağla
            result["enhanced_text"] = enhanced_part.rstrip() + "\n\n" + remaining_text.lstrip()
            result["explanation"] = (result.get("explanation", "") +
                f" (İlk {len(truncated)} karakter iyileştirildi, "
                f"kalan {len(remaining_text)} karakter orijinal olarak korundu)")

        return result

    # 🛡️ v3.3.3 [Faz 2]: Düzeltici Prompt ile LLM Retry
    def _call_llm_corrective(
        self,
        heading: str,
        content: str,
        failed_enhanced_text: str,
        integrity_issues: List[str],
        lost_entities: List[str],
        hallucinated_entities: List[str],
        weakness_types: List[str],
        violations: List[Dict[str, Any]],
        file_type: str
    ) -> Dict[str, Any]:
        """
        Düzeltici prompt ile LLM'i tekrar çağırır.

        Önceki iyileştirme integrity doğrulamasını geçemediyse,
        hataları ve kayıp verileri LLM'e göstererek düzeltme ister.
        Anchor extraction + re-injection dahildir.
        """
        from app.core.llm import call_llm_api
        from app.services.content_anchor_service import get_anchor_service

        # Anchor extraction — orijinal metinden (kırpılmış)
        # v3.3.3 [Code Review Fix]: Uzun içerikler için kırpma uygula
        max_content_chars = 6000
        if len(content) > max_content_chars:
            # Basit kırpma — retry'da karmaşık heading kesimi gereksiz
            cut_point = content.rfind("\n\n", 0, max_content_chars)
            if cut_point < max_content_chars // 2:
                cut_point = content.rfind("\n", 0, max_content_chars)
            if cut_point < max_content_chars // 2:
                cut_point = max_content_chars
            working_content = content[:cut_point]
        else:
            working_content = content

        anchor_svc = get_anchor_service()
        anchor_result = anchor_svc.extract_anchors(working_content)
        anchored_text = anchor_result.sanitized_text
        anchor_registry = anchor_result.anchor_registry

        # Hata özetini oluştur
        issues_text = "\n".join(f"- {issue}" for issue in integrity_issues[:5])

        lost_text = ", ".join(lost_entities[:10]) if lost_entities else "Belirtilmedi"

        hallucinated_text = ""
        if hallucinated_entities:
            hallucinated_text = (
                f"\n\n**EKLENEN SAHTE VERİLER (BUNLARI KALDIRMALISIN):**\n"
                f"{', '.join(hallucinated_entities[:5])}"
            )

        # Anchor bilgisi
        anchor_note = ""
        if anchor_registry:
            anchor_note = (
                "\n\n**⛔ KRİTİK VERİ KORUMA:**\n"
                "Metindeki ‹‹ANC_XXX›› formatındaki placeholder'lar gerçek verileri temsil eder.\n"
                "Bu placeholder'ları AYNEN KORU, SİLME, DEĞİŞTİRME. Yerlerini değiştirme.\n"
            )

        prompt = f"""⚠️ ÖNCEKİ İYİLEŞTİRMENDE CİDDİ HATALAR TESPİT EDİLDİ.
Lütfen orijinal metni BAZ ALARAK tekrar iyileştir. Bu sefer aşağıdaki hataları YAPMA.

**TESPİT EDİLEN HATALAR:**
{issues_text}

**KAYIP/DEĞİŞTİRİLEN VERİLER:**
{lost_text}{hallucinated_text}

**ORİJİNAL İÇERİK (BUNU BAZ AL):**
{anchored_text}{anchor_note}

**Dosya Tipi:** {file_type}
**Bölüm Başlığı:** {heading or '(Başlık yok)'}

**KRİTİK KURALLAR (BU SEFER MUTLAKA UYULMALIDIR):**
1. Orijinal metindeki TÜM sayıları (1.234,56 gibi) AYNEN koru — format değiştirme
2. TÜM tarihleri, URL'leri, email adreslerini AYNEN koru
3. ASLA orijinalde olmayan yeni bilgi, sayı veya isim EKLEME
4. ASLA "Not:", "Açıklama:", "Yorum:" gibi meta-tekstler ekleme
5. Sadece yapısal iyileştirme yap: başlık, paragraf, format düzenleme
6. ‹‹ANC_XXX›› placeholder'larını AYNEN BIRAK, silme

**Yanıt Formatı (JSON):**
{{
    "heading": "İyileştirilmiş başlık",
    "enhanced_text": "İyileştirilmiş metin",
    "change_type": "content_restructured",
    "explanation": "Yapılan düzeltmelerin açıklaması"
}}"""

        messages = [
            {
                "role": "system",
                "content": (
                    "Sen doküman optimizasyon uzmanısın. ÖNCEKİ denemende bütünlük hataları yapıldı. "
                    "Bu sefer ÇOK DİKKATLİ ol — orijinal verileri ASLA silme veya değiştirme. "
                    "Yanıtını SADECE JSON formatında ver."
                )
            },
            {"role": "user", "content": prompt}
        ]

        response = call_llm_api(messages)
        result = self._parse_llm_response(response, heading, content)

        # Anchor re-injection + recovery
        if anchor_registry:
            enhanced_text = result.get("enhanced_text", "")
            # Adım 1: Placeholder → orijinal değer
            enhanced_text = anchor_svc.reinject_anchors(enhanced_text, anchor_registry)
            # Adım 2: Kayıp anchor'ları kurtarıp geri ekle
            enhanced_text, recovered = anchor_svc.recover_missing(
                enhanced_text, anchor_registry, working_content
            )
            result["enhanced_text"] = enhanced_text

            if recovered:
                result["explanation"] = (
                    result.get("explanation", "") +
                    f" (⚠ retry: {len(recovered)} kayıp veri otomatik kurtarıldı)"
                )

        log_system_event(
            "DEBUG",
            f"Corrective LLM çağrısı tamamlandı: heading='{heading[:30]}'",
            "enhancer"
        )

        return result

    def _build_fix_instructions(self, weakness_types: List[str]) -> str:
        """Weakness tipine göre spesifik iyileştirme talimatları"""
        instructions = []

        instruction_map = {
            "heading_missing": "- Bu bölümün uygun bir başlığı yok. İçeriğe uygun, kısa ve açıklayıcı bir Heading ekle.",
            "content_too_short": "- İçerik çok kısa. Mevcut bilgiyi daha açıklayıcı hale getir (ama yeni bilgi EKLEME).",
            "table_format_issue": "- Tablo formatı bozuk. Sütun başlıklarını netleştir, hücre hizalamasını düzelt.",
            "encoding_issue": "- Türkçe karakter encoding sorunu var. Bozuk karakterleri (Ã¼→ü, Ã§→ç, Ã¶→ö, Ä±→ı, ÅŸ→ş) düzelt.",
            "structure_weak": "- Başlık hiyerarşisi zayıf. Alt başlıklar (##, ###) ekleyerek içeriği daha iyi yapılandır.",
            "low_density": "- Metin yoğunluğu düşük. Gereksiz boşlukları kaldır ve paragrafları birleştir.",
            "redundant_content": "- Tekrarlayan header/footer içerik var. Her bölümde tekrar eden boilerplate metinleri kaldır.",
            "excess_whitespace": "- Fazla boş satır/paragraf var. Gereksiz boşlukları temizle.",
            # Excel özel
            "header_row_missing": "- Excel'de başlık satırı eksik. İlk satırı sütun başlıkları olarak yeniden düzenle.",
            "merged_cells": "- Birleştirilmiş hücreler var. Her hücrenin kendi değerini taşıyacak şekilde yapıyı düzelt.",
            "description_rows": "- Veri tablosunun üstünde açıklama satırları var. Açıklamaları ayrı bir bölüme taşı veya kaldır.",
            "empty_gaps": "- Veri blokları arasında boş satırlar var. Boşlukları kaldırarak sürekli bir veri akışı oluştur.",
            "inconsistent_types": "- Sütunlarda karışık veri tipleri var. Her sütunda tutarlı format kullanılmalı.",
            "formula_issue": "- Formüllü hücreler var. Formülleri değerlerine çevir (hesaplanmış sonuçları yaz).",
            "hidden_sheets": "- Gizli sayfalar var. Gizli sayfa içeriğini ana bölüme dahil et veya gereksizse kaldır.",
            # DOCX özel
            "textbox_issue": "- Metin kutuları (text box) var. İçindeki metinleri normal paragraflara dönüştür.",
            "list_format_issue": "- Manuel liste kullanılmış. Word'ün yerleşik liste stillerini kullan.",
        }

        for wt in weakness_types:
            if wt in instruction_map:
                instructions.append(instruction_map[wt])

        if not instructions:
            instructions.append("- Genel kalite iyileştirmesi: başlık yapısı, paragraf düzeni ve okunabilirliği artır.")

        return "\n".join(instructions)

    def _parse_llm_response(
        self,
        response: str,
        fallback_heading: str,
        fallback_content: str
    ) -> Dict[str, Any]:
        """LLM JSON yanıtını parse et"""

        # JSON bloğunu bul
        try:
            # Markdown code block içindeyse çıkar
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', response)
            if json_match:
                json_str = json_match.group(1).strip()
            else:
                # Direkt JSON olabilir
                json_start = response.find('{')
                json_end = response.rfind('}')
                if json_start >= 0 and json_end > json_start:
                    json_str = response[json_start:json_end + 1]
                else:
                    raise ValueError("JSON bulunamadı")

            result = json.loads(json_str)

            return {
                "heading": result.get("heading", fallback_heading),
                "enhanced_text": result.get("enhanced_text", fallback_content),
                "change_type": result.get("change_type", "content_restructured"),
                "explanation": result.get("explanation", "LLM ile iyileştirildi.")
            }

        except (json.JSONDecodeError, ValueError) as e:
            log_system_event("DEBUG", f"LLM JSON parse fallback: {e}", "enhancer")
            # Fallback: ham yanıtı kullan
            return {
                "heading": fallback_heading,
                "enhanced_text": response.strip() if len(response.strip()) > 20 else fallback_content,
                "change_type": "content_restructured",
                "explanation": "LLM yanıtı yapılandırılamadı, ham iyileştirme uygulandı."
            }
