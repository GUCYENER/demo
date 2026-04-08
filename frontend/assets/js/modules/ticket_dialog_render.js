/* ─────────────────────────────────────────────
   NGSSAI — Ticket Dialog Render Module
   v2.30.1 · ticket_history.js'den ayrıştırıldı
   Dialog mesajları, legacy format, thread render
   ───────────────────────────────────────────── */

/**
 * Dialog mesajlarını API'den yükle ve render et
 */
async function loadDialogMessages(dialogId, container, ticketId) {
    if (!dialogId || !container) return;

    try {
        const response = await window.VYRA_API.request(`/dialogs/${dialogId}/messages?limit=100`, { method: "GET" });

        if (response && response.length > 0) {
            container.innerHTML = renderConversationThread(response);
            container.dataset.loaded = 'true';
        } else {
            container.innerHTML = `
                <div class="thread-empty">
                    <i class="fa-solid fa-inbox"></i>
                    <span>Bu görüşmede henüz mesaj yok.</span>
                </div>
            `;
            container.dataset.loaded = 'true';
        }
    } catch (err) {
        console.error('[TicketHistory] Mesaj yükleme hatası:', err);
        container.innerHTML = `
            <div class="thread-error">
                <i class="fa-solid fa-exclamation-triangle"></i>
                <span>Mesajlar yüklenemedi: ${err.message || 'Bilinmeyen hata'}</span>
            </div>
        `;
    }
}

/**
 * Ticket için eski formatı göster (first/last)
 * 🆕 v2.23.0: RAG-only ticket'lar için rag_results göster
 */
function renderLegacyFormat(container, ticketId) {
    // Cache'den ticket bilgisini bul (string/int uyumsuzluğu için == kullan)
    const ticket = _historyCache?.find(t => String(t.id) === String(ticketId));

    if (!ticket) {
        console.warn('[TicketHistory] Cache\'de ticket bulunamadı:', ticketId, 'Cache:', _historyCache?.map(t => t.id));
        container.innerHTML = '<p class="text-gray-500">Çözüm bilgisi bulunamadı.</p>';
        container.dataset.loaded = 'true';
        return;
    }

    const userQuery = ticket.description || ticket.query || 'Talep bilgisi yok';

    // 🆕 v2.23.0: RAG sonuçları varsa onları göster (rag_only veya her durumda)
    const ragResults = ticket.rag_results || [];
    const finalSolution = ticket.final_solution;
    const interactionType = ticket.interaction_type || 'unknown';

    // VYRA cevabını oluştur
    let vyraContent = '';

    if (ragResults.length > 0) {
        // RAG sonuçları var - kartları göster
        vyraContent = `
            <div class="vyra-rag-section">
                <div class="rag-section-header">
                    <i class="fa-solid fa-search"></i>
                    <span>Bilgi Tabanından Bulunan Sonuçlar (${ragResults.length})</span>
                </div>
                ${renderRAGCardsForHistory(ragResults)}
            </div>
        `;
    }

    if (finalSolution) {
        // AI değerlendirmesi yapılmış - onu da ekle
        vyraContent += `
            <div class="vyra-solution-section">
                <div class="solution-section-header">
                    <i class="fa-solid fa-brain"></i>
                    <span>AI Değerlendirmesi</span>
                </div>
                <div class="solution-content">${formatSolution(finalSolution)}</div>
            </div>
        `;
    } else if (ragResults.length === 0) {
        // Ne RAG ne AI var - bilgi yok mesajı
        vyraContent = '<p class="text-gray-500">Henüz çözüm bilgisi oluşturulmamış.</p>';
    }

    // Etkileşim tipi badge
    let interactionBadge = '';
    if (interactionType === 'rag_only') {
        interactionBadge = '<span class="interaction-badge badge-rag">🔍 RAG Araması</span>';
    } else if (interactionType === 'ai_evaluation') {
        interactionBadge = '<span class="interaction-badge badge-ai">🧠 AI Değerlendirmesi</span>';
    } else if (interactionType === 'user_selection') {
        interactionBadge = '<span class="interaction-badge badge-user">👆 Kullanıcı Seçimi</span>';
    }

    container.innerHTML = `
        <div class="thread-message thread-user">
            <div class="thread-message-header">
                <i class="fa-solid fa-user"></i>
                <span class="thread-role">Kullanıcı</span>
            </div>
            <div class="thread-message-content">${escapeHtml(userQuery)}</div>
        </div>
        <div class="thread-message thread-assistant">
            <div class="thread-message-header">
                <i class="fa-solid fa-robot"></i>
                <span class="thread-role">VYRA</span>
                ${interactionBadge}
            </div>
            <div class="thread-message-content">${vyraContent}</div>
        </div>
    `;
    container.dataset.loaded = 'true';
}

/**
 * Mesaj listesini WhatsApp tarzı thread olarak render et
 */
function renderConversationThread(messages) {
    if (!messages || messages.length === 0) {
        return '<p class="thread-empty">Mesaj bulunamadı.</p>';
    }

    let html = '';

    for (const msg of messages) {
        const isUser = msg.role === 'user';
        const roleClass = isUser ? 'thread-user' : 'thread-assistant';
        const icon = isUser ? 'fa-user' : 'fa-robot';
        const roleName = isUser ? 'Kullanıcı' : 'VYRA';

        // Mesaj zamanı
        let timeStr = '';
        if (msg.created_at) {
            const date = new Date(msg.created_at);
            timeStr = date.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
        }

        // Content type'a göre render
        let content = msg.content || '';

        // v2.49.1: Görseller artık metadata'dan render edildiği için
        // content'teki raw <img> tagleri ve "📷 İlgili Görseller:" başlığını temizle
        if (!isUser && msg.metadata && msg.metadata.image_ids && msg.metadata.image_ids.length > 0) {
            content = content.replace(/<img\s[^>]*>/gi, '');
            content = content.replace(/📷\s*İlgili Görseller:?\s*/g, '');
            content = content.replace(/\n{3,}/g, '\n\n'); // fazla boş satırları temizle
        }

        // Quick reply mesajlarını özel göster
        if (msg.content_type === 'quick_reply') {
            // v2.21.12: Quick reply içinde markdown varsa formatla
            const hasMarkdown = /###|\*\*|-\s|^\d+\.|[*-]\s/.test(content);
            if (hasMarkdown) {
                content = formatSolution(content);
            } else {
                content = `<span class="thread-quick-reply">${escapeHtml(content)}</span>`;
            }
        } else {
            // Normal mesaj için Markdown formatla
            content = formatSolution(content);
        }

        // 🆕 v2.49.0: Relative /api/ URL'leri absolute backend URL'e çevir
        const apiBase = (typeof API_BASE_URL !== 'undefined')
            ? API_BASE_URL
            : (window.API_BASE_URL || 'http://localhost:8002');
        content = content.replace(/src="\/api\//g, `src="${apiBase}/api/`);

        // 🆕 v2.49.1: Metadata'daki image_ids'den görselleri direkt render et
        let imageHtml = '';
        if (!isUser && msg.metadata && msg.metadata.image_ids && msg.metadata.image_ids.length > 0) {
            const imgTags = msg.metadata.image_ids.map(imgId =>
                `<img class="rag-inline-image" src="${apiBase}/api/rag/images/${imgId}" alt="Doküman görseli" data-image-id="${imgId}" loading="lazy" />`
            ).join(' ');
            imageHtml = `
                <div class="thread-images-section">
                    <div class="dt-section-label dt-section-info">
                        <span class="dt-section-icon">📷</span>
                        <span class="dt-section-title">İlgili Görseller</span>
                    </div>
                    <div class="dt-image-container">${imgTags}</div>
                </div>
            `;
        }

        // v2.21.8: RAG sonuçları metadata'da varsa kartları da göster
        let ragCardsHtml = '';
        if (msg.metadata && msg.metadata.rag_results && msg.metadata.rag_results.length > 0) {
            ragCardsHtml = renderRAGCardsForHistory(msg.metadata.rag_results);
        }

        html += `
            <div class="thread-message ${roleClass}">
                <div class="thread-message-header">
                    <i class="fa-solid ${icon}"></i>
                    <span class="thread-role">${roleName}</span>
                    ${timeStr ? `<span class="thread-time">${timeStr}</span>` : ''}
                </div>
                <div class="thread-message-content">${content}</div>
                ${imageHtml}
                ${ragCardsHtml}
            </div>
        `;
    }

    return html;
}

/**
 * v2.21.8: RAG sonuç kartlarını Geçmiş Çözümler için render et (readonly)
 */
function renderRAGCardsForHistory(ragResults) {
    if (!ragResults || ragResults.length === 0) return '';

    let cardsHtml = '<div class="history-rag-cards">';

    for (let i = 0; i < ragResults.length; i++) {
        const r = ragResults[i];
        const fileName = r.file_name || `Seçenek ${i + 1}`;
        const score = r.similarity_score || 0;
        const scorePercent = Math.round(score * 100);

        // Ana içerik - chunk_text (çözüm detayı)
        let chunkText = r.chunk_text || '';
        // İlk 300 karakteri göster (çok uzunsa kısalt)
        if (chunkText.length > 300) {
            chunkText = chunkText.substring(0, 300) + '...';
        }

        // Dosya tipi ve heading (varsa)
        const fileType = r.file_type || '';
        const heading = r.heading || '';

        cardsHtml += `
            <div class="history-rag-card">
                <div class="history-rag-card-header">
                    <span class="history-rag-filename">${escapeHtml(fileName)}</span>
                    <span class="history-rag-score">${scorePercent}%</span>
                </div>
                <div class="history-rag-card-body">
                    ${heading ? `<div class="history-rag-heading"><strong>📑</strong> ${formatMarkdownToHTML(heading)}</div>` : ''}
                    ${chunkText ? `<div class="history-rag-content">${formatMarkdownToHTML(chunkText)}</div>` : ''}
                    ${fileType ? `<div class="history-rag-type"><small>📄 ${escapeHtml(fileType)}</small></div>` : ''}
                </div>
            </div>
        `;
    }

    cardsHtml += '</div>';
    return cardsHtml;
}
