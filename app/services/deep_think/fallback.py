"""
VYRA Deep Think - Fallback Response Module
============================================
LLM offline/failure durumunda RAG sonuçlarını doğrudan formatlama.
v2.30.1: deep_think_service.py'den ayrıştırıldı
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional
from collections import OrderedDict
import re

from app.services.deep_think.types import IntentType, IntentResult


class DeepThinkFallbackMixin:
    """Fallback response methods for DeepThinkService (Mixin pattern)."""

    def _fallback_response(self, results: List[Dict], intent: IntentResult) -> str:
        """
        🆕 v2.29.2: LLM başarısız olursa RAG sonuçlarını akıllı filtreleme ile gösterir.
        
        Özellikler:
        - Sorgudan hedef kategori çıkarır
        - Sadece en alakalı kategoriyi gösterir
        - Diğer kategorilerin varlığını bildirir
        - Sheet adını kaynak formatına ekler
        """
        if not results:
            return "❌ Bilgi tabanında bu konuyla ilgili sonuç bulunamadı."
        
        import re
        from collections import OrderedDict
        
        # 1️⃣ Sonuçları parse et (ortak helper)
        parsed_items = self._parse_rag_results(results)
        
        # 2️⃣ Sorgudan hedef kategoriyi tespit et
        query_keywords = intent.keywords if intent.keywords else []
        query_lower = " ".join(query_keywords).lower()
        
        # Kategori öncelikleri
        target_category = None
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
                target_category = cat_name
                break
        
        # 3️⃣ Kategoriye göre grupla
        grouped = OrderedDict()
        for item in parsed_items:
            cat = item["category"]
            if cat not in grouped:
                grouped[cat] = []
            grouped[cat].append(item)
        
        # 4️⃣ En alakalı kategoriyi seç
        if target_category and target_category in grouped:
            primary_category = target_category
        else:
            # En yüksek skorlu kategoriyi bul
            cat_scores = {}
            for cat, items in grouped.items():
                cat_scores[cat] = max(item["score"] for item in items)
            primary_category = max(cat_scores, key=cat_scores.get)
        
        primary_items = grouped.get(primary_category, [])
        primary_items.sort(key=lambda x: x["score"], reverse=True)
        
        # 5️⃣ Çıktı oluştur - sadece birincil kategori
        lines = [f"📋 **{primary_category}** ({len(primary_items)} adet)\n"]
        
        for i, item in enumerate(primary_items[:15], 1):
            score_pct = int(item['score'] * 100)
            cmd = item["command"][:40]
            desc = item["description"]
            
            # 🆕 v2.29.8: Modern SaaS inline format
            if desc:
                lines.append(f"{i}. `{cmd}`\n   ↳ {desc} ({score_pct}%)")
            else:
                lines.append(f"{i}. `{cmd}` ({score_pct}%)")
        
        # 6️⃣ Diğer kategorileri bildir - interaktif buton ile
        other_categories = []
        other_category_count = 0
        for cat, items in grouped.items():
            if cat != primary_category:
                other_categories.append(cat)
                other_category_count += len(items)
        
        if other_categories:
            # 🆕 v2.29.13: Tıklanabilir göster butonu - data-shown-count ile
            cat_list = ", ".join(other_categories[:5])
            lines.append(f"\n💡 **Diğer kategorilerde de {other_category_count} sonuç var:** {cat_list}")
            lines.append(f"<button class='show-other-categories-btn' data-shown-count='1' onclick='DialogChatModule.showOtherCategories(this)'>📋 Göster</button>")
        
        # 7️⃣ Kaynak bilgisi - sheet adı ve açıklama dahil (tek satırda)
        source_info = {}  # {dosya: set(sheet_names)}
        for item in primary_items:
            sf = item.get("source_file", "")
            sn = item.get("sheet_name", "")
            if sf:
                if sf not in source_info:
                    source_info[sf] = set()
                if sn:
                    source_info[sf].add(sn)
        
        if source_info:
            lines.append("\n📚 **KAYNAKLAR**")
            for sf, sheets in source_info.items():
                if sheets:
                    sheet_str = ", ".join(sorted(sheets))
                    lines.append(f"• [{sf}] - **{sheet_str}** - {primary_category} ve açıklamaları")
                else:
                    lines.append(f"• [{sf}]")
        
        lines.append("\n_⚠️ LLM bağlantısı kurulamadı._")
        
        return "\n".join(lines)
    
    def _score_to_bar(self, score: float) -> str:
        """Skoru görsel bar'a çevirir."""
        filled = int(score * 10)
        empty = 10 - filled
        bar = "🟩" * filled + "⬜" * empty
        return f"{bar} {score:.0%}"
    
    def _next_category_response(self, results: List[Dict], intent: IntentResult, category_index: int) -> str:
        """
        🆕 v2.29.13: Sadece N. kategorideki sonuçları gösterir.
        
        Her Göster butonuna tıklandığında bir sonraki kategori gösterilir.
        Hala kategori varsa buton tekrar eklenir.
        """
        if not results:
            return "❌ Bilgi tabanında sonuç bulunamadı."
        
        from collections import OrderedDict
        
        # Sonuçları parse et (ortak helper) ve kategorize et
        parsed_items = self._parse_rag_results(results)
        grouped = OrderedDict()
        for item in parsed_items:
            cat = item["category"]
            if cat not in grouped:
                grouped[cat] = []
            grouped[cat].append(item)
        
        # Kategori listesi (sıralı)
        category_list = list(grouped.keys())
        
        # Eğer istenilen index geçerliyse
        if category_index < len(category_list):
            target_category = category_list[category_index]
            items = grouped[target_category]
            items.sort(key=lambda x: x["score"], reverse=True)
            
            output_lines = [f"🏷️ **{target_category}** ({len(items)} sonuç)\n"]
            
            for i, item in enumerate(items[:15], 1):
                score_pct = int(item['score'] * 100)
                cmd = item["command"][:40]
                desc = item["description"]
                
                if desc:
                    output_lines.append(f"{i}. `{cmd}`\n   ↳ {desc} ({score_pct}%)")
                else:
                    output_lines.append(f"{i}. `{cmd}` ({score_pct}%)")
            
            # Hala gösterilmemiş kategori var mı?
            remaining_categories = len(category_list) - category_index - 1
            if remaining_categories > 0:
                remaining_cats = ", ".join(category_list[category_index + 1:category_index + 4])
                output_lines.append(f"\n💡 **Diğer kategorilerde de sonuç var:** {remaining_cats}{'...' if remaining_categories > 3 else ''}")
                next_index = category_index + 1
                output_lines.append(f"<button class='show-other-categories-btn' data-shown-count='{next_index}' onclick='DialogChatModule.showOtherCategories(this)'>📋 Göster</button>")
            
            # Kaynak bilgisi
            source_info = {}
            for item in items:
                sf = item.get("source_file", "")
                sn = item.get("sheet_name", "")
                if sf:
                    if sf not in source_info:
                        source_info[sf] = set()
                    if sn:
                        source_info[sf].add(sn)
            
            if source_info:
                output_lines.append("\n📚 **KAYNAKLAR**")
                for sf, sheets in source_info.items():
                    if sheets:
                        sheet_str = ", ".join(sorted(sheets))
                        output_lines.append(f"• [{sf}] - **{sheet_str}** - {target_category} ve açıklamaları")
                    else:
                        output_lines.append(f"• [{sf}]")
            
            return "\n".join(output_lines)
        else:
            return "✅ Tüm kategoriler gösterildi."

