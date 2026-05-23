/**
 * VYRA Dialog Chat - Utility Functions
 * =====================================
 * Stateless yardımcı fonksiyonlar.
 * dialog_chat.js ana modülünden ayrıştırılmıştır.
 * 
 * Version: 2.0.0 (2026-02-09) - Deep Think Structured Response Formatter
 *   - Tüm Deep Think yanıt türlerini (LIST, HOW_TO, TROUBLESHOOT, SINGLE_ANSWER) destekler
 *   - Excel, DOCX, PDF, PPTX, TXT — tüm doküman türlerinden gelen yanıtlara uyumlu
 *   - Yapısal HTML üretimi: .dt-* class hiyerarşisi
 */

window.DialogChatUtils = (function () {
    'use strict';

    /**
     * ISO tarih string'ini HH:mm formatına çevirir.
     */
    function formatTime(isoString) {
        try {
            const date = new Date(isoString);
            return date.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
        } catch {
            return '';
        }
    }

    // =========================================================================
    // DEEP THINK STRUCTURED RESPONSE DETECTION
    // =========================================================================

    /**
     * İçeriğin Deep Think yapısal yanıt olup olmadığını tespit eder.
     * Tüm intent türlerini kapsar: LIST_REQUEST, HOW_TO, TROUBLESHOOT, SINGLE_ANSWER
     */
    function _isDeepThinkResponse(content) {
        const trimmed = content.trim();
        // Pattern 1: Kategori listesi (📋 ** veya 🏷️ **)
        if (/^(📋|🏷️)\s*\*\*/.test(trimmed)) return true;
        // Pattern 2: HOW_TO (🎯 **)
        if (/^🎯\s*\*\*/.test(trimmed)) return true;
        // Pattern 3: TROUBLESHOOT (🔴 **)
        if (/^🔴\s*\*\*/.test(trimmed)) return true;
        // Pattern 4: SINGLE_ANSWER (📖 **)
        if (/^📖\s*\*\*/.test(trimmed)) return true;
        // Pattern 5: Genel özet (📋 **Özet:**)
        if (/^📋\s*\*\*Özet/.test(trimmed)) return true;
        return false;
    }

    // =========================================================================
    // DEEP THINK STRUCTURED FORMATTER
    // =========================================================================

    /**
     * Inline metin formatlaması: **bold**, `code`, [link](url)
     */
    function _inlineFormat(text) {
        let out = escapeHtml(text);
        // Bold
        out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        // Inline code
        out = out.replace(/`([^`]+)`/g, '<code class="dt-command">$1</code>');
        return out;
    }

    /**
     * Skor değerine göre CSS class belirler.
     */
    function _getScoreClass(score) {
        if (score >= 80) return 'high';
        if (score >= 50) return 'mid';
        return 'low';
    }

    /**
     * Section emoji'sine göre section CSS tipini belirler.
     */
    function _getSectionType(icon) {
        if (['🎯', '📌', '✅'].includes(icon)) return 'primary';
        if (['🔴', '⚠️'].includes(icon)) return 'warning';
        if (['🔍', '📞', '💡'].includes(icon)) return 'secondary';
        return 'info';
    }

    /**
     * Deep Think yapısal yanıtını zengin HTML'e dönüştürür.
     * 
     * Desteklenen formatlar:
     * - LIST_REQUEST:   📋 **Kategori** (N adet) + numaralı `komut` + ↳ açıklama (skor%)
     * - HOW_TO:         🎯 **Amaç:** + 📌 **Adımlar:** + numaralı adımlar
     * - TROUBLESHOOT:   🔴 **Sorun:** + 🔍 **Olası Nedenler:** + ✅ **Çözüm Adımları:**
     * - SINGLE_ANSWER:  📖 **Konu** + tanım + kullanım
     * - Kaynak bilgisi: 📚 **KAYNAKLAR** + • [dosya] formatı
     */
    function _formatDeepThinkStructured(content) {
        // 🔧 v2.33.2: Prompt leak temizleme (backend kaçırırsa ikinci savunma katmanı)
        content = content
            .replace(/ÖNEMLİ:\s*\n(?:\s*\d+\.\s+.*\n?){1,10}/g, '')
            .replace(/FORMAT TALİMATI:[\s\S]*?(?=\n📋|\n🎯|\n🔴|\n📖|\n\d+\.|$)/g, '')
            .replace(/⚠️\s*KRİTİK KURALLAR:[\s\S]*?(?=\n📋|\n🏷️|\n\d+\.|$)/g, '')
            .replace(/^.*SADECE yukarıdaki bilgi tabanı içeriğini kullan.*$/gmi, '')
            .replace(/^.*Bilgi tabanında olmayan şeyleri UYDURMA.*$/gmi, '')
            .replace(/^.*Tüm ilgili bilgileri dahil et.*hiçbirini atlama.*$/gmi, '')
            .replace(/^.*Kaynak dosya adlarını belirt.*$/gmi, '')
            .replace(/^.*Türkçe yanıt ver.*$/gmi, '')
            .replace(/\n{3,}/g, '\n\n')
            .trim();

        const lines = content.split('\n');
        let html = '<div class="dt-response">';
        let inItems = false;
        let inSources = false;
        let inFeedbackSection = false;
        let skipNextShowBtn = false;

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i].trim();

            if (!line) continue;

            // ── FEEDBACK_SECTION gizle ──
            if (line === '[FEEDBACK_SECTION]') { inFeedbackSection = true; continue; }
            if (line === '[/FEEDBACK_SECTION]') { inFeedbackSection = false; continue; }
            if (inFeedbackSection) continue;

            // ── Separator ──
            if (line === '---') {
                html += '<div class="dt-divider"></div>';
                continue;
            }

            // ── RAG Inline Images: <img> etiketlerini doğrudan HTML olarak geçir ──
            if (line.startsWith('<img ') || line.includes('rag-inline-image')) {
                if (inItems) { html += '</div>'; inItems = false; }
                html += `<div class="dt-image-container">${line}</div>`;
                continue;
            }

            // ── 📷 İlgili Görseller header ──
            if (line.startsWith('📷')) {
                if (inItems) { html += '</div>'; inItems = false; }
                if (inSources) { html += '</div></div>'; inSources = false; }
                html += `<div class="dt-section-label dt-section-info">
                    <span class="dt-section-icon">📷</span>
                    <span class="dt-section-title">İlgili Görseller</span>
                </div>`;
                continue;
            }

            // ════════════════════════════════════════════════════
            // CATEGORY HEADER: 📋 **Kategori** (N adet) veya 🏷️ **Kategori** (N sonuç)
            // ════════════════════════════════════════════════════
            const catHeaderMatch = line.match(/^(📋|🏷️)\s*\*\*([^*]+)\*\*\s*(.*)$/);
            if (catHeaderMatch) {
                if (inItems) { html += '</div>'; inItems = false; }
                if (inSources) { html += '</div></div>'; inSources = false; }

                const icon = catHeaderMatch[1];
                const title = catHeaderMatch[2].trim();
                const countRaw = catHeaderMatch[3].replace(/[()]/g, '').trim();

                // 📋 **Özet:** metin → section olarak render et (wrap için)
                const titleLower = title.toLowerCase().replace(/:$/, '');
                if (titleLower === 'özet' || titleLower === 'özeti' || titleLower === 'sonuç') {
                    if (countRaw) {
                        html += `<div class="dt-section dt-section-primary">
                            <div class="dt-section-header">
                                <span class="dt-section-icon">${icon}</span>
                                <span class="dt-section-title">${escapeHtml(title)}</span>
                            </div>
                            <div class="dt-section-value">${_inlineFormat(countRaw)}</div>
                        </div>`;
                    } else {
                        html += `<div class="dt-section-label dt-section-primary">
                            <span class="dt-section-icon">${icon}</span>
                            <span class="dt-section-title">${escapeHtml(title)}</span>
                        </div>`;
                        html += '<div class="dt-items">';
                        inItems = true;
                    }
                    continue;
                }

                html += `<div class="dt-header">
                    <div class="dt-header-icon">${icon}</div>
                    <div class="dt-header-info">
                        <div class="dt-header-title">${escapeHtml(title)}</div>
                        ${countRaw ? `<span class="dt-header-count">${escapeHtml(countRaw)}</span>` : ''}
                    </div>
                </div>`;
                html += '<div class="dt-items">';
                inItems = true;
                continue;
            }

            // ════════════════════════════════════════════════════
            // SECTION HEADER: 🎯 **Amaç:** değer, 📌 **Adımlar:**, 🔴 **Sorun:** vs.
            // (💡 **Diğer kategorilerde...** hariç — o ayrı ele alınır)
            // ════════════════════════════════════════════════════
            const sectionMatch = line.match(/^(🎯|📌|🔴|🔍|✅|📖|⚠️|📞)\s*\*\*([^*]+)\*\*\s*(.*)$/);
            if (sectionMatch && !line.includes('Diğer kategori')) {
                if (inItems) { html += '</div>'; inItems = false; }
                if (inSources) { html += '</div></div>'; inSources = false; }

                const sIcon = sectionMatch[1];
                const sTitle = sectionMatch[2].trim();
                const sValue = sectionMatch[3].trim();
                const sType = _getSectionType(sIcon);

                if (sValue) {
                    // Inline value section (örn: 🎯 **Amaç:** Port konfigürasyonu)
                    html += `<div class="dt-section dt-section-${sType}">
                        <div class="dt-section-header">
                            <span class="dt-section-icon">${sIcon}</span>
                            <span class="dt-section-title">${escapeHtml(sTitle)}</span>
                        </div>
                        <div class="dt-section-value">${_inlineFormat(sValue)}</div>
                    </div>`;
                } else {
                    // Sadece başlık, altında içerik gelecek (örn: 📌 **Adımlar:**)
                    html += `<div class="dt-section-label dt-section-${sType}">
                        <span class="dt-section-icon">${sIcon}</span>
                        <span class="dt-section-title">${escapeHtml(sTitle)}</span>
                    </div>`;
                    html += '<div class="dt-items">';
                    inItems = true;
                }
                continue;
            }

            // ════════════════════════════════════════════════════
            // NUMBERED ITEMS: 1. `komut` veya 1️⃣ `adım` veya 1. Metin satırı
            // ════════════════════════════════════════════════════
            // Normalize emoji numbers: 1️⃣ → 1.
            let normalizedLine = line
                .replace(/^(\d)️⃣\s*/, '$1. ')
                .replace(/^🔟\s*/, '10. ');

            const numberedMatch = normalizedLine.match(/^(\d+)\.\s+(.+)$/);
            if (numberedMatch) {
                const num = numberedMatch[1];
                let itemContent = numberedMatch[2].trim();

                // Backtick içindeki komutu ayıkla
                const cmdMatch = itemContent.match(/^`([^`]+)`\s*(.*)$/);
                let command = '';
                let restText = itemContent;

                if (cmdMatch) {
                    command = cmdMatch[1];
                    restText = cmdMatch[2].trim();
                }

                // Sonraki satırda ↳ açıklama var mı?
                let description = '';
                let scorePercent = '';

                if (i + 1 < lines.length) {
                    const nextLine = lines[i + 1].trim();
                    if (nextLine.startsWith('↳')) {
                        const descContent = nextLine.replace(/^↳\s*/, '');
                        const scoreMatch = descContent.match(/^(.+?)\s*\((\d+)%\)\s*$/);
                        if (scoreMatch) {
                            description = scoreMatch[1].trim();
                            scorePercent = scoreMatch[2];
                        } else {
                            description = descContent.trim();
                        }
                        i++; // ↳ satırını atla
                    }
                }

                // Skor aynı satırda olabilir: `komut` (75%)
                if (!scorePercent) {
                    const inlineScore = restText.match(/\((\d+)%\)/);
                    if (inlineScore) {
                        scorePercent = inlineScore[1];
                        restText = restText.replace(/\(\d+%\)/, '').trim();
                    }
                }

                // Backtick yoksa tüm metni "komut/başlık" olarak kullan
                if (!command && restText) {
                    command = restText;
                    restText = '';
                }

                // restText'ten açıklama
                if (!description && restText) {
                    description = restText;
                }

                const scoreNum = parseInt(scorePercent || '0');
                const scoreClass = _getScoreClass(scoreNum);

                if (!inItems) {
                    html += '<div class="dt-items">';
                    inItems = true;
                }

                html += `<div class="dt-item">
                    <div class="dt-item-num">${num}</div>
                    <div class="dt-item-body">
                        <div class="dt-item-header">
                            <span class="dt-item-content">${_inlineFormat(command)}</span>
                            ${scorePercent ? `<span class="dt-score dt-score-${scoreClass}">${scorePercent}%</span>` : ''}
                        </div>
                        ${description ? `<div class="dt-description">${_inlineFormat(description)}</div>` : ''}
                    </div>
                </div>`;
                continue;
            }

            // ════════════════════════════════════════════════════
            // ↳ ORPHAN CONTINUATION (numbered item mantığında yakalanamamışsa)
            // ════════════════════════════════════════════════════
            if (line.startsWith('↳')) {
                const cont = line.replace(/^↳\s*/, '');
                html += `<div class="dt-continuation">${_inlineFormat(cont)}</div>`;
                continue;
            }

            // ════════════════════════════════════════════════════
            // BULLET POINTS: • madde veya - madde
            // ════════════════════════════════════════════════════
            if (line.startsWith('•') || line.match(/^-\s+\S/)) {
                const bulletContent = line.replace(/^[•\-]\s*/, '');

                if (inSources) {
                    // Kaynak öğesi: • [dosya.xlsx] - **Sheet** - açıklama
                    let sourceHtml = escapeHtml(bulletContent);
                    sourceHtml = sourceHtml.replace(/\[([^\]]+)\]/g, '<span class="dt-source-file"><i class="fa-solid fa-file-lines"></i> $1</span>');
                    sourceHtml = sourceHtml.replace(/\*\*([^*]+)\*\*/g, '<span class="dt-source-sheet">$1</span>');
                    html += `<div class="dt-source-item">${sourceHtml}</div>`;
                } else {
                    // Normal madde
                    if (!inItems) {
                        html += '<div class="dt-items">';
                        inItems = true;
                    }
                    html += `<div class="dt-bullet">
                        <span class="dt-bullet-dot"></span>
                        <span class="dt-bullet-text">${_inlineFormat(bulletContent)}</span>
                    </div>`;
                }
                continue;
            }

            // ════════════════════════════════════════════════════
            // 💡 DİĞER KATEGORİLER BİLGİSİ
            // 0 sonuç varsa gösterme
            // ════════════════════════════════════════════════════
            if (line.startsWith('💡')) {
                if (inItems) { html += '</div>'; inItems = false; }

                // "0 sonuç" kontrolü — 0 sonuç varsa hiç gösterme
                const zeroMatch = line.match(/\b0\s+sonu[çc]/i);
                if (zeroMatch) {
                    skipNextShowBtn = true;
                    continue;
                }

                let catLine = escapeHtml(line.replace(/^💡\s*/, ''));
                catLine = catLine.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

                html += `<div class="dt-other-categories">
                    <div class="dt-other-icon"><i class="fa-solid fa-lightbulb"></i></div>
                    <span>${catLine}</span>
                </div>`;
                skipNextShowBtn = false;
                continue;
            }

            // ════════════════════════════════════════════════════
            // RAW HTML BUTTON (Göster butonu — backend'den gelir)
            // 0 sonuç durumunda da gizle
            // ════════════════════════════════════════════════════
            if (line.includes('show-other-categories-btn')) {
                if (!skipNextShowBtn) {
                    html += `<div class="dt-show-btn-wrapper">${line}</div>`;
                }
                skipNextShowBtn = false;
                continue;
            }

            // ════════════════════════════════════════════════════
            // 📚 KAYNAKLAR bölümü
            // ════════════════════════════════════════════════════
            if (line.includes('📚') && line.toUpperCase().includes('KAYNAKLAR')) {
                if (inItems) { html += '</div>'; inItems = false; }

                html += `<div class="dt-sources">
                    <div class="dt-sources-header">
                        <i class="fa-solid fa-book-open"></i> Kaynaklar
                    </div>
                    <div class="dt-sources-list">`;
                inSources = true;
                continue;
            }

            // ════════════════════════════════════════════════════
            // WARNING: _⚠️ LLM bağlantısı kurulamadı._
            // ════════════════════════════════════════════════════
            if (line.startsWith('_⚠️') || (line.startsWith('⚠️') && !line.includes('**'))) {
                if (inItems) { html += '</div>'; inItems = false; }
                if (inSources) { html += '</div></div>'; inSources = false; }

                const warnText = line.replace(/^_?⚠️\s*/, '').replace(/_$/, '');
                html += `<div class="dt-warning">
                    <i class="fa-solid fa-triangle-exclamation"></i>
                    <span>${escapeHtml(warnText)}</span>
                </div>`;
                continue;
            }

            // ════════════════════════════════════════════════════
            // _Kaynak: [dosya.docx]_
            // ════════════════════════════════════════════════════
            if (line.startsWith('_Kaynak:') || line.startsWith('_kaynak:')) {
                if (inItems) { html += '</div>'; inItems = false; }
                const srcText = line.replace(/^_/, '').replace(/_$/, '');
                html += `<div class="dt-source-inline">
                    <i class="fa-solid fa-quote-left"></i>
                    <span>${_inlineFormat(srcText)}</span>
                </div>`;
                continue;
            }

            // ════════════════════════════════════════════════════
            // DEFAULT: Normal paragraf
            // ════════════════════════════════════════════════════
            html += `<p class="dt-paragraph">${_inlineFormat(line)}</p>`;
        }

        // Açık kalan container'ları kapat
        if (inItems) html += '</div>';
        if (inSources) html += '</div></div>';

        html += '</div>';
        return html;
    }

    // =========================================================================
    // MAIN FORMAT FUNCTION
    // =========================================================================

    /**
     * Markdown benzeri içeriği HTML'e çevirir.
     * Deep Think yapısal yanıtları özel parser ile, diğerleri klasik line-by-line.
     */
    function formatMessageContent(content) {
        // ── Deep Think yapısal yanıt kontrolü ──
        if (_isDeepThinkResponse(content)) {
            let result = _formatDeepThinkStructured(content);
            // 🆕 v2.38.2: Relative API URL'leri absolute backend URL'e çevir
            result = _rewriteApiUrls(result);
            return result;
        }

        // ── Klasik line-by-line işleme (mevcut mantık korunur) ──
        const lines = content.split('\n');
        const processedLines = [];
        let inOrderedList = false;
        let inFeedbackSection = false;

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i].trim();

            if (!line) {
                if (inOrderedList) {
                    processedLines.push('</ol>');
                    inOrderedList = false;
                }
                continue;
            } else if (line.startsWith('###')) {
                if (inOrderedList) {
                    processedLines.push('</ol>');
                    inOrderedList = false;
                }
                processedLines.push(line.replace(/^###\s+(.+)$/, '<h3>$1</h3>'));
            } else if (line === '---') {
                if (inOrderedList) {
                    processedLines.push('</ol>');
                    inOrderedList = false;
                }
                processedLines.push('<hr>');
            } else if (line === '[FEEDBACK_SECTION]') {
                if (inOrderedList) {
                    processedLines.push('</ol>');
                    inOrderedList = false;
                }
                inFeedbackSection = true;
            } else if (line === '[/FEEDBACK_SECTION]') {
                inFeedbackSection = false;
            } else if (inFeedbackSection) {
                continue;
            } else if (/^\d+\.\s/.test(line)) {
                if (!inOrderedList) {
                    processedLines.push('<ol class="vyra-ordered-list">');
                    inOrderedList = true;
                }
                const listContent = line.replace(/^\d+\.\s+/, '');
                processedLines.push('<li>' + listContent + '</li>');
            } else if (line.startsWith('<img ') || line.includes('rag-inline-image')) {
                // RAG inline görseller — escape edilmeden doğrudan HTML olarak geçir
                if (inOrderedList) {
                    processedLines.push('</ol>');
                    inOrderedList = false;
                }
                processedLines.push('<div class="dt-image-container">' + line + '</div>');
            } else {
                if (inOrderedList) {
                    processedLines.push('</ol>');
                    inOrderedList = false;
                }
                processedLines.push('<p>' + line + '</p>');
            }
        }

        if (inOrderedList) {
            processedLines.push('</ol>');
        }

        let formatted = processedLines.join('\n');

        // Markdown download linkleri → onclick ile auth indirme
        formatted = formatted.replace(
            /\[([^\]]+)\]\((\/api\/rag\/download\/[^)]+)\)/g,
            '<a href="javascript:void(0)" class="download-link" onclick="DialogChatModule.downloadFile(\'$2\', \'$1\')" title="İndir">$1 <i class="fa-solid fa-download"></i></a>'
        );

        // Bold
        formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

        // Inline code
        formatted = formatted.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');

        // Quick reply emojileri temizle
        formatted = formatted.replace(/👍 👎/g, '');

        // 🆕 v2.38.2: Relative API URL'leri absolute backend URL'e çevir
        formatted = _rewriteApiUrls(formatted);

        return formatted;
    }

    /**
     * 🆕 v2.38.2: Relative /api/ URL'leri absolute backend URL'e dönüştürür.
     * Frontend (port 5500) ve Backend (port 8002) farklı portlarda çalıştığı için,
     * <img src="/api/rag/images/123"> gibi relative URL'ler frontend'e yönlenir ve 404 alır.
     * Bu fonksiyon bunları http://localhost:8002/api/... şekline çevirir.
     */
    function _rewriteApiUrls(html) {
        // API_BASE_URL'i config.js'den veya window'dan al
        const apiBase = (typeof API_BASE_URL !== 'undefined')
            ? API_BASE_URL
            : (window.API_BASE_URL || 'http://localhost:8002');

        // src="/api/..." → src="http://localhost:8002/api/..."
        return html.replace(/src="\/api\//g, `src="${apiBase}/api/`);
    }

    /**
     * HTML özel karakterlerini escape eder.
     */
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Kullanıcı adının baş harflerini döndürür (avatar için).
     */
    function getUserInitial() {
        const name = localStorage.getItem('user_full_name') || localStorage.getItem('user_name') || 'U';
        const parts = name.trim().split(' ');
        if (parts.length >= 2) {
            return (parts[0].charAt(0) + parts[1].charAt(0)).toUpperCase();
        }
        return name.charAt(0).toUpperCase();
    }

    /**
     * Unified toast wrapper - VyraToast mevcutsa kullanır, yoksa console.
     */
    function showToast(type, message) {
        if (typeof VyraToast !== 'undefined') {
            VyraToast[type](message);
        } else {
            console.log(`[Toast ${type}] ${message}`);
        }
    }

    /**
     * Dosya uzantısına göre Font Awesome ikonu döndürür.
     */
    function getFileTypeIcon(fileType) {
        const type = (fileType || '').toLowerCase().replace('.', '');
        const icons = {
            'docx': '<i class="fa-solid fa-file-word" style="color: #2b579a;"></i>',
            'doc': '<i class="fa-solid fa-file-word" style="color: #2b579a;"></i>',
            'pdf': '<i class="fa-solid fa-file-pdf" style="color: #dc2626;"></i>',
            'xlsx': '<i class="fa-solid fa-file-excel" style="color: #217346;"></i>',
            'xls': '<i class="fa-solid fa-file-excel" style="color: #217346;"></i>',
            'pptx': '<i class="fa-solid fa-file-powerpoint" style="color: #d24726;"></i>',
            'ppt': '<i class="fa-solid fa-file-powerpoint" style="color: #d24726;"></i>',
            'txt': '<i class="fa-solid fa-file-lines" style="color: #6b7280;"></i>',
            'csv': '<i class="fa-solid fa-file-csv" style="color: #22c55e;"></i>',
            'json': '<i class="fa-solid fa-file-code" style="color: #f59e0b;"></i>',
            'html': '<i class="fa-solid fa-file-code" style="color: #e34c26;"></i>',
            'md': '<i class="fa-solid fa-file-lines" style="color: #083d77;"></i>'
        };
        return icons[type] || '<i class="fa-solid fa-file" style="color: #9ca3af;"></i>';
    }

    /**
     * JS string escape (tek tırnak, çift tırnak, ters eğik çizgi, newline).
     */
    function escapeForJs(text) {
        return text
            .replace(/\\/g, '\\\\')
            .replace(/'/g, "\\'")
            .replace(/"/g, '\\"')
            .replace(/\n/g, ' ')
            .replace(/\r/g, '');
    }

    // =========================================================================
    // v4.0: DB SORGU SONUCU — TABLO RENDER
    // =========================================================================

    /**
     * DB sorgu sonucunu scrollable HTML tablosuna çevirir.
     * @param {string[]} columns - Sütun adları
     * @param {Object[]} rows    - Satır verisi (dict listesi)
     * @param {Object}   meta    - {row_count, rows_shown, sql_executed, source_db}
     * @returns {string} HTML string
     */
    function renderSQLResultTable(columns, rows, meta) {
        if (!columns || columns.length === 0 || !rows || rows.length === 0) {
            return '';
        }

        // v3.30.0: büyük sonuçlarda virtual scroll kullan
        if (rows.length > (window.VirtualScrollTable?.THRESHOLD || 200) && window.VirtualScrollTable) {
            var vsEl = window.VirtualScrollTable.create(columns, rows, meta);
            var tmp = document.createElement('div');
            tmp.appendChild(vsEl);
            return tmp.innerHTML;
        }

        const rowCount = meta?.row_count || rows.length;
        const rowsShown = meta?.rows_shown || rows.length;
        const sourceDb = meta?.source_db || '';
        const truncated = rowCount > rowsShown;

        // v3.27.2: drag-drop + kolon görünürlüğü için tabloyu izole tut
        const tableId = 'dbtbl_' + Date.now().toString(36) + '_' + Math.floor(Math.random() * 1e6).toString(36);

        let html = `<div class="db-result-table-wrap" data-table-id="${tableId}">`;

        // Meta bar + Kolon yönetim butonu (v3.27.2)
        html += `<div class="db-result-meta">`;
        if (sourceDb) html += `<span class="db-result-db">🗄️ ${escapeHtml(sourceDb)}</span>`;
        html += `<span class="db-result-count">📊 ${rowsShown} kayıt`;
        if (truncated) html += ` <span class="db-truncated-badge">(toplam ${rowCount})</span>`;
        html += `</span>`;
        html += `<button type="button" class="db-cols-btn" onclick="window.DBTableUI.toggleColMenu('${tableId}', event)" title="Kolonları göster/gizle ve sürükleyerek yeniden sırala">⚙️ Kolonlar</button>`;
        html += `</div>`;

        // Kolon menü (gizli başlar)
        html += `<div class="db-cols-menu" id="${tableId}_menu" hidden>`;
        html += `<div class="db-cols-menu-head"><span>Görünür kolonlar</span><button type="button" class="db-cols-menu-close" onclick="window.DBTableUI.toggleColMenu('${tableId}')" aria-label="Kapat">×</button></div>`;
        html += `<div class="db-cols-menu-actions">`;
        html += `<button type="button" class="db-cols-mini" onclick="window.DBTableUI.allCols('${tableId}', true)">Tümünü göster</button>`;
        html += `<button type="button" class="db-cols-mini" onclick="window.DBTableUI.allCols('${tableId}', false)">Tümünü gizle</button>`;
        html += `</div>`;
        html += `<div class="db-cols-menu-list">`;
        columns.forEach(col => {
            const safeCol = escapeHtml(col);
            const colAttr = safeCol.replace(/"/g, '&quot;');
            html += `<label class="db-col-item"><input type="checkbox" checked data-col="${colAttr}" onchange="window.DBTableUI.toggleCol('${tableId}', this.dataset.col, this.checked)"><span>${safeCol}</span></label>`;
        });
        html += `</div></div>`;

        // Tablo
        html += `<div class="db-table-scroll"><table class="db-result-table" data-table-id="${tableId}">`;

        // Header — draggable
        html += `<thead><tr>`;
        columns.forEach(col => {
            const safeCol = escapeHtml(col);
            const colAttr = safeCol.replace(/"/g, '&quot;');
            html += `<th draggable="true" data-col="${colAttr}"`
                  + ` ondragstart="window.DBTableUI.onDragStart(event)"`
                  + ` ondragover="window.DBTableUI.onDragOver(event)"`
                  + ` ondragenter="window.DBTableUI.onDragEnter(event)"`
                  + ` ondragleave="window.DBTableUI.onDragLeave(event)"`
                  + ` ondrop="window.DBTableUI.onDrop(event)"`
                  + ` ondragend="window.DBTableUI.onDragEnd(event)">`
                  + `<span class="th-grip" aria-hidden="true">⋮⋮</span><span class="th-label">${safeCol}</span></th>`;
        });
        html += `</tr></thead>`;

        // Body — her hücreye data-col
        html += `<tbody>`;
        rows.forEach((row, rowIdx) => {
            const cls = rowIdx % 2 === 0 ? '' : ' class="alt-row"';
            html += `<tr${cls}>`;
            columns.forEach(col => {
                const val = row[col];
                const safeCol = escapeHtml(col);
                const colAttr = safeCol.replace(/"/g, '&quot;');
                const display = val === null || val === undefined ? '<span class="null-val">—</span>' : escapeHtml(String(val));
                html += `<td data-col="${colAttr}">${display}</td>`;
            });
            html += `</tr>`;
        });
        html += `</tbody></table></div>`;

        if (truncated) {
            html += `<div class="db-truncated-note">⚠️ Toplam ${rowCount} kayıttan ilk ${rowsShown} tanesi gösteriliyor. Tümünü görmek için Excel'e aktarın.</div>`;
        }

        html += `</div>`;
        return html;
    }

    // =========================================================================
    // v4.0: DİSAMBIGUATION KARTI
    // =========================================================================

    /**
     * Çoklu schema'da aynı isimli tablo için kullanıcı seçim kartı.
     * @param {Object[]} candidates - [{schema, table_name, full_name, business_name_tr, description_tr, row_estimate}]
     * @param {string}   query      - Orijinal kullanıcı sorusu
     * @param {string}   message    - Gösterilecek açıklama
     * @param {Function} onSelect   - Seçim callback: (full_name) => void
     * @returns {string} HTML string
     */
    function renderDisambiguationCard(candidates, query, message, onSelect) {
        const id = 'disambig_' + Date.now();

        // Callback'i global scope'a kaydet
        window[id + '_select'] = function(fullName) {
            if (typeof onSelect === 'function') onSelect(fullName);
            const card = document.getElementById(id);
            if (card) card.remove();
        };

        let html = `<div class="db-disambig-card" id="${id}">`;
        html += `<div class="db-disambig-header">`;
        html += `<span class="db-disambig-icon">🔍</span>`;
        html += `<span class="db-disambig-msg">${escapeHtml(message || 'Hangi tabloyu kastettiğinizi seçin:')}</span>`;
        html += `</div>`;
        html += `<div class="db-disambig-candidates">`;

        candidates.forEach(c => {
            const title = escapeHtml(c.business_name_tr || c.table_name);
            const schema = escapeHtml(c.schema || '');
            const tbl = escapeHtml(c.table_name);
            const desc = c.description_tr ? escapeHtml(c.description_tr) : '';
            const rows = c.row_estimate ? `~${Number(c.row_estimate).toLocaleString('tr-TR')} satır` : '';
            const fullName = escapeHtml(c.full_name);

            html += `<button class="db-disambig-btn" onclick="window['${id}_select']('${fullName}')">`;
            html += `<div class="db-disambig-btn-title">📋 ${title}</div>`;
            html += `<div class="db-disambig-btn-meta"><code>${schema}.${tbl}</code>`;
            if (rows) html += ` · ${rows}`;
            html += `</div>`;
            if (desc) html += `<div class="db-disambig-btn-desc">${desc}</div>`;
            html += `</button>`;
        });

        html += `</div>`;
        html += `<button class="db-disambig-cancel" onclick="document.getElementById('${id}').remove()">İptal</button>`;
        html += `</div>`;

        return html;
    }

    // =========================================================================
    // v4.0: RAPOR ŞABLONU ÖNERİLERİ
    // =========================================================================

    /**
     * DB_REPORT intent için şablon seçim kartı.
     * @param {Object[]} templates - [{title, description, hint}]
     * @param {string}   message   - Başlık mesajı
     * @param {Function} onSelect  - Seçim callback: (hint) => void
     * @returns {string} HTML string
     */
    function renderReportTemplates(templates, message, onSelect) {
        const id = 'rptmpl_' + Date.now();

        window[id + '_pick'] = function(hint) {
            if (typeof onSelect === 'function') onSelect(hint);
            const card = document.getElementById(id);
            if (card) card.remove();
        };

        let html = `<div class="db-template-card" id="${id}">`;
        html += `<div class="db-template-header">`;
        html += `<span class="db-template-icon">📊</span>`;
        html += `<span class="db-template-msg">${escapeHtml(message || 'Bir yaklaşım seçin:')}</span>`;
        html += `</div>`;
        html += `<div class="db-template-list">`;

        templates.forEach((t, i) => {
            const title = escapeHtml(t.title || `Seçenek ${i + 1}`);
            const desc = escapeHtml(t.description || '');
            const hint = escapeHtml(t.hint || t.title || '');
            html += `<button class="db-template-btn" onclick="window['${id}_pick']('${hint}')">`;
            html += `<div class="db-template-btn-title">${title}</div>`;
            if (desc) html += `<div class="db-template-btn-desc">${desc}</div>`;
            html += `</button>`;
        });

        html += `</div>`;
        html += `<button class="db-disambig-cancel" onclick="document.getElementById('${id}').remove()">Kendim yazayım</button>`;
        html += `</div>`;

        return html;
    }

    // =========================================================================
    // v4.0: FOLLOW-UP ÖNERİ CHIPS
    // =========================================================================

    /**
     * Sorgu sonrası proaktif follow-up öneri chip'leri.
     * @param {Object[]} suggestions - [{text, query}]
     * @param {Function} onSelect    - Seçim callback: (queryText) => void
     * @returns {string} HTML string
     */
    function renderFollowUpChips(suggestions, onSelect) {
        if (!suggestions || suggestions.length === 0) return '';

        const id = 'fuchips_' + Date.now() + '_' + Math.floor(Math.random() * 1000);

        // Global tetikleyici — data-q attribute'tan okur (escape sorunu yok)
        window[id + '_send'] = function(btn) {
            try {
                const q = (btn && btn.dataset && btn.dataset.q) || '';
                if (q && typeof onSelect === 'function') onSelect(q);
            } finally {
                const wrap = document.getElementById(id);
                if (wrap) wrap.remove();
            }
        };

        let html = `<div class="db-followup-wrap" id="${id}">`;
        html += `<div class="db-followup-label">💡 İlgili sorgular:</div>`;
        html += `<div class="db-followup-chips">`;

        suggestions.forEach(s => {
            // s.query: backend'e gönderilecek doğal dil cümlesi
            // s.text: chip üzerinde gösterilecek kısa/emoji'li etiket
            const sendQuery = s.query || s.text || '';
            const displayLabel = s.text || s.query || '';
            const qAttr = escapeHtml(sendQuery);   // attribute güvenli
            const labelHtml = escapeHtml(displayLabel);
            html += `<button class="db-followup-chip" data-q="${qAttr}" onclick="window['${id}_send'](this)">${labelHtml}</button>`;
        });

        html += `</div></div>`;
        return html;
    }

    // =========================================================================
    // v4.0: EXPORT BAR
    // =========================================================================

    /**
     * DB sorgu sonucu için export araç çubuğu.
     * @param {string[]} columns - Sütun adları
     * @param {Object[]} rows    - Satır verisi
     * @param {Object}   meta    - {title, query, sql}
     * @returns {string} HTML string
     */
    function renderExportBar(columns, rows, meta) {
        if (!rows || rows.length === 0) return '';

        const id = 'expbar_' + Date.now();
        const safeTitle = escapeForJs(meta?.title || 'VYRA Sorgu Sonucu');
        const safeQuery = escapeForJs(meta?.query || '');
        const safeSql = escapeForJs(meta?.sql || '');

        // Veriyi global scope'a kaydet (export handler kullanır)
        window[id + '_data'] = { columns, rows, title: meta?.title, query: meta?.query, sql: meta?.sql };

        let html = `<div class="db-export-bar" id="${id}">`;
        html += `<span class="db-export-label">İndir:</span>`;
        html += `<button class="db-export-btn excel" title="Excel olarak indir" onclick="window.DBExportHandler?.excel('${id}')">`;
        html += `<i class="fa-solid fa-file-excel"></i> Excel</button>`;
        html += `<button class="db-export-btn word" title="Word raporu" onclick="window.DBExportHandler?.word('${id}')">`;
        html += `<i class="fa-solid fa-file-word"></i> Word</button>`;
        html += `<button class="db-export-btn pdf" title="PDF olarak indir" onclick="window.DBExportHandler?.pdf('${id}')">`;
        html += `<i class="fa-solid fa-file-pdf"></i> PDF</button>`;
        html += `<button class="db-export-btn copy" title="CSV olarak kopyala" onclick="window.DBExportHandler?.copyCSV('${id}')">`;
        html += `<i class="fa-solid fa-copy"></i> Kopyala</button>`;
        html += `</div>`;

        return html;
    }

    // =========================================================================
    // v4.1: SQL MODAL BUTON
    // =========================================================================

    /**
     * SQL'i tam ekran modal'da gösteren buton HTML'i döndürür.
     * @param {string} sql - Gösterilecek SQL sorgusu
     * @returns {string} HTML button string
     */
    function renderSQLButton(sql) {
        if (!sql) return '';
        const id = 'sqlbtn_' + Date.now();
        // SQL'i global scope'a güvenli kaydet (onclick string injection'a karşı)
        window[id] = sql;
        return `<button class="db-sql-btn" title="SQL sorgusunu görüntüle" onclick="window.DialogChatUtils.showSQLModal(window['${id}'])">` +
               `<i class="fa-solid fa-code"></i> SQL</button>`;
    }

    /**
     * SQL içeriğini tam ekran modal'da gösterir.
     * @param {string} sql - Gösterilecek SQL metni
     */
    function showSQLModal(sql) {
        const existing = document.getElementById('vyra-sql-modal');
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.id = 'vyra-sql-modal';

        const escapedSql = escapeHtml(sql || '');

        modal.innerHTML =
            `<div class="vyra-sql-modal-overlay" id="vyra-sql-overlay">` +
            `  <div class="vyra-sql-modal-box" onclick="event.stopPropagation()">` +
            `    <div class="vyra-sql-modal-header">` +
            `      <span class="vyra-sql-modal-title"><i class="fa-solid fa-code"></i> Çalıştırılan SQL Sorgusu</span>` +
            `      <div class="vyra-sql-modal-actions">` +
            `        <button class="vyra-sql-copy-btn" id="vyra-sql-copy-btn"><i class="fa-regular fa-copy"></i> Kopyala</button>` +
            `        <button class="vyra-sql-close-btn" onclick="document.getElementById('vyra-sql-modal').remove()">✕</button>` +
            `      </div>` +
            `    </div>` +
            `    <div class="vyra-sql-modal-body">` +
            `      <pre class="vyra-sql-modal-code">${escapedSql}</pre>` +
            `    </div>` +
            `  </div>` +
            `</div>`;

        document.body.appendChild(modal);

        // Overlay tıklaması → kapat
        document.getElementById('vyra-sql-overlay').addEventListener('click', function(e) {
            if (e.target === this) modal.remove();
        });

        // Kopyala butonu
        document.getElementById('vyra-sql-copy-btn').addEventListener('click', function() {
            navigator.clipboard.writeText(sql).then(() => {
                this.innerHTML = '<i class="fa-solid fa-check"></i> Kopyalandı!';
                this.classList.add('copied');
                setTimeout(() => {
                    this.innerHTML = '<i class="fa-regular fa-copy"></i> Kopyala';
                    this.classList.remove('copied');
                }, 2000);
            }).catch(() => {
                // Fallback: execCommand
                const ta = document.createElement('textarea');
                ta.value = sql;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                this.textContent = '✅ Kopyalandı!';
                setTimeout(() => { this.innerHTML = '<i class="fa-regular fa-copy"></i> Kopyala'; }, 2000);
            });
        });

        // ESC tuşu → kapat
        const onKeyDown = (e) => {
            if (e.key === 'Escape') { modal.remove(); document.removeEventListener('keydown', onKeyDown); }
        };
        document.addEventListener('keydown', onKeyDown);
    }

    // PUBLIC API
    return {
        formatTime,
        formatMessageContent,
        escapeHtml,
        getUserInitial,
        showToast,
        getFileTypeIcon,
        escapeForJs,
        // v4.0
        renderSQLResultTable,
        renderDisambiguationCard,
        renderReportTemplates,
        renderFollowUpChips,
        renderExportBar,
        // v4.1
        renderSQLButton,
        showSQLModal,
    };
})();

// =============================================================================
// v3.27.2: DB Result Table — Column Drag/Drop + Visibility Manager
// =============================================================================
//
// renderSQLResultTable çıktısı için handler. State DOM içinde tutulur (data-col),
// modül stateless. Inline event handler'lardan çağrılır (CSP açıkken çalışır
// çünkü çağrılar tek isim üzerinden — JS dosyası dahili).
//
window.DBTableUI = (function () {
    'use strict';

    let dragSrcCol = null;
    let dragTableId = null;

    // v3.27.3: kolon tercihi persist (kolon-set hash → {order, hidden})
    const STORAGE_PREFIX = 'vyra:tbl_prefs:';

    function _table(tableId) {
        return document.querySelector('table.db-result-table[data-table-id="' + CSS.escape(tableId) + '"]');
    }

    function _allCols(tbl) {
        return Array.prototype.slice.call(tbl.querySelectorAll('thead th[data-col]'))
            .map(function (th) { return th.getAttribute('data-col'); });
    }

    function _prefsKey(colsForKey) {
        // Kolon setine bağlı stabil key — sıralı join (sıralama bağımsız hash).
        return STORAGE_PREFIX + (colsForKey || []).slice().sort().join('|');
    }

    function _savePrefs(tableId) {
        const tbl = _table(tableId);
        if (!tbl) return;
        const order = _allCols(tbl);
        if (!order.length) return;
        const hidden = order.filter(function (c) {
            const th = tbl.querySelector('thead th[data-col="' + c.replace(/"/g, '\\"') + '"]');
            return !!(th && th.style.display === 'none');
        });
        const payload = { order: order, hidden: hidden, v: 1, ts: Date.now() };
        try { localStorage.setItem(_prefsKey(order), JSON.stringify(payload)); } catch (_) {}
    }

    function _loadAndApplyPrefs(tableId) {
        const tbl = _table(tableId);
        if (!tbl) return;
        const current = _allCols(tbl);
        if (!current.length) return;
        let saved;
        try { saved = JSON.parse(localStorage.getItem(_prefsKey(current)) || 'null'); } catch (_) { return; }
        if (!saved || typeof saved !== 'object') return;

        // 1) Sıralama: kayıtlı order'a göre DOM'da yeniden diz
        if (Array.isArray(saved.order)) {
            const headRow = tbl.querySelector('thead tr');
            const bodyRows = tbl.querySelectorAll('tbody tr');
            saved.order.forEach(function (col) {
                if (!current.includes(col)) return; // schema değişmiş, atla
                const th = headRow && headRow.querySelector('th[data-col="' + col.replace(/"/g, '\\"') + '"]');
                if (th) headRow.appendChild(th);
                bodyRows.forEach(function (tr) {
                    const td = tr.querySelector('td[data-col="' + col.replace(/"/g, '\\"') + '"]');
                    if (td) tr.appendChild(td);
                });
            });
        }
        // 2) Gizleme uygula
        if (Array.isArray(saved.hidden)) {
            const menu = document.getElementById(tableId + '_menu');
            saved.hidden.forEach(function (col) {
                if (!current.includes(col)) return;
                _cellsFor(tbl, col).forEach(function (el) { el.style.display = 'none'; });
                if (menu) {
                    const cb = menu.querySelector('input[type="checkbox"][data-col="' + col.replace(/"/g, '\\"') + '"]');
                    if (cb) cb.checked = false;
                }
            });
        }
    }

    function getOrderedVisibleState(tableId) {
        // v3.27.3: Export & CSV için — kullanıcının gördüğü sıra+görünür kolonlar
        const tbl = _table(tableId);
        if (!tbl) return null;
        const visible = Array.prototype.slice.call(tbl.querySelectorAll('thead th[data-col]'))
            .filter(function (th) { return th.style.display !== 'none'; })
            .map(function (th) { return th.getAttribute('data-col'); });
        return { columns: visible };
    }

    // Yeni eklenen tabloları otomatik mount et (MutationObserver)
    function _initObserver() {
        if (!('MutationObserver' in window)) return;
        const obs = new MutationObserver(function (muts) {
            muts.forEach(function (m) {
                m.addedNodes && m.addedNodes.forEach(function (n) {
                    if (!(n instanceof HTMLElement)) return;
                    // Eklenen düğüm wrap olabilir veya alt ağaçta wrap içerebilir
                    const wraps = n.matches && n.matches('.db-result-table-wrap[data-table-id]')
                        ? [n]
                        : Array.prototype.slice.call(n.querySelectorAll ? n.querySelectorAll('.db-result-table-wrap[data-table-id]') : []);
                    wraps.forEach(function (w) {
                        const id = w.getAttribute('data-table-id');
                        if (id) {
                            try { _loadAndApplyPrefs(id); } catch (_) {}
                        }
                    });
                });
            });
        });
        obs.observe(document.body, { childList: true, subtree: true });
    }
    if (typeof document !== 'undefined' && document.body) {
        _initObserver();
    } else if (typeof document !== 'undefined') {
        document.addEventListener('DOMContentLoaded', _initObserver);
    }

    function _cellsFor(tbl, col) {
        // CSS attribute selector için tırnak escape — sadece data-col değeri
        const sel = 'th[data-col="' + col.replace(/"/g, '\\"') + '"], td[data-col="' + col.replace(/"/g, '\\"') + '"]';
        try { return tbl.querySelectorAll(sel); } catch (_) { return []; }
    }

    function toggleColMenu(tableId, ev) {
        if (ev) ev.stopPropagation();
        const menu = document.getElementById(tableId + '_menu');
        if (!menu) return;
        menu.hidden = !menu.hidden;
        if (!menu.hidden) {
            // Dış tıklamada kapat
            const closer = function (e) {
                if (!menu.contains(e.target) && !e.target.closest('.db-cols-btn')) {
                    menu.hidden = true;
                    document.removeEventListener('click', closer);
                }
            };
            setTimeout(() => document.addEventListener('click', closer), 0);
        }
    }

    function toggleCol(tableId, col, visible) {
        const tbl = _table(tableId);
        if (!tbl) return;
        _cellsFor(tbl, col).forEach(function (el) {
            el.style.display = visible ? '' : 'none';
        });
        _savePrefs(tableId);
    }

    function allCols(tableId, visible) {
        const tbl = _table(tableId);
        if (!tbl) return;
        const menu = document.getElementById(tableId + '_menu');
        if (!menu) return;
        menu.querySelectorAll('input[type="checkbox"][data-col]').forEach(function (cb) {
            cb.checked = !!visible;
            const t = _table(tableId);
            if (t) _cellsFor(t, cb.dataset.col).forEach(function (el) {
                el.style.display = visible ? '' : 'none';
            });
        });
        _savePrefs(tableId);
    }

    // ── Drag/Drop ────────────────────────────────────────────────────────────
    function onDragStart(e) {
        const th = e.target.closest('th[data-col]');
        if (!th) return;
        dragSrcCol = th.getAttribute('data-col');
        const tbl = th.closest('table.db-result-table');
        dragTableId = tbl ? tbl.getAttribute('data-table-id') : null;
        try { e.dataTransfer.effectAllowed = 'move'; } catch (_) {}
        try { e.dataTransfer.setData('text/plain', dragSrcCol); } catch (_) {}
        th.classList.add('dragging');
    }

    function onDragOver(e) {
        if (!dragSrcCol) return;
        e.preventDefault();
        try { e.dataTransfer.dropEffect = 'move'; } catch (_) {}
        return false;
    }

    function onDragEnter(e) {
        const th = e.target.closest('th[data-col]');
        if (th && dragSrcCol && th.getAttribute('data-col') !== dragSrcCol) {
            th.classList.add('drop-target');
        }
    }

    function onDragLeave(e) {
        const th = e.target.closest('th[data-col]');
        if (th) th.classList.remove('drop-target');
    }

    function onDrop(e) {
        e.preventDefault();
        const targetTh = e.target.closest('th[data-col]');
        if (!targetTh || !dragSrcCol) return false;
        const targetCol = targetTh.getAttribute('data-col');
        if (targetCol === dragSrcCol) return false;
        const tbl = targetTh.closest('table.db-result-table');
        if (!tbl || tbl.getAttribute('data-table-id') !== dragTableId) return false;
        _moveColumn(tbl, dragSrcCol, targetCol);
        targetTh.classList.remove('drop-target');
        return false;
    }

    function onDragEnd(_e) {
        document.querySelectorAll('th.dragging, th.drop-target').forEach(function (el) {
            el.classList.remove('dragging');
            el.classList.remove('drop-target');
        });
        dragSrcCol = null;
        dragTableId = null;
    }

    function _moveColumn(tbl, srcCol, tgtCol) {
        // Header
        const headRow = tbl.querySelector('thead tr');
        if (!headRow) { return; }
        const tableId = tbl.getAttribute('data-table-id');
        const srcTh = headRow.querySelector('th[data-col="' + srcCol.replace(/"/g, '\\"') + '"]');
        const tgtTh = headRow.querySelector('th[data-col="' + tgtCol.replace(/"/g, '\\"') + '"]');
        if (!srcTh || !tgtTh) return;
        const headChildren = Array.prototype.slice.call(headRow.children);
        const srcIdx = headChildren.indexOf(srcTh);
        const tgtIdx = headChildren.indexOf(tgtTh);
        if (srcIdx === tgtIdx) return;
        if (srcIdx < tgtIdx) {
            tgtTh.parentNode.insertBefore(srcTh, tgtTh.nextSibling);
        } else {
            tgtTh.parentNode.insertBefore(srcTh, tgtTh);
        }
        // Body rows — aynı index ile td'leri taşı
        tbl.querySelectorAll('tbody tr').forEach(function (tr) {
            const srcTd = tr.querySelector('td[data-col="' + srcCol.replace(/"/g, '\\"') + '"]');
            const tgtTd = tr.querySelector('td[data-col="' + tgtCol.replace(/"/g, '\\"') + '"]');
            if (!srcTd || !tgtTd || srcTd === tgtTd) return;
            const kids = Array.prototype.slice.call(tr.children);
            if (kids.indexOf(srcTd) < kids.indexOf(tgtTd)) {
                tgtTd.parentNode.insertBefore(srcTd, tgtTd.nextSibling);
            } else {
                tgtTd.parentNode.insertBefore(srcTd, tgtTd);
            }
        });
        if (tableId) _savePrefs(tableId);
    }

    return {
        toggleColMenu,
        toggleCol,
        allCols,
        onDragStart,
        onDragOver,
        onDragEnter,
        onDragLeave,
        onDrop,
        onDragEnd,
        // v3.27.3
        getOrderedVisibleState,
    };
})();
