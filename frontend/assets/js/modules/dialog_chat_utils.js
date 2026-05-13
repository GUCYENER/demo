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

        const rowCount = meta?.row_count || rows.length;
        const rowsShown = meta?.rows_shown || rows.length;
        const sourceDb = meta?.source_db || '';
        const truncated = rowCount > rowsShown;

        let html = `<div class="db-result-table-wrap">`;

        // Meta bar
        html += `<div class="db-result-meta">`;
        if (sourceDb) html += `<span class="db-result-db">🗄️ ${escapeHtml(sourceDb)}</span>`;
        html += `<span class="db-result-count">📊 ${rowsShown} kayıt`;
        if (truncated) html += ` <span class="db-truncated-badge">(toplam ${rowCount})</span>`;
        html += `</span></div>`;

        // Tablo
        html += `<div class="db-table-scroll"><table class="db-result-table">`;

        // Header
        html += `<thead><tr>`;
        columns.forEach(col => {
            html += `<th>${escapeHtml(col)}</th>`;
        });
        html += `</tr></thead>`;

        // Body
        html += `<tbody>`;
        rows.forEach((row, rowIdx) => {
            const cls = rowIdx % 2 === 0 ? '' : ' class="alt-row"';
            html += `<tr${cls}>`;
            columns.forEach(col => {
                const val = row[col];
                const display = val === null || val === undefined ? '<span class="null-val">—</span>' : escapeHtml(String(val));
                html += `<td>${display}</td>`;
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

        const id = 'fuchips_' + Date.now();

        window[id + '_send'] = function(q) {
            if (typeof onSelect === 'function') onSelect(q);
            const wrap = document.getElementById(id);
            if (wrap) wrap.remove();
        };

        let html = `<div class="db-followup-wrap" id="${id}">`;
        html += `<div class="db-followup-label">💡 İlgili sorgular:</div>`;
        html += `<div class="db-followup-chips">`;

        suggestions.forEach(s => {
            const label = escapeHtml(s.text || s.query);
            const q = escapeHtml(s.query || s.text);
            html += `<button class="db-followup-chip" onclick="window['${id}_send']('${q}')">${label}</button>`;
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
