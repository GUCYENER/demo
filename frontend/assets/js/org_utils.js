/**
 * Organization Management - Helper Functions
 */

// API Request Helper
// v3.34.0: vyraFetch delegate — friendly Türkçe error contract (502/503/504,
// network failure, JSON parse) merkezi olarak helper'da. `url` parametresi
// `/organizations` gibi başlangıç eğik çizgili path bekler (API_BASE_URL
// prefix'i vyraFetch içinde uygulanır). options.body objesi otomatik
// JSON.stringify edilir — caller'lar `JSON.stringify` çağırmamalıdır.
async function makeAuthRequest(url, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    // Eski caller'lar zaten JSON.stringify ediyor olabilir — bir kez daha
    // stringify etmemek için string body geldiğinde JSON.parse'la geri çevir.
    let body = options.body;
    if (typeof body === 'string') {
        try { body = JSON.parse(body); } catch (_) { /* binary/text → vyraFetch koruyamaz */ }
    }
    return window.vyraFetch(url, { method, body: body || null, auth: true });
}

// Loading Helpers
function showLoading(containerId) {
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-spinner fa-spin fa-3x"></i>
                <p>Yükleniyor...</p>
            </div>
        `;
    }
}

function hideLoading(containerId) {
    // Handled by render functions
}
