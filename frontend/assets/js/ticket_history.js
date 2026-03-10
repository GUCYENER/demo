/**
 * NGSSAI - Ticket History Module
 * Modern SaaS Accordion tasarımı ile geçmiş çözümler
 */

// --- GEÇMİŞ ÇÖZÜMLER (TICKET HISTORY) - ACCORDION ---

// 🔒 Çift yükleme koruması ve cache
let _historyLoading = false;
let _historyCache = null;
let _historyCacheTime = 0;
let _historyDebounceTimer = null;
const HISTORY_CACHE_TTL = 30000; // 30 saniye cache
const HISTORY_DEBOUNCE_MS = 300; // 300ms debounce

// 📄 Pagination state
let _currentPage = 1;
let _totalPages = 1;
let _totalItems = 0;
const PAGE_SIZE = 5;

// 🔍 Arama/Filtre state - Ay başı ve sonu varsayılan
const now = new Date();
const firstDayOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
const lastDayOfMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0);

let _searchQuery = '';
let _startDate = formatDateForAPI(firstDayOfMonth);
let _endDate = formatDateForAPI(lastDayOfMonth);
let _sourceTypeFilter = ''; // v2.24.0: '' = Tümü, 'vyra_chat' only

// Tarih formatla (YYYY-MM-DD) - API için
function formatDateForAPI(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

// Türkçe ay isimleri
const TR_MONTHS = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran',
    'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];

// Tarihi Türkçe formatla (görüntüleme için)
function formatDateTR(dateStr) {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    return `${date.getDate()} ${TR_MONTHS[date.getMonth()]} ${date.getFullYear()}`;
}

async function loadTicketHistory(forceRefresh = false, page = 1) {
    const container = document.getElementById("ticketHistoryList");
    if (!container) return;

    // 🔒 Çift yükleme koruması
    if (_historyLoading) {
        console.log('[TicketHistory] Zaten yükleniyor, atlanıyor...');
        return;
    }

    // 💾 Cache kontrolü (aynı sayfa ve 30 saniye içinde tekrar yüklenmesin)
    const now = Date.now();
    if (!forceRefresh && _historyCache && _currentPage === page && (now - _historyCacheTime) < HISTORY_CACHE_TTL) {
        console.log('[TicketHistory] Cache kullanılıyor');
        renderTicketHistory(_historyCache);
        return;
    }

    try {
        _historyLoading = true;
        _currentPage = page;

        container.innerHTML = `
            <div class="ticket-loading">
                <i class="fa-solid fa-spinner fa-spin"></i>
                <span>Geçmiş çözümler yükleniyor...</span>
            </div>
        `;

        // v2.21.1: Source type'a göre API çağrıları
        let ticketApiUrl = `/tickets/history?page=${page}&page_size=${PAGE_SIZE}`;
        if (_startDate) ticketApiUrl += `&start_date=${_startDate}`;
        if (_endDate) ticketApiUrl += `&end_date=${_endDate}`;

        let dialogApiUrl = `/dialogs/history?limit=${PAGE_SIZE}&offset=${(page - 1) * PAGE_SIZE}`;
        if (_sourceTypeFilter) dialogApiUrl += `&source_type=${_sourceTypeFilter}`;

        // Source type filtresine göre hangi API'leri çağır
        let ticketData = { items: [], total: 0 };
        let dialogData = { items: [], total: 0 };

        if (_sourceTypeFilter === 'vyra_chat') {
            // Sadece dialog'ları getir
            dialogData = await window.VYRA_API.request(dialogApiUrl, { method: "GET" }).catch(e => ({ items: [], total: 0 }));
        } else {
            // Tümü - sadece dialog'ları çek (v2.24.0: ticket özelliği kaldırıldı)
            dialogData = await window.VYRA_API.request(dialogApiUrl, { method: "GET" }).catch(e => ({ items: [], total: 0 }));
        }

        console.log('[TicketHistory] Loaded:', { tickets: ticketData.total, dialogs: dialogData.total });

        // Dialog'ları ticket formatına dönüştür
        const dialogItems = (dialogData.items || []).map(d => ({
            id: `dialog-${d.id}`,
            title: d.title || 'NGSSAI Analiz Süreci',
            description: d.first_question || 'Talep bilgisi yok',
            final_solution: d.last_answer || 'Cevap yok',
            created_at: d.created_at,
            source_type: d.source_type || 'vyra_chat',
            _isDialog: true
        }));

        // Ticket'lara source_type ekle
        const ticketItems = (ticketData.items || []).map(t => ({
            ...t,
            source_type: t.source_type || 'vyra_chat',
            _isDialog: false
        }));

        // Birleştir ve tarihe göre sırala
        let allItems = [...ticketItems, ...dialogItems].sort((a, b) =>
            new Date(b.created_at) - new Date(a.created_at)
        );

        // Pagination bilgilerini güncelle
        _totalItems = (ticketData.total || 0) + (dialogData.total || 0);
        _totalPages = Math.ceil(_totalItems / PAGE_SIZE) || 1;

        // İçerik araması (client-side filtreleme - backend'de yoksa)
        let filteredItems = allItems;
        if (_searchQuery && _searchQuery.trim()) {
            const query = _searchQuery.toLowerCase().trim();
            filteredItems = allItems.filter(ticket =>
                (ticket.title && ticket.title.toLowerCase().includes(query)) ||
                (ticket.description && ticket.description.toLowerCase().includes(query)) ||
                (ticket.final_solution && ticket.final_solution.toLowerCase().includes(query))
            );
        }

        // Cache'e kaydet
        _historyCache = filteredItems;
        _historyCacheTime = Date.now();

        renderTicketHistory(_historyCache);

    } catch (err) {
        console.error('[TicketHistory] Error:', err);
        container.innerHTML = `
            <div class="ticket-error">
                <i class="fa-solid fa-exclamation-triangle"></i>
                <span>Geçmiş çözümler yüklenemedi: ${err.message || 'Bilinmeyen hata'}</span>
            </div>
        `;
    } finally {
        _historyLoading = false;
    }
}

// 🔒 Debounce ile güvenli yükleme - çift tıklamaları engeller
function loadTicketHistoryDebounced(forceRefresh = false) {
    if (_historyDebounceTimer) {
        clearTimeout(_historyDebounceTimer);
    }
    _historyDebounceTimer = setTimeout(() => {
        loadTicketHistory(forceRefresh);
    }, HISTORY_DEBOUNCE_MS);
}

function renderTicketHistory(tickets) {
    const container = document.getElementById("ticketHistoryList");
    if (!container) return;

    container.innerHTML = "";

    if (!tickets || tickets.length === 0) {
        container.innerHTML = `
            <div class="ticket-empty">
                <i class="fa-solid fa-inbox"></i>
                <h4>Henüz çözüm kaydı yok</h4>
                <p>Oluşturduğunuz çözümler burada listelenecek.</p>
            </div>
        `;
        return;
    }

    // Accordion konteyner
    const accordionWrapper = document.createElement("div");
    accordionWrapper.className = "ticket-accordion";

    tickets.forEach((ticket, index) => {
        const accordionItem = createAccordionItem(ticket, index);
        accordionWrapper.appendChild(accordionItem);
    });

    container.appendChild(accordionWrapper);

    // Pagination UI ekle
    if (_totalPages > 1) {
        const paginationEl = createPaginationUI();
        container.appendChild(paginationEl);
    }
}

// Pagination UI oluştur
function createPaginationUI() {
    const pagination = document.createElement("div");
    pagination.className = "pagination-container";

    // Sayfa bilgisi
    const pageInfo = document.createElement("span");
    pageInfo.className = "pagination-info";
    pageInfo.textContent = `Sayfa ${_currentPage} / ${_totalPages} (Toplam ${_totalItems} kayıt)`;

    // Butonlar
    const buttonsContainer = document.createElement("div");
    buttonsContainer.className = "pagination-buttons";

    // İlk sayfa
    const firstBtn = document.createElement("button");
    firstBtn.className = "pagination-btn";
    firstBtn.innerHTML = '<i class="fa-solid fa-angles-left"></i>';
    firstBtn.title = "İlk Sayfa";
    firstBtn.disabled = _currentPage === 1;
    firstBtn.onclick = () => goToPage(1);

    // Önceki sayfa
    const prevBtn = document.createElement("button");
    prevBtn.className = "pagination-btn";
    prevBtn.innerHTML = '<i class="fa-solid fa-angle-left"></i>';
    prevBtn.title = "Önceki Sayfa";
    prevBtn.disabled = _currentPage === 1;
    prevBtn.onclick = () => goToPage(_currentPage - 1);

    // Sayfa numaraları
    const pageNumbers = document.createElement("div");
    pageNumbers.className = "pagination-numbers";

    const startPage = Math.max(1, _currentPage - 2);
    const endPage = Math.min(_totalPages, _currentPage + 2);

    for (let i = startPage; i <= endPage; i++) {
        const pageBtn = document.createElement("button");
        pageBtn.className = `pagination-num ${i === _currentPage ? 'active' : ''}`;
        pageBtn.textContent = i;
        pageBtn.onclick = () => goToPage(i);
        pageNumbers.appendChild(pageBtn);
    }

    // Sonraki sayfa
    const nextBtn = document.createElement("button");
    nextBtn.className = "pagination-btn";
    nextBtn.innerHTML = '<i class="fa-solid fa-angle-right"></i>';
    nextBtn.title = "Sonraki Sayfa";
    nextBtn.disabled = _currentPage === _totalPages;
    nextBtn.onclick = () => goToPage(_currentPage + 1);

    // Son sayfa
    const lastBtn = document.createElement("button");
    lastBtn.className = "pagination-btn";
    lastBtn.innerHTML = '<i class="fa-solid fa-angles-right"></i>';
    lastBtn.title = "Son Sayfa";
    lastBtn.disabled = _currentPage === _totalPages;
    lastBtn.onclick = () => goToPage(_totalPages);

    buttonsContainer.appendChild(firstBtn);
    buttonsContainer.appendChild(prevBtn);
    buttonsContainer.appendChild(pageNumbers);
    buttonsContainer.appendChild(nextBtn);
    buttonsContainer.appendChild(lastBtn);

    pagination.appendChild(pageInfo);
    pagination.appendChild(buttonsContainer);

    return pagination;
}

// Sayfaya git
function goToPage(page) {
    if (page < 1 || page > _totalPages || page === _currentPage) return;
    loadTicketHistory(true, page);
}

function createAccordionItem(ticket, index) {
    const item = document.createElement("div");
    item.className = "accordion-item";
    item.setAttribute("data-ticket-id", ticket.id);

    // Tarih formatla
    const date = new Date(ticket.created_at).toLocaleDateString('tr-TR', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });

    // Kullanıcı sorgusu (description)
    const userQuery = ticket.description || ticket.query || 'Talep bilgisi yok';

    // v2.24.0: Sadece NGSSAI'ye Sor badge'i (support ticket kaldırıldı)
    const isDialog = ticket._isDialog || ticket.source_type === 'vyra_chat';
    const badgeText = "Bilgi Tabanı";
    const badgeClass = 'badge-vyra';
    const badgeIcon = 'fa-robot';
    const itemIcon = isDialog ? 'fa-comments' : 'fa-ticket';
    // Başlık (title veya kısaltılmış query)
    const title = ticket.title || userQuery.substring(0, 50) + (userQuery.length > 50 ? '...' : '');



    // Final solution
    const finalSolution = ticket.final_solution || 'Çözüm bilgisi yok';

    // ÇYM metni
    const cymText = ticket.cym_text || '';
    const cymSection = cymText ? `
        <div class="accordion-cym">
            <div class="cym-header">
                <i class="fa-solid fa-phone"></i>
                <span>Çağrı Merkezi Notu</span>
                <button class="cym-copy-btn" onclick="copyToClipboard(this, '${escapeForAttribute(cymText)}')">
                    <i class="fa-solid fa-copy"></i> Kopyala
                </button>
            </div>
            <pre class="cym-content">${escapeHtml(cymText)}</pre>
        </div>
    ` : '';

    // Corpix AI Değerlendirmesi bölümü
    const llmEvaluation = ticket.llm_evaluation || '';
    const llmEvaluationSection = llmEvaluation ? `
        <div class="accordion-section accordion-llm-section">
            <div class="accordion-section-header llm-result-header">
                <i class="fa-solid fa-brain"></i>
                <span>Corpix AI Değerlendirmesi</span>
            </div>
            <div class="accordion-llm-content llm-result-content">
                ${formatLLMEvaluationForHistory(llmEvaluation)}
            </div>
        </div>
    ` : `
        <div class="accordion-section accordion-llm-section">
            <div class="llm-evaluate-container-history">
                <button class="llm-evaluate-btn-history" onclick="requestLLMEvaluationForHistory('${ticket.id}', this)" data-ticket-id="${ticket.id}">
                    <i class="fa-solid fa-brain"></i>
                    <span class="llm-btn-text">Corpix ile Değerlendir</span>
                </button>
            </div>
            <div class="llm-evaluation-result-history hidden" id="llmResult-${ticket.id}">
                <div class="llm-result-header">
                    <i class="fa-solid fa-brain"></i>
                    <span>Corpix AI Değerlendirmesi</span>
                </div>
                <div class="llm-result-content" id="llmResultContent-${ticket.id}"></div>
            </div>
        </div>
    `;

    item.innerHTML = `
        <div class="accordion-header" onclick="toggleAccordion(this)">
            <div class="accordion-header-left">
                <div class="accordion-icon">
                    <i class="fa-solid ${itemIcon}"></i>
                </div>
                <div class="accordion-info">
                    <h4 class="accordion-title">${escapeHtml(title)}</h4>
                    <div class="accordion-meta">
                        <span class="accordion-date">
                            <i class="fa-regular fa-clock"></i> ${date}
                        </span>
                        <span class="accordion-id">#${ticket.id}</span>
                    </div>
                </div>
            </div>
            <div class="accordion-header-right">
                <span class="accordion-badge ${badgeClass}">
                    <i class="fa-solid ${badgeIcon}"></i> ${badgeText}
                </span>
                <div class="accordion-chevron">
                    <i class="fa-solid fa-chevron-down"></i>
                </div>
            </div>
        </div>
        <div class="accordion-body">
            <!-- v2.21.6: Full conversation thread placeholder -->
            <div class="conversation-thread" id="thread-${ticket.id}" data-dialog-id="${isDialog ? ticket.id.replace('dialog-', '') : ''}" data-loaded="false">
                <div class="thread-loading">
                    <i class="fa-solid fa-spinner fa-spin"></i>
                    <span>Görüşme geçmişi yükleniyor...</span>
                </div>
            </div>

            ${cymSection}
        </div>
    `;

    return item;
}

// Accordion aç/kapat
function toggleAccordion(header) {
    const item = header.closest('.accordion-item');
    const isOpen = item.classList.contains('open');

    // Toggle current
    item.classList.toggle('open');

    // v2.21.6: Açıldığında tam mesaj geçmişini yükle (sadece ilk açılışta)
    if (!isOpen) {
        const threadContainer = item.querySelector('.conversation-thread');
        if (threadContainer && threadContainer.dataset.loaded === 'false') {
            const dialogId = threadContainer.dataset.dialogId;
            const ticketId = item.dataset.ticketId;

            if (dialogId) {
                loadDialogMessages(dialogId, threadContainer, ticketId);
            } else {
                // Ticket ise eski formatı göster (first/last)
                renderLegacyFormat(threadContainer, ticketId);
            }
        }
    }
}

// --- FORMATTING ---
// v2.30.1: modules/ticket_formatter.js modülüne taşındı.


// 🔍 Arama fonksiyonu
function searchTicketHistory() {
    const searchInput = document.getElementById("historySearchInput");
    const startDateInput = document.getElementById("historyStartDate");
    const endDateInput = document.getElementById("historyEndDate");

    _searchQuery = searchInput?.value || '';
    _startDate = startDateInput?.value || '';
    _endDate = endDateInput?.value || '';

    // İlk sayfadan başla ve yeniden yükle
    loadTicketHistory(true, 1);
}

// 🗑️ Aramayı temizle
function clearSearch() {
    const searchInput = document.getElementById("historySearchInput");
    const startDateInput = document.getElementById("historyStartDate");
    const endDateInput = document.getElementById("historyEndDate");
    const sourceTypeSelect = document.getElementById("sourceTypeFilter");

    if (searchInput) searchInput.value = '';
    if (startDateInput) startDateInput.value = '';
    if (endDateInput) endDateInput.value = '';
    if (sourceTypeSelect) sourceTypeSelect.value = '';

    _searchQuery = '';
    _startDate = '';
    _endDate = '';
    _sourceTypeFilter = '';

    // İlk sayfadan başla ve yeniden yükle
    loadTicketHistory(true, 1);
}


// Event Listener: Geçmiş Çözümler sekmesi - ARTIK home_page.js showSection'dan çağrılıyor
// Tab/Menu listener'ları KALDIRILDI - çift yükleme önlendi

const refreshHistoryBtn = document.getElementById("btnRefreshHistory");
const historySearchBtn = document.getElementById("btnSearchHistory");
const historyClearBtn = document.getElementById("btnClearSearch");
const historySearchInput = document.getElementById("historySearchInput");
const sourceTypeFilterSelect = document.getElementById("sourceTypeFilter");

// Yenile butonu (forceRefresh ile cache atla)
if (refreshHistoryBtn) {
    refreshHistoryBtn.addEventListener("click", async () => {
        console.log('[TicketHistory] Yenile tıklandı');
        refreshHistoryBtn.classList.add("loading");
        await loadTicketHistory(true);  // forceRefresh = true
        setTimeout(() => {
            refreshHistoryBtn.classList.remove("loading");
        }, 500);
    });
}

// Arama butonu
if (historySearchBtn) {
    historySearchBtn.addEventListener("click", () => {
        searchTicketHistory();
    });
}

// Temizle butonu
if (historyClearBtn) {
    historyClearBtn.addEventListener("click", () => {
        clearSearch();
    });
}

// Enter tuşu ile arama
if (historySearchInput) {
    historySearchInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
            searchTicketHistory();
        }
    });
}

// v2.21.1: Tür filtresi değişikliği
if (sourceTypeFilterSelect) {
    sourceTypeFilterSelect.addEventListener("change", () => {
        _sourceTypeFilter = sourceTypeFilterSelect.value;
        console.log('[TicketHistory] Source type filter:', _sourceTypeFilter);
        loadTicketHistory(true, 1);
    });
}

// 📅 Date Range Picker - Türkçe tarih gösterimi
const dateRangeBtn = document.getElementById("dateRangeBtn");
const dateRangeText = document.getElementById("dateRangeText");
const startDateInput = document.getElementById("historyStartDate");
const endDateInput = document.getElementById("historyEndDate");

// --- DATE RANGE ---
// v2.30.1: modules/ticket_date_range.js modülüne taşındı.


// Sayfa yüklendiğinde tarih inputlarını başlat
document.addEventListener("DOMContentLoaded", initializeDateInputs);
// Eğer DOM zaten yüklendiyse hemen çalıştır
if (document.readyState !== 'loading') {
    initializeDateInputs();
}

// Global erişim
window.toggleAccordion = toggleAccordion;
window.copyToClipboard = copyToClipboard;
window.loadTicketHistory = loadTicketHistory;
window.loadTicketHistoryDebounced = loadTicketHistoryDebounced;
window.searchTicketHistory = searchTicketHistory;
window.clearSearch = clearSearch;
window.requestLLMEvaluationForHistory = requestLLMEvaluationForHistory;
window.loadDialogMessages = loadDialogMessages;

// ========================================
// v2.21.6: FULL DIALOG MESSAGES LOADING
// ========================================

// --- DIALOG RENDER ---
// v2.30.1: modules/ticket_dialog_render.js modülüne taşındı.


// ========================================
// CORPIX AI DEĞERLENDİRME FONKSİYONLARI
// ========================================

// --- LLM EVALUATION ---
// v2.30.1: modules/ticket_llm_eval.js modülüne taşındı.

