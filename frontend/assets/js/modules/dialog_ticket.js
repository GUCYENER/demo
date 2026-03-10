/* ─────────────────────────────────────────────
   NGSSAI — Dialog Ticket & Corpix Module
   v2.30.1 · dialog_chat.js'den ayrıştırıldı
   Ticket Summary, Corpix Fallback, Chat Mode
   ───────────────────────────────────────────── */

window.DialogTicketModule = (function () {
    'use strict';

    const API_BASE = (window.API_BASE_URL || 'http://localhost:8002') + '/api';

    const { escapeHtml, showToast } = window.DialogChatUtils;

    // v2.49.1: Kopyalama için sorun metnini sakla (DOM bağımlılığı kaldırıldı)
    let _lastSorunText = '';

    // =============================================================================
    // PARENT MODULE HELPERS (dialog_chat.js'ten delegation)
    // =============================================================================

    function getParent() { return window.DialogChatModule; }

    // =============================================================================
    // TICKET SUMMARY & CORPIX FALLBACK (v2.24.5)
    // =============================================================================

    /**
     * Ticket Modal event listener'larını bağla
     */
    function bindTicketModalEvents() {
        const modal = document.getElementById('ticketSummaryModal');
        const closeBtn = document.getElementById('closeTicketModal');
        const closeBtnAlt = document.getElementById('btnCloseTicketModal');
        const copyBtn = document.getElementById('btnCopyTicket');

        // ESC ile kapat
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && modal && !modal.classList.contains('hidden')) {
                closeTicketModal();
            }
        });

        // X butonu ile kapat
        if (closeBtn) {
            closeBtn.addEventListener('click', closeTicketModal);
        }
        if (closeBtnAlt) {
            closeBtnAlt.addEventListener('click', closeTicketModal);
        }

        // Kopyala butonu
        if (copyBtn) {
            copyBtn.addEventListener('click', copyTicketSummary);
        }

        // Overlay tıklaması ile KAPATMA (kullanıcı kuralı)
        // modal.addEventListener('click', ...) OLMAYACAK
    }

    /**
     * Çağrı Aç butonuna tıklandığında
     */
    async function handleOpenTicketSummary() {
        const parent = getParent();
        const currentDialogId = parent?._getDialogId?.();

        if (!currentDialogId) {
            showToast('warning', 'Önce bir soru sormalısınız');
            return;
        }

        // Modal'ı aç
        const modal = document.getElementById('ticketSummaryModal');
        const summaryText = document.getElementById('ticketSummaryText');

        if (!modal || !summaryText) return;

        // Loading göster
        summaryText.innerHTML = `
            <div class="loading-spinner">
                <i class="fa-solid fa-spinner fa-spin"></i>
                <span>Çağrı metni oluşturuluyor...</span>
            </div>
        `;
        modal.classList.remove('hidden');

        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`${API_BASE}/dialogs/${currentDialogId}/generate-ticket-summary`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });

            if (response.ok) {
                const data = await response.json();
                const rawSummary = data.summary || '';

                // v2.49.0: Konu ve Sorun Tanımı'nı parse et
                let konu = '';
                let sorunTanimi = '';

                // **Konu:** ... parse
                const konuMatch = rawSummary.match(/\*\*Konu:\*\*\s*(.+?)(?=\n\*\*|\n\n|$)/s);
                if (konuMatch) {
                    konu = konuMatch[1].trim();
                }

                // **Sorun Tanımı:** ... parse (en sondaki match, tüm kalan metni al)
                const sorunMatch = rawSummary.match(/\*\*Sorun Tan[ıi]m[ıi]:\*\*\s*([\s\S]*?)$/);
                if (sorunMatch) {
                    sorunTanimi = sorunMatch[1].trim();
                }

                // Parse başarısızsa ham metni göster
                if (!konu && !sorunTanimi) {
                    sorunTanimi = rawSummary
                        .replace(/\*\*/g, '')
                        .trim();
                }

                // v2.49.1: Kopyalama için sorun metnini sakla
                _lastSorunText = sorunTanimi;

                summaryText.innerHTML = `
                    <div class="ticket-parsed-content">
                        ${konu ? `
                        <div class="ticket-field">
                            <div class="ticket-field-label">
                                <i class="fa-solid fa-tag"></i>
                                <span>Konu</span>
                            </div>
                            <div class="ticket-field-value ticket-konu">${escapeHtml(konu)}</div>
                        </div>
                        ` : ''}
                        <div class="ticket-field">
                            <div class="ticket-field-label">
                                <i class="fa-solid fa-align-left"></i>
                                <span>Sorun Tanımı</span>
                            </div>
                            <div class="ticket-field-value ticket-sorun">${escapeHtml(sorunTanimi).replace(/\n/g, '<br>')}</div>
                        </div>
                    </div>
                `;
            } else {
                summaryText.innerHTML = `
                    <div class="ticket-error">
                        <i class="fa-solid fa-exclamation-triangle"></i>
                        <span>Çağrı metni oluşturulamadı. Lütfen tekrar deneyin.</span>
                    </div>
                `;
            }
        } catch (error) {
            console.error('[DialogChat] Ticket özeti hatası:', error);
            summaryText.innerHTML = `
                <div class="ticket-error">
                    <i class="fa-solid fa-exclamation-triangle"></i>
                    <span>Bağlantı hatası.</span>
                </div>
            `;
        }
    }

    /**
     * Ticket modal'ı kapat
     */
    function closeTicketModal() {
        const modal = document.getElementById('ticketSummaryModal');
        if (modal) {
            modal.classList.add('hidden');
        }
    }

    /**
     * v2.49.1: Sadece sorun tanımı metnini panoya kopyala
     * DOM'a bağımlı değil, module-level _lastSorunText değişkenini kullanır
     */
    async function copyTicketSummary() {
        if (!_lastSorunText) {
            showToast('warning', 'Kopyalanacak metin bulunamadı');
            return;
        }

        try {
            await navigator.clipboard.writeText(_lastSorunText);
            showToast('success', 'Sorun tanımı panoya kopyalandı!');

            // Kopyala butonunda visual feedback
            const copyBtn = document.getElementById('btnCopyTicket');
            if (copyBtn) {
                const originalHTML = copyBtn.innerHTML;
                copyBtn.innerHTML = '<i class="fa-solid fa-check"></i> Kopyalandı';
                copyBtn.classList.add('copied');
                setTimeout(() => {
                    copyBtn.innerHTML = originalHTML;
                    copyBtn.classList.remove('copied');
                }, 2000);
            }
        } catch (error) {
            console.error('[DialogChat] Kopyalama hatası:', error);
            showToast('error', 'Kopyalama başarısız');
        }
    }

    /**
     * v2.24.5: Corpix fallback aksiyonlarını yönet
     */
    async function handleCorpixAction(action, query = '') {
        const parent = getParent();
        const currentDialogId = parent?._getDialogId?.();

        if (action === 'ask_corpix') {
            if (!currentDialogId || !query) {
                showToast('warning', 'Soru gönderilemedi');
                return;
            }

            // Typing indicator göster
            if (parent?.showTypingIndicator) parent.showTypingIndicator();

            try {
                const token = localStorage.getItem('access_token');
                const response = await fetch(`${API_BASE}/dialogs/${currentDialogId}/ask-corpix`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ query: query })
                });

                if (parent?.hideTypingIndicator) parent.hideTypingIndicator();

                if (response.ok) {
                    const data = await response.json();
                    if (parent?.addAssistantMessage) parent.addAssistantMessage(data);
                } else {
                    const errorData = await response.json().catch(() => ({}));
                    console.error('[DialogChat] Corpix hatası:', errorData);
                    if (parent?.addSystemMessage) parent.addSystemMessage('❌ Corpix yanıt veremedi.');
                }
            } catch (error) {
                if (parent?.hideTypingIndicator) parent.hideTypingIndicator();
                console.error('[DialogChat] Corpix bağlantı hatası:', error);
                if (parent?.addSystemMessage) parent.addSystemMessage('❌ Corpix yanıt veremedi.');
            }
        } else if (action === 'no_corpix') {
            // Hayır seçildi
            if (parent?.addSystemMessage) parent.addSystemMessage('👍 Anladım. Başka bir konuda yardımcı olabilir miyim?');
        }
    }

    // escapeHtml → DialogChatUtils'ten delegasyon (dosya başında tanımlandı)

    /**
     * v2.26.0: Corpix modunda mesaj gönder (RAG araması yapılmaz)
     */
    async function sendCorpixMessage(content) {
        const parent = getParent();

        try {
            const token = localStorage.getItem('access_token');
            let currentDialogId = parent?._getDialogId?.();

            // Dialog yoksa oluştur
            if (!currentDialogId) {
                const dialogRes = await fetch(`${API_BASE}/dialogs`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ title: null })
                });
                if (dialogRes.ok) {
                    const dialog = await dialogRes.json();
                    currentDialogId = dialog.id;
                    if (parent?._setDialogId) parent._setDialogId(dialog.id);
                }
            }

            // Corpix API'ye gönder
            const startTime = performance.now();
            const response = await fetch(`${API_BASE}/dialogs/${currentDialogId}/ask-corpix`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ query: content })
            });

            if (parent?.hideTypingIndicator) parent.hideTypingIndicator();
            const responseTime = ((performance.now() - startTime) / 1000).toFixed(2);

            if (response.ok) {
                const data = await response.json();
                if (parent?.addAssistantMessage) parent.addAssistantMessage(data, null, true, responseTime);
            } else {
                const errorData = await response.json().catch(() => ({}));
                console.error('[DialogChat] Corpix hatası:', errorData);

                // VPN hatası kontrolü
                if (window.isVPNNetworkError && window.isVPNNetworkError(errorData?.detail || '')) {
                    if (window.showVPNErrorPopup) window.showVPNErrorPopup();
                } else {
                    if (parent?.addSystemMessage) parent.addSystemMessage('❌ Corpix şu anda yanıt veremedi. Lütfen tekrar deneyin.');
                }
            }
        } catch (error) {
            if (parent?.hideTypingIndicator) parent.hideTypingIndicator();
            console.error('[DialogChat] Corpix bağlantı hatası:', error);
            if (parent?.addSystemMessage) parent.addSystemMessage('❌ Bağlantı hatası. VPN bağlantınızı kontrol edin.');
        }
    }

    /**
     * v2.26.0: Chat mode toggle UI'ını güncelle
     */
    function updateChatModeUI() {
        const parent = getParent();
        const chatMode = parent?.getChatMode?.() || 'rag';

        const ragToggle = document.getElementById('ragModeToggle');
        const corpixToggle = document.getElementById('corpixModeToggle');
        const modeBadge = document.getElementById('chatModeBadge');

        if (ragToggle) {
            ragToggle.classList.toggle('active', chatMode === 'rag');
        }
        if (corpixToggle) {
            corpixToggle.classList.toggle('active', chatMode === 'corpix');
        }
        if (modeBadge) {
            modeBadge.textContent = chatMode === 'rag' ? '🔍 RAG' : '💬 Corpix';
            modeBadge.className = `chat-mode-badge mode-${chatMode}`;
        }
    }

    // v2.26.0: Header mod butonunu güncelle
    function updateHeaderModeBtn() {
        const parent = getParent();
        const chatMode = parent?.getChatMode?.() || 'rag';

        const icon = document.getElementById('chatModeIcon');
        const label = document.getElementById('chatModeLabel');
        const btn = document.getElementById('chatModeToggleBtn');

        if (!icon || !label || !btn) return;

        if (chatMode === 'rag') {
            // RAG modundayız, buton Vyra sohbete geçişi gösterir
            icon.className = 'fa-solid fa-comments';
            label.textContent = 'Vyra ile Sohbet et';
            btn.title = 'Vyra ile sohbet moduna geç';
            btn.classList.remove('rag-active');
        } else {
            // Vyra sohbet modundayız, buton RAG'a geçişi gösterir
            icon.className = 'fa-solid fa-database';
            label.textContent = 'Bilgi Tabanında Ara';
            btn.title = 'Bilgi tabanında arama moduna geç';
            btn.classList.add('rag-active');
        }
    }


    return {
        bindTicketModalEvents,
        handleOpenTicketSummary,
        closeTicketModal,
        copyTicketSummary,
        handleCorpixAction,
        sendCorpixMessage,
        updateChatModeUI,
        updateHeaderModeBtn
    };
})();
