/**
 * VYRA Dialog Chat Module
 * ========================
 * WhatsApp tarzı AI chat modülü
 * 
 * Version: 2.15.0 (Modular Refactor)
 * 
 * Modüler Yapı:
 *   dialog_chat_utils.js   → Stateless utility fonksiyonlar
 *   dialog_chat.js         → Ana modül (state + iş mantığı)
 */

window.DialogChatModule = (function () {
    'use strict';

    // =========================================================================
    // UTILITY DELEGATION (dialog_chat_utils.js'ten)
    // =========================================================================
    const { formatTime, formatMessageContent, escapeHtml, getUserInitial,
        showToast, getFileTypeIcon, escapeForJs } = window.DialogChatUtils;

    // =============================================================================
    // STATE
    // =============================================================================

    let currentDialogId = null;
    let isRecording = false;
    let mediaRecorder = null;
    let audioChunks = [];
    let pendingImages = [];
    let recognition = null;  // Web Speech API
    let isSpeaking = false;  // TTS durumu
    let activeSpeakBtn = null; // Şu an aktif hoparlör butonu
    let lastAddedMessageId = null; // Son eklenen mesaj ID (duplicate önleme)
    let isWaitingForResponse = false; // HTTP response bekliyor mu?
    let selectedCardIds = []; // Çoklu kart seçimi için
    let chatMode = 'rag'; // v3.6.0: 'rag', 'db' veya 'llm' - sohbet modu

    // v3.15.1: Aktif uzun-süren DB sorgu job_id'leri — "Yeni Soru Sor" tıklanınca
    // veya sayfa kapatılınca toplu iptal için. Set, dialog süresince birikir;
    // her job tamamlandığında (done/error) silinir.
    const activeJobs = new Set();

    // v3.16.0: DB modunda son asistan mesajının id'si — "Önceki konu ile ilgili" follow-up
    // çıpası olarak kullanılır. 'saved' eventinden assistant id alınır.
    let lastDbAssistantMessageId = null;
    // v3.16.0: Kullanıcının "Önceki konu ile ilgili soru sor" badge'ine tıkladığı an
    // ayarlanır; sonraki POST'da follow_up_message_id olarak gönderilir.
    // Tek seferlik (one-shot): mesaj gönderildikten sonra null'a düşürülür.
    let pendingFollowupAnchorId = null;

    const API_BASE = (window.API_BASE_URL || 'http://localhost:8002') + '/api';

    // v3.1.1: Parametrik firma adı — BrandingEngine'den oku
    function _appName() { return window.BrandingEngine?.getAppName?.() || 'VYRA'; }
    function _appInitial() { return window.BrandingEngine?.getAppInitial?.() || 'V'; }

    // =============================================================================
    // INITIALIZATION
    // =============================================================================

    let isInitialized = false;

    function init() {
        // Duplicate event listener önleme - sadece bir kez başlat
        if (isInitialized) {
            console.log('[DialogChat] Zaten başlatılmış, sadece mesajlar yenileniyor...');
            loadActiveDialog();
            return;
        }

        console.log('[DialogChat] Modül başlatılıyor...');
        isInitialized = true;

        // Event listeners
        bindEvents();

        // Speech Recognition başlat
        initSpeechRecognition();

        // Browser Notification izni iste
        requestNotificationPermission();

        // Aktif dialog varsa yükle
        loadActiveDialog();
    }

    // =============================================================================
    // BROWSER NOTIFICATIONS
    // =============================================================================

    function requestNotificationPermission() {
        if ('Notification' in window && Notification.permission === 'default') {
            Notification.requestPermission().then(permission => {
                console.log('[DialogChat] Notification izni:', permission);
            });
        }
    }

    function showNotification(title, body) {
        // v3.14.6: Uygulama içi bildirim merkezine HER zaman ekle (zil ikonu badge'i),
        // böylece kullanıcı başka menüdeyken sorgu bittiğini görebilir.
        //
        // v3.15.5: DB modunda iken kullanıcı zaten dialog ekranında oturuyorsa
        // sonucu doğrudan göreceği için sağdan akan toast gereksiz — bastır.
        // Farklı bir menüde ise (örn. parametreler, geçmiş) toast gösterilir.
        // Zil badge'i her durumda güncellenir.
        let suppressToast = false;
        try {
            const dialogSection = document.getElementById('sectionDialog');
            const dialogVisible = dialogSection && !dialogSection.classList.contains('hidden');
            if (dialogVisible && chatMode === 'db') {
                suppressToast = true;
            }
        } catch (_) { /* DOM erişim hatası — toast yine de görünebilir */ }

        try {
            if (window.NgssNotification && typeof window.NgssNotification.add === 'function') {
                window.NgssNotification.add('success', title, body, _getDialogIdSafe(), null, { suppressToast });
            }
        } catch (e) { /* sessiz başarısızlık */ }

        // Sadece sayfa görünmüyorsa browser-level notification göster
        if (document.hidden && 'Notification' in window && Notification.permission === 'granted') {
            const notification = new Notification(title, {
                body: body,
                icon: '/assets/images/vyra_logo.png',
                tag: 'vyra-response',
                requireInteraction: true
            });

            notification.onclick = () => {
                // Pencereyi öne getir
                window.focus();
                // NGSSAI'ye Sor sekmesine git
                navigateToDialogTab();
                notification.close();
            };

            // 10 saniye sonra otomatik kapat
            setTimeout(() => notification.close(), 10000);
        }
    }

    function _getDialogIdSafe() {
        try { return currentDialogId; } catch (_) { return null; }
    }

    function navigateToDialogTab() {
        // Tab'ı aktif et
        const dialogTab = document.querySelector('[data-tab="dialog"]') || document.querySelector('[data-tab="dialog-chat"]');
        if (dialogTab) {
            dialogTab.click();
        }
        // Scroll to bottom
        setTimeout(() => scrollToBottom(), 100);
    }

    function bindEvents() {
        // Send button
        const sendBtn = document.getElementById('dialogSendBtn');
        if (sendBtn) {
            sendBtn.addEventListener('click', handleSendMessage);
        }

        // Input textarea - Enter ile gönder
        const input = document.getElementById('dialogInput');
        if (input) {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSendMessage();
                }
            });

            input.addEventListener('input', () => {
                updateSendButtonState();
                autoResizeTextarea(input);
            });

            // Image paste
            input.addEventListener('paste', handlePaste);
        }

        // Voice button
        const voiceBtn = document.getElementById('dialogVoiceBtn');
        if (voiceBtn) {
            voiceBtn.addEventListener('click', toggleVoiceRecording);
        }

        // Attach button
        const attachBtn = document.getElementById('dialogAttachBtn');
        if (attachBtn) {
            attachBtn.addEventListener('click', () => {
                document.getElementById('dialogFileInput')?.click();
            });
        }

        // File input
        const fileInput = document.getElementById('dialogFileInput');
        if (fileInput) {
            fileInput.addEventListener('change', handleFileSelect);
        }

        // New dialog button
        const newDialogBtn = document.getElementById('dialogNewBtn');
        if (newDialogBtn) {
            newDialogBtn.addEventListener('click', startNewDialog);
        }

        // v2.24.5: Çağrı Aç butonu
        const ticketBtn = document.getElementById('dialogTicketBtn');
        if (ticketBtn) {
            ticketBtn.addEventListener('click', handleOpenTicketSummary);
        }

        // v2.24.5: Ticket Modal event listeners
        bindTicketModalEvents();
    }

    // =============================================================================
    // DIALOG MANAGEMENT
    // =============================================================================

    // =============================================================================
    // LIFECYCLE MANAGEMENT
    // =============================================================================

    /**
     * Modül pasife çekildiğinde (tab değişimi vb.) çağrılır.
     * v3.15.1: Artık dialog'u KAPATMAZ ve DOM'u temizlemez —
     * kullanıcı başka menüye geçip geri döndüğünde soruları/yanıtları görsün.
     * Yalnızca "Yeni Soru Sor" tıklanınca dialog kapatılır + iptal edilir.
     */
    async function deactivate() {
        if (!currentDialogId) return;
        // No-op: state ve DOM korunur. Backend tarafındaki inactivity scheduler
        // (SCHEDULER_INTERVAL_SECONDS) yeterince uzun süre kullanılmayan dialog'u kapatır.
        console.log(`[DialogChat] Menü geçişi: dialog #${currentDialogId} state korunuyor.`);
    }

    async function loadActiveDialog() {
        const container = document.getElementById('dialogMessages');

        // v3.15.1: Eğer halihazırda bir dialog açık ve DOM doluysa (kullanıcı sadece
        // başka menüye gidip geri geldi), hiçbir şey yapma — state'i koru.
        if (currentDialogId && container && container.children.length > 0) {
            console.log(`[DialogChat] Dialog #${currentDialogId} state korunmuş, yeniden yükleme atlanıyor.`);
            return;
        }

        // v2.21.12: UI'ı temizle (duplicate mesaj önleme)
        if (container) {
            container.innerHTML = '';
        }

        // v2.25.1: Eğer zaten bir dialog açıksa (notification'dan gelmiş olabilir), devam et
        if (currentDialogId) {
            console.log(`[DialogChat] Mevcut dialog #${currentDialogId} ile devam ediliyor...`);
            await loadDialogById(currentDialogId);
            return;
        }

        // v2.24.6: Hoşgeldin mesajı HEMEN göster (API çağrılarından önce)
        addSystemMessage('👋 Merhaba! Size nasıl yardımcı olabilirim? Sorununuzu yazın veya ekran görüntüsü paylaşın.');

        // v2.21.12: Textarea'yı aktifle (hemen yazabilsin)
        const textarea = document.getElementById('dialogInput');
        if (textarea) {
            textarea.disabled = false;
            textarea.placeholder = 'Mesajınızı yazın...';
        }

        // v2.24.6: Çağrı Aç butonu başlangıçta pasif (sonuç gelince aktifleşecek)
        setTicketButtonEnabled(false);

        // v2.25.1: Aktif dialog varsa DEVAM ET (kapatma!)
        // Sadece "Yeni Sohbet" tıklanırsa yeni dialog oluşturulacak
        try {
            const token = localStorage.getItem('access_token');
            if (!token) return;

            // v3.19.2: Yeni login sonrası temiz başla — eski aktif dialog'a devam etme
            const freshLogin = sessionStorage.getItem('vyra_fresh_login');
            if (freshLogin) {
                sessionStorage.removeItem('vyra_fresh_login');
                console.log('[DialogChat] Fresh login — yeni dialog ile başlanıyor');
                await createInitialDialogBackground();
                return;
            }

            // 1️⃣ Aktif dialog'u kontrol et (F5/refresh durumlarında devam için)
            const checkResponse = await fetch(`${API_BASE}/dialogs/active`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (checkResponse.ok) {
                const existingDialog = await checkResponse.json();

                if (existingDialog.id) {
                    // 2️⃣ v2.25.1: Aktif dialog varsa DEVAM ET (Strict Mode kaldırıldı)
                    console.log(`[DialogChat] Aktif dialog #${existingDialog.id} bulundu, devam ediliyor...`);
                    currentDialogId = existingDialog.id;

                    // Mevcut mesajları yükle
                    await loadDialogById(existingDialog.id);
                    return;
                }
            }

            // 3️⃣ Aktif dialog yoksa yeni oluştur
            await createInitialDialogBackground();

        } catch (error) {
            console.error('[DialogChat] Dialog yönetimi hatası:', error);
            // Hoşgeldin mesajı zaten gösterildi, hata durumunda sadece logla
        }

        // 📝 Buton durumlarını güncelle
        updateSendButtonState();
    }

    /**
     * v2.24.6: Arka planda dialog oluştur (UI zaten hazır)
     */
    async function createInitialDialogBackground() {
        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`${API_BASE}/dialogs`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ title: null })
            });

            if (response.ok) {
                const dialog = await response.json();
                currentDialogId = dialog.id;
                console.log(`[DialogChat] Yeni dialog #${dialog.id} oluşturuldu`);
            }
        } catch (error) {
            console.error('[DialogChat] İlk dialog oluşturulamadı:', error);
        }
    }

    /**
     * v2.24.6: Çağrı Aç butonu durumunu ayarla
     */
    function setTicketButtonEnabled(enabled) {
        const ticketBtn = document.getElementById('dialogTicketBtn');
        if (ticketBtn) {
            ticketBtn.disabled = !enabled;
            if (enabled) {
                ticketBtn.classList.remove('btn-disabled');
            } else {
                ticketBtn.classList.add('btn-disabled');
            }
        }
    }

    // Legacy: Eski kod uyumluluğu için kalabilen versiyon
    async function createInitialDialog() {
        await createInitialDialogBackground();
    }

    async function startNewDialog() {
        try {
            const token = localStorage.getItem('access_token');

            // v3.15.1: Önce devam eden uzun DB sorgularını iptal et — sistemi yormayalım.
            // Fire-and-forget: hata olsa bile yeni dialog açma işlemini bloklamasın.
            if (activeJobs.size > 0 && currentDialogId) {
                console.log(`[DialogChat] ${activeJobs.size} aktif DB sorgu iptal ediliyor...`);
                const jobsToCancel = Array.from(activeJobs);
                activeJobs.clear();
                const cancelHeaders = token ? { 'Authorization': `Bearer ${token}` } : {};
                jobsToCancel.forEach((jId) => {
                    fetch(`${API_BASE}/dialogs/${currentDialogId}/jobs/${encodeURIComponent(jId)}/cancel`, {
                        method: 'POST',
                        headers: cancelHeaders,
                    }).catch(() => { /* sessiz başarısızlık — registry'de yoksa zaten bitmiştir */ });
                });
            }

            // v2.25.1: Önce mevcut aktif dialog'u kapat
            if (currentDialogId) {
                console.log(`[DialogChat] Mevcut dialog #${currentDialogId} kapatılıyor (Yeni Sohbet)...`);
                await fetch(`${API_BASE}/dialogs/${currentDialogId}/close`, {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}` }
                });
            }

            // Yeni dialog oluştur
            const response = await fetch(`${API_BASE}/dialogs`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ title: null })
            });

            if (response.ok) {
                const dialog = await response.json();
                currentDialogId = dialog.id;
                clearMessages();
                resetNewDialogButtonHighlight(); // Animasyonu kaldır
                addSystemMessage('🎉 ' + _appName() + '\'ye yeni soru sorabilirsiniz. Size nasıl yardımcı olabilirim?');

                // Çağrı Aç butonunu pasifleştir (yeni dialog boş)
                setTicketButtonEnabled(false);

                console.log(`[DialogChat] Yeni dialog #${dialog.id} başlatıldı`);
            }
        } catch (error) {
            console.error('[DialogChat] Yeni dialog oluşturulamadı:', error);
            showToast('error', 'Dialog başlatılamadı');
        }
    }

    /**
     * v2.24.6: Belirli bir dialog ID ile mesajları yükle
     * Notification'dan tıklandığında kullanılır.
     */
    async function loadDialogById(dialogId) {
        if (!dialogId) {
            console.warn('[DialogChat] loadDialogById: Dialog ID gerekli');
            return;
        }

        console.log(`[DialogChat] Dialog #${dialogId} yükleniyor...`);

        // UI'yı temizle
        const container = document.getElementById('dialogMessages');
        if (container) {
            container.innerHTML = '';
        }

        // Current dialog'u set et
        currentDialogId = dialogId;

        // Çağrı Aç butonunu aktifleştir (mesajlar varsa)
        setTicketButtonEnabled(true);

        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`${API_BASE}/dialogs/${dialogId}/messages`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (response.ok) {
                const messages = await response.json();
                console.log(`[DialogChat] Dialog #${dialogId} - ${messages.length} mesaj yüklendi`);

                if (messages.length > 0) {
                    renderMessages(messages);
                } else {
                    addSystemMessage('👋 Merhaba! Size nasıl yardımcı olabilirim?');
                }
            } else {
                console.error('[DialogChat] Dialog mesajları alınamadı');
                addSystemMessage('👋 Merhaba! Size nasıl yardımcı olabilirim?');
            }
        } catch (error) {
            console.error('[DialogChat] loadDialogById hatası:', error);
            addSystemMessage('⚠️ Mesajlar yüklenirken bir hata oluştu.');
        }

        // Buton durumlarını güncelle
        updateSendButtonState();
    }

    async function loadMessages() {
        if (!currentDialogId) return;

        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`${API_BASE}/dialogs/${currentDialogId}/messages`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (response.ok) {
                const messages = await response.json();
                console.log('[DialogChat] Mesajlar yüklendi:', messages.length, 'adet');

                // Debug: Her mesajın metadata'sını kontrol et
                messages.forEach((msg, i) => {
                    if (msg.role === 'assistant' && msg.metadata?.quick_reply) {
                        console.log(`[DialogChat] Mesaj #${i} quick_reply var:`, msg.metadata.quick_reply.type);
                    }
                });

                renderMessages(messages);
            }
        } catch (error) {
            console.error('[DialogChat] Mesajlar yüklenemedi:', error);
        }
    }

    // =============================================================================
    // MESSAGE HANDLING
    // =============================================================================

    async function handleSendMessage() {
        const input = document.getElementById('dialogInput');
        const content = input?.value?.trim();

        if (!content && pendingImages.length === 0) return;

        // UI güncelle
        input.value = '';
        resetTextareaHeight(); // Textarea boyutunu resetle
        updateSendButtonState();

        // Sohbet başladı - animasyonu durdur
        stopNewDialogButtonAnimation();

        // v2.24.6: Mesaj gönderildi, Çağrı Aç butonunu aktifleştir
        setTicketButtonEnabled(true);

        // Kullanıcı mesajını göster
        addUserMessage(content, pendingImages);

        // Typing indicator göster
        showTypingIndicator();

        // v3.6.0: Mod kontrolü - LLM modunda direkt LLM'e git
        if (chatMode === 'llm') {
            await sendLlmMessage(content);
            return;
        }

        // v3.14.0: DB modunda paralel sorgu desteği — isWaitingForResponse engelleme
        // DB sorguları eşzamanlı çalışabilir, diğer modlarda sıralı kalır
        const isDbMode = chatMode === 'db';
        if (!isDbMode) {
            isWaitingForResponse = true;
        }

        // v3.16.0: Follow-up anchor'ı POST'tan ÖNCE yerel değişkene al ve modül state'ini
        // anında temizle. Bu, error/timeout/iptal gibi yollardan biten istekler için de
        // anchor'ın sızıntı yapmamasını garanti eder. Truly one-shot davranış.
        const followupAnchorForThisSend = (isDbMode && pendingFollowupAnchorId) ? pendingFollowupAnchorId : null;
        if (followupAnchorForThisSend) {
            pendingFollowupAnchorId = null;
            _hideFollowupIndicator();
        }

        // ⏱️ Response time ölçümü başla
        const startTime = performance.now();

        try {
            const token = localStorage.getItem('access_token');

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
                    console.log(`[DialogChat] Mesaj için yeni dialog #${dialog.id} oluşturuldu`);
                }
            }

            // 🆕 v2.50.0: Streaming SSE endpoint
            const response = await fetch(`${API_BASE}/dialogs/${currentDialogId}/messages/stream`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    content: content || '[Görsel]',
                    images: pendingImages.map(img => img.base64),
                    source_type: chatMode === 'db' ? 'db' : 'rag',
                    // v3.16.0: Follow-up çıpası bu istek için consume edilmiş (state
                    // zaten temizlendi); body'ye yerel snapshot'ı yaz.
                    ...(followupAnchorForThisSend
                        ? { follow_up_message_id: followupAnchorForThisSend }
                        : {})
                })
            });

            if (!response.ok) {
                hideTypingIndicator();
                // HTTP hatası
                try {
                    const errorData = await response.json();
                    const errorDetail = errorData?.detail || '';
                    if (window.isVPNNetworkError && window.isVPNNetworkError(errorDetail)) {
                        if (window.showVPNErrorPopup) window.showVPNErrorPopup();
                        addSystemMessage('🌐 LLM bağlantı hatası. VPN bağlantınızı kontrol edin.');
                    } else {
                        addSystemMessage('❌ Yanıt alınamadı. Lütfen tekrar deneyin.');
                    }
                } catch (parseError) {
                    addSystemMessage('❌ Yanıt alınamadı. Lütfen tekrar deneyin.');
                }
                return;
            }

            // SSE stream okuma
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let streamingEl = null;
            let streamedText = '';
            let savedMessageId = null;
            let savedQuickReply = null;
            let finalContent = null;
            let finalMetadata = null;
            let buffer = '';
            let firstChunkReceived = false;

            // v3.14.5: Idle watchdog — 90sn boyunca hiçbir byte gelmezse stream'i kapat
            // Backend her 15sn'de heartbeat (`:` comment frame) yolluyor, normalde tetiklenmez.
            const IDLE_TIMEOUT_MS = 90000;
            let watchdogTimer = null;
            let watchdogTripped = false;
            const resetWatchdog = () => {
                if (watchdogTimer) clearTimeout(watchdogTimer);
                watchdogTimer = setTimeout(() => {
                    watchdogTripped = true;
                    console.warn(`[DialogChat] SSE stream ${IDLE_TIMEOUT_MS / 1000}sn boyunca sessiz — kapatılıyor.`);
                    try { reader.cancel(); } catch (_) { /* noop */ }
                }, IDLE_TIMEOUT_MS);
            };
            resetWatchdog();

            // v3.14.6: Bekleyen DB sorgusu için 1 saniyelik gerçek-zamanlı sayaç.
            // timeout_warning geldiğinde start, done/error/stream-end'de stop.
            // v3.15.0: 60sn üzerinde "Xdk Ys" formatı + activeJobId iptal için.
            let elapsedTickHandle = null;
            let elapsedSeconds = 0;
            let activeJobId = null;
            const _formatElapsed = (sec) => {
                const s = Math.max(0, parseInt(sec) || 0);
                if (s < 60) return `${s}s`;
                const m = Math.floor(s / 60);
                const r = s % 60;
                return `${m}dk ${r}s`;
            };
            const startElapsedTicker = () => {
                if (elapsedTickHandle) return;
                elapsedTickHandle = setInterval(() => {
                    elapsedSeconds += 1;
                    if (!streamingEl) return;
                    const counterEl = streamingEl.querySelector('.db-timeout-elapsed');
                    if (counterEl) counterEl.textContent = _formatElapsed(elapsedSeconds);
                }, 1000);
            };
            const stopElapsedTicker = () => {
                if (elapsedTickHandle) {
                    clearInterval(elapsedTickHandle);
                    elapsedTickHandle = null;
                }
            };

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                resetWatchdog(); // her byte geldiğinde watchdog sıfırla

                // Backend ilk veriyi gönderdi, uçan daktilo bekleme modunu kapat!
                if (!firstChunkReceived) {
                    hideTypingIndicator();
                    firstChunkReceived = true;
                }

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || ''; // Son satır incomplete olabilir

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const jsonStr = line.slice(6).trim();
                    if (!jsonStr) continue;

                    try {
                        const event = JSON.parse(jsonStr);
                        const eventType = event.type;
                        const eventData = event.data;

                        switch (eventType) {
                            case 'rag_complete':
                                streamingEl = createStreamingMessage();
                                updateStreamingStatus(streamingEl, `📚 ${eventData.result_count} sonuç bulundu, yanıt hazırlanıyor...`);
                                break;

                            case 'status':
                                if (!streamingEl) {
                                    streamingEl = createStreamingMessage();
                                }
                                updateStreamingStatus(streamingEl, `⏳ ${eventData}`);
                                break;

                            case 'token':
                                if (!streamingEl) {
                                    streamingEl = createStreamingMessage();
                                }
                                streamedText += eventData;
                                appendStreamToken(streamingEl, eventData);
                                break;

                            case 'cached':
                                finalContent = eventData.content;
                                finalMetadata = eventData;
                                break;

                            case 'done':
                                finalContent = eventData.content;
                                finalMetadata = eventData.metadata || {};
                                break;

                            case 'saved':
                                savedMessageId = eventData.message_id;
                                savedQuickReply = eventData.quick_reply;
                                // v3.16.0: DB modunda son asistan mesajının id'sini
                                // hatırla — sonraki follow-up için çıpa olacak.
                                // Anchor zaten POST'tan önce consume edildi.
                                if (isDbMode && savedMessageId) {
                                    lastDbAssistantMessageId = savedMessageId;
                                }
                                break;

                            // v4.0: Disambiguation — aynı isimde çoklu tablo
                            case 'clarification': {
                                if (streamingEl) streamingEl.remove();
                                const { candidates, query: cQuery, message: cMsg } = eventData;
                                const disambigHtml = window.DialogChatUtils.renderDisambiguationCard(
                                    candidates, cQuery, cMsg,
                                    (selectedFull) => {
                                        // Kullanıcı tablo seçti — schema_hint ile yeniden gönder
                                        _sendDbMessageWithHint(cQuery, selectedFull, null);
                                    }
                                );
                                _insertInteractiveBlock(disambigHtml);
                                isWaitingForResponse = false;
                                hideTypingIndicator();
                                return;
                            }

                            // v4.0: Rapor şablonu önerileri (DB_REPORT intent)
                            case 'suggestions': {
                                if (streamingEl) streamingEl.remove();
                                const { templates, message: sMsg, intent } = eventData;
                                if (intent === 'DB_REPORT' && templates?.length) {
                                    const origQuery = content; // closure
                                    const tmplHtml = window.DialogChatUtils.renderReportTemplates(
                                        templates, sMsg,
                                        (hint) => {
                                            // Kullanıcı şablon seçti — report_template ile yeniden gönder
                                            _sendDbMessageWithHint(origQuery, null, hint);
                                        }
                                    );
                                    _insertInteractiveBlock(tmplHtml);
                                }
                                isWaitingForResponse = false;
                                hideTypingIndicator();
                                return;
                            }

                            // v3.14.0: Asenkron DB sorgu — job başlatıldı
                            case 'job_queued': {
                                const { job_id: jqId, query_text_short: jqShort } = eventData;
                                if (!streamingEl) {
                                    streamingEl = createStreamingMessage();
                                }
                                // XSS-safe: DOM API ile oluştur
                                const mentionDiv = document.createElement('div');
                                mentionDiv.className = 'db-query-mention';
                                mentionDiv.dataset.jobId = jqId;

                                const iconSpan = document.createElement('span');
                                iconSpan.className = 'db-query-mention-icon';
                                iconSpan.textContent = '💬';

                                const textSpan = document.createElement('span');
                                textSpan.className = 'db-query-mention-text';
                                textSpan.textContent = jqShort; // Auto-escaped

                                const statusSpan = document.createElement('span');
                                statusSpan.className = 'db-query-status';
                                statusSpan.id = `dbqs_${jqId}`;
                                statusSpan.textContent = '⏳ Çalışıyor...';

                                mentionDiv.appendChild(iconSpan);
                                mentionDiv.appendChild(textSpan);
                                mentionDiv.appendChild(statusSpan);

                                // streamingEl'in content alanına ekle
                                const contentEl = streamingEl.querySelector('.message-content') || streamingEl;
                                contentEl.appendChild(mentionDiv);
                                break;
                            }

                            // v3.14.0: Progressive Timeout — sorgu devam ediyor bildirimi
                            case 'timeout_warning': {
                                const { message: twMsg, elapsed: twElapsed, estimate: twEst, job_id: twJob, max_wait: twMaxWait, sql: twSql } = eventData;
                                if (!streamingEl) {
                                    streamingEl = createStreamingMessage();
                                }
                                // v3.15.0: aktif job_id'yi yakala (iptal butonu için)
                                // v3.15.1: modül seviyesinde activeJobs Set'ine ekle —
                                // "Yeni Soru Sor" tıklanınca toplu iptal için.
                                if (twJob) {
                                    activeJobId = twJob;
                                    activeJobs.add(twJob);
                                }
                                // DOM API ile XSS-safe oluştur (appendStreamToken HTML'i escape eder)
                                const twDiv = document.createElement('div');
                                twDiv.className = 'db-timeout-info';
                                // v3.14.6: gerçek-zamanlı sayaç (.db-timeout-elapsed) eklendi
                                // v3.15.0: max_wait bilgisi + İptal Et butonu
                                // v3.15.6: "SQL Görüntüle" butonu — kullanıcı beklerken
                                // backend'in ürettiği SQL'i kontrol edebilsin.
                                const _maxWaitMin = twMaxWait ? Math.max(1, Math.floor(parseInt(twMaxWait) / 60)) : null;
                                const _hasSql = !!(twSql && String(twSql).trim());
                                twDiv.innerHTML =
                                    `<div class="db-timeout-icon">⏳</div>` +
                                    `<div class="db-timeout-text"></div>` +
                                    `<div class="db-timeout-elapsed-wrap"><span class="db-timeout-elapsed">0s</span> geçti` +
                                    (_maxWaitMin ? ` <span class="db-timeout-maxwait">/ maks ${_maxWaitMin}dk</span>` : '') +
                                    `</div>` +
                                    `<div class="db-timeout-progress">` +
                                    `<div class="db-timeout-bar" style="animation: db-timeout-fill ${parseInt(twEst) || 30}s linear forwards"></div>` +
                                    `</div>` +
                                    `<div class="db-timeout-hint">Sorgu arka planda çalışmaya devam ediyor...</div>` +
                                    `<div class="db-timeout-actions">` +
                                    (_hasSql ? `<button type="button" class="db-timeout-sql-btn" title="Çalıştırılan SQL'i görüntüle"><i class="fa-solid fa-code"></i> SQL Görüntüle</button>` : '') +
                                    `<button type="button" class="db-timeout-cancel-btn">🛑 İptal Et</button>` +
                                    `</div>`;
                                // Mesaj metni XSS-safe textContent ile
                                twDiv.querySelector('.db-timeout-text').textContent = twMsg;
                                // v3.15.6: SQL butonu — DialogChatUtils.showSQLModal mevcut, onu kullan.
                                if (_hasSql) {
                                    const sqlBtn = twDiv.querySelector('.db-timeout-sql-btn');
                                    if (sqlBtn) {
                                        sqlBtn.addEventListener('click', () => {
                                            try {
                                                if (window.DialogChatUtils && typeof window.DialogChatUtils.showSQLModal === 'function') {
                                                    window.DialogChatUtils.showSQLModal(String(twSql));
                                                }
                                            } catch (_e) { /* sessiz */ }
                                        });
                                    }
                                }
                                // v3.15.0: İptal butonu click handler
                                const cancelBtn = twDiv.querySelector('.db-timeout-cancel-btn');
                                if (cancelBtn) {
                                    cancelBtn.addEventListener('click', async () => {
                                        if (!activeJobId) return;
                                        cancelBtn.disabled = true;
                                        cancelBtn.textContent = '⏳ İptal ediliyor...';
                                        try {
                                            const dlgId = _getDialogIdSafe();
                                            if (!dlgId) {
                                                cancelBtn.textContent = '⚠️ Diyalog bulunamadı';
                                                return;
                                            }
                                            const token = localStorage.getItem('access_token');
                                            const headers = { 'Content-Type': 'application/json' };
                                            if (token) headers['Authorization'] = `Bearer ${token}`;
                                            const resp = await fetch(`/api/dialogs/${dlgId}/jobs/${encodeURIComponent(activeJobId)}/cancel`, {
                                                method: 'POST',
                                                headers,
                                            });
                                            if (resp.ok) {
                                                cancelBtn.textContent = '✓ İptal sinyali gönderildi';
                                            } else {
                                                cancelBtn.textContent = '⚠️ İptal başarısız';
                                                cancelBtn.disabled = false;
                                            }
                                        } catch (_e) {
                                            cancelBtn.textContent = '⚠️ Bağlantı hatası';
                                            cancelBtn.disabled = false;
                                        }
                                    });
                                }
                                const twContent = streamingEl.querySelector('.message-content') || streamingEl;
                                twContent.appendChild(twDiv);
                                // v3.14.6: sayacı başlat ve mevcut elapsed'ten devam ettir
                                elapsedSeconds = parseInt(twElapsed) || 0;
                                const initialCounter = twDiv.querySelector('.db-timeout-elapsed');
                                if (initialCounter) initialCounter.textContent = _formatElapsed(elapsedSeconds);
                                startElapsedTicker();
                                break;
                            }

                            // v3.14.5: Periyodik progress tick — sorgu bekleme süresince her 10sn
                            case 'progress_tick': {
                                const { elapsed: ptElapsed, max_wait: ptMax, message: ptMsg, job_id: ptJob } = eventData;
                                if (!streamingEl) {
                                    streamingEl = createStreamingMessage();
                                }
                                if (ptJob) {
                                    activeJobId = ptJob;
                                    activeJobs.add(ptJob);
                                }
                                const existing = streamingEl.querySelector('.db-timeout-info .db-timeout-text');
                                if (existing) {
                                    existing.textContent = ptMsg || `⏳ ${ptElapsed}sn — sorgu devam ediyor...`;
                                } else {
                                    updateStreamingStatus(streamingEl, ptMsg || `⏳ ${ptElapsed}sn — sorgu devam ediyor...`);
                                }
                                // v3.14.6: backend tarafından gelen elapsed ile sayacı senkronize et
                                if (typeof ptElapsed === 'number' && ptElapsed > elapsedSeconds) {
                                    elapsedSeconds = ptElapsed;
                                }
                                const counterEl = streamingEl.querySelector('.db-timeout-elapsed');
                                if (counterEl) counterEl.textContent = _formatElapsed(elapsedSeconds);
                                if (!elapsedTickHandle) startElapsedTicker();
                                break;
                            }

                            // v4.0: Follow-up önerileri
                            // v3.16.0: DB modunda chip listesinin EN BAŞINA
                            // "🔗 Önceki konu ile ilgili soru sor" badge eklenir.
                            // Kullanıcı tıklayınca pendingFollowupAnchorId ayarlanır,
                            // textarea'ya odaklanılır, placeholder güncellenir.
                            case 'followup': {
                                const { suggestions: fuSugg } = eventData;
                                if (fuSugg?.length) {
                                    const fuHtml = window.DialogChatUtils.renderFollowUpChips(
                                        fuSugg,
                                        (q) => {
                                            // Kullanıcı follow-up seçti — normal DB sorgusu gönder
                                            const inputEl = document.getElementById('dialogInput');
                                            if (inputEl) {
                                                inputEl.value = q;
                                                handleSendMessage();
                                            }
                                        }
                                    );
                                    // v3.16.0: DB modunda badge'i chip listesinin başına ekle.
                                    let prefixHtml = '';
                                    if (isDbMode && lastDbAssistantMessageId) {
                                        prefixHtml = `<button type="button" class="db-followup-anchor-badge" data-anchor-id="${lastDbAssistantMessageId}" title="Bir sonraki mesajın önceki sorgu üzerinde değişiklik olduğunu belirt"><i class="fa-solid fa-link"></i> Önceki konu ile ilgili soru sor</button>`;
                                    }
                                    _insertInteractiveBlock(prefixHtml + fuHtml);
                                    // Badge tıklama handler'ı
                                    if (prefixHtml) {
                                        try {
                                            const badges = document.querySelectorAll('.db-followup-anchor-badge[data-anchor-id]');
                                            badges.forEach((btn) => {
                                                if (btn.dataset.bound === '1') return;
                                                btn.dataset.bound = '1';
                                                btn.addEventListener('click', () => {
                                                    const aid = parseInt(btn.dataset.anchorId, 10);
                                                    if (!aid) return;
                                                    pendingFollowupAnchorId = aid;
                                                    _showFollowupIndicator(aid);
                                                    const inp = document.getElementById('dialogInput');
                                                    if (inp) {
                                                        inp.placeholder = '↪ Önceki sorgu üzerinde değişiklik isteyin...';
                                                        inp.focus();
                                                    }
                                                });
                                            });
                                        } catch (_e) { /* sessiz */ }
                                    }
                                }
                                break;
                            }

                            case 'error':
                                console.error('[DialogChat] Stream error:', eventData);
                                if (streamingEl) streamingEl.remove();
                                addSystemMessage('❌ Yanıt üretilirken hata oluştu. Lütfen tekrar deneyin.');
                                return;
                        }
                    } catch (parseErr) {
                        console.warn('[DialogChat] SSE parse error:', parseErr);
                    }
                }
            }

            // v3.14.5: Stream bitti — idle watchdog'u temizle
            if (watchdogTimer) { clearTimeout(watchdogTimer); watchdogTimer = null; }
            // v3.14.6: gerçek-zamanlı sayaç da durdurulur
            stopElapsedTicker();

            // v3.14.5: Watchdog tetiklendiyse kullanıcıya net hata mesajı ver
            if (watchdogTripped && !finalContent) {
                if (streamingEl) streamingEl.remove();
                addSystemMessage('⏱️ Sunucu yanıt vermedi (90sn sessizlik). Sorgu çok uzun sürüyor olabilir — daha dar bir kapsamla tekrar deneyin.');
                return;
            }

            // ⏱️ Response time hesapla
            const responseTime = ((performance.now() - startTime) / 1000).toFixed(2);

            // Stream container'ı temizle
            if (streamingEl) {
                streamingEl.remove();
            }

            // Final mesajı AddAssistantMessage ile göster
            if (finalContent) {
                const msgObj = {
                    id: savedMessageId || 0,
                    role: 'assistant',
                    content: finalContent,
                    content_type: 'text',
                    metadata: finalMetadata,
                    created_at: new Date().toISOString()
                };

                lastAddedMessageId = savedMessageId;
                addAssistantMessage(msgObj, savedQuickReply, true, responseTime);

                // v4.0: DB sorgu sonucu — tablo + export bar + SQL butonu
                if (finalMetadata?.db_only) {
                    const cols = finalMetadata.columns || [];
                    const rows = finalMetadata.raw_data || [];
                    const sqlText = finalMetadata.sql_executed || finalMetadata.sql || '';

                    let blockHtml = '';

                    // Tablo + export bar (sadece veri varsa)
                    if (rows.length > 0 && cols.length > 0) {
                        const tblHtml = window.DialogChatUtils.renderSQLResultTable(cols, rows, finalMetadata);
                        const expHtml = window.DialogChatUtils.renderExportBar(cols, rows, {
                            title: 'VYRA Sorgu Sonucu',
                            query: content,
                            sql: sqlText,
                        });
                        blockHtml += tblHtml + expHtml;
                    }

                    // SQL butonu — her DB yanıtında göster
                    if (sqlText) {
                        blockHtml += window.DialogChatUtils.renderSQLButton(sqlText);
                    }

                    if (blockHtml) {
                        _insertInteractiveBlock(blockHtml);
                    }
                }

                // Response time'ı backend'e kaydet
                if (savedMessageId) {
                    saveResponseTime(savedMessageId, parseFloat(responseTime));
                }

                // 🔔 Notification
                const previewText = finalContent.substring(0, 100) || 'Yanıt hazır';
                showNotification('🤖 ' + _appName() + ' Yanıtladı', previewText);
            } else {
                addSystemMessage('❌ Yanıt alınamadı.');
            }

        } catch (error) {
            hideTypingIndicator();
            console.error('[DialogChat] Mesaj gönderilemedi:', error);

            // v3.14.5/3.14.6: Network hatası türünü ayrıştır — INCOMPLETE_CHUNKED/timeout için özel mesaj
            const errorMsg = error?.message || String(error);
            const lowerMsg = errorMsg.toLowerCase();
            const isChunkedErr = lowerMsg.includes('incomplete') || lowerMsg.includes('chunked');
            const isAbortErr = lowerMsg.includes('abort') || lowerMsg.includes('cancel');
            // v3.14.6: TypeError 'Failed to fetch' / 'NetworkError' / 'Load failed' tarayıcıya göre değişir
            const isLongRunningNetErr = lowerMsg.includes('failed to fetch') ||
                                        lowerMsg.includes('network error') ||
                                        lowerMsg.includes('load failed') ||
                                        lowerMsg.includes('err_incomplete') ||
                                        lowerMsg.includes('err_empty_response');

            if (isChunkedErr || isAbortErr || isLongRunningNetErr) {
                addSystemMessage('⏱️ Sunucu bağlantısı uzun süre yanıt vermediği için kesildi. Sorgu çok uzun sürüyor olabilir — daha dar bir kapsamla tekrar deneyin veya sorguyu daraltın.');
            } else if (window.isVPNNetworkError && window.isVPNNetworkError(errorMsg)) {
                if (window.showVPNErrorPopup) window.showVPNErrorPopup();
                addSystemMessage('🌐 Bağlantı hatası. VPN veya internet bağlantınızı kontrol edin.');
            } else {
                // v3.14.6: errorMsg ham haliyle DOM'a basılamaz (addSystemMessage innerHTML kullanıyor — XSS riski).
                // Detay zaten console.error ile loglandı (line 845).
                addSystemMessage('❌ Bağlantı hatası. Tarayıcı konsolundan detay görebilirsiniz.');
            }
        } finally {
            // v3.14.5: Watchdog timer'ı her durumda temizle (memory leak engeli)
            // Not: watchdogTimer 'let' ile içeride bildirildiği için TDZ riski olabilir;
            // try-catch ile sarmalanmış erişim güvenli.
            try { if (watchdogTimer) clearTimeout(watchdogTimer); } catch (_) { /* TDZ */ }
            // v3.14.6: gerçek-zamanlı sayacı da temizle
            try { if (elapsedTickHandle) clearInterval(elapsedTickHandle); } catch (_) { /* TDZ */ }
            // v3.15.1: job tamamlandı → activeJobs Set'inden sil
            try { if (typeof activeJobId !== 'undefined' && activeJobId) activeJobs.delete(activeJobId); } catch (_) { /* TDZ */ }
            isWaitingForResponse = false;
        }

        // Görselleri temizle
        clearPendingImages();
    }

    // =============================================================================
    // STREAMING HELPERS (v2.50.0)
    // =============================================================================

    /**
     * 🆕 v2.50.0: Boş streaming mesaj container'ı oluşturur.
     * Token geldiğinde bu container'a ekleme yapılır.
     */
    function createStreamingMessage() {
        const container = document.getElementById('dialogMessages');
        if (!container) return null;

        const row = document.createElement('div');
        row.className = 'message-row assistant streaming-row';
        row.innerHTML = `
            <div class="message-header-row">
                <div class="message-avatar vyra">${_appInitial()}</div>
                <span class="message-sender-name">${_appName()}</span>
            </div>
            <div class="message-bubble assistant streaming-bubble">
                <div class="streaming-status"></div>
                <div class="streaming-content"></div>
                <span class="streaming-cursor">▌</span>
            </div>
        `;

        container.appendChild(row);
        scrollToBottom();
        return row;
    }

    /**
     * 🆕 v2.50.0: Streaming mesajdaki durum satırını günceller.
     */
    function updateStreamingStatus(streamingEl, text) {
        if (!streamingEl) return;
        const statusEl = streamingEl.querySelector('.streaming-status');
        if (statusEl) {
            statusEl.textContent = text;
            statusEl.style.display = text ? 'block' : 'none';
        }
    }

    /**
     * 🆕 v2.50.0: Streaming mesaja token ekler ve scroll'u korur.
     */
    function appendStreamToken(streamingEl, token) {
        if (!streamingEl) return;
        const contentEl = streamingEl.querySelector('.streaming-content');
        if (!contentEl) return;

        // Status'u gizle (token gelmeye başladı)
        const statusEl = streamingEl.querySelector('.streaming-status');
        if (statusEl) statusEl.style.display = 'none';

        // Token ekle
        contentEl.textContent += token;

        // Auto-scroll (sadece kullanıcı en alttaysa)
        const messagesContainer = document.getElementById('dialogMessages');
        if (messagesContainer) {
            const isNearBottom = messagesContainer.scrollHeight - messagesContainer.scrollTop - messagesContainer.clientHeight < 100;
            if (isNearBottom) {
                scrollToBottom();
            }
        }
    }

    /**
     * v4.0: Chat mesaj listesine interaktif HTML bloğu (disambiguation, follow-up, export bar) ekler.
     */
    function _insertInteractiveBlock(html) {
        if (!html) return;
        const container = document.getElementById('dialogMessages');
        if (!container) return;
        const wrap = document.createElement('div');
        wrap.className = 'db-interactive-block';
        wrap.innerHTML = html;
        container.appendChild(wrap);
        container.scrollTop = container.scrollHeight;
    }

    // v3.16.0: Follow-up çıpası aktifken textarea üstünde gösterilen rozet.
    // Kullanıcı çıpadan vazgeçerse X ile kapatabilir.
    function _showFollowupIndicator(anchorId) {
        try {
            let ind = document.getElementById('dbFollowupIndicator');
            const input = document.getElementById('dialogInput');
            if (!input) return;
            const host = input.parentElement || input;
            if (!ind) {
                ind = document.createElement('div');
                ind.id = 'dbFollowupIndicator';
                ind.className = 'db-followup-indicator';
                ind.innerHTML = `<span class="dfi-text"><i class="fa-solid fa-link"></i> Önceki konu ile ilgili sor</span><button type="button" class="dfi-clear" title="Vazgeç" aria-label="Vazgeç">×</button>`;
                host.insertBefore(ind, input);
                const clearBtn = ind.querySelector('.dfi-clear');
                if (clearBtn) clearBtn.addEventListener('click', () => {
                    pendingFollowupAnchorId = null;
                    _hideFollowupIndicator();
                });
            }
            ind.dataset.anchorId = String(anchorId);
            ind.style.display = '';
        } catch (_e) { /* sessiz */ }
    }

    function _hideFollowupIndicator() {
        try {
            const ind = document.getElementById('dbFollowupIndicator');
            if (ind) ind.remove();
            const inp = document.getElementById('dialogInput');
            if (inp && inp.placeholder && inp.placeholder.startsWith('↪')) {
                inp.placeholder = 'Mesajınızı yazın...';
            }
        } catch (_e) { /* sessiz */ }
    }

    /**
     * v4.0: schema_hint veya report_template ile DB mesajını yeniden gönderir.
     * Disambiguation seçimi veya rapor şablonu seçimi sonrasında çağrılır.
     */
    async function _sendDbMessageWithHint(query, schemaHint, reportTemplate) {
        if (!currentDialogId || !query) return;

        hideTypingIndicator();
        showTypingIndicator();
        isWaitingForResponse = true;

        const token = localStorage.getItem('access_token');
        const body = {
            content: query,
            source_type: 'db',
        };
        if (schemaHint) body.schema_hint = schemaHint;
        if (reportTemplate) body.report_template = reportTemplate;

        try {
            const response = await fetch(`${API_BASE}/dialogs/${currentDialogId}/messages/stream`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify(body),
            });

            if (!response.ok) {
                hideTypingIndicator();
                isWaitingForResponse = false;
                addSystemMessage('❌ İstek gönderilemedi. Lütfen tekrar deneyin.');
                return;
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let streamingEl = null;
            let streamedText = '';
            let finalContent = null;
            let finalMetadata = null;
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const jsonStr = line.slice(6).trim();
                    if (!jsonStr) continue;
                    try {
                        const ev = JSON.parse(jsonStr);
                        switch (ev.type) {
                            case 'status':
                                if (streamingEl) updateStreamingStatus(streamingEl, `⏳ ${ev.data}`);
                                break;
                            case 'token':
                                if (!streamingEl) streamingEl = createStreamingMessage();
                                streamedText += ev.data;
                                appendStreamToken(streamingEl, ev.data);
                                break;
                            case 'done':
                                finalContent = ev.data.content;
                                finalMetadata = ev.data.metadata || {};
                                break;
                            case 'followup': {
                                const { suggestions: fs } = ev.data;
                                if (fs?.length) {
                                    const fHtml = window.DialogChatUtils.renderFollowUpChips(fs,
                                        (q) => { const inp = document.getElementById('dialogInput'); if (inp) { inp.value = q; handleSendMessage(); } });
                                    _insertInteractiveBlock(fHtml);
                                }
                                break;
                            }
                            case 'error':
                                if (streamingEl) streamingEl.remove();
                                addSystemMessage('❌ ' + (ev.data || 'Hata oluştu.'));
                                hideTypingIndicator();
                                isWaitingForResponse = false;
                                return;
                        }
                    } catch (_) {}
                }
            }

            if (streamingEl) streamingEl.remove();
            if (finalContent) {
                const msgObj = { id: 0, role: 'assistant', content: finalContent, content_type: 'text', metadata: finalMetadata, created_at: new Date().toISOString() };
                addAssistantMessage(msgObj, null, true, '');

                if (finalMetadata?.db_only && finalMetadata?.raw_data?.length > 0) {
                    const cols = finalMetadata.columns || [];
                    const rows = finalMetadata.raw_data || [];
                    if (cols.length > 0) {
                        const tblHtml = window.DialogChatUtils.renderSQLResultTable(cols, rows, finalMetadata);
                        const expHtml = window.DialogChatUtils.renderExportBar(cols, rows, { title: 'VYRA Sorgu Sonucu', query, sql: finalMetadata.sql_executed });
                        _insertInteractiveBlock(tblHtml + expHtml);
                    }
                }
            }
        } catch (err) {
            console.error('[DialogChat] _sendDbMessageWithHint hatası:', err);
            addSystemMessage('❌ Bağlantı hatası oluştu.');
        } finally {
            hideTypingIndicator();
            isWaitingForResponse = false;
        }
    }

    /**
     * 🆕 v2.50.0: Streaming mesajı son haline getirir (şu an no-op, final render addAssistantMessage ile yapılıyor).
     */
    function finalizeStreamingMessage(streamingEl) {
        if (streamingEl) {
            streamingEl.remove();
        }
    }

    // =============================================================================
    // MULTI-SELECT CARD FUNCTIONS
    // =============================================================================

    function toggleCardSelection(cardId, cardElement) {
        // Toggle seçim
        const index = selectedCardIds.indexOf(cardId);
        if (index > -1) {
            selectedCardIds.splice(index, 1);
            cardElement.classList.remove('card-selected');
            // Checkbox icon güncelle
            const checkbox = cardElement.querySelector('.card-checkbox i');
            if (checkbox) {
                checkbox.className = 'fa-regular fa-square';
            }
        } else {
            selectedCardIds.push(cardId);
            cardElement.classList.add('card-selected');
            // Checkbox icon güncelle
            const checkbox = cardElement.querySelector('.card-checkbox i');
            if (checkbox) {
                checkbox.className = 'fa-solid fa-check-square';
            }
        }

        // 🔧 v2.21.3: "Seçilenleri Gönder" butonunu güncelle
        // closest() ile bu kartın ait olduğu mesajdaki butonu bul
        const messageContainer = cardElement.closest('.message-assistant');
        const multiSelectBtn = messageContainer
            ? messageContainer.querySelector('#multiSelectBtn')
            : document.getElementById('multiSelectBtn');

        // 🔧 v2.21.3: Buton her zaman aktif - sadece text güncelle
        if (multiSelectBtn) {
            if (selectedCardIds.length > 0) {
                multiSelectBtn.innerHTML = `<i class="fa-solid fa-paper-plane"></i> ${selectedCardIds.length} Seçimi Gönder`;
            } else {
                multiSelectBtn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Seçilenleri Gönder';
            }
        }

        // Input durumunu güncelle
        updateSendButtonState();
    }

    function toggleSelectAll() {
        const cards = document.querySelectorAll('.quick-reply-card:not(.card-disabled):not(.card-selected)');
        const allCards = document.querySelectorAll('.quick-reply-card:not(.card-disabled)');
        const selectAllIcon = document.getElementById('selectAllIcon');
        const totalCount = allCards.length;

        if (selectedCardIds.length < totalCount) {
            // Hepsini seç
            selectedCardIds = [];
            allCards.forEach((card, idx) => {
                const cardId = parseInt(card.dataset.cardId);
                if (!isNaN(cardId)) {
                    selectedCardIds.push(cardId);
                    card.classList.add('card-selected');
                    const checkbox = card.querySelector('.card-checkbox i');
                    if (checkbox) checkbox.className = 'fa-solid fa-check-square';
                }
            });
            if (selectAllIcon) selectAllIcon.className = 'fa-solid fa-check-square';
        } else {
            // Hepsini kaldır
            allCards.forEach(card => {
                card.classList.remove('card-selected');
                const checkbox = card.querySelector('.card-checkbox i');
                if (checkbox) checkbox.className = 'fa-regular fa-square';
            });
            selectedCardIds = [];
            if (selectAllIcon) selectAllIcon.className = 'fa-regular fa-square';
        }

        // 🔧 v2.21.3: Buton durumunu güncelle - closest() ile doğru butonu bul
        const messageContainer = selectAllIcon?.closest('.message-assistant');
        const multiSelectBtn = messageContainer
            ? messageContainer.querySelector('#multiSelectBtn')
            : document.getElementById('multiSelectBtn');

        // 🔧 v2.21.3: Buton her zaman aktif - sadece text güncelle
        if (multiSelectBtn) {
            if (selectedCardIds.length > 0) {
                multiSelectBtn.innerHTML = `<i class="fa-solid fa-paper-plane"></i> ${selectedCardIds.length} Seçimi Gönder`;
            } else {
                multiSelectBtn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Seçilenleri Gönder';
            }
        }

        updateSendButtonState();
    }

    async function handleMultiSelect() {
        if (!currentDialogId || selectedCardIds.length === 0) return;

        // Seçilen kartların bilgilerini al
        const cards = document.querySelectorAll('.quick-reply-card');
        const selectedTitles = selectedCardIds.map(id => {
            const card = cards[id];
            return card?.querySelector('.card-title')?.textContent?.trim() || `Seçenek ${id + 1}`;
        });

        // Kullanıcı mesajı
        const userMessage = selectedCardIds.length === 1
            ? `✅ "${selectedTitles[0]}" seçeneği ile devam ediyorum`
            : `✅ ${selectedCardIds.length} seçenek seçtim: ${selectedTitles.join(', ')}`;

        addUserMessage(userMessage);

        // Son assistant mesajını bul ve message ID al
        const lastAssistantMsg = [...document.querySelectorAll('.message-assistant')].pop();
        const targetMessageId = lastAssistantMsg?.dataset?.messageId
            ? parseInt(lastAssistantMsg.dataset.messageId)
            : null;

        // Kartları ve butonları kaldır
        if (lastAssistantMsg) {
            const cardsContainer = lastAssistantMsg.querySelector('.quick-reply-cards');
            if (cardsContainer) cardsContainer.remove();
            const actionsSection = lastAssistantMsg.querySelector('.multi-select-actions');
            if (actionsSection) actionsSection.remove();
        }

        // Input'u tekrar aktif et
        updateSendButtonState();

        showTypingIndicator();

        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`${API_BASE}/dialogs/${currentDialogId}/quick-reply`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    action: 'multi_select',
                    selection_ids: selectedCardIds,
                    message_id: targetMessageId
                })
            });

            hideTypingIndicator();

            if (response.ok) {
                const message = await response.json();
                addAssistantMessage(message);
            }
        } catch (error) {
            hideTypingIndicator();
            console.error('[DialogChat] Multi-select hatası:', error);
        } finally {
            // Seçimleri sıfırla
            selectedCardIds = [];
        }
    }

    async function handleQuickReply(action, selectionId = null) {
        if (!currentDialogId) return;

        // Kullanıcı seçimini Türkçe mesaj olarak göster
        let userMessage = '';
        if (action === 'select' && selectionId !== null) {
            // Seçilen kartın başlığını ve detayını bul
            const cards = document.querySelectorAll('.quick-reply-card');
            const selectedCard = cards[selectionId];
            const cardTitle = selectedCard?.querySelector('.card-title')?.textContent?.trim() || `Seçenek ${selectionId + 1}`;

            // İlk detay bilgisini al (Uygulama Adı öncelikli)
            const firstDetail = selectedCard?.querySelector('.card-detail')?.textContent?.trim() || '';

            // Detay varsa "Dosya Adı - Detay" formatında göster
            const selectedText = firstDetail ? `${cardTitle} - ${firstDetail}` : cardTitle;
            userMessage = `✅ "${selectedText}" seçeneği ile devam ediyorum`;
        } else if (action === 'yes') {
            userMessage = '👍 Evet, bu çözüm işime yaradı';
        } else if (action === 'no') {
            userMessage = '👎 Hayır, farklı bir çözüm istiyorum';
        } else if (action === 'yes_more') {
            userMessage = '👍 Evet, başka sorum var';
        } else if (action === 'no_more') {
            userMessage = '👋 Hayır, teşekkürler';
        } else if (action === 'not_interested') {
            userMessage = '⏭️ Bu seçenekler ilgimi çekmiyor, farklı bir soru sormak istiyorum';
        } else if (action === 'ai_evaluate') {
            userMessage = '🤖 AI ile tüm sonuçları değerlendir';
        }

        // Kullanıcı yanıtını göster
        if (userMessage) {
            addUserMessage(userMessage);
        }

        // Quick reply kartlarını/butonlarını READ-ONLY yap (tekrar tıklanmasın)
        // ÖNEMLİ: Sadece son assistant mesajındaki kartları hedefle
        const allMessages = document.querySelectorAll('.message-row.assistant');
        const lastAssistantMsg = allMessages[allMessages.length - 1];

        if (lastAssistantMsg && action === 'select' && selectionId !== null) {
            const cardsContainer = lastAssistantMsg.querySelector('.quick-reply-cards');
            if (cardsContainer) {
                // Tüm kartları read-only yap
                cardsContainer.classList.add('cards-readonly');
                const allCards = cardsContainer.querySelectorAll('.quick-reply-card');
                allCards.forEach((card, idx) => {
                    // Onclick kaldır
                    card.removeAttribute('onclick');
                    card.style.cursor = 'default';
                    card.style.pointerEvents = 'none';
                    card.classList.add('card-disabled');

                    // Seçilen karta tik işareti ekle
                    if (idx === selectionId) {
                        card.classList.remove('card-disabled');
                        card.classList.add('card-selected');
                        // Tik işareti ekle (header'a)
                        const header = card.querySelector('.quick-reply-card-header');
                        if (header && !header.querySelector('.card-check')) {
                            const checkIcon = document.createElement('span');
                            checkIcon.className = 'card-check';
                            checkIcon.innerHTML = '<i class="fa-solid fa-check-circle"></i>';
                            header.appendChild(checkIcon);
                        }
                    }
                });
            }
        } else if (lastAssistantMsg) {
            // 🔧 v2.21.2: AI Evaluate seçildiğinde kartları silme (collapse etme), sadece disable et
            if (action === 'ai_evaluate') {
                const cardsContainer = lastAssistantMsg.querySelector('.quick-reply-cards');
                if (cardsContainer) {
                    cardsContainer.classList.add('cards-readonly');
                    // Kartları tıklanamaz yap
                    cardsContainer.querySelectorAll('.quick-reply-card').forEach(card => {
                        card.removeAttribute('onclick');
                        card.style.cursor = 'default';
                        card.style.pointerEvents = 'none';
                        card.classList.add('card-disabled');
                    });
                }

                // Buton grubunu pasif yap ama görünür bırak
                const actionsSection = lastAssistantMsg.querySelector('.multi-select-actions');
                if (actionsSection) {
                    actionsSection.style.pointerEvents = 'none';
                    actionsSection.style.opacity = '0.6';
                }
            } else {
                // Diğer action'larda (yes/no/not_interested gibi) son mesajdaki kartları kaldır
                const cardsContainer = lastAssistantMsg.querySelector('.quick-reply-cards');
                if (cardsContainer) cardsContainer.remove();

                // Multi-select ve action butonlarını kaldır
                const actionsSection = lastAssistantMsg.querySelector('.multi-select-actions');
                if (actionsSection) actionsSection.remove();

                // İlgimi Çekmiyor butonunu da kaldır (varsa eski yapıdan)
                const notInterestedSection = lastAssistantMsg.querySelector('.not-interested-section');
                if (notInterestedSection) notInterestedSection.remove();
            }
        }

        // Evet/Hayır butonlarını kaldır (son mesajdan)
        if (lastAssistantMsg) {
            const btnContainer = lastAssistantMsg.querySelector('.quick-reply-container');
            if (btnContainer) btnContainer.remove();

            // "Başka sorunuz var mı?" butonlarını da answered olarak işaretle
            const askMoreContainer = lastAssistantMsg.querySelector('.ask-more-section .quick-reply-container');
            if (askMoreContainer) {
                askMoreContainer.classList.add('answered');
                // Butonları disable et
                askMoreContainer.querySelectorAll('button').forEach(btn => {
                    btn.disabled = true;
                    btn.classList.add('btn-disabled');
                });
            }
        }

        // 📝 Input alanını tekrar aktif et (kartlar/butonlar kaldırıldı)
        updateSendButtonState();

        showTypingIndicator();

        // 🔒 Hedef mesajın ID'sini al (güvenilir seçim için)
        const targetMessageId = lastAssistantMsg?.dataset?.messageId
            ? parseInt(lastAssistantMsg.dataset.messageId)
            : null;

        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`${API_BASE}/dialogs/${currentDialogId}/quick-reply`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    action,
                    selection_id: selectionId,
                    message_id: targetMessageId  // 🔒 Direkt mesaj ID ile al
                })
            });

            hideTypingIndicator();

            if (response.ok) {
                const message = await response.json();
                addAssistantMessage(message);
            }
        } catch (error) {
            hideTypingIndicator();
            console.error('[DialogChat] Quick reply hatası:', error);
        }
    }

    async function sendFeedback(messageId, feedbackType, btn = null) {
        try {
            const token = localStorage.getItem('access_token');
            await fetch(`${API_BASE}/dialogs/${currentDialogId}/feedback`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ message_id: messageId, feedback_type: feedbackType })
            });

            // Butonu seçili hale getir
            if (btn) {
                // Aynı mesajdaki diğer feedback butonlarından selected kaldır
                const parent = btn.closest('.feedback-buttons');
                if (parent) {
                    parent.querySelectorAll('.feedback-btn').forEach(b => {
                        b.classList.remove('selected');
                    });
                }
                // Tıklananı seçili yap
                btn.classList.add('selected');
            }

            showToast('success', 'Geri bildiriminiz kaydedildi!');
        } catch (error) {
            console.error('[DialogChat] Feedback gönderilemedi:', error);
        }
    }

    // 🆕 v2.29.13: Diğer kategorileri sırayla göster
    async function showOtherCategories(btn) {
        // 🛡️ v2.29.14: WebSocket duplicate önleme - HTTP response bekliyoruz
        isWaitingForResponse = true;

        try {
            // Gösterilen kategori sayısını takip et (butondan)
            const shownCount = parseInt(btn?.dataset?.shownCount || '1', 10);

            // Son kullanıcı mesajını bul
            const userMessages = document.querySelectorAll('#dialogMessages .message-row.user .message-content');
            const lastUserMessage = userMessages.length > 0 ? userMessages[userMessages.length - 1] : null;

            if (!lastUserMessage) {
                showToast('error', 'Son sorgu bulunamadı');
                return;
            }

            const query = lastUserMessage.textContent.trim();
            showTypingIndicator();

            // Butonu devre dışı bırak
            if (btn) {
                btn.disabled = true;
                btn.textContent = '⏳ Yükleniyor...';
            }

            const token = localStorage.getItem('access_token');
            const response = await fetch(`${API_BASE}/dialogs/${currentDialogId}/messages`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    content: `Sonraki kategori[${shownCount}]: ${query}`
                })
            });

            hideTypingIndicator();

            if (response.ok) {
                const data = await response.json();
                if (data.message) {
                    // Duplicate önleme: ÖNCE ID'yi kaydet
                    lastAddedMessageId = data.message.id;
                    addAssistantMessage(data.message);
                }
            } else {
                showToast('error', 'Sunucu hatası');
            }
        } catch (error) {
            hideTypingIndicator();
            console.error('[DialogChat] Sonraki kategori yüklenemedi:', error);
            showToast('error', 'Sonraki kategori yüklenirken hata oluştu');
        } finally {
            // HTTP response geldi veya hata oldu - artık beklemiyoruz
            isWaitingForResponse = false;
        }
    }

    // =============================================================================
    // RENDERING
    // =============================================================================

    function renderMessages(messages) {
        const container = document.getElementById('dialogMessages');
        if (!container) return;

        container.innerHTML = '';

        if (messages.length === 0) {
            container.innerHTML = `
                <div class="dialog-empty-state">
                    <div class="dialog-empty-icon">💬</div>
                    <div class="dialog-empty-title">Merhaba!</div>
                    <div class="dialog-empty-subtitle">
                        Size nasıl yardımcı olabilirim? Sorununuzu yazın veya ekran görüntüsü paylaşın.
                    </div>
                </div>
            `;
            // 📝 Empty state'te de buton durumunu güncelle
            updateSendButtonState();
            return;
        }

        messages.forEach(msg => {
            if (msg.role === 'user') {
                addUserMessage(msg.content, null, msg.created_at, false);
            } else if (msg.role === 'assistant') {
                // Quick reply ve response time bilgisini metadata'dan al (varsa)
                const quickReply = msg.metadata?.quick_reply || null;
                const responseTime = msg.metadata?.response_time || null;

                console.log('[DialogChat] Assistant mesaj render:', {
                    id: msg.id,
                    hasQuickReply: !!quickReply,
                    quickReplyType: quickReply?.type,
                    optionsCount: quickReply?.options?.length
                });

                addAssistantMessage(msg, quickReply, false, responseTime);
            }
        });

        scrollToBottom();

        // 📝 Input ve buton durumlarını güncelle
        updateSendButtonState();
    }

    function addUserMessage(content, images = null, timestamp = null, scroll = true) {
        const container = document.getElementById('dialogMessages');
        if (!container) return;

        // Empty state'i temizle
        const empty = container.querySelector('.dialog-empty-state');
        if (empty) empty.remove();

        const time = timestamp ? formatTime(timestamp) : formatTime(new Date().toISOString());
        const userInitial = getUserInitial();

        let imagesHtml = '';
        if (images && images.length > 0) {
            imagesHtml = `<div class="message-images">${images.map(img =>
                `<img src="${img.preview || img.base64}" alt="Görsel" class="message-image">`
            ).join('')}</div>`;
        }

        const userName = localStorage.getItem('user_full_name') || localStorage.getItem('user_name') || '';
        const html = `
            <div class="message-row user">
                <div class="message-bubble user">
                    ${imagesHtml}
                    <div class="message-content">${escapeHtml(content)}</div>
                </div>
                <div class="message-user-meta">${userName ? userName + ' · ' : ''}${time}</div>
            </div>
        `;

        container.insertAdjacentHTML('beforeend', html);
        if (scroll) scrollToBottom();
    }

    function addAssistantMessage(message, quickReply = null, scroll = true, responseTime = null) {
        const container = document.getElementById('dialogMessages');
        if (!container) return;

        const time = message.created_at ? formatTime(message.created_at) : formatTime(new Date().toISOString());
        const content = formatMessageContent(message.content);

        let quickReplyHtml = '';
        let feedbackSectionHtml = '';
        let askMoreHtml = '';

        if (quickReply && quickReply.type === 'document_selection') {
            // selected_option_ids varsa kartlar zaten seçilmiş demek - read-only göster
            // Tek seçim: selected_option_id (number), Çoklu seçim: selected_option_ids (array)
            const selectedIds = quickReply.selected_option_ids ||
                (quickReply.selected_option_id !== undefined ? [quickReply.selected_option_id] : null);
            const isReadonly = selectedIds !== null;

            // 🔧 KRİTİK: Yeni seçim kartları geldiğinde önceki seçimleri sıfırla
            // Bu, farklı sorulardaki seçimlerin birleşmesini önler
            if (!isReadonly) {
                selectedCardIds = [];
                console.log('[DialogChat] Yeni seçim kartları - selectedCardIds sıfırlandı');
            }

            quickReplyHtml = `
                <div class="quick-reply-cards${isReadonly ? ' cards-readonly' : ''}" data-message-id="${message.id || ''}">
                    ${quickReply.options.map((opt, i) => {
                const details = opt.details || {};
                const isSelected = isReadonly && selectedIds.includes(i);
                const isDisabled = isReadonly && !selectedIds.includes(i);

                // Class'ları belirle
                let cardClasses = 'quick-reply-card';
                if (isSelected) cardClasses += ' card-selected';
                if (isDisabled) cardClasses += ' card-disabled';

                // Onclick: read-only değilse toggle seçim
                const onclickAttr = isReadonly ? '' : `onclick="DialogChatModule.toggleCardSelection(${i}, this)"`;
                const cursorStyle = isReadonly ? 'style="cursor: default; pointer-events: none;"' : '';

                return `
                            <div class="${cardClasses}" data-card-id="${i}" ${onclickAttr} ${cursorStyle}>
                                <div class="quick-reply-card-header">
                                    <span class="card-number">${i + 1}</span>
                                    <span class="card-file-icon">${getFileTypeIcon(opt.file_type)}</span>
                                    <span class="card-title">${escapeHtml(opt.file_name || opt.label)}</span>
                                    <span class="card-score">%${opt.score || 0}</span>
                                    <span class="card-checkbox">
                                        <i class="fa-${isSelected ? 'solid fa-check-square' : 'regular fa-square'}"></i>
                                    </span>
                                </div>
                                ${opt.heading ? `<div class="card-heading"><i class="fa-solid fa-bookmark"></i> ${escapeHtml(opt.heading)}</div>` : ''}
                                <div class="quick-reply-card-body">
                                    ${details.uygulama_adi ? `<div class="card-detail"><strong>Uygulama Adı:</strong> ${escapeHtml(details.uygulama_adi)}</div>` : ''}
                                    ${details.keyflow_search ? `<div class="card-detail"><strong>Keyflow Search:</strong> ${escapeHtml(details.keyflow_search)}</div>` : ''}
                                    ${details.talep_tipi ? `<div class="card-detail"><strong>Talep Tipi:</strong> ${escapeHtml(details.talep_tipi)}</div>` : ''}
                                    ${details.rol_secimi ? `<div class="card-detail"><strong>Rol/Yetki Adı:</strong> ${escapeHtml(details.rol_secimi)}</div>` : ''}
                                    ${details.yetki_bilgisi ? `<div class="card-detail"><strong>Yetki Bilgisi:</strong> ${escapeHtml(details.yetki_bilgisi)}</div>` : ''}
                                    ${details.onizleme ? `<div class="card-detail card-preview">${escapeHtml(details.onizleme)}</div>` : ''}
                                    ${!details.uygulama_adi && !details.onizleme && opt.chunk_preview ? `<div class="card-detail card-preview">${escapeHtml(opt.chunk_preview)}</div>` : ''}
                                </div>
                                ${!isReadonly ? `<div class="quick-reply-card-footer">
                                    <span class="card-select-hint">☑️ Seçmek için tıklayın</span>
                                </div>` : ''}
                            </div>
                        `;
            }).join('')}
                </div>
                ${!isReadonly ? `
                <div class="multi-select-actions">
                    <label class="select-all-label" onclick="DialogChatModule.toggleSelectAll()">
                        <span class="select-all-checkbox">
                            <i class="fa-regular fa-square" id="selectAllIcon"></i>
                        </span>
                        <span class="select-all-text">Tümünü Seç</span>
                    </label>
                    <button class="multi-select-btn" id="multiSelectBtn" onclick="DialogChatModule.handleMultiSelect()">
                        <i class="fa-solid fa-paper-plane"></i> Seçilenleri Gönder
                    </button>
                    <button class="ai-evaluate-btn" onclick="DialogChatModule.handleQuickReply('ai_evaluate')">
                        <i class="fa-solid fa-robot"></i> AI ile Değerlendir
                    </button>
                    <button class="not-interested-btn" onclick="DialogChatModule.handleQuickReply('not_interested')">
                        <i class="fa-regular fa-hand"></i> İlgimi Çekmiyor
                    </button>
                </div>` : ''}
            `;
        } else if (quickReply && quickReply.type === 'corpix_fallback') {
            // v3.6.0: LLM fallback - RAG sonuç bulamadı, LLM sohbet modu öner
            quickReplyHtml = `
                <div class="quick-reply-container corpix-fallback">
                    <button class="quick-reply-btn corpix-yes corpix-mode-switch" onclick="DialogChatModule.switchToLlmMode()">
                        <i class="fa-solid fa-comments"></i> Sohbete Geç
                    </button>
                    <button class="quick-reply-btn corpix-retry" onclick="DialogChatModule.handleLlmAction('ask_llm', '${escapeHtml(message.metadata?.original_query || '')}')">
                        <i class="fa-solid fa-robot"></i> Bu Soruyu LLM'e Sor
                    </button>
                </div>
            `;
        } else if (message.content.includes('👍 👎') && message.content.includes('Başka bir sorunuz var mı?')) {
            // Çözüm mesajı - feedback ve soru ayrı ayrı render edilecek
            // Feedback butonları mesaj içinde inline olarak gösterilecek (CSS ile)
            // Evet/Hayır butonları en altta gösterilecek

            // Daha önce yanıt verilmiş mi kontrol et
            const isAnswered = quickReply?.answered || false;
            const disabledAttr = isAnswered ? 'disabled' : '';
            const disabledClass = isAnswered ? 'btn-disabled' : '';
            const onclickYes = isAnswered ? '' : `onclick="DialogChatModule.handleQuickReply('yes_more')"`;
            const onclickNo = isAnswered ? '' : `onclick="DialogChatModule.handleQuickReply('no_more')"`;

            askMoreHtml = `
                <div class="ask-more-section">
                    <div class="ask-more-divider"></div>
                    <p class="ask-more-text">Başka bir sorunuz var mı?</p>
                    <div class="quick-reply-container${isAnswered ? ' answered' : ''}">
                        <button class="quick-reply-btn yes ${disabledClass}" ${onclickYes} ${disabledAttr}>
                            <i class="fa-solid fa-thumbs-up"></i> Evet
                        </button>
                        <button class="quick-reply-btn no ${disabledClass}" ${onclickNo} ${disabledAttr}>
                            <i class="fa-solid fa-thumbs-down"></i> Hayır
                        </button>
                    </div>
                </div>
            `;
        } else if (message.content.includes('👍 👎')) {
            // Normal feedback içeren mesaj
            quickReplyHtml = `
                <div class="quick-reply-container">
                    <button class="quick-reply-btn yes" onclick="DialogChatModule.handleQuickReply('yes')">
                        <i class="fa-solid fa-thumbs-up"></i> Evet
                    </button>
                    <button class="quick-reply-btn no" onclick="DialogChatModule.handleQuickReply('no')">
                        <i class="fa-solid fa-thumbs-down"></i> Hayır
                    </button>
                </div>
            `;
        }

        // Feedback butonları - mesaj tipine göre karar ver
        // "Çözüm Bulundu!", "Bilgi Tabanından Buldum!", "Çözüm Seçildi!" mesajlarında faydalı/faydasız göster
        // Diğerlerinde (harika mesajı vb.) sadece hoparlör
        const isSolutionMessage = message.content.includes('Çözüm Bulundu!')
            || message.content.includes('Bilgi Tabanından Buldum!')
            || message.content.includes('Çözüm Seçildi!');

        // v2.21.7: AI değerlendirmesi sonucu mesajlarında da feedback göster (CatBoost ML için)
        const isAIEvaluationFeedback = message.content.includes('[FEEDBACK_SECTION]')
            || message.content.includes('feedback-section');

        // 🆕 v2.29.6: Deep Think yanıtlarında da feedback göster (ML öğrenmesi için)
        // 🔧 v2.38.3: SINGLE_ANSWER (📖), HOW_TO (🎯), TROUBLESHOOT (🔴) eklendi
        const isDeepThinkResponse = message.content.includes('📋 **')
            || message.content.includes('🏷️ **')
            || message.content.includes('📚 KAYNAKLAR')
            || message.content.includes('📖 **')       // SINGLE_ANSWER
            || message.content.includes('🎯 **Amaç')   // HOW_TO
            || message.content.includes('🔴 **Sorun')   // TROUBLESHOOT
            || message.content.includes('_Kaynak:');     // Tüm Deep Think yanıtları

        let feedbackHtml = '';
        if (message.id) {
            if (isSolutionMessage || isAIEvaluationFeedback || isDeepThinkResponse) {
                // Çözüm, AI değerlendirmesi veya Deep Think yanıtı - tüm feedback butonları göster
                feedbackHtml = `
                    <div class="feedback-buttons">
                        <button class="feedback-btn like" onclick="DialogChatModule.sendFeedback(${message.id}, 'helpful', this)" title="Faydalı">
                            <i class="fa-solid fa-thumbs-up"></i>
                        </button>
                        <button class="feedback-btn dislike" onclick="DialogChatModule.sendFeedback(${message.id}, 'not_helpful', this)" title="Faydasız">
                            <i class="fa-solid fa-thumbs-down"></i>
                        </button>
                        <button class="feedback-btn speak" onclick="DialogChatModule.speakMessage(${message.id}, this)" title="Sesli Oku">
                            <i class="fa-solid fa-volume-high"></i>
                        </button>
                    </div>
                `;
            } else {
                // Diğer mesajlar - sadece hoparlör
                feedbackHtml = `
                    <div class="feedback-buttons">
                        <button class="feedback-btn speak" onclick="DialogChatModule.speakMessage(${message.id}, this)" title="Sesli Oku">
                            <i class="fa-solid fa-volume-high"></i>
                        </button>
                    </div>
                `;
            }
        }

        // ⏱️ Response time gösterimi
        const responseTimeHtml = responseTime ? `
            <span class="response-time" title="Yanıt süresi">
                <i class="fa-solid fa-clock"></i> ${responseTime}s
            </span>
        ` : '';

        // 🎯 v2.49.0: RAG eşleşme skoru gösterimi
        const bestScore = message.metadata?.best_score || 0;
        const ragScoreHtml = bestScore > 0 ? `
            <span class="rag-score" title="RAG eşleşme skoru">
                <i class="fa-solid fa-bullseye"></i> ${bestScore.toFixed(2)}
            </span>
        ` : '';

        // Eğer askMoreHtml varsa, mesaj içeriğinden "Başka bir sorunuz var mı?" kaldır
        let cleanedContent = content;
        if (askMoreHtml) {
            cleanedContent = content
                .replace(/<hr>/g, '')
                .replace(/Başka bir sorunuz var mı\?/g, '')
                .replace(/---<br>/g, '<hr class="solution-divider">')
                .trim();
        }

        // 🎨 Feedback butonlarını feedback-section içine göm
        // "Bu çözümler işinize yaradı mı?" mesajının hemen altına ortalayarak ekle
        let finalFeedbackHtml = feedbackHtml;

        // 🤖 v2.20.9: Tek sonuç için AI önerisi butonu (Bilgi Tabanından Buldum!)
        const isSingleRAGResult = message.content.includes('Bilgi Tabanından Buldum!');
        const aiEvaluateSingleBtn = isSingleRAGResult && message.id ? `
            <div class="ai-evaluate-single-container">
                <button class="ai-evaluate-btn single-result" onclick="DialogChatModule.handleQuickReply('ai_evaluate')" data-message-id="${message.id}">
                    <i class="fa-solid fa-robot"></i> AI önerisi al
                </button>
            </div>
        ` : '';

        // 🆕 v2.51.0: CatBoost bypass — "Vyra önerisi al" butonu
        const canEnhance = message.metadata?.can_enhance === true;
        const originalQuery = message.metadata?.original_query || '';
        const enhanceBtn = canEnhance && message.id ? `
            <div class="vyra-enhance-container" id="enhance-container-${message.id}">
                <button class="vyra-enhance-btn" 
                    data-message-id="${message.id}"
                    data-query="${escapeHtml(originalQuery)}"
                    onclick="DialogChatModule.handleEnhance(this)"
                    title="LLM ile cevabı iyileştir">
                    <i class="fa-solid fa-wand-magic-sparkles"></i> ${_appName()} önerisi al
                </button>
            </div>
        ` : '';

        // feedback-section içeren mesajlarda butonları section içine göm
        if (cleanedContent.includes('feedback-section') && feedbackHtml) {
            // Regex ile feedback-section'ın içindeki son </div>'i bul ve butonları ekle
            // <div class="feedback-section">...<p>text</p></div> → <div class="feedback-section">...<p>text</p><buttons></buttons></div>
            cleanedContent = cleanedContent.replace(
                /(<div class="feedback-section">[\s\S]*?)(<\/div>)/,
                `$1<div class="feedback-buttons-inline">${feedbackHtml}</div>${aiEvaluateSingleBtn}$2`
            );
            finalFeedbackHtml = ''; // Artık dışarıda ayrı buton yok
        }

        // 🆕 v2.52.1: İlgisiz sonuç — "Vyra ile Sohbet Et" butonu
        const noRelevantResult = message.metadata?.no_relevant_result === true;
        const llmChatBtn = noRelevantResult ? `
            <div class="vyra-corpix-container">
                <button class="vyra-corpix-btn" onclick="DialogChatModule.switchToLlmMode()">
                    <i class="fa-solid fa-comments"></i> ${_appName()} ile Sohbet Et
                </button>
            </div>
        ` : '';

        const messageId = message.id || '';
        const html = `
            <div class="message-row assistant" data-message-id="${messageId}">
                <div class="message-header-row">
                    <div class="message-avatar vyra">${_appInitial()}</div>
                    <span class="message-sender-name">${_appName()}</span>
                    <span class="message-time">${time}</span>
                </div>
                <div class="message-bubble assistant">
                    <div class="message-content">${cleanedContent}</div>
                    ${quickReplyHtml}
                    ${enhanceBtn}
                    ${llmChatBtn}
                    ${finalFeedbackHtml}
                    ${askMoreHtml}
                    <div class="message-meta">
                        ${ragScoreHtml}
                        ${responseTimeHtml}
                    </div>
                </div>
            </div>
        `;

        container.insertAdjacentHTML('beforeend', html);
        if (scroll) scrollToBottom();

        // 🎯 Sohbet tamamlandıysa + butonunu vurgula
        if (message.content && message.content.includes('İyi günler dilerim')) {
            highlightNewDialogButton();
        }

        // 📝 Input durumunu güncelle (kartlar varsa disable olacak)
        updateSendButtonState();
    }

    // =============================================================================
    // NEW DIALOG BUTTON HIGHLIGHT
    // =============================================================================

    function highlightNewDialogButton() {
        const btn = document.getElementById('dialogNewBtn');
        if (btn && !btn.classList.contains('highlight')) {
            btn.classList.add('highlight');
            btn.classList.remove('chat-active'); // Animasyonu tekrar başlat
            console.log('[DialogChat] + butonu vurgulandı - yeni soru için hazır');
        }
    }

    function resetNewDialogButtonHighlight() {
        const btn = document.getElementById('dialogNewBtn');
        if (btn) {
            btn.classList.remove('highlight');
            btn.classList.remove('chat-active'); // Yeni dialog başladı, animasyon tekrar başlasın
            console.log('[DialogChat] + butonu animasyonu resetlendi');
        }
    }

    function stopNewDialogButtonAnimation() {
        const btn = document.getElementById('dialogNewBtn');
        if (btn) {
            btn.classList.add('chat-active');
            btn.classList.remove('highlight');
        }
    }

    function addSystemMessage(content, extraClass = '') {
        const container = document.getElementById('dialogMessages');
        if (!container) return;

        const rowClass = `message-row assistant${extraClass ? ' ' + extraClass : ''}`;
        const html = `
            <div class="${rowClass}">
                <div class="message-header-row">
                    <div class="message-avatar vyra">${_appInitial()}</div>
                    <span class="message-sender-name">${_appName()}</span>
                </div>
                <div class="message-bubble assistant">
                    <div class="message-content">${content}</div>
                </div>
            </div>
        `;

        container.insertAdjacentHTML('beforeend', html);
        scrollToBottom();
    }

    // v3.19.3: Mod değişim sistem mesajlarının üst üste birikmesini engelle.
    // Önceki mode-info satırlarını temizle, sonra yenisini ekle.
    function addModeInfoMessage(content) {
        const container = document.getElementById('dialogMessages');
        if (container) {
            container.querySelectorAll('.mode-info-msg').forEach(el => el.remove());
        }
        addSystemMessage(content, 'mode-info-msg');
    }

    function clearMessages() {
        const container = document.getElementById('dialogMessages');
        if (container) container.innerHTML = '';
    }

    function showTypingIndicator() {
        const container = document.getElementById('dialogMessages');
        if (!container) return;

        const existing = container.querySelector('.typing-row');
        if (existing) return;

        const html = `
            <div class="message-row assistant typing-row">
                <div class="message-header-row">
                    <div class="message-avatar vyra">${_appInitial()}</div>
                    <span class="message-sender-name">${_appName()}</span>
                </div>
                <div class="typing-indicator">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            </div>
        `;

        container.insertAdjacentHTML('beforeend', html);
        scrollToBottom();
    }

    function hideTypingIndicator() {
        const indicator = document.querySelector('.typing-row');
        if (indicator) indicator.remove();
    }
    // =========================================================================
    // VOICE/TTS → dialog_voice.js modülüne taşındı (v2.30.1)
    // Delegation: window.DialogVoiceModule
    // =========================================================================

    function initSpeechRecognition() {
        if (window.DialogVoiceModule) window.DialogVoiceModule.initSpeechRecognition();
    }
    function toggleVoiceRecording() {
        if (window.DialogVoiceModule) window.DialogVoiceModule.toggleVoiceRecording();
    }
    function speakMessage(messageId, btn) {
        if (window.DialogVoiceModule) window.DialogVoiceModule.speakMessage(messageId, btn);
    }
    function speakText(text, btn) {
        if (window.DialogVoiceModule) window.DialogVoiceModule.speakText(text, btn);
    }

    // =========================================================================
    // IMAGE HANDLING → dialog_images.js modülüne taşındı (v2.30.1)
    // Delegation: window.DialogImagesModule
    // =========================================================================

    function handlePaste(e) {
        if (window.DialogImagesModule) window.DialogImagesModule.handlePaste(e);
    }
    function handleFileSelect(e) {
        if (window.DialogImagesModule) window.DialogImagesModule.handleFileSelect(e);
    }
    function clearPendingImages() {
        pendingImages = [];
        if (window.DialogImagesModule) window.DialogImagesModule.clearPendingImages();
    }
    function renderImagePreviews() {
        if (window.DialogImagesModule) window.DialogImagesModule.renderImagePreviews();
    }
    function removeImage(index) {
        if (window.DialogImagesModule) window.DialogImagesModule.removeImage(index);
    }


    // =============================================================================
    // IMAGE SYNC (dialog_images.js ile state senkronizasyonu)
    // =============================================================================

    function _syncPendingImages(images) {
        pendingImages = images;
        updateSendButtonState();
    }

    // =============================================================================
    // UTILITIES
    // =============================================================================

    function updateSendButtonState() {
        const input = document.getElementById('dialogInput');
        const sendBtn = document.getElementById('dialogSendBtn');
        const newDialogBtn = document.getElementById('dialogNewBtn');

        if (sendBtn) {
            const hasContent = input?.value?.trim().length > 0 || pendingImages.length > 0;

            // 🔧 v2.21.3: Textarea artık her zaman aktif
            // Kullanıcı seçenek kartları gösterilirken bile yeni soru yazabilir
            sendBtn.disabled = !hasContent;

            // Textarea her zaman enabled
            if (input) {
                input.disabled = false;
                input.placeholder = 'Mesajınızı yazın...';
            }
        }

        // "VYRA'ya sor +" butonunu kontrol et
        // Dialog sekmesi açıkken ve boş/yeni dialog durumundayken disable
        if (newDialogBtn) {
            const container = document.getElementById('dialogMessages');
            const isEmptyState = container?.querySelector('.dialog-empty-state');
            const hasNoMessages = container && container.children.length === 0;
            const hasOnlySystemMsg = container &&
                container.children.length === 1 &&
                container.innerHTML.includes('yeni soru sorabilirsiniz');

            // Boş durum veya sadece karşılama mesajı varsa butonu pasif yap
            const shouldDisableNewBtn = isEmptyState || hasNoMessages || hasOnlySystemMsg;
            newDialogBtn.disabled = shouldDisableNewBtn;

            // Görsel stil ve animasyon
            if (shouldDisableNewBtn) {
                newDialogBtn.style.opacity = '0.5';
                newDialogBtn.style.cursor = 'not-allowed';
                newDialogBtn.style.animation = 'none';  // Yanıp sönmeyi durdur
            } else {
                newDialogBtn.style.opacity = '1';
                newDialogBtn.style.cursor = 'pointer';
                newDialogBtn.style.animation = '';  // CSS'ten animasyonu geri al
            }
        }
    }

    function autoResizeTextarea(textarea) {
        if (!textarea) return;

        // Reset height to calculate new scrollHeight
        textarea.style.height = 'auto';

        // Max height: 150px (yaklaşık 6 satır)
        const maxHeight = 150;
        const newHeight = Math.min(textarea.scrollHeight, maxHeight);

        textarea.style.height = newHeight + 'px';

        // Max height'a ulaşıldıysa scroll aktif, değilse gizli
        textarea.style.overflowY = textarea.scrollHeight > maxHeight ? 'auto' : 'hidden';
    }

    function resetTextareaHeight() {
        const textarea = document.getElementById('dialogInput');
        if (textarea) {
            textarea.style.height = 'auto';
            textarea.style.overflowY = 'hidden';
        }
    }

    function scrollToBottom() {
        const container = document.getElementById('dialogMessages');
        if (container) {
            container.scrollTop = container.scrollHeight;
        }
    }

    // formatTime, formatMessageContent, escapeHtml, getUserInitial,
    // showToast, getFileTypeIcon → DialogChatUtils'e taşındı (dialog_chat_utils.js)

    /**
     * Response time'ı backend'e kaydet
     */
    async function saveResponseTime(messageId, responseTime) {
        if (!messageId || !currentDialogId) return;

        try {
            const token = localStorage.getItem('access_token');
            await fetch(`${API_BASE}/dialogs/${currentDialogId}/response-time`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    message_id: messageId,
                    response_time: responseTime
                })
            });
        } catch (error) {
            console.warn('[DialogChat] Response time kaydedilemedi:', error);
        }
    }

    // =============================================================================
    // WEBSOCKET INTEGRATION (v2.15.0)
    // =============================================================================

    /**
     * WebSocket'ten gelen mesajı UI'a ekle.
     * websocket_client.js tarafından çağrılır.
     * 
     * Duplicate kontrolü: Aynı mesaj ID'si zaten eklenmişse tekrar eklenmez.
     */
    function addMessageFromWS(message, quickReply = null) {
        console.log('[DialogChat] WebSocket mesajı alındı, message_id:', message?.id, 'lastAdded:', lastAddedMessageId);

        // Duplicate kontrolü 1: Son eklenen mesaj ile aynı mı?
        if (message?.id && message.id === lastAddedMessageId) {
            console.log('[DialogChat] WebSocket duplicate: lastAddedMessageId ile aynı, atlanıyor');
            return;
        }

        // Duplicate kontrolü 2: DOM'da zaten var mı?
        if (message?.id) {
            const existingMessage = document.querySelector(`[data-message-id="${message.id}"]`);
            if (existingMessage) {
                console.log('[DialogChat] WebSocket duplicate: DOM\'da zaten var, atlanıyor');
                return;
            }
        }

        // Typing indicator'ı kapat
        hideTypingIndicator();

        // Mesajı ekle
        addAssistantMessage(message, quickReply, true);

        // Browser notification (kullanıcı başka sekmede veya menüdeyse)
        if (document.hidden || !isDialogSectionVisible()) {
            showToast('info', '🤖 ' + _appName() + ' yanıtladı! Dialog sekmesine bakın.');
        }
    }

    /**
     * Dialog section görünür mü kontrol et.
     */
    function isDialogSectionVisible() {
        const dialogSection = document.getElementById('sectionDialog');
        return dialogSection && !dialogSection.classList.contains('hidden');
    }

    /**
     * Dosya indirme - auth token ile fetch yaparak indirme.
     * Tarayıcı doğrudan URL açamaz çünkü backend auth gerektiriyor.
     * @param {string} url - Download URL (/api/rag/download/filename)
     * @param {string} fileName - Dosya adı (görüntüleme için)
     */
    async function downloadFile(url, fileName) {
        try {
            // Loading göster
            showToast('Dosya indiriliyor...', 'info');

            // Auth token ile fetch yap
            const token = localStorage.getItem('access_token');
            const response = await fetch(`${window.API_BASE_URL || 'http://localhost:8002'}${url}`, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (!response.ok) {
                if (response.status === 401) {
                    showToast('Oturum süresi dolmuş, lütfen yeniden giriş yapın', 'error');
                    return;
                }
                if (response.status === 404) {
                    showToast('Dosya bulunamadı', 'error');
                    return;
                }
                throw new Error(`HTTP ${response.status}`);
            }

            // Blob olarak al
            const blob = await response.blob();

            // Blob'u indirme linki olarak sun
            const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = downloadUrl;
            a.download = fileName || 'document';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(downloadUrl);

            showToast('Dosya indirildi!', 'success');

        } catch (error) {
            console.error('[DialogChat] Download error:', error);
            showToast('Dosya indirme hatası: ' + error.message, 'error');
        }
    }
    // =========================================================================
    // TICKET/LLM → dialog_ticket.js modülüne taşındı (v2.30.1)
    // Delegation: window.DialogTicketModule
    // =========================================================================

    function bindTicketModalEvents() {
        if (window.DialogTicketModule) window.DialogTicketModule.bindTicketModalEvents();
    }
    function handleOpenTicketSummary() {
        if (window.DialogTicketModule) window.DialogTicketModule.handleOpenTicketSummary();
    }
    function sendCorpixMessage(content) {
        if (window.DialogTicketModule) return window.DialogTicketModule.sendCorpixMessage(content);
    }
    function handleCorpixAction(action, query) {
        if (window.DialogTicketModule) window.DialogTicketModule.handleCorpixAction(action, query);
    }
    function updateChatModeUI() {
        if (window.DialogTicketModule) window.DialogTicketModule.updateChatModeUI();
    }
    function updateHeaderModeBtn() {
        if (window.DialogTicketModule) window.DialogTicketModule.updateHeaderModeBtn();
    }

    // =============================================================================
    // 🆕 v2.51.0: VYRA ÖNERİSİ — CatBoost bypass cevabını LLM ile iyileştir
    // =============================================================================

    async function handleEnhance(btnElement) {
        const messageId = parseInt(btnElement.dataset.messageId);
        const query = btnElement.dataset.query;
        const container = document.getElementById(`enhance-container-${messageId}`);
        if (!container) return;

        // Button → spinner
        container.innerHTML = `
            <div class="vyra-enhance-loading">
                <i class="fa-solid fa-spinner fa-spin"></i> ${_appName()} düşünüyor...
            </div>
        `;

        try {
            const dialogId = currentDialogId;
            if (!dialogId) {
                container.innerHTML = '<span class="vyra-enhance-error">Dialog bulunamadı</span>';
                return;
            }

            const response = await fetch(`${window.API_BASE_URL || 'http://localhost:8002'}/api/dialogs/${dialogId}/messages/enhance`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`
                },
                body: JSON.stringify({ query: query, message_id: messageId })
            });

            const data = await response.json();

            if (data.success && data.content) {
                // Mesaj içeriğini güncelle
                const msgRow = document.querySelector(`.message-row[data-message-id="${messageId}"]`);
                if (msgRow) {
                    const contentEl = msgRow.querySelector('.message-content');
                    if (contentEl) {
                        let enhancedHtml = formatMessageContent(data.content);
                        
                        // v3.4.1: Görselleri koru — backend'den gelen image_ids veya mevcut görseller
                        const imageIds = data.image_ids || [];
                        if (imageIds.length > 0) {
                            const apiBase = window.API_BASE_URL || 'http://localhost:8002';
                            const imgTags = imageIds.map(imgId =>
                                `<img class="rag-inline-image" src="${apiBase}/api/rag/images/${imgId}" alt="Doküman görseli" data-image-id="${imgId}" loading="lazy" />`
                            ).join(' ');
                            enhancedHtml += `
                                <div class="thread-images-section">
                                    <div class="dt-section-label dt-section-info">
                                        <span class="dt-section-icon">📷</span>
                                        <span class="dt-section-title">İlgili Görseller</span>
                                    </div>
                                    <div class="dt-image-container">${imgTags}</div>
                                </div>
                            `;
                        } else {
                            // Fallback: mevcut mesajdaki görselleri kurtar
                            const existingImages = contentEl.querySelector('.thread-images-section, .rag-inline-image');
                            if (existingImages) {
                                const imgSection = contentEl.querySelector('.thread-images-section');
                                if (imgSection) {
                                    enhancedHtml += imgSection.outerHTML;
                                }
                            }
                        }
                        
                        contentEl.innerHTML = enhancedHtml;
                    }
                }
                // Butonu kaldır
                container.innerHTML = `
                    <div class="vyra-enhance-success">
                        <i class="fa-solid fa-check"></i> ${_appName()} önerisi uygulandı 
                        <span class="enhance-time">(${(data.elapsed_ms / 1000).toFixed(1)}s)</span>
                    </div>
                `;
                // 3 saniye sonra kaldır
                setTimeout(() => container.remove(), 3000);
            } else {
                container.innerHTML = `
                    <div class="vyra-enhance-error">
                        <i class="fa-solid fa-exclamation-triangle"></i> ${data.error || 'İyileştirilemedi'}
                    </div>
                `;
            }
        } catch (err) {
            console.error('[DialogChat] Enhance hatası:', err);
            container.innerHTML = '<span class="vyra-enhance-error">Bağlantı hatası</span>';
        }
    }

    // =============================================================================
    // PUBLIC API
    // =============================================================================

    return {
        init,
        handleQuickReply,
        sendFeedback,
        showOtherCategories,
        removeImage,
        startNewDialog,
        speakText,
        speakMessage,
        toggleCardSelection,
        toggleSelectAll,
        handleMultiSelect,
        // WebSocket entegrasyon fonksiyonları
        addMessageFromWS,
        showTypingIndicator,
        hideTypingIndicator,
        // Rendering (child modüller için)
        addAssistantMessage,
        addSystemMessage,
        // Duplicate önleme
        isWaitingForResponse: () => isWaitingForResponse,
        // Dosya indirme
        downloadFile,
        deactivate,
        // v3.6.0: LLM fallback (delegation → DialogTicketModule)
        handleLlmAction: function(action, query) {
            return window.DialogTicketModule?.handleLlmAction(action, query);
        },
        // v2.24.6: Notification'dan dialog yükleme
        loadDialogById,
        // v2.51.0: Vyra önerisi
        handleEnhance,
        // v3.6.0: Chat mode yönetimi (rag / db / llm)
        getChatMode: () => chatMode,
        setChatMode: (mode) => {
            if (mode === 'rag' || mode === 'db' || mode === 'llm') {
                chatMode = mode;
                updateChatModeUI();
                console.log(`[DialogChat] Mod değişti: ${mode}`);
            }
        },
        switchToLlmMode: () => {
            // v3.16.0: DB→başka moda geçişte follow-up anchor'ı temizle
            if (pendingFollowupAnchorId) { pendingFollowupAnchorId = null; _hideFollowupIndicator(); }
            chatMode = 'llm';
            updateChatModeUI();
            updateHeaderModeBtn();
            const mkb = document.getElementById('modeKb');
            const mdb = document.getElementById('modeDb');
            const mch = document.getElementById('modeChat');
            if (mkb) mkb.classList.remove('selected');
            if (mdb) mdb.classList.remove('selected');
            if (mch) mch.classList.add('selected');
            showToast('info', '💬 ' + _appName() + ' sohbet modu aktif');
            addModeInfoMessage('💬 ' + _appName() + ' ile sohbet moduna geçildi.');
        },
        switchToRagMode: () => {
            // v3.16.0: DB→başka moda geçişte follow-up anchor'ı temizle
            if (pendingFollowupAnchorId) { pendingFollowupAnchorId = null; _hideFollowupIndicator(); }
            chatMode = 'rag';
            updateChatModeUI();
            updateHeaderModeBtn();
            const mkb = document.getElementById('modeKb');
            const mdb = document.getElementById('modeDb');
            const mch = document.getElementById('modeChat');
            if (mkb) mkb.classList.add('selected');
            if (mdb) mdb.classList.remove('selected');
            if (mch) mch.classList.remove('selected');
            showToast('info', '📚 Bilgi tabanında arama modu aktif');
            addModeInfoMessage('📚 Bilgi tabanında arama modu aktif.');
        },
        switchToDbMode: () => {
            chatMode = 'db';
            updateChatModeUI();
            updateHeaderModeBtn();
            const mkb = document.getElementById('modeKb');
            const mdb = document.getElementById('modeDb');
            const mch = document.getElementById('modeChat');
            if (mkb) mkb.classList.remove('selected');
            if (mdb) mdb.classList.add('selected');
            if (mch) mch.classList.remove('selected');
            showToast('info', '🗄️ Veritabanında arama modu aktif');
            addModeInfoMessage('🗄️ Veritabanında arama moduna geçildi. Tablolardaki verilere doğrudan sorgu atabilirsiniz.');
        },
        toggleChatMode: () => {
            if (chatMode === 'rag') {
                DialogChatModule.switchToLlmMode();
            } else {
                DialogChatModule.switchToRagMode();
            }
        },
        // Internal accessors (child modüller için)
        _getDialogId: () => currentDialogId,
        _setDialogId: (id) => { currentDialogId = id; },
        _syncPendingImages
    };

})();

// =============================================================================
// v4.0: DB Export Handler (Global)
// =============================================================================
window.DBExportHandler = (function () {
    'use strict';

    const API_BASE = (window.API_BASE_URL || 'http://localhost:8002') + '/api';

    function _getData(barId) {
        return window[barId + '_data'] || null;
    }

    function _getToken() {
        return localStorage.getItem('access_token') || '';
    }

    async function _doExport(barId, format) {
        const d = _getData(barId);
        if (!d) { console.warn('[DBExport] Veri bulunamadı:', barId); return; }

        const endpoint = `${API_BASE}/db/export/${format}`;
        const body = {
            columns: d.columns,
            rows: d.rows,
            title: d.title || 'VYRA Sorgu Sonucu',
            query: d.query || '',
            sql: d.sql || '',
            include_narrative: format !== 'excel',
        };

        try {
            const btn = document.querySelector(`#${barId} .db-export-btn.${format}`);
            if (btn) { btn.disabled = true; btn.textContent = '⏳'; }

            const resp = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${_getToken()}`,
                },
                body: JSON.stringify(body),
            });

            if (!resp.ok) {
                const err = await resp.text();
                throw new Error(`Export hatası: ${resp.status} — ${err}`);
            }

            // Dosyayı indir
            const blob = await resp.blob();
            const ext = format === 'excel' ? 'xlsx' : format === 'word' ? 'docx' : 'pdf';
            const filename = (d.title || 'vyra_export').replace(/[^\w\s-]/g, '').trim().replace(/\s+/g, '_') + `_${Date.now()}.${ext}`;
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 2000);

        } catch (e) {
            console.error('[DBExport]', e);
            if (window.DialogChatUtils?.showToast) {
                window.DialogChatUtils.showToast('error', '❌ Export başarısız: ' + e.message);
            }
        } finally {
            const btn = document.querySelector(`#${barId} .db-export-btn.${format}`);
            if (btn) {
                btn.disabled = false;
                const labels = { excel: '<i class="fa-solid fa-file-excel"></i> Excel', word: '<i class="fa-solid fa-file-word"></i> Word', pdf: '<i class="fa-solid fa-file-pdf"></i> PDF' };
                btn.innerHTML = labels[format] || format;
            }
        }
    }

    function copyCSV(barId) {
        const d = _getData(barId);
        if (!d || !d.rows?.length) return;
        const header = d.columns.join('\t');
        const body = d.rows.map(r => d.columns.map(c => String(r[c] ?? '')).join('\t')).join('\n');
        const csv = header + '\n' + body;
        navigator.clipboard.writeText(csv).then(() => {
            if (window.DialogChatUtils?.showToast) {
                window.DialogChatUtils.showToast('success', '✅ Veri panoya kopyalandı (sekme ayrımlı)');
            }
        }).catch(e => {
            console.error('[DBExport] Kopyalama hatası:', e);
        });
    }

    return {
        excel: (barId) => _doExport(barId, 'excel'),
        word:  (barId) => _doExport(barId, 'word'),
        pdf:   (barId) => _doExport(barId, 'pdf'),
        copyCSV,
    };
})();

// Auto-init when DOM ready
document.addEventListener('DOMContentLoaded', () => {
    // Dialog sekmesi aktif olduğunda init edilecek
    console.log('[DialogChat] Modül yüklendi');
});
