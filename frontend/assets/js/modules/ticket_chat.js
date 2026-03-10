/* -------------------------------
   VYRA - Ticket Chat Module
   Çözüm öner işlemi ve LLM entegrasyonu
-------------------------------- */

/**
 * TicketChat modülü - Çözüm öner butonu, WebSocket/API entegrasyonu
 * @module TicketChatModule
 */
window.TicketChatModule = (function () {
    'use strict';

    // State
    let isProcessingRequest = false;
    let solutionProvided = false;
    let requestStartTime = null;

    // DOM elementleri
    function getElements() {
        return {
            suggestBtn: document.getElementById("suggestBtn"),
            suggestTooltip: document.getElementById("suggestTooltip"),
            problemTextArea: document.getElementById("problemText"),
            loadingBox: document.getElementById("loadingBox"),
            keyboardHint: document.querySelector('.keyboard-hint'),
        };
    }

    // --- Buton durumu güncelle ---
    function updateButtonState() {
        const el = getElements();
        if (!el.problemTextArea || !el.suggestBtn) return;

        const hasText = el.problemTextArea.value.trim().length > 0;
        el.suggestBtn.disabled = !hasText && !solutionProvided;

        if (el.suggestTooltip) {
            el.suggestTooltip.style.display = hasText ? 'none' : 'block';
        }
    }

    // --- Progress element ---
    function createProgressElement() {
        const el = getElements();
        if (!el.loadingBox) return null;

        let progressEl = el.loadingBox.querySelector('.progress-text');
        if (!progressEl) {
            progressEl = document.createElement('p');
            progressEl.className = 'progress-text text-sm text-gray-400 mt-2';
            el.loadingBox.appendChild(progressEl);
        }
        return progressEl;
    }

    function updateProgress(progressEl, text) {
        if (progressEl) progressEl.textContent = text;
    }

    // --- Yeni soru moduna sıfırla (v2.24.0) ---
    function resetToNewRequest() {
        const el = getElements();

        // Textarea'yı temizle ve aktif et
        if (el.problemTextArea) {
            el.problemTextArea.value = "";
            el.problemTextArea.disabled = false;
            el.problemTextArea.focus();
        }

        // Görsel preview temizle
        const imagePreviewContainer = document.getElementById("imagePreviewContainer");
        const imagePreview = document.getElementById("imagePreview");
        const imageInput = document.getElementById("imageInput");
        const attachImageBtn = document.getElementById("attachImageBtn");
        if (imagePreviewContainer) imagePreviewContainer.classList.add("hidden");
        if (imagePreview) imagePreview.src = "";
        if (imageInput) imageInput.value = "";
        if (attachImageBtn) attachImageBtn.disabled = false;  // Attach butonu aktif

        // Çözüm kutusunu gizle
        if (window.SolutionDisplayModule) {
            window.SolutionDisplayModule.hide();
        }

        // CYM sıfırla
        const showCYM = document.getElementById("showCYM");
        const cymContent = document.getElementById("cymContent");
        if (showCYM) showCYM.checked = false;
        if (cymContent) cymContent.classList.add("hidden");

        // Buton'u eski haline döndür
        if (el.suggestBtn) {
            el.suggestBtn.innerHTML = "Çözüm Öner";
            el.suggestBtn.classList.remove("new-request-mode");
            el.suggestBtn.disabled = true;
        }

        solutionProvided = false;

        // Keyboard hint göster
        if (el.keyboardHint) el.keyboardHint.style.display = 'block';

        // Yanıt süresini sıfırla
        const responseTimeEl = document.getElementById("responseTime");
        if (responseTimeEl) responseTimeEl.textContent = "--";

        // Tooltip göster
        if (el.suggestTooltip) el.suggestTooltip.style.display = 'block';
    }

    // --- Çözüm sağlandı durumuna geç ---
    function setSolutionProvided() {
        const el = getElements();
        solutionProvided = true;

        if (el.suggestBtn) {
            el.suggestBtn.innerHTML = '<i class="fa-solid fa-plus"></i> Yeni Soru';
            el.suggestBtn.classList.add("new-request-mode");
            el.suggestBtn.disabled = false;
        }

        if (el.keyboardHint) el.keyboardHint.style.display = 'none';
        if (el.problemTextArea) el.problemTextArea.disabled = true;

        // Attach butonu pasif
        const attachImageBtn = document.getElementById("attachImageBtn");
        if (attachImageBtn) attachImageBtn.disabled = true;
    }

    // --- Async ticket sonucu işle ---
    function handleAsyncResult(result) {
        if (!result) return;

        const responseTime = ((performance.now() - requestStartTime) / 1000).toFixed(1);
        const el = getElements();
        const problem = el.problemTextArea ? el.problemTextArea.value : "";

        if (window.SolutionDisplayModule) {
            window.SolutionDisplayModule.show(result, problem, responseTime);
        }

        setSolutionProvided();
        isProcessingRequest = false;

        if (el.suggestBtn) el.suggestBtn.classList.remove("loading");

        // Ticket history yenile
        if (typeof window.loadTicketHistory === 'function') {
            window.loadTicketHistory(true);
        }
    }

    // --- Ana çözüm öner fonksiyonu ---
    async function suggestSolution() {
        const el = getElements();

        // Eğer çözüm zaten verilmişse, sıfırla
        if (solutionProvided) {
            resetToNewRequest();
            return;
        }

        const problem = el.problemTextArea ? el.problemTextArea.value.trim() : "";
        if (!problem) {
            alert("Lütfen sorununuzu detaylı yazın.");
            return;
        }

        // 🔒 Org yetki kontrolü - kullanıcının aktif org'u var mı?
        try {
            const orgCheckResponse = await window.VYRA_API.request("/users/me/organizations", { method: "GET" });
            const activeOrgs = (orgCheckResponse || []).filter(o => o.is_active);

            if (activeOrgs.length === 0) {
                if (typeof VyraToast !== 'undefined') {
                    VyraToast.warning('⚠️ Doküman organizasyon yetkiniz bulunamamıştır. Lütfen yöneticinizle iletişime geçin.');
                } else {
                    alert('Doküman organizasyon yetkiniz bulunamamıştır. Lütfen yöneticinizle iletişime geçin.');
                }
                return;
            }
        } catch (orgErr) {
            console.error('[NGSSAI] Org kontrol hatası:', orgErr);
            // Hata durumunda devam et (eski davranış)
        }

        // Çift istek koruması
        if (isProcessingRequest || el.suggestBtn?.disabled) {
            console.log("[NGSSAI] İşlem zaten devam ediyor, duplicate önlendi");
            return;
        }

        // Korumaları aktif et
        isProcessingRequest = true;
        if (el.suggestBtn) {
            el.suggestBtn.disabled = true;
            el.suggestBtn.classList.add("loading");
        }
        if (el.problemTextArea) el.problemTextArea.disabled = true;

        // Attach butonu pasif - çözüm süreci başladı
        const attachImageBtn = document.getElementById("attachImageBtn");
        if (attachImageBtn) attachImageBtn.disabled = true;

        // Loading göster
        if (window.SolutionDisplayModule) {
            window.SolutionDisplayModule.showLoading();
        }

        requestStartTime = performance.now();
        const progressEl = createProgressElement();
        updateProgress(progressEl, "Çözüm önerisi hazırlanıyor...");

        try {
            // WebSocket ile async mod
            if (typeof VyraWebSocket !== 'undefined' && VyraWebSocket.isConnected()) {
                updateProgress(progressEl, "📡 İşlem arka planda başlatıldı...");

                await VyraWebSocket.createTicketAsync(problem, (error, result) => {
                    if (error) {
                        console.error('[NGSSAI] Async ticket hatası:', error);
                        if (window.SolutionDisplayModule) {
                            window.SolutionDisplayModule.hide();
                        }

                        // 🌐 VPN/Network hatası kontrolü
                        if (window.isVPNNetworkError && window.isVPNNetworkError(error)) {
                            window.showVPNErrorPopup();
                        } else if (typeof VyraToast !== 'undefined') {
                            VyraToast.error('Çözüm hazırlanamadı: ' + error);
                        } else {
                            alert('Çözüm hazırlanamadı: ' + error);
                        }

                        // Hata durumunda reset
                        isProcessingRequest = false;
                        el.suggestBtn.disabled = false;
                        el.suggestBtn.classList.remove("loading");
                        el.suggestBtn.innerHTML = "Çözüm Öner";
                        if (el.problemTextArea) el.problemTextArea.disabled = false;
                        // Attach butonu aktif - hata durumu
                        const attachBtn = document.getElementById("attachImageBtn");
                        if (attachBtn) attachBtn.disabled = false;
                    } else {
                        handleAsyncResult(result);
                    }
                });

                if (typeof VyraToast !== 'undefined') {
                    VyraToast.info('Çözüm önerisi hazırlanıyor...');
                }

            } else {
                // Fallback: Senkron mod
                updateProgress(progressEl, "📚 Bilgi tabanı aranıyor...");

                const response = await window.VYRA_API.request("/tickets/from-chat", {
                    method: "POST",
                    body: { query: problem }
                });

                const responseTime = ((performance.now() - requestStartTime) / 1000).toFixed(1);

                if (window.SolutionDisplayModule) {
                    window.SolutionDisplayModule.show(response, problem, responseTime);
                }

                setSolutionProvided();
                isProcessingRequest = false;
                el.suggestBtn.classList.remove("loading");
            }

        } catch (err) {
            if (window.SolutionDisplayModule) {
                window.SolutionDisplayModule.hide();
            }
            alert("Hata oluştu: " + err.message);
            console.error("Chat Error:", err);

            el.suggestBtn.disabled = false;
            el.suggestBtn.classList.remove("loading");
            isProcessingRequest = false;
            if (el.problemTextArea) el.problemTextArea.disabled = false;
        }
    }

    // --- Event Listeners ---
    function setupEventListeners() {
        const el = getElements();

        // Textarea input - buton durumu
        if (el.problemTextArea) {
            el.problemTextArea.addEventListener("input", updateButtonState);

            // Ctrl+Enter kısayolu
            el.problemTextArea.addEventListener("keydown", (e) => {
                if (e.ctrlKey && e.key === "Enter") {
                    e.preventDefault();
                    if (el.suggestBtn && !el.suggestBtn.disabled) {
                        suggestSolution();
                    }
                }
            });
        }

        // Çözüm öner butonu
        if (el.suggestBtn && !el.suggestBtn.hasAttribute('data-listener-added')) {
            el.suggestBtn.setAttribute('data-listener-added', 'true');
            el.suggestBtn.addEventListener("click", suggestSolution);
        }
    }

    // --- Init ---
    function init() {
        setupEventListeners();
        updateButtonState();
    }

    // Public API
    return {
        init: init,
        suggest: suggestSolution,
        reset: resetToNewRequest,
        updateButtonState: updateButtonState,
        handleAsyncResult: handleAsyncResult,
        setSolutionProvided: setSolutionProvided
    };
})();

// Global fonksiyonlar (backward compatibility)
window.handleAsyncTicketResult = function (result) {
    if (window.TicketChatModule) {
        window.TicketChatModule.handleAsyncResult(result);
    }
};

window.resetToNewRequest = function () {
    if (window.TicketChatModule) {
        window.TicketChatModule.reset();
    }
};

// Otomatik init
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', window.TicketChatModule.init);
} else {
    window.TicketChatModule.init();
}
