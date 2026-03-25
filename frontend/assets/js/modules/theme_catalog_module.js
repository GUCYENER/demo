/**
 * VYRA Theme Catalog Module
 * ==========================
 * Sistem Parametreleri > Tasarım sekmesinde
 * 11 hazır SaaS temasını kart grid görünümünde listeler.
 * v2.59.0
 */
window.ThemeCatalogModule = (function () {
    'use strict';

    const API_BASE = window.API_BASE_URL || '';
    let themes = [];

    function getToken() {
        return localStorage.getItem('access_token') || '';
    }

    async function load() {
        const grid = document.getElementById('themeCatalogGrid');
        if (!grid) return;

        try {
            const res = await fetch(API_BASE + '/api/themes/', {
                headers: { 'Authorization': 'Bearer ' + getToken() }
            });
            if (!res.ok) throw new Error('Tema listesi alınamadı');
            themes = await res.json();
            // preview_colors JSON string olabilir, parse et
            themes = themes.map(t => {
                if (typeof t.preview_colors === 'string') {
                    try { t.preview_colors = JSON.parse(t.preview_colors); } catch(e) {}
                }
                return t;
            });
            render(grid);
        } catch (err) {
            console.error('[ThemeCatalog] Yükleme hatası:', err);
            grid.innerHTML = '<p class="theme-error">Tema listesi yüklenemedi.</p>';
        }
    }

    function render(grid) {
        if (!themes.length) {
            grid.innerHTML = '<p class="theme-empty">Henüz tanımlı tema yok.</p>';
            return;
        }

        const cards = themes.map(t => {
            const colors = t.preview_colors || [];
            const gradientBar = colors.length >= 2
                ? `background: linear-gradient(135deg, ${colors[0]} 0%, ${colors[1]} 100%);`
                : `background: ${colors[0] || '#666'};`;

            return `
            <div class="theme-card" data-theme-id="${t.id}">
                <div class="theme-card-gradient" style="${gradientBar}"></div>
                <div class="theme-card-body">
                    <h4 class="theme-card-title">${escapeHtml(t.name)}</h4>
                    <p class="theme-card-desc">${escapeHtml(t.description || '')}</p>
                    <div class="theme-card-colors">
                        ${colors.map(c => `<span class="theme-color-dot" style="background:${c};" title="${c}"></span>`).join('')}
                    </div>
                </div>
                <div class="theme-card-footer">
                    <span class="theme-card-code">${escapeHtml(t.code)}</span>
                </div>
            </div>`;
        }).join('');

        grid.innerHTML = cards;
    }

    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    return { load: load };
})();
