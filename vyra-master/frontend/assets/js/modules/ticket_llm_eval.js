/* ─────────────────────────────────────────────
   VYRA – Ticket LLM Evaluation Module
   v2.30.1 · ticket_history.js'den ayrıştırıldı
   LLM değerlendirme ve formatlama
   ───────────────────────────────────────────── */

/**
 * Geçmiş çözüm için LLM değerlendirmesi iste
 */
async function requestLLMEvaluationForHistory(ticketId, buttonEl) {
    if (!ticketId || !buttonEl) return;

    // Accordion item'ı bul
    const accordionItem = buttonEl.closest('.accordion-item');
    if (!accordionItem) {
        console.error('[VYRA] Accordion item bulunamadı');
        return;
    }

    // Kullanıcı sorgusunu ve çözümü al
    const queryEl = accordionItem.querySelector('.accordion-query');
    const solutionEl = accordionItem.querySelector('.accordion-solution');

    const query = queryEl?.innerText || '';
    const solution = solutionEl?.innerText || '';

    if (!query || !solution) {
        if (typeof VyraToast !== 'undefined') {
            VyraToast.warning('Değerlendirilecek içerik bulunamadı.');
        }
        return;
    }

    // Loading state
    buttonEl.disabled = true;
    buttonEl.classList.add('loading');
    buttonEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> <span class="llm-btn-text">Değerlendiriliyor...</span>';

    try {
        // WebSocket client varsa kullan
        if (typeof VyraWebSocket !== 'undefined' && VyraWebSocket.evaluateWithLLM) {
            const result = await VyraWebSocket.evaluateWithLLM(query, solution, ticketId);

            // Sonucu göster
            const resultBox = document.getElementById(`llmResult-${ticketId}`);
            const resultContent = document.getElementById(`llmResultContent-${ticketId}`);

            if (resultBox && resultContent) {
                // v2.21.12: Markdown formatını uygula (Modern SaaS görünüm)
                const formattedContent = formatMarkdownToHTML(result.formatted_html || '');
                resultContent.innerHTML = formattedContent;
                resultBox.classList.remove('hidden');
            }

            // Butonu gizle
            const containerHistory = buttonEl.closest('.llm-evaluate-container-history');
            if (containerHistory) {
                containerHistory.style.display = 'none';
            }

            if (typeof VyraToast !== 'undefined') {
                VyraToast.success('Corpix AI değerlendirmesi tamamlandı!');
            }
        } else {
            // WebSocket client yoksa hata göster
            throw new Error('WebSocket bağlantısı bulunamadı');
        }

    } catch (err) {
        console.error('[VYRA] LLM değerlendirme hatası:', err);

        buttonEl.innerHTML = '<i class="fa-solid fa-brain"></i> <span class="llm-btn-text">Corpix ile Değerlendir</span>';
        buttonEl.disabled = false;
        buttonEl.classList.remove('loading');

        // 🌐 VPN/Network hatası kontrolü
        const errorMsg = err?.message || String(err);
        if (window.isVPNNetworkError && window.isVPNNetworkError(errorMsg)) {
            console.log('[VYRA] VPN/LLM bağlantı hatası tespit edildi - popup gösteriliyor');
            if (window.showVPNErrorPopup) {
                window.showVPNErrorPopup();
            }
            // VPN hatası durumunda Toast GÖSTERME (popup yeterli)
        } else if (typeof VyraToast !== 'undefined') {
            VyraToast.error('Değerlendirme hatası: ' + errorMsg);
        }
    }
}

/**
 * LLM değerlendirme metnini HTML'e formatla - Modern SaaS görünümü
 */
function formatLLMEvaluationForHistory(llmText) {
    if (!llmText) return '<p class="llm-empty-state">Değerlendirme içeriği yok</p>';

    let html = escapeHtml(llmText);

    // 1. Başlıklar (### ve ####) - Önce bunları işle
    html = html.replace(/^###\s+(.+)$/gm, '<h3 class="llm-h3">$1</h3>');
    html = html.replace(/^####\s+(.+)$/gm, '<h4 class="llm-h4">$1</h4>');

    // 2. Bold (**text**)
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // 3. Italic (*text*)
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');

    // 4. Code (`text`)
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // 5. Listeler
    // Markdown listelerini işlemeden önce satır satır ayıralım
    const lines = html.split('\n');
    let result = [];
    let listType = null; // 'ul' veya 'ol'

    for (let line of lines) {
        // Eğer zaten H3/H4 ise dokunma
        if (line.startsWith('<h3') || line.startsWith('<h4')) {
            if (listType) {
                result.push(`</${listType}>`);
                listType = null;
            }
            result.push(line);
            continue;
        }

        const trimmed = line.trim();

        // Bullet List (- veya *)
        const bulletMatch = trimmed.match(/^[-*]\s+(.+)$/);
        // Numbered List (1. ) 
        // Not: <h4 class="...">1. Adım</h4> gibi HTML tagleriyle karışmaması için dikkat
        const numberMatch = trimmed.match(/^(\d+)\.\s+(.+)$/);

        if (bulletMatch) {
            if (listType !== 'ul') {
                if (listType) result.push(`</${listType}>`);
                result.push('<ul class="llm-bullet-list">');
                listType = 'ul';
            }
            result.push(`<li>${bulletMatch[1]}</li>`);
        }
        else if (numberMatch) {
            if (listType !== 'ol') {
                if (listType) result.push(`</${listType}>`);
                result.push('<ol class="llm-steps-list">');
                listType = 'ol';
            }
            result.push(`<li>${numberMatch[2]}</li>`);
        }
        else {
            // Liste elemanı değil
            if (listType) {
                result.push(`</${listType}>`);
                listType = null;
            }

            if (trimmed) {
                // Key: Value tespiti (ve HTML etiketi ile başlamıyorsa)
                if (!trimmed.startsWith('<') && /^([A-Za-zÇçĞğİıÖöŞşÜü\s\/]+):\s*(.+)$/.test(trimmed)) {
                    result.push(trimmed.replace(/^([A-Za-zÇçĞğİıÖöŞşÜü\s\/]+):\s*(.+)$/, '<div class="llm-kv-row"><strong>$1:</strong> $2</div>'));
                } else {
                    // Düz paragraf
                    result.push(`<div class="llm-paragraph">${trimmed}</div>`);
                }
            }
        }
    }

    if (listType) {
        result.push(`</${listType}>`);
    }

    return result.join('');
}

// Global erişim - LLM fonksiyonları
window.requestLLMEvaluationForHistory = requestLLMEvaluationForHistory;
window.formatLLMEvaluationForHistory = formatLLMEvaluationForHistory;
