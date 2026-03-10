/**
 * Organization Management - Helper Functions
 */

// API Request Helper
async function makeAuthRequest(url, options = {}) {
    const token = localStorage.getItem('access_token');
    const headers = {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
        ...options.headers
    };

    const response = await fetch(`${window.API_BASE_URL || 'http://localhost:8002'}${url}`, {
        ...options,
        headers
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(error.detail || 'API Error');
    }

    return response.json();
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
