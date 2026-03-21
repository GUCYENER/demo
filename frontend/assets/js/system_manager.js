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
    let sessionStartTime = null;
    let sessionTimerInterval = null;

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
                `;
            }

            if (deletableStats && data.to_delete) {
                const d = data.to_delete;
                const total = (d.non_admin_users || 0) + (d.tickets || 0) + (d.dialogs || 0) +
                    (d.uploaded_files || 0) + (d.document_images || 0) + (d.rag_chunks || 0) +
                    (d.user_feedback || 0) + (d.document_topics || 0) +
                    (d.ml_training_samples || 0) + (d.ml_training_jobs || 0) +
                    (d.ml_training_schedules || 0) + (d.ml_models || 0) +
                    (d.learned_answers || 0) + (d.system_logs || 0);
                deletableStats.innerHTML = `
                    <span><i class="fa-solid fa-users mr-2"></i>${d.non_admin_users || 0} kullanıcı</span>
                    <span class="ml-4"><i class="fa-solid fa-ticket mr-2"></i>${d.tickets || 0} ticket</span>
                    <span class="ml-4"><i class="fa-solid fa-comments mr-2"></i>${d.dialogs || 0} dialog</span>
                    <span class="ml-4"><i class="fa-solid fa-file mr-2"></i>${d.uploaded_files || 0} dosya</span>
                    <span class="ml-4"><i class="fa-solid fa-puzzle-piece mr-2"></i>${d.rag_chunks || 0} chunk</span>
                    <span class="ml-4"><i class="fa-solid fa-robot mr-2"></i>${d.ml_models || 0} model</span>
                    <span class="ml-4"><i class="fa-solid fa-graduation-cap mr-2"></i>${d.learned_answers || 0} cevap</span>
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
            message: "Tüm ticket'lar, dialog'lar, RAG dosyaları, ML eğitim verileri, öğrenilmiş cevaplar ve sistem logları silinecek. Sadece admin kullanıcılar, LLM ve Prompt ayarları korunacak.",
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
