/* ─────────────────────────────────────────────
   VYRA – Ticket Handler Module
   v2.30.0 · home_page.js'den ayrıştırıldı
   Ticket hata işleme, async sonuç, sıfırlama
   ───────────────────────────────────────────── */

// 🆘 Ticket hatası işle
function handleTicketError(error, suggestBtn, problemTextArea) {
    console.error('[VYRA] Ticket hatası:', error);
    const loadingBox = document.getElementById("loadingBox");
    if (loadingBox) loadingBox.classList.add("hidden");

    // 🌐 VPN/Network hatası kontrolü
    if (window.isVPNNetworkError && window.isVPNNetworkError(error)) {
        window.showVPNErrorPopup();
    } else if (typeof VyraToast !== 'undefined') {
        VyraToast.error('Çözüm hazırlanamadı: ' + error);
    } else {
        alert('Çözüm hazırlanamadı: ' + error);
    }

    isProcessingRequest = false;
    if (suggestBtn) {
        suggestBtn.disabled = false;
        suggestBtn.classList.remove("loading");
        suggestBtn.innerHTML = "Çözüm Öner";
    }
    if (problemTextArea) problemTextArea.disabled = false;
}

// 🚀 Asenkron ticket sonucunu işle (WebSocket'ten gelen)
function handleAsyncTicketResult(result) {
    if (!result) return;

    // ⏱️ Yanıt süresini hesapla
    const responseTime = ((performance.now() - requestStartTime) / 1000).toFixed(1);
    const responseTimeEl = document.getElementById("responseTime");
    if (responseTimeEl) {
        responseTimeEl.textContent = `${responseTime}s`;
    }

    const loadingBox = document.getElementById("loadingBox");
    const finalSolutionBox = document.getElementById("finalSolutionBox");
    const solutionSteps = document.getElementById("solutionSteps");
    const cymText = document.getElementById("cymText");
    const suggestBtn = document.getElementById("suggestBtn");

    if (loadingBox) loadingBox.classList.add("hidden");
    if (finalSolutionBox) finalSolutionBox.classList.remove("hidden");

    // Kullanıcı talebini göster
    const userRequestTextEl = document.getElementById("userRequestText");
    const problemTextAreaSource = document.getElementById("problemText");
    if (userRequestTextEl && problemTextAreaSource) {
        userRequestTextEl.textContent = problemTextAreaSource.value || result.description || "-";
    }

    if (solutionSteps) {
        solutionSteps.innerHTML = "";
        const solutionHtml = formatSolutionForDisplay(result.final_solution);
        solutionSteps.innerHTML = solutionHtml;

        // Kaynak bilgisini göster
        updateSourceInfo(result.final_solution);
    }

    // ÇYM text
    if (cymText) cymText.textContent = result.cym_text || "ÇYM metni oluşturulamadı.";

    // 🎫 Ticket ID'yi SolutionDisplayModule'a kaydet (LLM değerlendirmesi için)
    if (result.id && window.SolutionDisplayModule?.setTicketInfo) {
        window.SolutionDisplayModule.setTicketInfo(result.id, [], problemTextAreaSource?.value || '');
        console.log('[VYRA] Ticket ID kaydedildi:', result.id);
    }

    // ✅ Çözüm verildi - butonu "Yeni Soru" olarak değiştir (v2.24.0)
    solutionProvided = true;
    if (suggestBtn) {
        suggestBtn.innerHTML = '<i class="fa-solid fa-plus"></i> Yeni Soru';
        suggestBtn.classList.add("new-request-mode");
        suggestBtn.disabled = false;
    }

    // Keyboard hint'i gizle
    const keyboardHint = document.querySelector('.keyboard-hint');
    if (keyboardHint) keyboardHint.style.display = 'none';

    // ✅ Textarea'yı disabled tut (çözüm gösterilirken yazılmasın)
    const problemTextArea = document.getElementById("problemText");
    if (problemTextArea) problemTextArea.disabled = true;

    // Ticket history'yi yenile
    if (typeof loadTicketHistory === 'function') {
        loadTicketHistory(true);
    }
}

// Ekranları sıfırla ve yeni soru moduna geç (v2.24.0)
function resetToNewRequest() {
    // Textarea'yı temizle ve ENABLE yap
    const problemTextArea = document.getElementById("problemText");
    if (problemTextArea) {
        problemTextArea.value = "";
        problemTextArea.disabled = false;  // ✅ Yeniden aktif et
        problemTextArea.focus();
    }

    // Görsel preview'ı temizle
    const imagePreviewContainer = document.getElementById("imagePreviewContainer");
    const imagePreview = document.getElementById("imagePreview");
    const imageInput = document.getElementById("imageInput");
    if (imagePreviewContainer) imagePreviewContainer.classList.add("hidden");
    if (imagePreview) imagePreview.src = "";
    if (imageInput) imageInput.value = "";

    // Çözüm kutusunu gizle
    finalSolutionBox.classList.add("hidden");
    loadingBox.classList.add("hidden");

    // CYM checkbox'ı sıfırla
    if (showCYM) showCYM.checked = false;
    if (cymContent) cymContent.classList.add("hidden");

    // Buton'u eski haline döndür
    suggestBtn.innerHTML = "Çözüm Öner";
    suggestBtn.classList.remove("new-request-mode");
    suggestBtn.disabled = true;
    solutionProvided = false;

    // Keyboard hint'i göster
    const keyboardHint = document.querySelector('.keyboard-hint');
    if (keyboardHint) keyboardHint.style.display = 'block';

    // Yanıt süresini sıfırla
    const responseTimeEl = document.getElementById("responseTime");
    if (responseTimeEl) responseTimeEl.textContent = "--";

    // Tooltip'i göster
    if (suggestTooltip) suggestTooltip.style.display = 'block';
}

// Progress element oluştur
function createProgressElement() {
    const loadingBox = document.getElementById("loadingBox");
    if (!loadingBox) return null;

    let progressEl = loadingBox.querySelector('.progress-text');
    if (!progressEl) {
        progressEl = document.createElement('p');
        progressEl.className = 'progress-text text-sm text-gray-400 mt-2';
        loadingBox.appendChild(progressEl);
    }
    return progressEl;
}

function updateProgress(el, text) {
    if (el) el.textContent = text;
}
