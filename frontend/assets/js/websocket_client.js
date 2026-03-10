/**
 * NGSSAI - WebSocket Client Module
 * ==========================================
 * Asenkron işlem sonuçları için WebSocket bağlantı yönetimi.
 */

(function () {
    'use strict';

    // --- CONFIGURATION ---
    const WS_BASE_URL = window.WS_BASE_URL || 'ws://localhost:8002/api/ws';
    const RECONNECT_DELAY_MS = 3000;
    const MAX_RECONNECT_ATTEMPTS = 5;
    const HEARTBEAT_INTERVAL_MS = 30000;

    // --- STATE ---
    let socket = null;
    let reconnectAttempts = 0;
    let heartbeatTimer = null;
    let isConnecting = false;
    let pendingTasks = new Map(); // task_id -> callback

    // --- CORE FUNCTIONS ---

    function getToken() {
        return localStorage.getItem('access_token');
    }

    function connect() {
        if (isConnecting || (socket && socket.readyState === WebSocket.OPEN)) {
            console.log('[NGSSAI-WS] Zaten bağlı veya bağlanıyor...');
            return;
        }

        const token = getToken();
        if (!token) {
            console.warn('[NGSSAI-WS] Token yok, WebSocket bağlantısı yapılamaz');
            return;
        }

        isConnecting = true;
        const wsUrl = `${WS_BASE_URL}?token=${encodeURIComponent(token)}`;

        console.log('[NGSSAI-WS] Bağlanıyor...');

        try {
            socket = new WebSocket(wsUrl);

            socket.onopen = function () {
                console.log('[NGSSAI-WS] ✅ Bağlantı kuruldu');
                isConnecting = false;
                reconnectAttempts = 0;
                startHeartbeat();

                // UI durum güncelle
                updateConnectionStatus(true);

                // Bekleyen görevleri sorgula
                requestPendingTasks();
            };

            socket.onmessage = function (event) {
                try {
                    const data = JSON.parse(event.data);
                    handleMessage(data);
                } catch (err) {
                    console.error('[NGSSAI-WS] Mesaj parse hatası:', err);
                }
            };

            socket.onclose = function (event) {
                console.log('[NGSSAI-WS] Bağlantı kapandı:', event.code, event.reason);
                isConnecting = false;
                stopHeartbeat();
                updateConnectionStatus(false);
                scheduleReconnect();
            };

            socket.onerror = function (error) {
                console.error('[NGSSAI-WS] Hata:', error);
                isConnecting = false;
            };

        } catch (err) {
            console.error('[NGSSAI-WS] Bağlantı hatası:', err);
            isConnecting = false;
            scheduleReconnect();
        }
    }

    function disconnect() {
        stopHeartbeat();
        if (socket) {
            socket.close();
            socket = null;
        }
        reconnectAttempts = 0;
    }

    function scheduleReconnect() {
        if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
            console.warn('[NGSSAI-WS] Maksimum yeniden bağlanma denemesi aşıldı');
            return;
        }

        reconnectAttempts++;
        const delay = RECONNECT_DELAY_MS * reconnectAttempts;
        console.log(`[NGSSAI-WS] ${delay}ms sonra yeniden bağlanılacak (deneme ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})`);

        setTimeout(() => {
            if (!socket || socket.readyState === WebSocket.CLOSED) {
                connect();
            }
        }, delay);
    }

    function startHeartbeat() {
        stopHeartbeat();
        heartbeatTimer = setInterval(() => {
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ type: 'ping' }));
            }
        }, HEARTBEAT_INTERVAL_MS);
    }

    function stopHeartbeat() {
        if (heartbeatTimer) {
            clearInterval(heartbeatTimer);
            heartbeatTimer = null;
        }
    }

    function updateConnectionStatus(isConnected) {
        const statusEl = document.getElementById('wsConnectionStatus');
        if (!statusEl) return;

        const dotEl = statusEl.querySelector('.status-dot');
        const textEl = statusEl.querySelector('.status-text');

        if (isConnected) {
            statusEl.classList.remove('offline');
            statusEl.classList.add('online');
            if (dotEl) dotEl.style.background = '#10b981';
            if (textEl) textEl.textContent = 'Çevrimiçi';
        } else {
            statusEl.classList.remove('online');
            statusEl.classList.add('offline');
            if (dotEl) dotEl.style.background = '#ef4444';
            if (textEl) textEl.textContent = 'Çevrimdışı';
        }
    }

    function send(message) {
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify(message));
            return true;
        }
        console.warn('[NGSSAI-WS] Mesaj gönderilemedi, bağlantı yok');
        return false;
    }

    function requestPendingTasks() {
        send({ type: 'get_pending_tasks' });
    }

    // --- MESSAGE HANDLERS ---

    function handleMessage(data) {
        console.log('[NGSSAI-WS] Mesaj alındı:', data.type);

        switch (data.type) {
            case 'connected':
                console.log('[NGSSAI-WS] Sunucu bağlantı onayı:', data.message);
                break;

            case 'pong':
                // Heartbeat yanıtı, sessizce geç
                break;

            case 'task_complete':
                handleTaskComplete(data);
                break;

            case 'task_failed':
                handleTaskFailed(data);
                break;

            case 'task_status':
                handleTaskStatus(data);
                break;

            case 'pending_tasks':
                handlePendingTasks(data);
                break;

            // === DIALOG MESAJ TİPLERİ (v2.15.0) ===
            case 'dialog_message':
                handleDialogMessage(data);
                break;

            case 'dialog_typing':
                handleDialogTyping(data);
                break;

            // === RAG UPLOAD BİLDİRİMLERİ (v2.39.0) ===
            case 'rag_upload_complete':
                handleRagUploadComplete(data);
                break;

            case 'rag_upload_failed':
                handleRagUploadFailed(data);
                break;

            case 'error':
                console.error('[NGSSAI-WS] Sunucu hatası:', data.message);
                break;

            default:
                console.log('[NGSSAI-WS] Bilinmeyen mesaj tipi:', data.type);
        }
    }

    function handleTaskComplete(data) {
        const { task_id, result } = data;
        console.log('[NGSSAI-WS] ✅ Görev tamamlandı:', task_id);

        // Callback varsa çağır
        const callback = pendingTasks.get(task_id);
        if (callback) {
            callback(null, result);
            pendingTasks.delete(task_id);
        }

        // Global event dispatch
        window.dispatchEvent(new CustomEvent('vyra:task_complete', {
            detail: { task_id, result }
        }));

        // Toast bildirimi
        if (typeof VyraToast !== 'undefined') {
            VyraToast.success('Çözüm önerisi hazır!');
        }

        // 🔔 Browser notification (kullanıcı başka sekmede/browserdayse)
        showTicketNotification(result);

        // Sonucu göster
        showSolutionResult(result);
    }

    /**
     * v2.24.0: NGSSAI'ye Sor için browser notification göster
     * Tıklandığında dialog sekmesine yönlendirir
     */
    function showTicketNotification(result) {
        const title = '✅ Çözüm Önerisi Hazır!';
        const body = result?.final_solution?.substring(0, 100) || 'Çözüm öneriniz hazırlandı';

        // 1️⃣ Her durumda NgssNotification ile in-app bildirim göster
        if (typeof NgssNotification !== 'undefined') {
            NgssNotification.add('success', title, body);
        }

        // 2️⃣ Sayfa gizliyse browser notification da göster
        if (document.hidden && 'Notification' in window && Notification.permission === 'granted') {
            const notification = new Notification(title, {
                body: body,
                icon: '/assets/images/vyra_logo.png',
                tag: 'vyra-ticket-response',
                requireInteraction: true
            });

            notification.onclick = () => {
                // Pencereyi öne getir
                window.focus();

                // v2.24.0: NGSSAI'ye Sor (Dialog) sekmesine git
                const dialogTab = document.getElementById('tabDialog');
                if (dialogTab) {
                    dialogTab.click();
                }

                notification.close();
            };

            // 10 saniye sonra otomatik kapat
            setTimeout(() => notification.close(), 10000);
        }
    }

    function handleTaskFailed(data) {
        const { task_id, error } = data;
        console.error('[NGSSAI-WS] ❌ Görev başarısız:', task_id, error);

        // Callback varsa çağır
        const callback = pendingTasks.get(task_id);
        if (callback) {
            callback(error, null);
            pendingTasks.delete(task_id);
        }

        // Global event dispatch
        window.dispatchEvent(new CustomEvent('vyra:task_failed', {
            detail: { task_id, error }
        }));

        // 🌐 VPN/Network hatası kontrolü
        if (window.isVPNNetworkError && window.isVPNNetworkError(error)) {
            window.showVPNErrorPopup();
        } else if (typeof VyraToast !== 'undefined') {
            VyraToast.error('Çözüm hazırlanamadı: ' + (error || 'Bilinmeyen hata'));
        }
    }

    function handleTaskStatus(data) {
        console.log('[NGSSAI-WS] Görev durumu:', data.task_id, data.status);
    }

    function handlePendingTasks(data) {
        const tasks = data.tasks || [];
        console.log('[NGSSAI-WS] Bekleyen görevler:', tasks.length);

        // Bekleyen görev varsa bildir
        if (tasks.length > 0) {
            tasks.forEach(task => {
                if (typeof VyraToast !== 'undefined') {
                    VyraToast.info(`Bekleyen görev: ${task.progress_message}`);
                }
            });
        }
    }

    // === DIALOG MESSAGE HANDLERS (v2.15.0) ===

    function handleDialogMessage(data) {
        const message = data.message;
        const quickReply = data.quick_reply;
        const dialogId = data.dialog_id;

        console.log('[NGSSAI-WS] 💬 Dialog mesajı alındı:', dialogId);

        // Duplicate önleme: Eğer DialogChatModule HTTP response bekliyorsa, mesajı ekleme
        // (HTTP response zaten ekleyecek)
        const isWaiting = window.DialogChatModule?.isWaitingForResponse?.();
        if (isWaiting) {
            console.log('[NGSSAI-WS] HTTP response bekleniyor, WebSocket mesajı atlanıyor (duplicate önleme)');
            // Ama notification ekle (kullanıcı başka sekmede olabilir)
        } else {
            // DialogChatModule varsa mesajı ekle
            if (window.DialogChatModule && typeof DialogChatModule.addMessageFromWS === 'function') {
                DialogChatModule.addMessageFromWS(message, quickReply);
            }
        }

        // Notification Center'a bildirim ekle (tıklayınca dialog sekmesine gider)
        if (typeof NgssNotification !== 'undefined') {
            const msgPreview = message?.content?.substring(0, 80) || 'Yeni yanıt hazır';
            // v2.24.6: dialogId parametresi eklendi
            NgssNotification.add('success', '🤖 NGSSAI Yanıtladı', msgPreview, dialogId);
        }

        // Browser notification göster (kullanıcı başka sekmede/browserdayse)
        if (document.hidden) {
            showDialogNotification(message);
        }

        // Global event dispatch
        window.dispatchEvent(new CustomEvent('vyra:dialog_message', {
            detail: { dialog_id: dialogId, message, quick_reply: quickReply }
        }));
    }

    function handleDialogTyping(data) {
        const isTyping = data.is_typing;

        // DialogChatModule varsa typing indicator göster/gizle
        if (window.DialogChatModule) {
            if (isTyping && typeof DialogChatModule.showTypingIndicator === 'function') {
                DialogChatModule.showTypingIndicator();
            } else if (!isTyping && typeof DialogChatModule.hideTypingIndicator === 'function') {
                DialogChatModule.hideTypingIndicator();
            }
        }
    }

    function showDialogNotification(message) {
        // Browser notification izni kontrolü
        if (!('Notification' in window) || Notification.permission !== 'granted') {
            return;
        }

        const title = '🤖 NGSSAI Yanıtladı';
        const body = message?.content?.substring(0, 100) || 'Yeni yanıt hazır';

        const notification = new Notification(title, {
            body: body,
            icon: '/assets/images/vyra_logo.png',
            tag: 'vyra-dialog-response',
            requireInteraction: true
        });

        notification.onclick = () => {
            // Pencereyi öne getir
            window.focus();

            // NGSSAI'ye Sor sekmesine git
            const dialogTab = document.getElementById('tabDialog');
            if (dialogTab) {
                dialogTab.click();
            }

            notification.close();
        };

        // 10 saniye sonra otomatik kapat
        setTimeout(() => notification.close(), 10000);
    }

    // === RAG UPLOAD HANDLERS (v2.39.0) ===

    /**
     * v2.39.0: RAG dosya yükleme tamamlandı bildirimi
     * WebSocket üzerinden gelen mesajı işler.
     */
    function handleRagUploadComplete(data) {
        const fileNames = data.file_names || [];
        const processedCount = data.processed_count || 0;
        const totalChunks = data.total_chunks || 0;
        const failedFiles = data.failed_files || [];

        console.log('[NGSSAI-WS] 📄 RAG upload tamamlandı:', processedCount, 'dosya,', totalChunks, 'chunk');

        // Dosya isimleri özeti
        const fileList = fileNames.length <= 3
            ? fileNames.join(', ')
            : `${fileNames.slice(0, 2).join(', ')} ve ${fileNames.length - 2} dosya daha`;

        // Kısmi hata varsa uyarı, yoksa başarı
        const hasWarning = failedFiles.length > 0;
        const title = hasWarning ? '⚠️ Dosya Yükleme Kısmi Başarı' : '📄 Dosya Yüklendi';
        const body = hasWarning
            ? `${processedCount}/${fileNames.length} dosya işlendi. Hata: ${failedFiles.join(', ')}`
            : `Bilgi tabanına eklendi: ${fileList} (${totalChunks} chunk)`;
        const notifType = hasWarning ? 'warning' : 'success';

        // 1️⃣ NgssNotification ile in-app bildirim (tıklanınca Bilgi Tabanı sekmesine gider)
        if (typeof NgssNotification !== 'undefined') {
            NgssNotification.add(notifType, title, body, null, 'rag');
        }

        // 2️⃣ Dosya listesini yenile (kullanıcı RAG ekranındaysa)
        if (window.RAGUpload && typeof RAGUpload.loadFiles === 'function') {
            RAGUpload.filesCurrentPage = 1;
            RAGUpload.loadFiles();
            RAGUpload.loadStats();
            console.log('[NGSSAI-WS] RAG dosya listesi yenilendi');
        }

        // 3️⃣ Browser notification (kullanıcı başka sekmede/browserdayse)
        if (document.hidden && 'Notification' in window && Notification.permission === 'granted') {
            const notification = new Notification(title, {
                body: body,
                icon: '/assets/images/vyra_logo.png',
                tag: 'vyra-rag-upload',
                requireInteraction: false
            });

            notification.onclick = () => {
                window.focus();
                // Bilgi Tabanı sekmesine git
                if (typeof NgssNotification !== 'undefined') {
                    NgssNotification.navigateToRag();
                }
                notification.close();
            };

            setTimeout(() => notification.close(), 10000);
        }

        // 4️⃣ Global event dispatch
        window.dispatchEvent(new CustomEvent('vyra:rag_upload_complete', {
            detail: { file_names: fileNames, processed_count: processedCount, total_chunks: totalChunks }
        }));
    }

    /**
     * v2.39.0: RAG dosya yükleme başarısız bildirimi
     */
    function handleRagUploadFailed(data) {
        const fileNames = data.file_names || [];
        const failedFiles = data.failed_files || fileNames;
        const message = data.message || 'Dosya işleme hatası';

        console.error('[NGSSAI-WS] ❌ RAG upload başarısız:', failedFiles);

        // NgssNotification ile hata bildirimi
        if (typeof NgssNotification !== 'undefined') {
            NgssNotification.add('error', '❌ Dosya İşleme Hatası', message, null, 'rag');
        }

        // Dosya listesini yenile (failed durumunu görmek için)
        if (window.RAGUpload && typeof RAGUpload.loadFiles === 'function') {
            RAGUpload.loadFiles();
        }

        // Global event dispatch
        window.dispatchEvent(new CustomEvent('vyra:rag_upload_failed', {
            detail: { file_names: fileNames, failed_files: failedFiles, message }
        }));
    }

    // --- UI HELPERS ---

    function showSolutionResult(result) {
        if (!result) return;

        const loadingBox = document.getElementById('loadingBox');
        const finalSolutionBox = document.getElementById('finalSolutionBox');

        // Loading'i gizle
        if (loadingBox) {
            loadingBox.classList.add('hidden');
        }

        // 🆕 v2.23.0: Artık RAG sonuçları + ticket_id döner
        // SolutionDisplayModule ile göster
        if (typeof window.SolutionDisplayModule !== 'undefined') {
            // ticket_id'yi sakla (AI değerlendirme için)
            window.currentTicketId = result.ticket_id;
            window.currentRagResults = result.rag_results || [];

            // RAG sonuçlarını göster
            window.SolutionDisplayModule.showRagResults(result);
        } else {
            // Fallback - eski davranış (basit gösterim)
            if (finalSolutionBox) {
                finalSolutionBox.classList.remove('hidden');
            }
            const solutionSteps = document.getElementById('solutionSteps');
            if (solutionSteps) {
                if (result.rag_results && result.rag_results.length > 0) {
                    solutionSteps.innerHTML = `<p class="text-yellow-400">🔍 ${result.rag_results.length} sonuç bulundu. Corpix ile değerlendirmek için butona tıklayın.</p>`;
                } else {
                    solutionSteps.innerHTML = `<p class="text-gray-400">Bilgi tabanında sonuç bulunamadı. Corpix ile değerlendirmek için butona tıklayın.</p>`;
                }
            }
        }

        // Ticket history'yi yenile
        if (typeof loadTicketHistory === 'function') {
            loadTicketHistory(true);
        }
    }

    // Fallback formatSolution - SolutionDisplayModule yoksa basit format
    function formatSolution(solution) {
        if (!solution) return '<p class="text-gray-500">Çözüm bilgisi yok</p>';
        // Basit fallback - modül yüklüyse zaten yukarıda kullanılıyor
        return `<p class="solution-text">${solution}</p>`;
    }

    // --- PUBLIC API ---

    /**
     * Asenkron ticket oluşturma isteği gönder
     */
    async function createTicketAsync(query, onComplete) {
        const token = getToken();
        if (!token) {
            throw new Error('Token bulunamadı');
        }

        // Loading göster
        const loadingBox = document.getElementById('loadingBox');
        const finalSolutionBox = document.getElementById('finalSolutionBox');

        if (loadingBox) loadingBox.classList.remove('hidden');
        if (finalSolutionBox) finalSolutionBox.classList.add('hidden');

        try {
            const response = await fetch(`${window.API_BASE_URL || 'http://localhost:8002'}/api/tickets/from-chat-async`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({ query })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'İstek başarısız');
            }

            const data = await response.json();
            console.log('[NGSSAI-WS] Görev oluşturuldu:', data.task_id);

            // Callback'i kaydet
            if (onComplete) {
                pendingTasks.set(data.task_id, onComplete);
            }

            // Toast bildirimi
            if (typeof VyraToast !== 'undefined') {
                VyraToast.info('Çözüm önerisi hazırlanıyor...');
            }

            return data;

        } catch (err) {
            console.error('[NGSSAI-WS] Async ticket hatası:', err);
            if (loadingBox) loadingBox.classList.add('hidden');
            throw err;
        }
    }

    /**
     * RAG araması yap (LLM kullanmadan)
     * Seçenek A: NGSSAI'ye Sor gibi hızlı arama
     */
    async function searchRAG(query) {
        const token = getToken();
        if (!token) {
            throw new Error('Token bulunamadı');
        }

        // Loading göster
        const loadingBox = document.getElementById('loadingBox');
        const finalSolutionBox = document.getElementById('finalSolutionBox');
        const ragSelectionBox = document.getElementById('ragSelectionBox');

        if (loadingBox) loadingBox.classList.remove('hidden');
        if (finalSolutionBox) finalSolutionBox.classList.add('hidden');
        if (ragSelectionBox) ragSelectionBox.classList.add('hidden');

        try {
            const response = await fetch(`${window.API_BASE_URL || 'http://localhost:8002'}/api/tickets/search`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({ query })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Arama başarısız');
            }

            const data = await response.json();
            console.log('[NGSSAI-WS] RAG araması tamamlandı:', data.results?.length, 'sonuç');

            if (loadingBox) loadingBox.classList.add('hidden');

            return data;

        } catch (err) {
            console.error('[NGSSAI-WS] RAG arama hatası:', err);
            if (loadingBox) loadingBox.classList.add('hidden');
            throw err;
        }
    }

    /**
     * Seçilen RAG sonucundan ticket oluştur
     */
    async function createTicketFromSelection(query, chunkText, fileName) {
        const token = getToken();
        if (!token) {
            throw new Error('Token bulunamadı');
        }

        try {
            const response = await fetch(`${window.API_BASE_URL || 'http://localhost:8002'}/api/tickets/create-from-selection`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({
                    query: query,
                    selected_chunk_text: chunkText,
                    selected_file_name: fileName
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Ticket oluşturulamadı');
            }

            const data = await response.json();
            console.log('[NGSSAI-WS] Ticket oluşturuldu:', data.id);

            return data;

        } catch (err) {
            console.error('[NGSSAI-WS] Ticket oluşturma hatası:', err);
            throw err;
        }
    }

    /**
     * Seçilen sonucu LLM (Corpix) ile değerlendir
     * @param {string} query - Kullanıcı sorgusu
     * @param {string} context - Çözüm içeriği
     * @param {number|null} ticketId - Varsa değerlendirmeyi bu ticket'a kaydeder
     */
    async function evaluateWithLLM(query, context, ticketId = null) {
        const token = getToken();
        if (!token) {
            throw new Error('Token bulunamadı');
        }

        try {
            const requestBody = {
                query: query,
                context: context
            };

            // ticket_id varsa ekle
            if (ticketId) {
                requestBody.ticket_id = ticketId;
            }

            const response = await fetch(`${window.API_BASE_URL || 'http://localhost:8002'}/api/tickets/evaluate-with-llm`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify(requestBody)
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'LLM değerlendirmesi başarısız');
            }

            const data = await response.json();
            console.log('[NGSSAI-WS] LLM değerlendirmesi tamamlandı', ticketId ? `(Ticket #${ticketId}'e kaydedildi)` : '');

            return data;

        } catch (err) {
            console.error('[NGSSAI-WS] LLM değerlendirme hatası:', err);
            throw err;
        }
    }

    // --- INITIALIZATION ---

    function init() {
        // Sayfa yüklendiğinde bağlan
        if (getToken()) {
            connect();

            // 🔔 Browser notification izni iste (ilk seferde)
            if ('Notification' in window && Notification.permission === 'default') {
                Notification.requestPermission().then(permission => {
                    console.log('[NGSSAI-WS] Notification izni:', permission);
                });
            }
        }

        // Token değişikliklerini dinle
        window.addEventListener('storage', (e) => {
            if (e.key === 'access_token') {
                if (e.newValue) {
                    connect();
                } else {
                    disconnect();
                }
            }
        });

        // Sayfa kapanırken bağlantıyı kapat
        window.addEventListener('beforeunload', () => {
            disconnect();
        });
    }

    // --- EXPORT ---

    window.VyraWebSocket = {
        connect,
        disconnect,
        send,
        createTicketAsync,
        searchRAG,
        createTicketFromSelection,
        evaluateWithLLM,
        isConnected: () => socket && socket.readyState === WebSocket.OPEN
    };

    // Auto-init
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
