/**
 * VYRA Branding Engine
 * ====================
 * Login ve Home ekranlarında firma bazlı dinamik CSS tema,
 * uygulama adı ve logo uygulaması.
 * v2.59.0
 */
(function() {
    'use strict';

    var STORAGE_KEY = 'vyra_company_branding';

    /**
     * CSS değişkenlerini document root'a uygular.
     * @param {Object} cssVars - { "--gold": "#xxx", ... }
     */
    function applyThemeCSS(cssVars) {
        if (!cssVars || typeof cssVars !== 'object') return;
        var root = document.documentElement;
        Object.keys(cssVars).forEach(function(key) {
            root.style.setProperty(key, cssVars[key]);
        });
    }

    /**
     * v2.60.1: Accent renginin parlaklığına göre kontrast metin rengi hesaplar.
     * Açık accent (teal, sarı, yeşil) → koyu metin (#111827)
     * Koyu accent (mor, lacivert) → beyaz metin (#ffffff)
     */
    function getContrastTextColor(hexColor) {
        if (!hexColor || hexColor.charAt(0) !== '#') return '#ffffff';
        var hex = hexColor.replace('#', '');
        if (hex.length === 3) hex = hex[0]+hex[0]+hex[1]+hex[1]+hex[2]+hex[2];
        var r = parseInt(hex.substring(0, 2), 16);
        var g = parseInt(hex.substring(2, 4), 16);
        var b = parseInt(hex.substring(4, 6), 16);
        var luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
        return luminance > 0.55 ? '#111827' : '#ffffff';
    }

    /**
     * v2.60.1: HEX rengini rgba formatına dönüştürür.
     */
    function hexToRgba(hexColor, alpha) {
        if (!hexColor || hexColor.charAt(0) !== '#') return 'rgba(107,114,128,' + alpha + ')';
        var hex = hexColor.replace('#', '');
        if (hex.length === 3) hex = hex[0]+hex[0]+hex[1]+hex[1]+hex[2]+hex[2];
        var r = parseInt(hex.substring(0, 2), 16);
        var g = parseInt(hex.substring(2, 4), 16);
        var b = parseInt(hex.substring(4, 6), 16);
        return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
    }

    /**
     * Tema accent rengine göre hardcoded mavi renkleri override eden dinamik CSS inject eder.
     * @param {Object} modeVars - Aktif mod CSS değişkenleri { "--gold": "#xxx", ... }
     */
    function injectAccentOverride(modeVars) {
        if (!modeVars || !modeVars['--gold']) return;
        var accent = modeVars['--gold'];
        var accent2 = modeVars['--gold-2'] || accent;
        var accentDim = modeVars['--gold-dim'] || 'rgba(234,179,8,0.12)';
        var accentGlow = modeVars['--gold-glow'] || 'rgba(234,179,8,0.18)';
        var gradAcc = modeVars['--grad-acc'] || 'linear-gradient(135deg,' + accent + ',' + accent2 + ')';
        var gradBtn = modeVars['--grad-btn'] || gradAcc;
        // v2.60.1: Kontrast metin rengi — accent üzerinde okunabilir metin
        var primaryOn = getContrastTextColor(accent);
        var accentFocusShadow = '0 0 0 3px ' + hexToRgba(accent, 0.15);

        // Eski style varsa kaldır
        var old = document.getElementById('vyra-accent-override');
        if (old) old.remove();

        var style = document.createElement('style');
        style.id = 'vyra-accent-override';
        style.textContent = [
            /* ==============================================
               GLOBAL CSS KÖK DEĞİŞKEN OVERRIDE
               var() kullanan TÜM dosyalar otomatik düzelir
               ============================================== */
            ':root {',
            /* global.css değişkenleri */
            '  --secondary: ' + accent + ' !important;',
            '  --secondary-light: ' + accent + ' !important;',
            '  --secondary-dark: ' + accent2 + ' !important;',
            '  --accent-purple: ' + accent + ' !important;',
            '  --accent-indigo: ' + accent + ' !important;',
            '  --accent-indigo-light: ' + accent + ' !important;',
            '  --accent-indigo-subtle: ' + accent + ' !important;',
            '  --primary: ' + accent + ' !important;',
            '  --primary-light: ' + accent + ' !important;',
            '  --primary-dark: ' + accent2 + ' !important;',
            '  --primary-darker: ' + accent2 + ' !important;',
            '  --shadow-primary: 0 4px 16px ' + accentGlow + ' !important;',
            '  --shadow-secondary: 0 4px 16px ' + accentGlow + ' !important;',
            '  --border-focus: ' + accent + ' !important;',
            '  --primary-on: ' + primaryOn + ' !important;',
            '  --primary-focus-shadow: ' + accentFocusShadow + ' !important;',
            /* home.html inline CSS değişkenleri */
            '  --accent: ' + accent + ' !important;',
            '  --accent-2: ' + accent2 + ' !important;',
            '  --accent-glow: ' + accentGlow + ' !important;',
            '  --accent-subtle: ' + accentDim + ' !important;',
            '  --grad-logo: ' + gradBtn + ' !important;',
            '  --grad-acc: ' + gradAcc + ' !important;',
            '  --grad-send: ' + gradBtn + ' !important;',
            '  --border-accent: ' + (modeVars['--border-accent'] || accentGlow) + ' !important;',
            '  --text-acc: ' + accent + ' !important;',
            '  --bg-msg-user: ' + accentDim + ' !important;',
            '  --orb-1: ' + accentDim + ' !important;',
            '  --orb-2: ' + accentDim + ' !important;',
            '  --shadow-input: ' + (modeVars['--shadow-input'] || '0 0 0 1px ' + accent + ', 0 0 18px ' + accentDim) + ' !important;',
            '}',
            /* ==============================================
               HOME.CSS - Sidebar, Tab, Button, İnput
               ============================================== */
            // Sidebar active
            '.menu-item.active { background: linear-gradient(135deg, ' + accentDim + ' 0%, rgba(0,0,0,0.05) 100%) !important; color: ' + accent + ' !important; border-color: ' + accentGlow + ' !important; box-shadow: 0 4px 12px ' + accentGlow + ' !important; }',
            '.menu-item.active i { color: ' + accent + ' !important; }',
            // Sidebar logo
            '.sb-logo-icon { background: ' + gradBtn + ' !important; box-shadow: 0 0 0 1px rgba(255,255,255,0.10), 0 0 40px ' + accentGlow + ', 0 8px 28px rgba(0,0,0,0.4) !important; }',
            // Topbar
            '.tb-btn-primary { background: ' + gradBtn + ' !important; }',
            '.tb-agent-avatar { background: ' + gradBtn + ' !important; }',
            // Tab active/hover
            '.modern-tab:hover, .tab-button:hover, .tab:hover { border-color: ' + accent + ' !important; }',
            '.modern-tab.active, .tab-button.active, .tab.active { background: ' + gradBtn + ' !important; border-color: ' + accent + ' !important; box-shadow: 0 4px 16px ' + accentGlow + ' !important; }',
            // Avatar
            '.avatar-initials { background: ' + gradBtn + ' !important; border-color: ' + accent + ' !important; box-shadow: 0 4px 16px ' + accentGlow + ' !important; }',
            '.profile-avatar-wrapper img { border-color: ' + accent + ' !important; }',
            '.role-badge.admin { background: ' + gradBtn + ' !important; border-color: ' + accent + ' !important; }',
            // Buttons
            '.main-btn { background: ' + gradBtn + ' !important; box-shadow: 0 4px 16px ' + accentGlow + ' !important; }',
            '.textarea-send-btn:not(:disabled) { background: ' + gradBtn + ' !important; box-shadow: 0 4px 16px ' + accentGlow + ' !important; }',
            '.logout-btn { background: ' + gradBtn + ' !important; }',
            '.tab-fav-btn:hover, .tab-fav-btn.favorited { color: ' + accent + ' !important; }',
            // Input focus
            '.input-textarea:focus { border-color: ' + accent + ' !important; box-shadow: 0 0 0 4px ' + accentDim + ' !important; }',
            '.textarea-attach-btn:hover { background: ' + accentDim + ' !important; border-color: ' + accent + ' !important; color: ' + accent + ' !important; }',
            '.loading-box { border-left-color: ' + accent + ' !important; }',
            /* ==============================================
               DIALOG-CHAT.CSS - Sohbet ikonları, butonları
               ============================================== */
            '.mode-card:hover { border-color: ' + accent + ' !important; }',
            '.mode-card.active { border-color: ' + accent + ' !important; box-shadow: 0 0 16px ' + accentGlow + ' !important; }',
            '.msg-badge-score { background: ' + accentDim + ' !important; color: ' + accent + ' !important; }',
            '.dt-enhance-btn { background: ' + gradBtn + ' !important; }',
            '.dt-enhance-btn:hover { box-shadow: 0 4px 16px ' + accentGlow + ' !important; }',
            '.sohbet-btn { background: ' + gradBtn + ' !important; }',
            '.sohbet-btn:hover { box-shadow: 0 6px 20px ' + accentGlow + ' !important; }',
            '.chat-bubble-assistant .source-link { color: ' + accent + ' !important; }',
            '.streaming-cursor { background: ' + accent + ' !important; }',
            /* ==============================================
               RAG_UPLOAD.CSS - Dosya yükleme, arama
               ============================================== */
            '.rag-upload-zone:hover, .rag-upload-zone.drag-over { border-color: ' + accent + ' !important; }',
            '.rag-action-btn { color: ' + accent + ' !important; }',
            '.rag-action-btn:hover { background: ' + accentDim + ' !important; }',
            '.source-badge { background: ' + accentDim + ' !important; color: ' + accent + ' !important; }',
            /* ==============================================
               MODAL.CSS - Modal butonları
               ============================================== */
            '.modal-btn-primary, .vyra-modal-ok { background: ' + gradBtn + ' !important; color: #fff !important; }',
            '.modal-btn-primary:hover, .vyra-modal-ok:hover { box-shadow: 0 4px 16px ' + accentGlow + ' !important; }',
            /* ==============================================
               AUTHORIZATION.CSS - Yetkilendirme
               ============================================== */
            '.auth-toggle-active { background: ' + gradBtn + ' !important; }',
            '.auth-role-badge.active { background: ' + accentDim + ' !important; border-color: ' + accent + ' !important; color: ' + accent + ' !important; }',
            /* ==============================================
               TICKET-HISTORY.CSS - Ticket kartları
               ============================================== */
            '.ticket-status-badge.open { background: ' + accentDim + ' !important; color: ' + accent + ' !important; }',
            /* ==============================================
               NOTIFICATION + MATURITY + DS_LEARNING
               ============================================== */
            '.notification-action-btn { color: ' + accent + ' !important; }',
            '.maturity-bar-fill { background: ' + gradBtn + ' !important; }',
            '.cl-status-running { color: ' + accent + ' !important; }',
            '.cl-countdown { background: ' + accentDim + ' !important; color: ' + accent + ' !important; }',
            /* ==============================================
               HOME.CSS — Tüm hardcoded accent seçicileri
               ============================================== */
            // Section / Form / Select / Textarea / Input focus
            '.section-title i { color: ' + accent + ' !important; }',
            '.form-label i { color: ' + accent + ' !important; }',
            '.modern-select:focus { border-color: ' + accent + ' !important; }',
            '.form-textarea:focus { border-color: ' + accent + ' !important; }',
            '.num-spinner-btn { color: ' + accent + ' !important; }',
            '.num-spinner-wrap:focus-within { border-color: ' + accent + ' !important; }',
            'textarea.drag-over { border-color: ' + accent + ' !important; }',
            '.input-textarea:focus { border-color: ' + accent + ' !important; }',
            // Sidebar / Logo / Avatar / Tab
            '.sb-logo-icon { background: ' + gradBtn + ' !important; }',
            '.user-avatar-small { background: ' + gradBtn + ' !important; }',
            '.message-avatar.user { background: ' + gradBtn + ' !important; }',
            '.avatar-initials { background: ' + gradBtn + ' !important; }',
            '.format-badge { color: ' + accent + ' !important; }',
            '.tag-badge { color: ' + accent + ' !important; }',
            '.text-blue-400 { color: ' + accent + ' !important; }',
            '.text-indigo-400 { color: ' + accent + ' !important; }',
            '.hover\\:bg-blue-700:hover { background-color: ' + accent2 + ' !important; }',
            // LLM modal / result
            '.llm-modal-icon { background: ' + gradBtn + ' !important; }',
            '.llm-result-header i { color: ' + accent + ' !important; }',
            '.llm-result-header::before { background: ' + accent + ' !important; }',
            '.llm-result-content em { color: ' + accent + ' !important; }',
            '.llm-result-content ol li::before { background: ' + accent + ' !important; }',
            '.llm-steps-list li::before { background: ' + accent + ' !important; }',
            // ML training
            '.ml-hero-icon { background: ' + gradBtn + ' !important; }',
            '.ml-section-header i { color: ' + accent + ' !important; }',
            '.ml-stat-icon.model { color: ' + accent + ' !important; }',
            '.ml-stat-icon.pending { color: ' + accent + ' !important; }',
            '.ml-stat-info .stat-value.has-model { color: ' + accent + ' !important; }',
            '.training-progress-fill { background: ' + gradBtn + ' !important; }',
            '.training-progress-text { color: ' + accent + ' !important; }',
            // Step / Progress
            '.step-number { background: ' + gradBtn + ' !important; }',
            '.upload-icon { background: ' + gradBtn + ' !important; }',
            '.upload-progress-fill { background: ' + gradBtn + ' !important; }',
            '.files-count-badge { background: ' + gradBtn + ' !important; }',
            // Ticket
            '.ticket-field-label { color: ' + accent + ' !important; }',
            '.ticket-btn-copy { background: ' + gradBtn + ' !important; }',
            '.ticket-btn-copy:hover { background: ' + gradBtn + ' !important; }',
            '.ticket-summary-modal .ticket-icon { background: ' + gradBtn + ' !important; }',
            '.ticket-summary-text .loading-spinner { color: ' + accent + ' !important; }',
            // Logout
            '.logout-btn { background: ' + gradBtn + ' !important; }',
            '.logout-btn:hover { background: ' + gradBtn + ' !important; }',
            // SAAS toggle
            '.saas-toggle input:checked + .saas-toggle-track { background: ' + gradBtn + ' !important; }',
            // Loading
            '.loading-box { border-left-color: ' + accent + ' !important; }',
            /* ==============================================
               DIALOG-CHAT.CSS — Sohbet / Quick Reply
               ============================================== */
            '.message-bubble p:not(.dt-response p) strong { color: ' + accent + ' !important; }',
            '.message-bubble p:first-child strong { background: ' + gradBtn + ' !important; }',
            '.thread-message.thread-assistant { border-left-color: ' + accent + ' !important; }',
            '.thread-assistant .thread-message-header { color: ' + accent + ' !important; }',
            '.quick-reply-btn.corpix-yes { color: ' + accent + ' !important; }',
            '.quick-reply-btn.corpix-yes:hover { border-color: ' + accent + ' !important; }',
            '.quick-reply-btn.corpix-retry:hover { border-color: ' + accent + ' !important; }',
            '.quick-reply-btn.corpix-mode-switch:hover { border-color: ' + accent + ' !important; }',
            '.feedback-btn-speak { color: ' + accent + ' !important; }',
            '.feedback-btn-speak:hover { border-color: ' + accent + ' !important; }',
            '.feedback-btn-speak.speaking { border-color: ' + accent + ' !important; }',
            '.feedback-btn.speak:hover { border-color: ' + accent + ' !important; color: ' + accent + ' !important; }',
            '.feedback-btn.speak.speaking { border-color: ' + accent + ' !important; color: ' + accent + ' !important; }',
            '.dt-bullet-dot { background: ' + accent + ' !important; }',
            '.dt-header-count { color: ' + accent + ' !important; }',
            '.dt-source-file { color: ' + accent + ' !important; }',
            '.dt-source-sheet { color: ' + accent + ' !important; }',
            '.dt-sources-header i { color: ' + accent + ' !important; }',
            '.vyra-corpix-btn { background: ' + gradBtn + ' !important; }',
            '.vyra-corpix-btn:hover { background: ' + gradBtn + ' !important; }',
            /* ==============================================
               RAG_UPLOAD.CSS — Dosya yükleme
               ============================================== */
            '.rag-upload-zone.drag-over { border-color: ' + accent + ' !important; }',
            '.rag-card-number { background: ' + gradBtn + ' !important; }',
            '.rag-card-select-btn { color: ' + accent + ' !important; }',
            '.rag-checkbox { accent-color: ' + accent + ' !important; }',
            '.rag-checkbox:checked { background-color: ' + accent + ' !important; }',
            '.rag-org-title i { color: ' + accent + ' !important; }',
            '.rag-result-file i { color: ' + accent + ' !important; }',
            '.rag-role-codes-label { color: ' + accent + ' !important; }',
            '.rag-selection-box { border-left-color: ' + accent + ' !important; }',
            '.rag-selection-card:hover { border-color: ' + accent + ' !important; }',
            '.rag-selection-header { color: ' + accent + ' !important; }',
            '.rag-stat-icon.chunks { background: ' + gradBtn + ' !important; }',
            '.rag-stat-icon.files { background: ' + gradBtn + ' !important; }',
            '.rag-status-badge.processing { color: ' + accent + ' !important; }',
            '.rag-switch-btn { color: ' + accent + ' !important; }',
            '.rag-title i { color: ' + accent + ' !important; }',
            '.file-icon.doc { color: ' + accent + ' !important; }',
            '.file-icon.xls { color: ' + accent + ' !important; }',
            '.file-info .file-name-link:hover { color: ' + accent + ' !important; }',
            '.file-org-edit-info i { color: ' + accent + ' !important; }',
            '.image-preview-label i { color: ' + accent + ' !important; }',
            /* ==============================================
               AUTHORIZATION.CSS — Yetkilendirme
               ============================================== */
            '.auth-toggle-active { background: ' + gradBtn + ' !important; }',
            '.auth-role-badge.active { background: ' + accentDim + ' !important; border-color: ' + accent + ' !important; color: ' + accent + ' !important; }',
            '.role-selector-btn.active { background: ' + gradBtn + ' !important; }',
            /* ==============================================
               TICKET-HISTORY.CSS — Ticket kartları
               ============================================== */
            '.ticket-status-badge.open { background: ' + accentDim + ' !important; color: ' + accent + ' !important; }',
            '.history-rag-filename { color: ' + accent + ' !important; }',
            '.history-rag-heading { color: ' + accent + ' !important; }',
            '.history-rag-type { color: ' + accent + ' !important; }',
            '.sample-answer-btn { color: ' + accent + ' !important; }',
            '.sample-answer-btn:hover:not(:disabled) { border-color: ' + accent + ' !important; }',
            '.sample-intent { color: ' + accent + ' !important; }',
            '.sample-intent[data-intent=\"HOW_TO\"] { color: ' + accent + ' !important; }',
            '.sample-intent[data-intent=\"LIST_REQUEST\"] { color: ' + accent + ' !important; }',
            '.sample-query { color: ' + accent + ' !important; }',
            '.samples-filter-badge { color: ' + accent + ' !important; }',
            '.samples-filter-input:focus { border-color: ' + accent + ' !important; }',
            '.samples-filter-select:focus { border-color: ' + accent + ' !important; }',
            '.samples-link { color: ' + accent + ' !important; }',
            '.samples-page-btn:hover:not(:disabled) { color: ' + accent + ' !important; }',
            '.samples-page-info strong { color: ' + accent + ' !important; }',
            '.samples-table th.sortable.sort-desc .samples-sort-icon { color: ' + accent + ' !important; }',
            '.type-badge.manual { color: ' + accent + ' !important; }',
            '.status-badge.running { color: ' + accent + ' !important; }',
            '.learned-answer-question i { color: ' + accent + ' !important; }',
            /* ==============================================
               MODAL.CSS — Modal butonları
               ============================================== */
            '.modal-btn-primary, .vyra-modal-ok { background: ' + gradBtn + ' !important; color: #fff !important; }',
            '.modal-btn-primary:hover, .vyra-modal-ok:hover { box-shadow: 0 4px 16px ' + accentGlow + ' !important; }',
            '.vyra-modal-btn.confirm { background: ' + gradBtn + ' !important; }',
            '.vyra-modal-icon.info { color: ' + accent + ' !important; }',
            '.vyra-modal-icon.question { color: ' + accent + ' !important; }',
            '.vyra-modal-icon.success { color: ' + accent + ' !important; }',
            '.vyra-enhance-success { color: ' + accent + ' !important; }',
            '.modal-box .modal-footer .btn.primary { background: ' + gradBtn + ' !important; }',
            '.modal-box .modal-header h3 i { color: ' + accent + ' !important; }',
            /* ==============================================
               TOAST.CSS — Toast mesajları
               ============================================== */
            '.toast-info { border-left-color: ' + accent + ' !important; }',
            '.toast-info i { color: ' + accent + ' !important; }',
            '.toast-success { border-left-color: ' + accent + ' !important; }',
            '.toast-success i { color: ' + accent + ' !important; }',
            /* ==============================================
               NOTIFICATION.CSS — Bildirimler
               ============================================== */
            '.notification-bell:hover i { color: ' + accent + ' !important; }',
            '.notification-header h3 i { color: ' + accent + ' !important; }',
            '.notification-icon.info { color: ' + accent + ' !important; }',
            '.notification-icon.success { color: ' + accent + ' !important; }',
            '.notification-item.unread { border-left-color: ' + accent + ' !important; }',
            /* ==============================================
               MATURITY_SCORE_MODAL.CSS — Olgunluk skoru
               ============================================== */
            '.maturity-analyzing .spinner { border-top-color: ' + accent + ' !important; }',
            '.maturity-badge.score-good { color: ' + accent + ' !important; }',
            '.maturity-btn-enhance { background: ' + gradBtn + ' !important; }',
            '.maturity-btn-enhance:hover { background: ' + gradBtn + ' !important; }',
            '.maturity-btn-primary { background: ' + gradBtn + ' !important; }',
            '.maturity-file-tab.active { background: ' + gradBtn + ' !important; border-color: ' + accent + ' !important; }',
            '.maturity-modal-header h3 i { color: ' + accent + ' !important; }',
            '.maturity-score-label.good { color: ' + accent + ' !important; }',
            /* ==============================================
               DOCUMENT_ENHANCER_MODAL.CSS — Doküman geliştirici
               ============================================== */
            '.enhancer-btn-download { background: ' + gradBtn + ' !important; }',
            '.enhancer-btn-download:hover { background: ' + gradBtn + ' !important; }',
            '.enhancer-btn-upload { background: ' + gradBtn + ' !important; }',
            '.enhancer-btn-upload:hover { background: ' + gradBtn + ' !important; }',
            '.enhancer-change-badge.heading-added { color: ' + accent + ' !important; }',
            '.enhancer-confirm-btn.confirm { background: ' + gradBtn + ' !important; }',
            '.enhancer-confirm-btn.confirm:hover { background: ' + gradBtn + ' !important; }',
            '.enhancer-confirm-icon { color: ' + accent + ' !important; }',
            '.enhancer-explanation { color: ' + accent + ' !important; }',
            '.enhancer-icon-changed { color: ' + accent + ' !important; }',
            '.enhancer-loading-spinner { border-top-color: ' + accent + ' !important; }',
            '.enhancer-loading-step { color: ' + accent + ' !important; }',
            '.enhancer-modal-title i { color: ' + accent + ' !important; }',
            '.enhancer-summary-card-value.sections { color: ' + accent + ' !important; }',
            /* ==============================================
               FILE_GUIDELINES_MODAL.CSS — Dosya kılavuzu
               ============================================== */
            '.file-guidelines-title i { color: ' + accent + ' !important; }',
            '.file-guidelines-tab[data-tab=\"docx\"] i { color: ' + accent + ' !important; }',
            '.file-guidelines-tab[data-tab=\"xlsx\"] i { color: ' + accent + ' !important; }',
            '.guidelines-intro i { color: ' + accent + ' !important; }',
            '.guidelines-list.docx-rules .rule-icon { color: ' + accent + ' !important; }',
            /* ==============================================
               LDAP_SETTINGS.CSS — LDAP ayarları
               ============================================== */
            '.ldap-org-checkbox-item input[type=\"checkbox\"] { accent-color: ' + accent + ' !important; }',
            '.ldap-org-checkbox-item:has(input:checked) .ldap-org-checkbox-label { color: ' + accent + ' !important; }',
            '.ldap-org-checkbox-label i { color: ' + accent + ' !important; }',
            '.ldap-profile-notice i { color: ' + accent + ' !important; }',
            '.ldap-profile-notice strong { color: ' + accent + ' !important; }',
            /* ==============================================
               PERMISSIONS.CSS — İzinler
               ============================================== */
            '.perm-checkbox { accent-color: ' + accent + ' !important; }',
            '.perm-checkbox:checked+.perm-checkbox-text { color: ' + accent + ' !important; }',
            '.permission-info i { color: ' + accent + ' !important; }',
            '.permission-type-badge.menu { color: ' + accent + ' !important; }',
            '.permissions-loading i { color: ' + accent + ' !important; }',
            '.permissions-panel-title i { color: ' + accent + ' !important; }',
            /* ==============================================
               ORG_PERMISSIONS.CSS — Organizasyon izinleri
               ============================================== */
            '.org-badge-sm { background: ' + gradBtn + ' !important; }',
            '.org-modal-checkbox { accent-color: ' + accent + ' !important; }',
            '.org-modal-filter-checkbox input[type=\"checkbox\"] { accent-color: ' + accent + ' !important; }',
            '.org-modal-header h3 i { color: ' + accent + ' !important; }',
            '.org-pag-btn.active { background: ' + gradBtn + ' !important; border-color: ' + accent + ' !important; }',
            '.org-perm-domain-badge { color: ' + accent + ' !important; }',
            '.org-perm-org-badge { color: ' + accent + ' !important; }',
            '.org-search-box:focus-within { border-color: ' + accent + ' !important; }',
            /* ==============================================
               DATA_SOURCES.CSS — Veri kaynakları
               ============================================== */
            '.ds-wizard-btn.primary { background: ' + gradBtn + ' !important; }',
            '.ds-wizard-start-btn { background: ' + gradBtn + ' !important; }',
            '.ds-wizard-intro-icon i { color: ' + accent + ' !important; }',
            '.ds-wizard-intro-list li i { color: ' + accent + ' !important; }',
            '.ds-wizard-title i { color: ' + accent + ' !important; }',
            '.ds-step-loading-bar-inner { background: ' + gradBtn + ' !important; }',
            '.ds-step-loading-icon { color: ' + accent + ' !important; }',
            '.ds-step.running .ds-step-circle { border-color: ' + accent + ' !important; color: ' + accent + ' !important; }',
            '.ds-test-icon-wrap.ds-test-success { color: ' + accent + ' !important; }',
            '.ds-test-title.ds-test-success { color: ' + accent + ' !important; }',
            /* ==============================================
               DS_LEARNING.CSS — Veri öğrenme
               ============================================== */
            '.ds-lr-tab.active { border-bottom-color: ' + accent + ' !important; color: ' + accent + ' !important; }',
            '.ds-lr-stat-num { color: ' + accent + ' !important; }',
            '.ds-lr-card-question i { color: ' + accent + ' !important; }',
            '.ds-lr-answer-label { color: ' + accent + ' !important; }',
            '.ds-lr-job-filter label i { color: ' + accent + ' !important; }',
            '.ds-lr-job-select:focus { border-color: ' + accent + ' !important; }',
            '.ds-lr-type-badge.schema_description { color: ' + accent + ' !important; }',
            '.ds-obj-type-badge.table { color: ' + accent + ' !important; }',
            '.ds-job-type-badge.technology { color: ' + accent + ' !important; }',
            '.ds-job-type-badge.objects { color: ' + accent + ' !important; }',
            '.ds-job-detail-total-num { color: ' + accent + ' !important; }',
            '.ds-schedule-info i { color: ' + accent + ' !important; }',
            '.schedule-condition i { color: ' + accent + ' !important; }',
            '.schedule-condition select:focus { border-color: ' + accent + ' !important; }',
            '.schedule-field select:focus { border-color: ' + accent + ' !important; }',
            /* ==============================================
               SOLUTION / RESET
               ============================================== */
            '.solution-section-header i { color: ' + accent + ' !important; }',
            '.solution-alternative-header i { color: ' + accent + ' !important; }',
            '.solution-alternative-header span { color: ' + accent + ' !important; }',
            '.solution-list.alternative-list li::before { background: ' + accent + ' !important; }',
            '.solution-step-item.alternative .step-number-badge { background: ' + gradBtn + ' !important; }',
            '.reset-info-box { border-left-color: ' + accent + ' !important; }',
            '.reset-info-box strong { color: ' + accent + ' !important; }',
            '.reset-info-box>i { color: ' + accent + ' !important; }',
            /* ==============================================
               LDAP MODAL — Sarı butonlar
               ============================================== */
            '#ldapSettingModal .btn-primary-action { background: ' + gradBtn + ' !important; }',
            '.ldap-btn-save { background: ' + gradBtn + ' !important; }',
            '.ldap-btn-test { color: ' + accent + ' !important; border-color: ' + accent + ' !important; }',
            '.ldap-btn-test:hover { background: ' + accentDim + ' !important; }',
            /* ==============================================
               ORG PERMISSIONS — Ekle butonu, badge
               ============================================== */
            '.org-perm-add-form .btn-add-org { background: ' + gradBtn + ' !important; }',
            '.org-code-badge { border-color: ' + accentGlow + ' !important; color: ' + accent + ' !important; }',
            /* ==============================================
               DESIGN TAB — Seçili tema kartı
               ============================================== */
            '.design-theme-card.selected { border-color: ' + accent + ' !important; background: ' + accentDim + ' !important; }',
            '.design-theme-card.selected .dt-name { color: ' + accent + ' !important; }',
            '.design-save-btn { background: ' + gradBtn + ' !important; }',
            '.design-suggest-btn { color: ' + accent + ' !important; border-color: ' + accent + ' !important; }',
            '.design-suggest-btn:hover { background: ' + accentDim + ' !important; }',
            '.design-suggest-card:hover { border-color: ' + accent + ' !important; }',
            '.design-color-preview { border-color: ' + accent + ' !important; }',
            /* ==============================================
               SESSION TIMER — Oturum sayacı
               ============================================== */
            '#sessionTimer { color: ' + accent + ' !important; }',
            '.text-yellow-400 { color: ' + accent + ' !important; }',
            '.text-amber-400 { color: ' + accent + ' !important; }',
            /* ==============================================
               SİSTEM SIFIRLAMA — Reset sayıları
               ============================================== */
            '#totalRecordsToDelete { color: ' + accent + ' !important; }',
            '.reset-count-value { color: ' + accent + ' !important; }',
            '.reset-btn-danger { background: ' + gradBtn + ' !important; }',
            '.reset-section-title i { color: ' + accent + ' !important; }',
            /* ==============================================
               DS FORM — Data Sources form focus
               ============================================== */
            '.ds-form-select:focus { border-color: ' + accent + ' !important; }',
            '.ds-form-input:focus { border-color: ' + accent + ' !important; }',
            '.ds-details-section h4 i { color: ' + accent + ' !important; }',
            '.ds-card-actions .btn-edit { color: ' + accent + ' !important; }',
            '.ds-card-actions .btn-edit:hover { background: ' + accentDim + ' !important; }',
            '.ds-badge-type { background: ' + accentDim + ' !important; color: ' + accent + ' !important; }',
            /* ==============================================
               WARNING İKONLARI — Modal uyarı
               ============================================== */
            '.vyra-modal-icon.warning { color: ' + accent + ' !important; }',
            '.swal2-warning { border-color: ' + accent + ' !important; color: ' + accent + ' !important; }',
            '.swal2-confirm { background: ' + gradBtn + ' !important; }',
            /* ==============================================
               PROFİL — Profil düzenleme
               ============================================== */
            '.profile-edit-btn { background: ' + gradBtn + ' !important; }',
            '.profile-edit-btn:hover { box-shadow: 0 4px 16px ' + accentGlow + ' !important; }',
            '.profile-save-btn { background: ' + gradBtn + ' !important; }',
            '.profile-input:focus { border-color: ' + accent + ' !important; }',
            /* ==============================================
               SAAS KATEGORİ — Parametre
               ============================================== */
            '.saas-category-icon { color: ' + accent + ' !important; }',
            '.saas-section-title { color: ' + accent + ' !important; }',
            '.param-btn-save { background: ' + gradBtn + ' !important; }',
            '.param-btn-save:hover { box-shadow: 0 4px 16px ' + accentGlow + ' !important; }',
            /* ==============================================
               v2.60.1: KONTRAST — gradBtn arka planlı butonlarda metin rengi
               ============================================== */
            '.btn-primary { color: ' + primaryOn + ' !important; }',
            '.main-btn { color: ' + primaryOn + ' !important; }',
            '.logout-btn { color: ' + primaryOn + ' !important; }',
            '.tb-btn-primary { color: ' + primaryOn + ' !important; }',
            '.textarea-send-btn:not(:disabled) { color: ' + primaryOn + ' !important; }',
            '.modal-btn-primary, .vyra-modal-ok { color: ' + primaryOn + ' !important; }',
            '.vyra-modal-btn.confirm { color: ' + primaryOn + ' !important; }',
            '.swal2-confirm { color: ' + primaryOn + ' !important; }',
            '.profile-edit-btn { color: ' + primaryOn + ' !important; }',
            '.profile-save-btn { color: ' + primaryOn + ' !important; }',
            '.param-btn-save { color: ' + primaryOn + ' !important; }',
            '.design-save-btn { color: ' + primaryOn + ' !important; }',
            '.auth-toggle-active { color: ' + primaryOn + ' !important; }',
            '.step-number { color: ' + primaryOn + ' !important; }',
            '.upload-icon { color: ' + primaryOn + ' !important; }',
            '.files-count-badge { color: ' + primaryOn + ' !important; }',
            '.rag-card-number { color: ' + primaryOn + ' !important; }',
            '.org-badge-sm { color: ' + primaryOn + ' !important; }',
            '.ds-wizard-btn.primary { color: ' + primaryOn + ' !important; }',
            '.ds-wizard-start-btn { color: ' + primaryOn + ' !important; }',
            '.reset-btn-danger { color: ' + primaryOn + ' !important; }',
            '.role-badge.admin { color: ' + primaryOn + ' !important; }',
            '.sohbet-btn { color: ' + primaryOn + ' !important; }',
            '.vyra-corpix-btn { color: ' + primaryOn + ' !important; }',
            '.maturity-btn-enhance { color: ' + primaryOn + ' !important; }',
            '.maturity-btn-primary { color: ' + primaryOn + ' !important; }',
            '.enhancer-btn-download { color: ' + primaryOn + ' !important; }',
            '.enhancer-btn-upload { color: ' + primaryOn + ' !important; }',
            '.enhancer-confirm-btn.confirm { color: ' + primaryOn + ' !important; }',
            '.ldap-btn-save { color: ' + primaryOn + ' !important; }',
            '#ldapSettingModal .btn-primary-action { color: ' + primaryOn + ' !important; }',
            '.org-perm-add-form .btn-add-org { color: ' + primaryOn + ' !important; }',
            '.solution-step-item.alternative .step-number-badge { color: ' + primaryOn + ' !important; }',
            '.sb-logo-icon { color: ' + primaryOn + ' !important; }',
            '.avatar-initials { color: ' + primaryOn + ' !important; }',
            '.user-avatar-small { color: ' + primaryOn + ' !important; }',
            '.message-avatar.user { color: ' + primaryOn + ' !important; }',
            '.ml-hero-icon { color: ' + primaryOn + ' !important; }',
            '.llm-modal-icon { color: ' + primaryOn + ' !important; }',
            '.org-pag-btn.active { color: ' + primaryOn + ' !important; }',
            '.ticket-btn-copy { color: ' + primaryOn + ' !important; }',
            '.ticket-summary-modal .ticket-icon { color: ' + primaryOn + ' !important; }',
            '.dt-enhance-btn { color: ' + primaryOn + ' !important; }',
            '.rag-stat-icon.chunks { color: ' + primaryOn + ' !important; }',
            '.rag-stat-icon.files { color: ' + primaryOn + ' !important; }',
            '.role-selector-btn.active { color: ' + primaryOn + ' !important; }',
            '.maturity-file-tab.active { color: ' + primaryOn + ' !important; }',
            '.ds-step-loading-bar-inner { color: ' + primaryOn + ' !important; }',
            '.modal-box .modal-footer .btn.primary { color: ' + primaryOn + ' !important; }',
            '.modern-tab.active, .tab-button.active, .tab.active { color: ' + primaryOn + ' !important; }',
            '.training-progress-fill { color: ' + primaryOn + ' !important; }',
            '.upload-progress-fill { color: ' + primaryOn + ' !important; }',
            '.maturity-bar-fill { color: ' + primaryOn + ' !important; }',
            /* ==============================================
               v2.60.1: LOGIN PAGE — Kontrast ve focus shadow
               ============================================== */
            '.auth-form .btn-primary { color: ' + primaryOn + ' !important; }',
            '.form-group input:focus { box-shadow: ' + accentFocusShadow + ' !important; }',
            '.domain-select:focus { box-shadow: ' + accentFocusShadow + ' !important; }',
            '.btn-primary:hover { box-shadow: 0 6px 20px ' + hexToRgba(accent, 0.3) + ' !important; }',
            '.btn-primary.loading::after { border-color: ' + primaryOn + ' !important; border-top-color: transparent !important; }',
            /* ==============================================
               v2.60.1: PROFİL & YETKİLENDİRME — Kontrast
               ============================================== */
            '.btn-save-profile, .btn-change-password { color: ' + primaryOn + ' !important; background: ' + gradBtn + ' !important; }',
            '.btn-save-profile:hover, .btn-change-password:hover { box-shadow: 0 4px 12px ' + accentGlow + ' !important; }',
            '.profile-avatar { background: ' + gradBtn + ' !important; }',
            '.profile-avatar i { color: ' + primaryOn + ' !important; }',
            '.profile-section h4 { color: ' + accent + ' !important; }',
            '.profile-field input:focus { border-color: ' + accent + ' !important; box-shadow: ' + accentFocusShadow + ' !important; }',
            '.avatar-initials span { color: ' + primaryOn + ' !important; }',
            '.pending-alert { color: ' + accent + ' !important; }',
            '.status-badge.pending { color: ' + accent + ' !important; }',
            '.filter-checkbox input { accent-color: ' + accent + ' !important; }',
            '.modern-tab.active .tab-fav-btn { color: ' + hexToRgba(primaryOn === '#ffffff' ? '#ffffff' : '#111827', 0.5) + ' !important; }'
        ].join('\n');
        document.head.appendChild(style);
    }

    /**
     * Mevcut tema moduna göre CSS variables uygular.
     * @param {Object} themeData - { dark: {...}, light: {...} }
     */
    function applyThemeForCurrentMode(themeData) {
        if (!themeData) return;
        var mode = document.documentElement.getAttribute('data-theme') || 'dark';
        var vars = themeData[mode] || themeData['dark'];
        if (vars) {
            applyThemeCSS(vars);
            injectAccentOverride(vars);
        }
    }

    /**
     * Uygulama adını tüm sayfadaki dinamik alanlara uygular.
     * @param {string} appName - Firma uygulama adı
     */
    function applyAppName(appName) {
        if (!appName) return;

        // Login ekranı
        var ngssaiName = document.querySelector('.ngssai-name');
        if (ngssaiName) ngssaiName.textContent = appName;

        // Browser title
        var titleEl = document.querySelector('title');
        if (titleEl) {
            var currentTitle = titleEl.textContent;
            titleEl.textContent = currentTitle.replace(/NGSSAI|VYRA/g, appName);
        }

        // Version badge (login)
        var vBadge = document.getElementById('versionBadge');
        if (vBadge) {
            vBadge.textContent = vBadge.textContent.replace(/NGSSAI|VYRA/g, appName);
        }

        // Sidebar logo name (home)
        var sbName = document.querySelector('.sb-logo-name');
        if (sbName) sbName.textContent = appName;

        // Topbar agent name (home)
        var tbName = document.querySelector('.tb-agent-name');
        if (tbName) tbName.textContent = appName + ' Asistan';

        // Status bar version (home)
        var statusVer = document.getElementById('statusVersion');
        if (statusVer) {
            statusVer.textContent = statusVer.textContent.replace(/NGSSAI|VYRA/g, appName);
        }

        // Sidebar version (home)
        var sbVer = document.querySelector('.sb-version');
        if (sbVer) {
            sbVer.innerHTML = sbVer.innerHTML.replace(/NGSSAI|VYRA/g, appName);
        }

        // Dialog section header (partial — section_dialog.html)
        var dialogHeader = document.querySelector('#sectionDialog .tb-agent-name');
        if (dialogHeader) dialogHeader.textContent = appName + ' Asistan';

        // Dialog header title (partial — section_dialog.html)
        var dialogHeaderTitle = document.querySelector('.dialog-header-title');
        if (dialogHeaderTitle) dialogHeaderTitle.textContent = appName + ' Asistan';

        // Chat mode card — "VYRA ile Sohbet Et" → "DAHİ ile Sohbet Et"
        var chatModeTitle = document.querySelector('#modeChat .mc-title');
        if (chatModeTitle) {
            chatModeTitle.textContent = chatModeTitle.textContent.replace(/NGSSAI|VYRA/g, appName);
        }

        // Chat mode toggle label (partial — section_dialog.html)
        var chatModeLabel = document.getElementById('chatModeLabel');
        if (chatModeLabel) {
            chatModeLabel.textContent = chatModeLabel.textContent.replace(/NGSSAI|VYRA/g, appName);
        }

        // Chat mode toggle button title attribute
        var chatModeBtn = document.getElementById('chatModeToggleBtn');
        if (chatModeBtn) {
            var btnTitle = chatModeBtn.getAttribute('title') || '';
            chatModeBtn.setAttribute('title', btnTitle.replace(/NGSSAI|VYRA/g, appName));
        }
    }

    /**
     * Login ekranı sol paneldeki headline ve subtitle'ı günceller.
     * @param {string} headline - HTML destekli headline
     * @param {string} subtitle - Alt açıklama
     */
    function applyLoginContent(headline, subtitle) {
        // Guard: sadece login sayfasında çalış
        if (window.location.pathname.indexOf('login') === -1) return;
        var h1 = document.querySelector('.brand-h1');
        if (h1 && headline) h1.innerHTML = headline;

        var sub = document.querySelector('.brand-sub');
        if (sub && subtitle) sub.textContent = subtitle;
    }

    /**
     * Login ekranı feature kartlarını günceller.
     * @param {Array} features - [{title, desc, icon}]
     */
    function applyLoginFeatures(features) {
        // Guard: sadece login sayfasında çalış
        if (window.location.pathname.indexOf('login') === -1) return;
        if (!features || !Array.isArray(features)) return;
        var stack = document.querySelector('.feature-stack');
        if (!stack) return;

        var feats = stack.querySelectorAll('.feat');
        features.forEach(function(f, i) {
            if (feats[i]) {
                var title = feats[i].querySelector('.feat-title');
                var desc = feats[i].querySelector('.feat-desc');
                if (title) title.textContent = f.title;
                if (desc) desc.textContent = f.desc;
            }
        });
    }

    /**
     * Login ekranındaki sol üst logoyu firma logosuyla değiştirir.
     * @param {string} logoUrl - Logo URL'i
     */
    function applyLoginLogo(logoUrl) {
        // Guard: sadece login sayfasında çalış
        if (window.location.pathname.indexOf('login') === -1) return;
        if (!logoUrl) return;
        var API_BASE = window.API_BASE_URL || '';
        var logoIcon = document.querySelector('.ngssai-icon');
        if (!logoIcon) return;

        var img = new Image();
        img.onload = function() {
            logoIcon.innerHTML = '';
            img.className = 'login-company-logo-img';
            logoIcon.appendChild(img);
        };
        img.src = API_BASE + logoUrl;
    }

    /**
     * Browser tab favicon'ı firma logosuna günceller.
     * @param {string} logoUrl - Logo URL'i
     */
    function applyFavicon(logoUrl) {
        if (!logoUrl) return;
        var API_BASE = window.API_BASE_URL || '';
        var fav = document.getElementById('faviconLink');
        if (!fav) {
            fav = document.createElement('link');
            fav.id = 'faviconLink';
            fav.rel = 'icon';
            document.head.appendChild(fav);
        }
        fav.type = 'image/png';
        fav.href = API_BASE + logoUrl;
    }

    /**
     * Firma logosunu sidebar'daki icon alanına uygular (home ekranı).
     * @param {string} logoUrl - Logo URL'i
     */
    function applySidebarLogo(logoUrl) {
        if (!logoUrl) return;
        var API_BASE = window.API_BASE_URL || '';

        // Sidebar logo icon — SVG yerine img koy
        var logoIcon = document.querySelector('.sb-logo-icon');
        if (logoIcon) {
            var img = new Image();
            img.onload = function() {
                logoIcon.innerHTML = '';
                img.className = 'sb-logo-company-img';
                logoIcon.appendChild(img);
            };
            img.src = API_BASE + logoUrl;
        }

        // Topbar agent avatar
        var tbAvatar = document.querySelector('.tb-agent-avatar');
        if (tbAvatar) {
            var img2 = new Image();
            img2.onload = function() {
                tbAvatar.innerHTML = '';
                img2.className = 'tb-agent-company-img';
                tbAvatar.appendChild(img2);
            };
            img2.src = API_BASE + logoUrl;
        }
    }

    /**
     * Logo yoksa sidebar, topbar ve login ikonlarını firma ilk harfiyle günceller.
     * @param {string} letter - Gösterilecek harf
     */
    function applyInitialLetter(letter) {
        if (!letter) return;
        var svgHtml = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" overflow="hidden" style="width:100%;height:100%">' +
            '<text x="12" y="17" font-family="Geist,Arial,sans-serif" font-size="14" font-weight="700" fill="white" text-anchor="middle">' +
            letter + '</text></svg>';

        // Sidebar logo
        var sbIcon = document.querySelector('.sb-logo-icon');
        if (sbIcon) sbIcon.innerHTML = svgHtml;

        // Topbar agent avatar
        var tbAvatar = document.querySelector('.tb-agent-avatar');
        if (tbAvatar) tbAvatar.innerHTML = svgHtml;

        // Login sol üst ikon
        var loginIcon = document.querySelector('.ngssai-icon');
        if (loginIcon) loginIcon.innerHTML = svgHtml;
    }

    /**
     * Branding bilgisini localStorage'a kaydeder.
     * @param {Object} data - { app_name, theme, logo_url, company_id, company_name }
     */
    function saveBranding(data) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
        } catch (e) {
            console.warn('[BrandingEngine] localStorage kayıt hatası:', e);
        }
    }

    /**
     * Kaydedilmiş branding bilgisini yükler.
     * @returns {Object|null}
     */
    function loadBranding() {
        try {
            var raw = localStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch (e) {
            return null;
        }
    }

    /**
     * Branding bilgisini temizler.
     */
    function clearBranding() {
        localStorage.removeItem(STORAGE_KEY);
    }

    /**
     * Tüm branding bilgilerini uygular (login veya home ekranı için).
     * @param {Object} brandData - { app_name, theme, logo_url }
     */
    function applyAll(brandData) {
        if (!brandData) return;

        // CSS Tema uygula (JSON string → obje parse)
        if (brandData.theme && brandData.theme.css_variables) {
            var cssVars = brandData.theme.css_variables;
            if (typeof cssVars === 'string') {
                try { cssVars = JSON.parse(cssVars); } catch(e) { cssVars = null; }
            }
            if (cssVars) applyThemeForCurrentMode(cssVars);
        }

        // Uygulama adı uygula (app_name NGSSAI ise firma adını kullan)
        var displayName = brandData.app_name;
        if (!displayName || displayName === 'NGSSAI') {
            displayName = brandData.company_name || displayName;
        }
        if (displayName) {
            applyAppName(displayName);
        }

        // Login içerik güncelle — SADECE login sayfasında
        var isLoginPage = window.location.pathname.indexOf('login') !== -1;
        if (isLoginPage && brandData.theme) {
            applyLoginContent(
                brandData.theme.login_headline,
                brandData.theme.login_subtitle
            );
            // features_json JSON string → dizi parse
            var features = brandData.theme.features_json;
            if (typeof features === 'string') {
                try { features = JSON.parse(features); } catch(e) { features = null; }
            }
            applyLoginFeatures(features);
        }

        // Logo / ilk harf — önce ilk harfi uygula, logo varsa üzerine yaz
        var initial = ((displayName || brandData.company_name || 'N').charAt(0)).toUpperCase();

        // Favicon için SVG oluştur
        var accentColor = '%237C3AED';
        if (brandData.theme && brandData.theme.css_variables) {
            var cv = brandData.theme.css_variables;
            if (typeof cv === 'string') { try { cv = JSON.parse(cv); } catch(e) { cv = null; } }
            if (cv && cv.dark && cv.dark['--gold']) {
                accentColor = encodeURIComponent(cv.dark['--gold']);
            }
        }
        var svgFav = "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>" +
            "<rect width='32' height='32' rx='6' fill='" + accentColor + "'/>" +
            "<text x='16' y='22' font-family='Arial' font-size='18' font-weight='bold' fill='white' text-anchor='middle'>" + initial + "</text></svg>";
        var fav = document.getElementById('faviconLink');
        if (fav) { fav.type = 'image/svg+xml'; fav.href = svgFav; }

        // Sidebar, topbar ve login ikonlarını ilk harf ile güncelle (anında)
        applyInitialLetter(initial);

        // Logo varsa üzerine yaz (asenkron — img yüklenince)
        if (brandData.logo_url) {
            applyFavicon(brandData.logo_url);
            applyLoginLogo(brandData.logo_url);
            applySidebarLogo(brandData.logo_url);
        }
    }

    /**
     * Tema değişikliğini dinler ve CSS'i yeniden uygular.
     */
    function watchThemeChanges() {
        var observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(m) {
                if (m.attributeName === 'data-theme') {
                    var brandData = loadBranding();
                    if (brandData && brandData.theme && brandData.theme.css_variables) {
                        var cssVars = brandData.theme.css_variables;
                        if (typeof cssVars === 'string') {
                            try { cssVars = JSON.parse(cssVars); } catch(e) { cssVars = null; }
                        }
                        if (cssVars) applyThemeForCurrentMode(cssVars);
                    }
                }
            });
        });
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    }

    /**
     * Firma uygulama adını döndürür.
     * Tüm JS modülleri bu fonksiyonu kullanarak firma adına erişmelidir.
     * @returns {string} Firma adı (örn: "DAHİ", "VYRA")
     */
    function getAppName() {
        var bd = loadBranding();
        if (bd) {
            var name = bd.app_name;
            if (!name || name === 'NGSSAI') {
                name = bd.company_name || name;
            }
            if (name) return name;
        }
        return 'VYRA';
    }

    /**
     * Firma uygulama adının baş harfini döndürür (avatar ikonları için).
     * @returns {string} Tek harf (örn: "D", "V")
     */
    function getAppInitial() {
        return getAppName().charAt(0).toUpperCase();
    }

    // Public API
    window.BrandingEngine = {
        applyThemeCSS: applyThemeCSS,
        applyThemeForCurrentMode: applyThemeForCurrentMode,
        applyAppName: applyAppName,
        applyLoginContent: applyLoginContent,
        applyLoginFeatures: applyLoginFeatures,
        applyLoginLogo: applyLoginLogo,
        applyFavicon: applyFavicon,
        applySidebarLogo: applySidebarLogo,
        saveBranding: saveBranding,
        loadBranding: loadBranding,
        clearBranding: clearBranding,
        applyAll: applyAll,
        watchThemeChanges: watchThemeChanges,
        getAppName: getAppName,
        getAppInitial: getAppInitial
    };
})();
