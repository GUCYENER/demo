"""
VYRA Deep Think - Formatting Module
====================================
Format instructions, post-processing, and RAG result parsing.
v2.30.1: deep_think_service.py'den ayrıştırıldı
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional
import re

from app.services.deep_think.types import IntentType, IntentResult


class DeepThinkFormattingMixin:
    """Format-related methods for DeepThinkService (Mixin pattern)."""

    def _clean_prompt_leak(self, response: str) -> str:
        """
        🔧 v2.33.2: LLM yanıtından sızan prompt talimatlarını temizler.
        
        LLM bazen system/user prompt içeriğini yanıta kopyalayabiliyor.
        Bu metod bilinen kalıpları regex ile tespit edip temizler.
        """
        import re
        
        cleaned = response
        
        # Çok satırlı blok kalıpları (önce bunları temizle)
        block_patterns = [
            r'ÖNEMLİ:\s*\n(?:\s*\d+\.\s+.*\n?){1,10}',         # ÖNEMLİ: 1. 2. 3. ...
            r'FORMAT TALİMATI:[\s\S]*?(?=\n📋|\n🎯|\n🔴|\n📖|\n\d+\.|\Z)',  # FORMAT TALİMATI bloğu
            r'⚠️\s*KRİTİK KURALLAR:[\s\S]*?(?=\n📋|\n🏷️|\n\d+\.|\Z)',     # KRİTİK KURALLAR bloğu
            r'KULLANICI SORUSU:.*?\n---',                         # Soru kopyası
            r'SORU:.*?\n---',                                     # Kısa soru kopyası
            r'BİLGİ TABANI İÇERİĞİ.*?\n---',                    # Context kopyası
        ]
        
        for pattern in block_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.DOTALL | re.IGNORECASE)
        
        # Tek satır talimat leak kalıpları
        line_patterns = [
            r'^.*SADECE yukarıdaki bilgi tabanı içeriğini kullan.*$',
            r'^.*Bilgi tabanında olmayan şeyleri UYDURMA.*$',
            r'^.*Tüm ilgili bilgileri dahil et.*hiçbirini atlama.*$',
            r'^.*Kaynak dosya adlarını belirt.*$',
            r'^.*Türkçe yanıt ver.*$',
            r'^.*Türkçe ve profesyonel bir dil kullan.*$',
            r'^.*Alakasız sonuçları filtrele.*$',
        ]
        
        for pattern in line_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.MULTILINE | re.IGNORECASE)
        
        # Ardışık boş satırları temizle (3+ → 2)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        
        return cleaned.strip()


    def _get_format_instruction(self, intent: IntentResult) -> str:
        """Intent tipine göre format talimatı döndürür."""
        if intent.intent_type == IntentType.LIST_REQUEST:
            # 🆕 v2.29.8: Modern SaaS format - inline score badge
            target_cat = self._detect_target_category(intent.keywords or [])
            
            return f"""FORMAT TALİMATI:

📋 **{target_cat if target_cat else "[Kategori]"}** (X sonuç)

1. `komut_adı_1`
   ↳ Açıklama (100%)

2. `komut_adı_2`
   ↳ Açıklama (75%)

3. `komut_adı_3`
   ↳ Açıklama (50%)

⚠️ KRİTİK KURALLAR:
1. Her komut ARDIŞIK NUMARA ile başlamalı: 1., 2., 3., 4. ... (ZORUNLU!)
2. Açıklama ve skor AYNI SATIRDA olmalı: ↳ Açıklama (%skor)
3. Emoji bar (🟩🟩🟩) KULLANMA - sadece parantez içinde yüzde yaz
4. SADECE "{target_cat if target_cat else 'Kategori'}" kategorisinden sonuç göster
5. Sonunda "💡 Diğer kategorilerde de X sonuç var" belirt

📚 KAYNAKLAR bölümünde dosya adı göster"""

        elif intent.intent_type == IntentType.HOW_TO:
            return """FORMAT TALİMATI:
Profesyonel ADIM ADIM rehber hazırla:

🎯 **Amaç:** [Ne yapılacağını kısaca belirt]

📌 **Adımlar:**

  1️⃣ `Adım başlığı`
     ↳ Detaylı açıklama

  2️⃣ `İkinci adım`
     ↳ Detaylı açıklama

  3️⃣ `Üçüncü adım`
     ↳ Detaylı açıklama

💡 **İpucu:** [Varsa faydalı ipucu]
⚠️ **Dikkat:** [Varsa dikkat edilecek nokta]"""

        elif intent.intent_type == IntentType.TROUBLESHOOT:
            return """FORMAT TALİMATI:
Profesyonel SORUN GİDERME rehberi hazırla:

🔴 **Sorun:** [Sorunun net açıklaması]

🔍 **Olası Nedenler:**
  • [Neden 1]
  • [Neden 2]

✅ **Çözüm Adımları:**

  1️⃣ `İlk işlem`
     ↳ Beklenen sonuç

  2️⃣ `İkinci işlem`
     ↳ Beklenen sonuç

⚠️ **Dikkat:** [Kritik uyarılar]
📞 **Çözülmezse:** [Alternatif yöntem]"""

        elif intent.intent_type == IntentType.SINGLE_ANSWER:
            return """FORMAT TALİMATI:
Profesyonel TEKİL CEVAP hazırla:

📖 **[Konu Başlığı]**

**Tanım:** [Net ve öz açıklama]

**Kullanım:** `komut veya işlem`
  ↳ Nasıl/ne zaman kullanılır

**Örnek:** [Varsa örnek]

_Kaynak: [Dosya adı]_"""

        else:
            return """FORMAT TALİMATI:
Profesyonel yanıt hazırla:

📋 **Özet:** [Kısa özet]

**Detaylar:**
  • [Madde 1]
  • [Madde 2]

_Kaynak: [Dosya adı]_"""
    
    def _postprocess_llm_response(self, response: str, intent: IntentResult) -> str:
        """
        🆕 v2.29.11: LLM yanıtını post-process ederek numaralama düzeltir.
        
        Garanti eder:
        - Komutlar 1., 2., 3. ile numaralanır
        - Duplicate KAYNAKLAR başlığını temizler
        - v2.29.14: Daha sağlam komut tespiti
        """
        import re
        
        if intent.intent_type != IntentType.LIST_REQUEST:
            return response  # Sadece liste isteklerinde işle
        
        lines = response.split('\n')
        result_lines = []
        item_counter = 0
        seen_kaynaklar = False  # Duplicate KAYNAKLAR kontrolü
        i = 0
        
        # Atlanacak satır başlangıçları (komut DEĞİL olan satırlar)
        skip_prefixes = ('↳', '🟩', '💡', '📚', '•', '📋', '🏷️', '📌', '🎯', '⚠️', '---', '_Kaynak')
        
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            # Boş satırları doğrudan ekle
            if not stripped:
                result_lines.append(line)
                i += 1
                continue
            
            # Duplicate KAYNAKLAR kontrolü
            if '📚' in stripped and 'KAYNAKLAR' in stripped.upper():
                if seen_kaynaklar:
                    i += 1
                    continue  # Skip duplicate
                seen_kaynaklar = True
            
            # Kategori başlığı kontrolü - numarayı sıfırla
            if stripped.startswith('🏷️') or stripped.startswith('📋'):
                result_lines.append(line)
                item_counter = 0
                i += 1
                continue
            
            # Komut satırı tespiti: Birden fazla yöntemle tespit
            next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
            
            # Yöntem 1: Sonraki satır ↳ ile başlıyor
            has_arrow_next = next_line.startswith('↳')
            
            # Yöntem 2: Satır backtick komut içeriyor (LLM'in `komut` formatı)
            has_backtick_cmd = bool(re.match(r'^\s*\d*\.?\s*`[^`]+`', stripped))
            
            # Yöntem 3: Satır mevcut numara ile başlıyor ve sonraki satır puanlama içeriyor
            has_numbered_cmd = bool(re.match(r'^\s*\d+\.?\s+\S', stripped)) and (
                has_arrow_next or 
                re.search(r'\(\d+%\)', next_line) or
                re.search(r'\(\d+%\)', stripped)  # skor aynı satırda olabilir
            )
            
            is_command_line = (
                stripped and
                not any(stripped.startswith(p) for p in skip_prefixes) and
                (has_arrow_next or has_backtick_cmd or has_numbered_cmd)
            )
            
            if is_command_line:
                item_counter += 1
                # Mevcut numarayı temizle ve yenisini ekle
                cleaned = re.sub(r'^\s*\d+\.?\s*', '', line)
                result_lines.append(f"{item_counter}. {cleaned.strip()}")
                i += 1
                continue
            
            # 💡 Diğer kategorilerde satırından sonra Göster butonu ekle
            if '💡' in stripped and 'kategorilerde' in stripped.lower():
                result_lines.append(line)
                result_lines.append("<button class='show-other-categories-btn' data-shown-count='1' onclick='DialogChatModule.showOtherCategories(this)'>📋 Göster</button>")
                i += 1
                continue
            
            # Diğer satırları ekle
            result_lines.append(line)
            i += 1
        
        return '\n'.join(result_lines)
    
    def _parse_rag_results(self, results: List[Dict]) -> List[Dict]:
        """
        🆕 v2.29.14: RAG sonuçlarını parse eder ve kategorize eder.
        
        Gerçek chunk formatı: **Kategori:** Komut (aynı satırda)
        """
        import re
        parsed_items = []
        
        for r in results:
            content = r.get("content", "").strip()
            score = r.get("score", 0)
            source_file = r.get("source_file", "")
            metadata = r.get("metadata", {})
            sheet_name = metadata.get("sheet", "") if isinstance(metadata, dict) else ""
            
            lines = content.split('\n') if content else []
            first_line = lines[0] if lines else ""
            
            # Format: **Kategori Adı:** Komut
            category_match = re.match(r'\*\*([^*:]+):\*\*\s*(.+)', first_line)
            
            if category_match:
                category = category_match.group(1).strip()
                command = category_match.group(2).strip()
                
                # Açıklama ikinci satırda: **Açıklaması:** ...
                if len(lines) > 1:
                    desc_line = lines[1].strip()
                    desc_match = re.match(r'\*\*Açıklamas[ıi]:\*\*\s*(.+)', desc_line, re.IGNORECASE)
                    description = desc_match.group(1)[:80] if desc_match else desc_line[:80]
                else:
                    description = ""
            else:
                category = "Sonuçlar"
                command = first_line[:40] if first_line else content[:40]
                description = lines[1].strip()[:80] if len(lines) > 1 else ""
            
            if not command.strip():
                continue
            
            parsed_items.append({
                "category": category,
                "command": command,
                "description": description,
                "score": score,
                "source_file": source_file,
                "sheet_name": sheet_name
            })
        
        return parsed_items

