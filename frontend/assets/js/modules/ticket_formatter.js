/* ─────────────────────────────────────────────
   NGSSAI — Ticket Formatter Module
   v2.30.1 · ticket_history.js'den ayrıştırıldı
   Markdown/HTML formatlama, çözüm formatlama
   ───────────────────────────────────────────── */

/**
 * Hafif Markdown to HTML converter (bold, bullets, headings)
 * Modern SaaS görünüm için VYRA mesajlarını formatlar
 */
function formatMarkdownToHTML(text) {
    if (!text) return '';

    let html = text;

    // 🆕 v2.49.0: <img> taglerini encoding öncesi koruma altına al
    const imgPlaceholders = [];
    html = html.replace(/<img\s[^>]*>/gi, (match) => {
        const placeholder = `__IMG_PLACEHOLDER_${imgPlaceholders.length}__`;
        imgPlaceholders.push(match);
        return placeholder;
    });

    // XSS koruması için tehlikeli karakterleri encode et
    html = html.replace(/</g, '&lt;').replace(/>/g, '&gt;');

    // 1. Bold: **text** -> <strong>text</strong>
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

    // 2. Headings: ### Heading -> <h4>Heading</h4>
    html = html.replace(/^###\s+(.+)$/gm, '<h4 class="thread-heading">$1</h4>');
    html = html.replace(/^##\s+(.+)$/gm, '<h3 class="thread-heading">$1</h3>');

    // 3. Lists (bullet and numbered)
    const lines = html.split('\n');
    let inBulletList = false;
    let inNumberedList = false;
    let result = [];

    for (let line of lines) {
        const bulletMatch = line.match(/^[-*]\s+(.+)$/);
        const numberedMatch = line.match(/^(\d+)\.\s+(.+)$/);

        if (bulletMatch) {
            // Close numbered list if open
            if (inNumberedList) {
                result.push('</ol>');
                inNumberedList = false;
            }
            // Start bullet list if not already started
            if (!inBulletList) {
                result.push('<ul class="thread-list">');
                inBulletList = true;
            }
            result.push(`<li>${bulletMatch[1]}</li>`);
        } else if (numberedMatch) {
            // Close bullet list if open
            if (inBulletList) {
                result.push('</ul>');
                inBulletList = false;
            }
            // Start numbered list if not already started
            if (!inNumberedList) {
                result.push('<ol class="thread-list">');
                inNumberedList = true;
            }
            result.push(`<li>${numberedMatch[2]}</li>`);
        } else {
            // Close any open lists
            if (inBulletList) {
                result.push('</ul>');
                inBulletList = false;
            }
            if (inNumberedList) {
                result.push('</ol>');
                inNumberedList = false;
            }
            if (line.trim()) {
                result.push(line);
            }
        }
    }

    // Close any open lists at the end
    if (inBulletList) result.push('</ul>');
    if (inNumberedList) result.push('</ol>');

    html = result.join('\n');

    // 4. Line breaks
    html = html.replace(/\n/g, '<br>');

    // 🆕 v2.49.0: img placeholder'ları geri koy + dt-image-container ile sar
    for (let i = 0; i < imgPlaceholders.length; i++) {
        const placeholder = `__IMG_PLACEHOLDER_${i}__`;
        html = html.replace(placeholder, `<div class="dt-image-container">${imgPlaceholders[i]}</div>`);
    }

    // 🆕 v2.49.0: Relative /api/ URL'leri absolute backend URL'e çevir
    const apiBase = (typeof API_BASE_URL !== 'undefined')
        ? API_BASE_URL
        : (window.API_BASE_URL || 'http://localhost:8002');
    html = html.replace(/src="\/api\//g, `src="${apiBase}/api/`);

    return html;
}

/**
 * LLM değerlendirme mesajlarını formatla (Markdown destekli)
 */
function formatLLMEvaluationForHistory(solution) {
    // v2.21.12: FEEDBACK_SECTION satırlarını temizle
    solution = solution
        .split('\n')
        .filter(line => {
            const trimmed = line.trim();
            return trimmed !== '---' &&
                trimmed !== '[FEEDBACK_SECTION]' &&
                trimmed !== '[/FEEDBACK_SECTION]' &&
                !trimmed.startsWith('**Bu değerlendirme');
        })
        .join('\n')
        .trim();

    return formatMarkdownToHTML(solution);
}

// Çözümü formatla (numaralı liste formatı + Alternatif olarak ikonu için)
function formatSolution(solution) {
    if (!solution) return '<p class="text-gray-500">Çözüm bilgisi yok</p>';

    // v2.21.12: FEEDBACK_SECTION ve --- satırlarını temizle
    solution = solution
        .split('\n')
        .filter(line => {
            const trimmed = line.trim();
            return trimmed !== '---' &&
                trimmed !== '[FEEDBACK_SECTION]' &&
                trimmed !== '[/FEEDBACK_SECTION]' &&
                !trimmed.startsWith('**Bu değerlendirme');
        })
        .join('\n')
        .trim();

    // 🔧 v2.21.12: ÖNCE markdown kontrolü (AI değerlendirmeleri için)
    // SolutionDisplayModule markdown desteklemediği için BYPASS et
    const isMarkdown = /###|\*\*|-\s|^\d+\./.test(solution);
    if (isMarkdown) {
        return formatLLMEvaluationForHistory(solution);
    }

    // 🎯 SolutionDisplayModule varsa onu kullan (daha zengin key-value formatı)
    // Markdown içermeyenler için
    if (typeof window.SolutionDisplayModule !== 'undefined' && window.SolutionDisplayModule.format) {
        return window.SolutionDisplayModule.format(solution);
    }

    // Önce inline numaralı adımları kontrol et: "1) ... 2) ... 3) ..."
    const inlineNumberedPattern = /(\d+)[.\)]\s/g;
    const matches = solution.match(inlineNumberedPattern);

    // Eğer inline numaralı adımlar varsa ve yeni satır yoksa
    if (matches && matches.length >= 2 && !solution.includes('\n')) {
        return formatInlineStepsHistory(solution);
    }

    // Yeni satırlarla ayrılmış format
    const lines = solution.split('\n');
    let html = '';
    let inList = false;
    let inAlternative = false;
    let alternativeListStarted = false;

    lines.forEach(line => {
        const trimmedLine = line.trim();
        if (!trimmedLine) return;

        // "Alternatif olarak:" kontrolü
        const alternativeMatch = trimmedLine.match(/^alternatif(?:\s+olarak)?[:]/i);
        if (alternativeMatch) {
            // Önceki listeyi kapat
            if (inList) {
                html += '</ol>';
                inList = false;
            }

            // Alternatif bölümü başlığı (ikonlu)
            html += `
                <div class="alternative-section">
                    <div class="alternative-header">
                        <i class="fa-solid fa-shuffle"></i>
                        <span>Alternatif Olarak</span>
                    </div>
                </div>
            `;
            inAlternative = true;
            alternativeListStarted = false;
            return;
        }

        // Numaralı satır kontrolü (1. veya 1) formatında)
        const numberedMatch = trimmedLine.match(/^(\d+)[.\)]\s*(.+)/);

        if (numberedMatch) {
            if (!inList) {
                // Alternatif bölümündeyse farklı class kullan
                const listClass = inAlternative ? 'solution-list alternative-list' : 'solution-list';
                html += `<ol class="${listClass}">`;
                inList = true;
                if (inAlternative) alternativeListStarted = true;
            }
            html += `<li>${escapeHtml(numberedMatch[2])}</li>`;
        } else {
            if (inList) {
                html += '</ol>';
                inList = false;
            }

            // Kaynak satırı kontrolü (📄 veya Kaynak: ile başlayan)
            if (trimmedLine.startsWith('📄') || trimmedLine.toLowerCase().startsWith('kaynak:')) {
                html += `
                    <div class="source-info">
                        <i class="fa-solid fa-file-lines"></i>
                        <span>${escapeHtml(trimmedLine.replace('📄', '').replace(/^kaynak:/i, '').trim())}</span>
                    </div>
                `;
            } else if (trimmedLine === '---') {
                // Ayraç satırı
                html += '<hr class="solution-divider">';
            } else if (trimmedLine.includes('rag-inline-image') || trimmedLine.startsWith('<img ')) {
                // 🆕 v2.49.0: RAG görselleri — escape etmeden doğrudan HTML olarak geçir
                html += `<div class="dt-image-container">${trimmedLine}</div>`;
            } else {
                html += `<p>${escapeHtml(trimmedLine)}</p>`;
            }
        }
    });

    if (inList) html += '</ol>';

    return html || `<p>${escapeHtml(solution)}</p>`;
}

// Inline numaralı adımları ayır (geçmiş çözümler için)
function formatInlineStepsHistory(text) {
    // Kaynak bilgisini ayır
    let sourceHtml = '';
    const sourceMatch = text.match(/📄\s*Kaynak:\s*(.+?)(?:\s*$|\.?\s*$)/i) ||
        text.match(/Kaynak:\s*(.+?)(?:\s*$|\.?\s*$)/i);
    if (sourceMatch) {
        sourceHtml = `
            <div class="source-info">
                <i class="fa-solid fa-file-lines"></i>
                <span>${escapeHtml(sourceMatch[1].trim())}</span>
            </div>
        `;
        text = text.replace(sourceMatch[0], '').trim();
    }

    // "---" sonrasını ayır
    if (text.includes('---')) {
        text = text.split('---')[0].trim();
    }

    // Numaralı adımları bul ve ayır
    const stepPattern = /(\d+)[.\)]\s*([^0-9]+?)(?=\d+[.\)]|$)/g;
    const steps = [];
    let match;

    while ((match = stepPattern.exec(text)) !== null) {
        let stepContent = match[2].trim();

        // Kaynak bilgisini temizle
        if (stepContent.toLowerCase().includes('kaynak:')) {
            stepContent = stepContent.split(/kaynak:/i)[0].trim();
        }

        if (stepContent.length > 5) {
            steps.push(stepContent);
        }
    }

    // Adımlar bulunamadıysa düz metin
    if (steps.length === 0) {
        return `<p>${escapeHtml(text)}</p>${sourceHtml}`;
    }

    // Numaralı liste olarak döndür
    let html = '<ol class="solution-list">';
    steps.forEach(step => {
        html += `<li>${escapeHtml(step)}</li>`;
    });
    html += '</ol>';

    return html + sourceHtml;
}

// Clipboard kopyalama
function copyToClipboard(button, text) {
    // Escape karakterlerini geri dönüştür
    const decodedText = text.replace(/\\n/g, '\n').replace(/\\'/g, "'").replace(/\\"/g, '"');

    navigator.clipboard.writeText(decodedText).then(() => {
        const icon = button.querySelector('i');
        const originalClass = icon.className;
        icon.className = 'fa-solid fa-check';
        button.classList.add('copied');

        setTimeout(() => {
            icon.className = originalClass;
            button.classList.remove('copied');
        }, 2000);
    }).catch(err => {
        console.error('Kopyalama hatası:', err);
    });
}

// HTML escape
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Attribute için escape (tek tırnak ve yeni satırlar)
function escapeForAttribute(text) {
    if (!text) return '';
    return text.replace(/'/g, "\\'").replace(/"/g, '\\"').replace(/\n/g, '\\n');
}
