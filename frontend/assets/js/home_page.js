/* -------------------------------
   NGSSAI Modern SaaS UI – HOME JS
-------------------------------- */

// --- GÜVENLİK: Sayfa Erişim Kontrolü ---
// Token yoksa login sayfasına yönlendir (URL manipülasyonunu engeller)
(function authGuard() {
    const token = localStorage.getItem('access_token');
    if (!token) {
        console.warn('[NGSSAI] Token bulunamadı, login sayfasına yönlendiriliyor...');
        window.location.href = 'login.html';
        return;
    }

    // Token geçerliliğini kontrol et (expire süresi)
    try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        const expireTime = payload.exp * 1000; // Unix timestamp to ms
        if (Date.now() > expireTime) {
            console.warn('[NGSSAI] Token süresi dolmuş, login sayfasına yönlendiriliyor...');
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            window.location.href = 'login.html';
            return;
        }
    } catch (e) {
        console.error('[NGSSAI] Token parse hatası:', e);
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        window.location.href = 'login.html';
        return;
    }
})();

// --- VPN/NETWORK + ANİMASYON ---
// v2.30.0: modules/vpn_handler.js modülüne taşındı.

// --- ELEMENTLER ---
const sidebar = {
    newTicket: document.getElementById("menuNewTicket"),
    history: document.getElementById("menuHistory"),
    parameters: document.getElementById("menuParameters"),
    knowledgeBase: document.getElementById("menuKnowledgeBase"),
    authorization: document.getElementById("menuAuthorization"),
    organizations: document.getElementById("menuOrganizations"),
    profile: document.getElementById("menuProfile"),
    logout: document.getElementById("logoutBtn"),
};

const mainTabs = {
    container: document.getElementById("mainTabBar"), // Modern Tab container
    dialog: document.getElementById("tabDialog"),

    history: document.getElementById("tabHistory"),
    knowledgeBase: document.getElementById("tabKnowledgeBase"),
};

const sections = {
    dialog: document.getElementById("sectionDialog"),

    history: document.getElementById("sectionHistory"),
    parameters: document.getElementById("sectionParameters"),
    knowledgeBase: document.getElementById("sectionKnowledgeBase"),
    authorization: document.getElementById("sectionAuthorization"),
    organizations: document.getElementById("sectionOrganizations"),
    profile: document.getElementById("sectionProfile"),
};

// LLM Elementleri
const llmElements = {
    grid: document.getElementById("llmGrid"),
    modal: document.getElementById("llmModal"),
    btnNew: document.getElementById("btnNewLLM"),
    btnClose: document.getElementById("closeLlmModal"),
    btnCancel: document.getElementById("btnCancelLlm"),
    form: document.getElementById("llmForm"),
    modalTitle: document.getElementById("llmModalTitle"),
    // Inputs
    inputs: {
        id: document.getElementById("llmId"),
        vendor: document.getElementById("llmVendor"),
        provider: document.getElementById("llmProvider"),
        model: document.getElementById("llmModel"),
        apiUrl: document.getElementById("llmApiUrl"),
        token: document.getElementById("llmToken"),
        desc: document.getElementById("llmDesc"),
        temp: document.getElementById("llmTemp"),
        topP: document.getElementById("llmTopP"),
        timeout: document.getElementById("llmTimeout"),
    }
};

// Prompt Dizayn Elementleri
const promptElements = {
    grid: document.getElementById("promptGrid"),
    modal: document.getElementById("promptModal"),
    btnNew: document.getElementById("btnNewPrompt"),
    btnClose: document.getElementById("closePromptModal"),
    btnCancel: document.getElementById("btnCancelPrompt"),
    form: document.getElementById("promptForm"),
    modalTitle: document.getElementById("promptModalTitle"),
    inputs: {
        id: document.getElementById("promptId"),
        category: document.getElementById("promptCategory"),
        title: document.getElementById("promptTitle"),
        content: document.getElementById("promptContent"),
        description: document.getElementById("promptDescription"),
    }
};

// Parametreler Tab Elementleri
const paramTabs = {
    llmConfig: document.getElementById("tabLlmConfig"),
    promptDesign: document.getElementById("tabPromptDesign"),
    systemReset: document.getElementById("tabSystemReset"),
    contentLlmConfig: document.getElementById("contentLlmConfig"),
    contentPromptDesign: document.getElementById("contentPromptDesign"),
    contentSystemReset: document.getElementById("contentSystemReset"),
};

// Diğer Elementler (Chat/Ticket Create)
const sendBtn = document.getElementById("sendBtn");
const suggestBtn = sendBtn; // Geriye uyumluluk için alias
const suggestTooltip = null; // Kaldırıldı
const loadingBox = document.getElementById("loadingBox");
const finalSolutionBox = document.getElementById("finalSolutionBox");
const solutionSteps = document.getElementById("solutionSteps");
const showCYM = document.getElementById("showCYM");
const cymContent = document.getElementById("cymContent");
const cymText = document.getElementById("cymText");
const copyBtn = document.getElementById("copyBtn");
const newRequestBtn = document.getElementById("newRequestBtn");

// --- GÖNDER BUTONU AKTİFLİK KONTROLÜ ---
function updateSendButtonState() {
    const problemText = document.getElementById("problemText");
    if (!problemText || !sendBtn) return;

    const hasText = problemText.value.trim().length > 0;
    sendBtn.disabled = !hasText;
}

// Geriye uyumluluk için alias
const updateSuggestButtonState = updateSendButtonState;

// Textarea input event listener
const problemTextArea = document.getElementById("problemText");
if (problemTextArea) {
    problemTextArea.addEventListener("input", updateSuggestButtonState);

    // ⌨️ Ctrl+Enter kısayolu ile Çözüm Öner butonunu tetikle
    problemTextArea.addEventListener("keydown", (e) => {
        if (e.ctrlKey && e.key === "Enter") {
            e.preventDefault();
            // Buton aktif ve tıklanabilir mi kontrol et
            if (suggestBtn && !suggestBtn.disabled) {
                suggestBtn.click();
            }
        }
    });

    // Sayfa yüklendiğinde de kontrol et
    updateSuggestButtonState();
}

// --- FAVORİ TAB YÖNETİMİ (Sidebar event listener için öne alındı) ---
const FAV_TAB_KEY = 'vyra_favorite_tab';

function getFavoriteTab() {
    return localStorage.getItem(FAV_TAB_KEY) || 'dialog';
}

function setFavoriteTab(tabId) {
    localStorage.setItem(FAV_TAB_KEY, tabId);
    updateFavButtons();
    // Favori tıklandığında otomatik sekme geçişi
    showSection(tabId);
}

function updateFavButtons() {
    const favTab = getFavoriteTab();
    document.querySelectorAll('.tab-fav-btn').forEach(btn => {
        const tabId = btn.dataset.tab;
        if (tabId === favTab) {
            btn.classList.add('favorited');
        } else {
            btn.classList.remove('favorited');
        }
    });
}

// --- SIDEBAR NAVİGASYON ---

function activateSidebarItem(item) {
    // Tüm aktif classları kaldır
    Object.values(sidebar).forEach(el => {
        if (el) el.classList.remove("active");
    });
    // Seçileni aktif yap
    if (item) item.classList.add("active");
}

function showSection(sectionName, skipLoad = false) {
    const otherSections = document.getElementById("otherSections");
    const statusBar = document.getElementById("statusBar");

    Object.values(sections).forEach(el => {
        if (el && el !== sections.dialog) el.classList.add("hidden");
    });

    if (mainTabs.dialog) mainTabs.dialog.classList.remove("active");
    if (mainTabs.history) mainTabs.history.classList.remove("active");

    const mainTabBar = document.getElementById("mainTabBar");
    const topBar = document.getElementById("topBar");
    const showHomeElements = ["dialog", "history"].includes(sectionName);

    if (topBar) {
        if (showHomeElements) topBar.classList.remove("hidden");
        else topBar.classList.add("hidden");
    }
    if (mainTabBar) {
        if (showHomeElements) mainTabBar.classList.remove("hidden");
        else mainTabBar.classList.add("hidden");
    }

    if (sectionName !== "dialog" && window.DialogChatModule && typeof window.DialogChatModule.deactivate === 'function') {
        window.DialogChatModule.deactivate();
    }

    if (sectionName === "dialog") {
        sections.dialog.classList.remove("hidden");
        sections.dialog.style.display = "";
        if (otherSections) otherSections.classList.add("hidden");
        if (statusBar) statusBar.classList.remove("hidden");
        if (mainTabs.dialog) mainTabs.dialog.classList.add("active");
        if (!skipLoad) {
            if (window.DialogChatModule && typeof window.DialogChatModule.init === 'function') {
                window.DialogChatModule.init();
            }
        }
    } else if (sectionName === "history") {
        sections.dialog.classList.add("hidden");
        sections.dialog.style.display = "none";
        if (otherSections) otherSections.classList.remove("hidden");
        if (statusBar) statusBar.classList.remove("hidden");
        if (sections.history) sections.history.classList.remove("hidden");
        if (mainTabs.history) mainTabs.history.classList.add("active");
        if (typeof loadTicketHistoryDebounced === 'function') {
            loadTicketHistoryDebounced();
        }
    } else {
        sections.dialog.classList.add("hidden");
        sections.dialog.style.display = "none";
        if (otherSections) otherSections.classList.remove("hidden");
        if (statusBar) statusBar.classList.add("hidden");

        if (sectionName === "parameters") {
            if (sections.parameters) sections.parameters.classList.remove("hidden");
        } else if (sectionName === "knowledgeBase") {
            if (sections.knowledgeBase) sections.knowledgeBase.classList.remove("hidden");
            if (mainTabs.knowledgeBase) mainTabs.knowledgeBase.classList.add("active");
            if (window.RAGUpload && typeof window.RAGUpload.init === 'function') {
                window.RAGUpload.init();
            }
        } else if (sectionName === "authorization") {
            if (sections.authorization) sections.authorization.classList.remove("hidden");
            if (window.authorizationModule) {
                window.authorizationModule.loadAuthData();
            }
        } else if (sectionName === "organizations") {
            if (sections.organizations) sections.organizations.classList.remove("hidden");
            if (window.orgModule) {
                window.orgModule.loadOrganizations();
            }
        } else if (sectionName === "profile") {
            if (sections.profile) sections.profile.classList.remove("hidden");
            if (window.authorizationModule) {
                window.authorizationModule.loadProfile();
            }
        }
    }
}

// Event Listeners: Sidebar
if (sidebar.newTicket) {
    sidebar.newTicket.addEventListener("click", () => {
        activateSidebarItem(sidebar.newTicket);
        showSection("dialog");
    });
}

if (sidebar.history) {
    sidebar.history.addEventListener("click", () => {
        activateSidebarItem(sidebar.history);
        showSection("history");
    });
}

if (sidebar.parameters) {
    sidebar.parameters.addEventListener("click", () => {
        activateSidebarItem(sidebar.parameters);
        showSection("parameters");
        // Parametreler açılınca verileri paralel yükle (daha hızlı)
        Promise.all([loadLlmConfigs(), loadPrompts()]).catch(console.error);
    });
}

// Event Listeners: Tabs (Ana Sayfa İçinde)
// Modern tab yapısı - event delegation ile
document.querySelectorAll('.modern-tab, .n-tab-btn').forEach(tab => {
    tab.addEventListener('click', (e) => {
        if (e.target.closest('.tab-fav-btn')) return;

        const tabId = tab.dataset.tab;
        if (tabId === 'dialog') showSection('dialog');
        else if (tabId === 'history') showSection('history');
    });
});

// Fav buton event listeners
document.querySelectorAll('.tab-fav-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
        e.stopPropagation(); // Tab click'i engelleß
        const tabId = btn.dataset.tab;
        setFavoriteTab(tabId);
    });
});

// Sayfa yüklendiğinde favori tab'ı seç ve butonları güncelle
document.addEventListener('DOMContentLoaded', () => {
    updateFavButtons();
    const favTab = getFavoriteTab();
    showSection(favTab);
    activateSidebarItem(sidebar.newTicket);
});

// SendBtn click handler
if (sendBtn) {
    sendBtn.addEventListener('click', () => {
        if (sendBtn.disabled) return;
        // TicketChatModule varsa onu kullan, yoksa manual trigger
        if (window.TicketChatModule && typeof window.TicketChatModule.suggest === 'function') {
            window.TicketChatModule.suggest();
        }
    });
}

// Legacy fallback - eğer direkt element event listener varsa
if (mainTabs.history) {
    mainTabs.history.addEventListener("click", (e) => {
        if (e.target.closest('.tab-fav-btn')) return;
        showSection("history");
    });
}
if (mainTabs.knowledgeBase) {
    mainTabs.knowledgeBase.addEventListener("click", () => {
        showSection("knowledgeBase");
    });
}

// Sidebar: Bilgi Tabanı
if (sidebar.knowledgeBase) {
    sidebar.knowledgeBase.addEventListener("click", () => {
        activateSidebarItem(sidebar.knowledgeBase);
        showSection("knowledgeBase");
    });
}

// Sidebar: Yetkilendirme (Admin Only)
if (sidebar.authorization) {
    sidebar.authorization.addEventListener("click", () => {
        activateSidebarItem(sidebar.authorization);
        showSection("authorization");
    });
}

// Sidebar: Organizasyonlar (Admin Only)
if (sidebar.organizations) {
    sidebar.organizations.addEventListener("click", () => {
        activateSidebarItem(sidebar.organizations);
        showSection("organizations");
    });
}

// Sidebar: Profilim
if (sidebar.profile) {
    sidebar.profile.addEventListener("click", () => {
        console.log('[home_page.js] Profile clicked - calling showSection');
        activateSidebarItem(sidebar.profile);
        showSection("profile");
        console.log('[home_page.js] After showSection - profile hidden?', sections.profile?.classList.contains('hidden'));
    });
}

if (sidebar.logout) {
    sidebar.logout.addEventListener("click", () => {
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
        localStorage.removeItem("session_start_time"); // Oturum sayacını sıfırla
        window.location.href = "login.html";
    });
}

// --- GÖRSEL EKLEME ---
// NOT: Görsel ekleme işlemleri artık image_handler.js modülü tarafından yönetiliyor.
// Bu bölüm modülerleştirme sonrası kaldırıldı.
// Elementler hala bazı fonksiyonlarda kullanılabilir, sadece referans olarak tutuluyor:
const attachImageBtn = document.getElementById("attachImageBtn");
const imageInput = document.getElementById("imageInput");
const imagePreviewContainer = document.getElementById("imagePreviewContainer");
const imagePreview = document.getElementById("imagePreview");
const removeImageBtn = document.getElementById("removeImageBtn");


// --- PARAMETRELER TAB YÖNETİMİ ---
// v2.30.0: Tab geçişleri artık param_tabs.js modülü ile yönetiliyor.
// Backward-compat delegation (modüller yüklü değilse eski davranış):
function loadLlmConfigs() { if (window.LLMModule) return window.LLMModule.load(); }
function loadPrompts() { if (window.PromptModule) return window.PromptModule.load(); }
function loadSystemResetInfo() { if (window.SystemManagerModule) return window.SystemManagerModule.loadResetInfo(); }

// --- CHAT / TICKET CREATE (GERÇEK LLM) ---

// ⚡ Global flag - tek bir istek garantisi
let isProcessingRequest = false;
let solutionProvided = false; // Çözüm verildi mi?
let requestStartTime = null;  // İstek başlangıç zamanı

if (suggestBtn) {
    // Event listener'ı bir kez eklemek için flag
    if (!suggestBtn.hasAttribute('data-listener-added')) {
        suggestBtn.setAttribute('data-listener-added', 'true');

        suggestBtn.addEventListener("click", async () => {
            // Eğer çözüm zaten verilmişse, sıfırla ve yeni talep moduna geç
            if (solutionProvided) {
                resetToNewRequest();
                return;
            }

            const problem = document.getElementById("problemText").value.trim();
            if (!problem) {
                VyraModal.warning({ title: 'Eksik Bilgi', message: 'Lütfen sorununuzu detaylı yazın.' });
                return;
            }

            // ⚡ ÇİFT İSTEK KORUMASI: Global flag + disabled kontrolü
            if (isProcessingRequest || suggestBtn.disabled) {
                console.log("[NGSSAI] İşlem zaten devam ediyor, duplicate önlendi");
                return;
            }

            // Her iki korumayı da aktif et
            isProcessingRequest = true;
            suggestBtn.disabled = true;
            suggestBtn.classList.add("loading");

            // 🔒 Textarea'yı da disable yap (işlem sırasında değiştirilemez)
            const problemTextArea = document.getElementById("problemText");
            if (problemTextArea) problemTextArea.disabled = true;

            // 📎 Attach butonunu da disable yap
            if (attachImageBtn) attachImageBtn.disabled = true;

            loadingBox.classList.remove("hidden");
            finalSolutionBox.classList.add("hidden");

            // ⏱️ Zamanlayıcı başlat
            requestStartTime = performance.now();

            // ⚡ PROGRESS GÖSTERGESİ
            const progressEl = loadingBox.querySelector('.progress-text') || createProgressElement();
            updateProgress(progressEl, "Çözüm önerisi hazırlanıyor...");

            try {
                // 🚀 SEÇ>ENEK A: Önce RAG araması, sonra seçim veya direkt işlem
                if (typeof VyraWebSocket !== 'undefined' && VyraWebSocket.searchRAG) {
                    updateProgress(progressEl, "🔍 Bilgi tabanı aranıyor...");

                    // RAG araması yap (LLM kullanmadan, hızlı)
                    const ragResult = await VyraWebSocket.searchRAG(problem);

                    if (ragResult.has_results && ragResult.results.length > 1) {
                        // Çoklu sonuç - kartları göster, kullanıcı seçsin
                        loadingBox.classList.add("hidden");
                        showRAGSelectionCards(ragResult.results, problem);

                        // Buton ve textarea'yı aktif tut ama farklı bir moda geç
                        suggestBtn.disabled = true;
                        suggestBtn.innerHTML = '<i class="fa-solid fa-lightbulb"></i> Çözüm Öner';
                        isProcessingRequest = false;
                        if (problemTextArea) problemTextArea.disabled = true;
                        // Attach butonu da disable kalmalı
                        if (attachImageBtn) attachImageBtn.disabled = true;

                    } else if (ragResult.has_results && ragResult.results.length === 1) {
                        // Tek sonuç - içeriği direkt göster (AI çağırmadan)
                        const result = ragResult.results[0];
                        loadingBox.classList.add('hidden');

                        // Çözüm kutusunu göster
                        const finalSolutionBox = document.getElementById('finalSolutionBox');
                        const solutionSteps = document.getElementById('solutionSteps');

                        if (finalSolutionBox) finalSolutionBox.classList.remove('hidden');

                        // ⏱️ Yanıt süresini hesapla ve göster
                        const responseTime = ((performance.now() - requestStartTime) / 1000).toFixed(1);
                        const responseTimeEl = document.getElementById("responseTime");
                        if (responseTimeEl) {
                            responseTimeEl.textContent = `${responseTime}s`;
                        }

                        // RAG içeriğini formatla ve göster
                        if (solutionSteps && result.chunk_text) {
                            const formattedContent = window.SolutionDisplayModule?.format?.(result.chunk_text)
                                || `<p class="solution-text">${result.chunk_text}</p>`;
                            const sourceInfo = `<div class="source-info"><i class="fa-solid fa-file-lines"></i> Kaynak: <strong>${result.file_name}</strong></div>`;
                            solutionSteps.innerHTML = formattedContent + sourceInfo;
                        }

                        // State kaydet
                        window._selectedRAGResult = result;
                        window._selectedRAGQuery = problem;
                        window._currentRAGResults = ragResult.results;

                        // Çözüm sağlandı moduna geç
                        if (window.TicketChatModule?.setSolutionProvided) {
                            window.TicketChatModule.setSolutionProvided();
                        }

                        isProcessingRequest = false;
                        suggestBtn.classList.remove('loading');
                        console.log('[NGSSAI] Tek RAG sonucu gösterildi (AI çağrılmadı).');

                    } else {
                        // Sonuç yok - eski asenkron akışa devam et (LLM kullanır)
                        updateProgress(progressEl, "📡 Bilgi tabanında sonuç bulunamadı, AI işleniyor...");

                        await VyraWebSocket.createTicketAsync(problem, (error, result) => {
                            if (error) {
                                handleTicketError(error, suggestBtn, problemTextArea);
                            } else {
                                handleAsyncTicketResult(result);
                                isProcessingRequest = false;
                                suggestBtn.classList.remove("loading");
                            }
                        });

                        if (typeof VyraToast !== 'undefined') {
                            VyraToast.info('AI çözüm önerisi hazırlanıyor...');
                        }
                    }

                } else {
                    // Fallback: Senkron mod (WebSocket bağlı değilse)
                    updateProgress(progressEl, "📚 Bilgi tabanı aranıyor...");

                    const response = await window.VYRA_API.request("/tickets/from-chat", {
                        method: "POST",
                        body: { query: problem }
                    });

                    // ⏱️ Yanıt süresini hesapla
                    const responseTime = ((performance.now() - requestStartTime) / 1000).toFixed(1);
                    const responseTimeEl = document.getElementById("responseTime");
                    if (responseTimeEl) {
                        responseTimeEl.textContent = `${responseTime}s`;
                    }

                    loadingBox.classList.add("hidden");
                    finalSolutionBox.classList.remove("hidden");

                    // Kullanıcı talebini göster
                    const userRequestTextEl = document.getElementById("userRequestText");
                    if (userRequestTextEl) {
                        userRequestTextEl.textContent = problem;
                    }

                    solutionSteps.innerHTML = "";

                    // Backend'den gelen final solution'ı modern tasarımla göster
                    const solutionHtml = formatSolutionForDisplay(response.final_solution);
                    solutionSteps.innerHTML = solutionHtml;

                    // Kaynak bilgisini göster
                    updateSourceInfo(response.final_solution);

                    // ÇYM text
                    if (cymText) cymText.textContent = response.cym_text || "ÇYM metni oluşturulamadı.";

                    // ✅ Çözüm verildi - butonu "Yeni Soru" olarak değiştir (v2.24.0)
                    solutionProvided = true;
                    suggestBtn.innerHTML = '<i class="fa-solid fa-plus"></i> Yeni Soru';
                    suggestBtn.classList.add("new-request-mode");
                    suggestBtn.disabled = false;

                    // Keyboard hint'i gizle
                    const keyboardHint = document.querySelector('.keyboard-hint');
                    if (keyboardHint) keyboardHint.style.display = 'none';

                    // Korumaları kaldır
                    isProcessingRequest = false;
                    suggestBtn.classList.remove("loading");

                    // ✅ Textarea'yı disabled tut (çözüm gösterilirken yazılmasın)
                    if (problemTextArea) problemTextArea.disabled = true;
                }

            } catch (err) {
                loadingBox.classList.add("hidden");
                VyraModal.error({ title: 'Hata', message: 'Hata oluştu: ' + err.message });
                console.error("Chat Error:", err);

                // Hata durumunda da buton'u aktif et
                suggestBtn.disabled = false;
                suggestBtn.classList.remove("loading");

                // Korumaları kaldır
                isProcessingRequest = false;

                // 🔓 Textarea'yı tekrar enable yap
                const problemTextArea = document.getElementById("problemText");
                if (problemTextArea) problemTextArea.disabled = false;
            }
        });
    }
}

// --- TICKET HATA İŞLEME ---
// v2.30.0: modules/ticket_handler.js modülüne taşındı.


// --- RAG SEÇİM KARTLARI ---
// v2.30.0: modules/rag_cards.js modülüne taşındı.


// --- TICKET ASYNC SONUÇ + SIFIRLAMA ---
// v2.30.0: modules/ticket_handler.js modülüne taşındı.

// --- ÇÖZÜM FORMATLAMA ---
// v2.30.0: modules/solution_formatter.js modülüne taşındı.


if (showCYM) {
    showCYM.addEventListener("change", () => {
        cymContent.classList.toggle("hidden", !showCYM.checked);
    });
}

if (copyBtn) {
    copyBtn.addEventListener("click", () => {
        if (cymText) navigator.clipboard.writeText(cymText.textContent);
        if (typeof VyraToast !== 'undefined') {
            VyraToast.success('Çağrı metni kopyalandı.');
        }
    });
}

if (newRequestBtn) {
    newRequestBtn.addEventListener("click", () => {
        // TicketChatModule varsa onun reset fonksiyonunu kullan (tüm state'leri sıfırlar)
        if (window.TicketChatModule && typeof window.TicketChatModule.reset === 'function') {
            window.TicketChatModule.reset();
        } else {
            // Fallback: Manuel sıfırlama
            const problemText = document.getElementById("problemText");
            if (problemText) {
                problemText.value = "";
                problemText.disabled = false; // ⚡ KRİTİK: disabled'ı kaldır
                problemText.focus();
            }
            finalSolutionBox.classList.add("hidden");
            loadingBox.classList.add("hidden");
            if (showCYM) showCYM.checked = false;
            if (cymContent) cymContent.classList.add("hidden");
        }
    });
}


// --- VERSİYON, PROFİL, OTURUM SAYACI, SİSTEM SIFIRLAMA ---
// v2.30.0: Tüm sistem yönetim fonksiyonları system_manager.js modülüne taşındı.
// Modül auto-init ile versiyon, profil ve session timer'ı otomatik başlatıyor.
