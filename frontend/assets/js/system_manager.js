/* ─────────────────────────────────────────────
   NGSSAI — Sistem Yönetim Modülü
   v2.30.0 · home_page.js'den ayrıştırıldı
   versiyon, session timer, sidebar profil, sistem sıfırlama
   ───────────────────────────────────────────── */

window.SystemManagerModule = (function () {

    const API_BASE_URL = window.API_BASE_URL || 'http://localhost:8002';

    // --- VERSİYON ---
    async function loadAppVersion() {
        try {
            const response = await fetch(`${API_BASE_URL}/api/health`);
            if (response.ok) {
                const data = await response.json();
                const versionEl = document.getElementById('appVersion');
                if (versionEl && data.version) {
                    versionEl.textContent = `v${data.version}`;
                }
            }
        } catch (err) {
            console.warn('[NGSSAI] Versiyon yüklenemedi:', err);
        }
    }

    // --- OTURUM SAYACI ---
    // v2.53.1: Sayaç son login zamanından itibaren sayar.
    // login.js başarılı girişte session_start_time'ı set eder.
    // PC kapansa/tarayıcı kapansa bile sonraki login'de sıfırlanır.
    // v3.28.1: 30 dk threshold -> 15 sn countdown popup -> refresh veya auto-logout.
    let sessionStartTime = null;
    let sessionTimerInterval = null;

    // v3.28.1 — Session timeout config
    const SESSION_WARN_AT_SECONDS = 30 * 60;       // 30 dakika
    const SESSION_LOGOUT_COUNTDOWN_SECONDS = 15;   // popup içi countdown

    let _sessionWarningShown = false;
    let _logoutTimeoutId = null;
    let _logoutCountdownInterval = null;
    let _previousFocusEl = null;

    function startSessionTimer() {
        const storedStartTime = localStorage.getItem('session_start_time');

        if (storedStartTime) {
            const storedDate = new Date(storedStartTime);

            // Geçerlilik kontrolü: JWT token expire ile karşılaştır
            // Eğer saklanan süre > token expire süresi ise eski oturumdur, sıfırla
            try {
                const token = localStorage.getItem('access_token');
                if (token) {
                    const payload = JSON.parse(atob(token.split('.')[1]));
                    const tokenIssuedAt = new Date(payload.iat * 1000);
                    // Saklanan zaman, token'ın oluşturulma zamanından eskiyse → eski oturum
                    if (storedDate < tokenIssuedAt) {
                        sessionStartTime = tokenIssuedAt;
                        localStorage.setItem('session_start_time', tokenIssuedAt.toISOString());
                    } else {
                        sessionStartTime = storedDate;
                    }
                } else {
                    sessionStartTime = storedDate;
                }
            } catch (e) {
                sessionStartTime = storedDate;
            }
        } else {
            // Fallback: session_start_time yoksa (eski sürümden gelen kullanıcılar)
            sessionStartTime = new Date();
            localStorage.setItem('session_start_time', sessionStartTime.toISOString());
        }

        updateSessionTimer();
        sessionTimerInterval = setInterval(updateSessionTimer, 1000);
    }

    function updateSessionTimer() {
        if (!sessionStartTime) return;

        const now = new Date();
        const diff = Math.floor((now - sessionStartTime) / 1000);

        const hours = Math.floor(diff / 3600);
        const minutes = Math.floor((diff % 3600) / 60);
        const seconds = diff % 60;

        const timerStr = [
            hours.toString().padStart(2, '0'),
            minutes.toString().padStart(2, '0'),
            seconds.toString().padStart(2, '0')
        ].join(':');

        const timerEl = document.getElementById('sessionTimer');
        if (timerEl) {
            timerEl.textContent = timerStr;
            if (diff > 3600) {
                timerEl.classList.remove('text-gray-400');
                timerEl.classList.add('text-yellow-400');
            }
        }

        // v3.28.1 — 30 dk dolunca tek-seferlik uyarı popup'ı
        if (diff >= SESSION_WARN_AT_SECONDS && !_sessionWarningShown) {
            _showSessionWarning();
        }
    }

    // ============================================================
    // v3.28.1 — Session Timeout Modal
    // ============================================================
    function _ensureWarningModal() {
        if (document.getElementById('sessionTimeoutModal')) return;
        const html = ''
            + '<div id="sessionTimeoutModal" class="modal-overlay session-timeout-overlay" '
            +      'role="dialog" aria-modal="true" aria-labelledby="sessionTimeoutTitle" hidden>'
            +   '<div class="modal-box session-timeout-box">'
            +     '<div class="modal-header">'
            +       '<h3 id="sessionTimeoutTitle">'
            +         '<i class="fa-solid fa-clock"></i> Oturum Süreniz Doluyor'
            +       '</h3>'
            +     '</div>'
            +     '<div class="modal-body">'
            +       '<p>30 dakikadır oturumdasınız. Oturumu sürdürmek istiyor musunuz?</p>'
            +       '<p class="session-countdown-line">'
            +         '<strong id="sessionLogoutCountdown">15</strong> saniye içinde otomatik çıkış yapılacak.'
            +       '</p>'
            +       '<div class="session-countdown-bar" aria-hidden="true">'
            +         '<div id="sessionCountdownFill" class="session-countdown-bar-fill"></div>'
            +       '</div>'
            +     '</div>'
            +     '<div class="modal-footer">'
            +       '<button id="sessionContinueBtn" type="button" class="btn btn-primary" '
            +               'data-tooltip="Oturumu sürdür">'
            +         '<i class="fa-solid fa-rotate"></i> Devam Et'
            +       '</button>'
            +     '</div>'
            +   '</div>'
            + '</div>';
        const container = document.createElement('div');
        container.innerHTML = html.trim();
        const modal = container.firstElementChild;
        document.body.appendChild(modal);
        document.getElementById('sessionContinueBtn')
            .addEventListener('click', _onSessionContinue);
    }

    function _showSessionWarning() {
        if (_sessionWarningShown) return;
        _sessionWarningShown = true;
        _previousFocusEl = document.activeElement;

        _ensureWarningModal();
        const modal = document.getElementById('sessionTimeoutModal');
        if (!modal) return;
        modal.hidden = false;
        modal.classList.add('is-open');

        // 15 sn countdown başlat
        let remaining = SESSION_LOGOUT_COUNTDOWN_SECONDS;
        const countdownEl = document.getElementById('sessionLogoutCountdown');
        const fillEl = document.getElementById('sessionCountdownFill');
        if (countdownEl) countdownEl.textContent = remaining;
        if (fillEl) fillEl.style.width = '100%';

        _logoutCountdownInterval = setInterval(() => {
            remaining--;
            const r = Math.max(0, remaining);
            if (countdownEl) countdownEl.textContent = r;
            if (fillEl) fillEl.style.width = ((r / SESSION_LOGOUT_COUNTDOWN_SECONDS) * 100) + '%';
            if (r <= 0) {
                clearInterval(_logoutCountdownInterval);
                _logoutCountdownInterval = null;
            }
        }, 1000);

        _logoutTimeoutId = setTimeout(_forceLogout, SESSION_LOGOUT_COUNTDOWN_SECONDS * 1000);

        // A11y: focus continue button
        setTimeout(() => {
            const btn = document.getElementById('sessionContinueBtn');
            if (btn) {
                try { btn.focus(); } catch (_) {}
            }
        }, 50);
    }

    function _hideSessionWarning() {
        if (_logoutTimeoutId) {
            clearTimeout(_logoutTimeoutId);
            _logoutTimeoutId = null;
        }
        if (_logoutCountdownInterval) {
            clearInterval(_logoutCountdownInterval);
            _logoutCountdownInterval = null;
        }
        const modal = document.getElementById('sessionTimeoutModal');
        if (modal) {
            modal.classList.remove('is-open');
            modal.hidden = true;
        }
        // Return focus
        if (_previousFocusEl && typeof _previousFocusEl.focus === 'function') {
            try { _previousFocusEl.focus(); } catch (_) {}
        }
        _previousFocusEl = null;
    }

    async function _onSessionContinue() {
        const btn = document.getElementById('sessionContinueBtn');
        if (btn) {
            btn.classList.add('is-loading');
            btn.disabled = true;
        }
        try {
            // Refresh token ile yeni access token al
            if (window.VYRA_API && typeof window.VYRA_API.refreshToken === 'function') {
                await window.VYRA_API.refreshToken();
            }
            // Sayacı sıfırla — yeni 30 dk window
            sessionStartTime = new Date();
            localStorage.setItem('session_start_time', sessionStartTime.toISOString());
            _sessionWarningShown = false;
            _hideSessionWarning();
            if (window.showToast) {
                window.showToast('Oturumunuz yenilendi.', 'success');
            }
        } catch (err) {
            console.warn('[SessionTimeout] refresh hata, otomatik çıkış:', err);
            _forceLogout();
        } finally {
            if (btn) {
                btn.classList.remove('is-loading');
                btn.disabled = false;
            }
        }
    }

    function _forceLogout() {
        _hideSessionWarning();
        try {
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            localStorage.removeItem('session_start_time');
            localStorage.removeItem('user_data');
        } catch (_) {}
        if (sessionTimerInterval) {
            clearInterval(sessionTimerInterval);
            sessionTimerInterval = null;
        }
        // Login ekranı banner için query param
        window.location.href = 'login.html?reason=session_expired';
    }

    // --- SİDEBAR PROFİL ---
    async function loadSidebarProfile() {
        try {
            const token = localStorage.getItem('access_token');
            if (!token) return;

            const response = await fetch(`${API_BASE_URL}/api/users/me`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (response.ok) {
                const user = await response.json();

                const fullName = user.full_name || user.username || 'Kullanıcı';
                const nameEl = document.getElementById('sidebarUserName');
                if (nameEl) nameEl.textContent = fullName;

                localStorage.setItem('user_full_name', fullName);
                localStorage.setItem('user_name', user.username || '');

                // Avatar
                const avatarImgEl = document.getElementById('sidebarAvatarImg');
                const initialsEl = document.getElementById('sidebarAvatarInitials');

                if (user.avatar && avatarImgEl) {
                    avatarImgEl.src = user.avatar;
                    avatarImgEl.classList.remove('hidden');
                    if (initialsEl) initialsEl.classList.add('hidden');
                } else if (initialsEl) {
                    const initials = fullName.split(' ')
                        .map(word => word.charAt(0))
                        .slice(0, 2)
                        .join('')
                        .toUpperCase();
                    initialsEl.querySelector('span').textContent = initials || '?';
                    initialsEl.classList.remove('hidden');
                    if (avatarImgEl) avatarImgEl.classList.add('hidden');
                }

                // Rol rozeti
                const roleEl = document.getElementById('sidebarUserRole');
                if (roleEl) {
                    const roleName = user.role_name || user.role || 'user';
                    const roleDisplayNames = {
                        'admin': 'Yönetici', 'user': 'Kullanıcı', 'support': 'Destek',
                        'Admin': 'Yönetici', 'User': 'Kullanıcı'
                    };
                    roleEl.textContent = roleDisplayNames[roleName] || roleName;

                    const isAdmin = user.is_admin === true || user.is_admin === 1 ||
                        roleName === 'admin' || roleName === 'Admin';
                    if (isAdmin) { roleEl.classList.add('admin'); } else { roleEl.classList.remove('admin'); }
                    roleEl.classList.remove('hidden');
                }
            }
        } catch (err) {
            console.warn('[NGSSAI] Profil bilgisi yüklenemedi:', err);
        }
    }

    // --- SİSTEM SIFIRLAMA ---
    async function loadSystemResetInfo(companyId) {
        const protectedStats = document.getElementById("protectedStats");
        const deletableStats = document.getElementById("deletableStats");

        try {
            const qp = companyId ? `?company_id=${companyId}` : '';
            const data = await window.VYRA_API.request("/system/info" + qp);

            if (protectedStats && data.protected) {
                protectedStats.innerHTML = `
                    <span><i class="fa-solid fa-user-shield mr-2"></i>${data.protected.admin_users} admin</span>
                    <span class="ml-4"><i class="fa-solid fa-brain mr-2"></i>${data.protected.llm_configs} LLM</span>
                    <span class="ml-4"><i class="fa-solid fa-wand-magic-sparkles mr-2"></i>${data.protected.prompt_templates} prompt</span>
                    <span class="ml-4"><i class="fa-solid fa-database mr-2"></i>${data.protected.data_sources || 0} kaynak</span>
                `;
            }

            if (deletableStats && data.to_delete) {
                const d = data.to_delete;
                // v3.29.7: Agentic Query Learning tabloları toplamı (v3.21-v3.29 — 16 tablo)
                const agenticLearningTotal =
                    (d.learned_db_queries || 0) + (d.ds_synthetic_query_runs || 0) +
                    (d.ds_column_embeddings || 0) + (d.agentic_query_decisions || 0) +
                    (d.agentic_query_feedback || 0) + (d.agentic_size_observations || 0) +
                    (d.catboost_models || 0) + (d.few_shot_examples || 0) +
                    (d.business_glossary || 0) + (d.metric_definitions || 0) +
                    (d.synonym_suggestions || 0) + (d.pipeline_events || 0) +
                    (d.pipeline_traces || 0) + (d.user_preferences || 0) +
                    (d.ds_code_values || 0) + (d.learned_query_failures || 0);
                const total = (d.non_admin_users || 0) + (d.tickets || 0) + (d.dialogs || 0) +
                    (d.uploaded_files || 0) + (d.document_images || 0) + (d.rag_chunks || 0) +
                    (d.user_feedback || 0) + (d.document_topics || 0) +
                    (d.ml_training_samples || 0) + (d.ml_training_jobs || 0) +
                    (d.ml_training_schedules || 0) + (d.ml_models || 0) +
                    (d.learned_answers || 0) +
                    (d.ds_learning_results || 0) + (d.ds_db_objects || 0) +
                    (d.ds_discovery_jobs || 0) + (d.sql_audit_log || 0) +
                    (d.system_logs || 0) +
                    agenticLearningTotal;
                deletableStats.innerHTML = `
                    <span><i class="fa-solid fa-users mr-2"></i>${d.non_admin_users || 0} kullanıcı</span>
                    <span class="ml-4"><i class="fa-solid fa-ticket mr-2"></i>${d.tickets || 0} ticket</span>
                    <span class="ml-4"><i class="fa-solid fa-comments mr-2"></i>${d.dialogs || 0} dialog</span>
                    <span class="ml-4"><i class="fa-solid fa-file mr-2"></i>${d.uploaded_files || 0} dosya</span>
                    <span class="ml-4"><i class="fa-solid fa-puzzle-piece mr-2"></i>${d.rag_chunks || 0} chunk</span>
                    <span class="ml-4"><i class="fa-solid fa-robot mr-2"></i>${d.ml_models || 0} model</span>
                    <span class="ml-4"><i class="fa-solid fa-graduation-cap mr-2"></i>${d.learned_answers || 0} cevap</span>
                    <span class="ml-4"><i class="fa-solid fa-magnifying-glass-chart mr-2"></i>${d.ds_learning_results || 0} QA</span>
                    <span class="ml-4"><i class="fa-solid fa-table mr-2"></i>${d.ds_db_objects || 0} keşif</span>
                    <span class="ml-4"><i class="fa-solid fa-clipboard-list mr-2"></i>${d.sql_audit_log || 0} audit</span>
                    <span class="ml-4" data-tooltip="learned_db_queries + synthetic + embeddings + feedback + catboost + few-shot + glossary + metric + pipeline traces + user_preferences + ds_code_values + learned_query_failures (v3.29 Faz 6)"><i class="fa-solid fa-brain mr-2"></i>${agenticLearningTotal.toLocaleString('tr-TR')} agentic öğrenme</span>
                    <div class="mt-2 text-yellow-400"><strong>Toplam ${total.toLocaleString('tr-TR')} kayıt silinecek</strong></div>
                `;
            }
        } catch (err) {
            console.warn("[NGSSAI] Sistem bilgisi yüklenemedi:", err);
            if (protectedStats) protectedStats.innerHTML = '<span class="text-gray-500">Bilgi yüklenemedi</span>';
            if (deletableStats) deletableStats.innerHTML = '<span class="text-gray-500">Bilgi yüklenemedi</span>';
        }
    }

    function performSystemReset() {
        window.VyraModal.danger({
            title: "Dikkat! Bu İşlem Geri Alınamaz",
            message: "Tüm ticket'lar, dialog'lar, RAG dosyaları, ML eğitim verileri, öğrenilmiş cevaplar, DS öğrenme verileri, agentic query öğrenme (v3.21–v3.29: learned_db_queries, synthetic, embeddings, feedback, CatBoost modelleri, few-shot, glossary, metric, pipeline traces, user prefs, ds_code_values, learned_query_failures), SQL audit logları ve sistem logları silinecek. Kaynak tanımları, admin kullanıcılar, LLM ve Prompt ayarları korunacak.",
            confirmText: "Sistemi Sıfırla",
            cancelText: "İptal",
            onConfirm: async () => {
                const btn = document.getElementById("btnSystemReset");
                if (btn) {
                    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Sıfırlanıyor...';
                    btn.disabled = true;
                }
                try {
                    const result = await window.VYRA_API.request("/system/reset", { method: "POST" });
                    if (result.success) {
                        window.VyraModal.success({
                            title: "Sistem Sıfırlandı",
                            message: "Tüm veriler başarıyla temizlendi. Login sayfasına yönlendiriliyorsunuz...",
                            confirmText: "Tamam",
                            onConfirm: () => {
                                localStorage.removeItem("access_token");
                                localStorage.removeItem("refresh_token");
                                localStorage.removeItem("user_data");
                                window.location.href = "login.html";
                            }
                        });
                    }
                } catch (err) {
                    console.error("[NGSSAI] Sistem sıfırlama hatası:", err);
                    window.VyraModal.error({
                        title: "Sıfırlama Hatası",
                        message: err.message || "Bilinmeyen bir hata oluştu"
                    });
                    if (btn) {
                        btn.innerHTML = '<i class="fa-solid fa-rotate-left"></i> Sistemi Sıfırla';
                        btn.disabled = false;
                    }
                }
            }
        });
    }

    // --- EVENT LISTENERS ---
    const btnSystemReset = document.getElementById("btnSystemReset");
    if (btnSystemReset) btnSystemReset.addEventListener("click", performSystemReset);

    // Sidebar profil alanına tıklanınca profil sayfasına git
    const sidebarProfileArea = document.getElementById('sidebarProfileArea');
    if (sidebarProfileArea) {
        sidebarProfileArea.addEventListener('click', () => {
            const profileMenu = document.getElementById('menuProfile');
            if (profileMenu) profileMenu.click();
        });
    }

    // --- INIT (otomatik çalıştır) ---
    loadAppVersion();
    loadSidebarProfile();
    startSessionTimer();

    // --- PUBLIC API ---
    return {
        loadVersion: loadAppVersion,
        loadProfile: loadSidebarProfile,
        loadResetInfo: loadSystemResetInfo,
        performReset: performSystemReset,
        startTimer: startSessionTimer,
    };

})();

// Backward-compat aliases
window.loadAppVersion = window.SystemManagerModule.loadVersion;
window.loadSidebarProfile = window.SystemManagerModule.loadProfile;
window.loadSystemResetInfo = window.SystemManagerModule.loadResetInfo;
window.performSystemReset = window.SystemManagerModule.performReset;
window.startSessionTimer = window.SystemManagerModule.startTimer;
