/**
 * NGSSAI - Login/Register Module
 * Modern SaaS Authentication
 */

(function () {
    "use strict";

    // API Base URL — config.js'ten dinamik (production/development)
    const API_BASE = window.API_BASE_URL || "http://localhost:8002";

    // DOM Elements
    const loginForm = document.getElementById("loginForm");
    const registerForm = document.getElementById("registerForm");
    const tabs = document.querySelectorAll(".auth-tab");
    const passwordToggles = document.querySelectorAll("[data-toggle-password]");

    // ---- Tab Switching ----
    function initTabs() {
        tabs.forEach(tab => {
            tab.addEventListener("click", () => {
                const targetTab = tab.dataset.tab;

                // Update tabs
                tabs.forEach(t => t.classList.remove("active"));
                tab.classList.add("active");

                // Update forms
                document.querySelectorAll(".auth-form").forEach(form => {
                    form.classList.remove("active");
                });

                if (targetTab === "login") {
                    loginForm.classList.add("active");
                } else {
                    registerForm.classList.add("active");
                }

                // Clear errors
                hideAllMessages();
            });
        });
    }

    // ---- Password Toggle ----
    function initPasswordToggles() {
        passwordToggles.forEach(toggle => {
            toggle.addEventListener("click", () => {
                const wrapper = toggle.closest(".password-wrapper");
                const input = wrapper.querySelector("input");
                const icon = toggle.querySelector("i");

                if (input.type === "password") {
                    input.type = "text";
                    icon.classList.remove("fa-eye");
                    icon.classList.add("fa-eye-slash");
                } else {
                    input.type = "password";
                    icon.classList.remove("fa-eye-slash");
                    icon.classList.add("fa-eye");
                }
            });
        });
    }

    // ---- Messages ----
    function showError(elementId, message) {
        const el = document.getElementById(elementId);
        if (el) {
            el.textContent = message;
            el.classList.add("show");
        }
    }

    function showSuccess(elementId, message) {
        const el = document.getElementById(elementId);
        if (el) {
            el.textContent = message;
            el.classList.add("show");
        }
    }

    function hideAllMessages() {
        document.querySelectorAll(".error-message, .success-message").forEach(el => {
            el.classList.remove("show");
        });
    }

    // ---- LDAP Domain Loading (Polling) ----
    let _domainPollTimer = null;

    async function loadLdapDomains() {
        const domainSelect = document.getElementById('login-domain');
        if (!domainSelect) return;

        const maxWaitMs = 30000; // 30 saniye boyunca dene
        const intervalMs = 2000; // 2 saniyede bir
        const startTime = Date.now();

        async function tryLoad() {
            try {
                // v3.34.0: vyraFetch — non-JSON proxy hatalarında bile friendly Türkçe mesaj
                // fırlatır, polling akışı try/catch ile bunu zaten yutuyor.
                const data = await window.vyraFetch('/auth/ldap-domains', { auth: false });
                if (data && data.domains && data.domains.length > 0) {
                    // Mevcut LDAP seçeneklerini temizle (Lokal seçeneği kalsın)
                    domainSelect.querySelectorAll('option[data-ldap]').forEach(o => o.remove());

                    data.domains.forEach(d => {
                        const option = document.createElement('option');
                        option.value = d.domain;
                        option.textContent = d.display_name;
                        option.setAttribute('data-ldap', 'true');
                        domainSelect.appendChild(option);
                    });

                    // v2.51.1: Son LDAP seçeneğini otomatik seç (Turkcell Active Directory)
                    const ldapOptions = domainSelect.querySelectorAll('option[data-ldap]');
                    if (ldapOptions.length > 0) {
                        domainSelect.value = ldapOptions[ldapOptions.length - 1].value;
                    }

                    // Başarılı — polling durdur
                    if (_domainPollTimer) { clearInterval(_domainPollTimer); _domainPollTimer = null; }
                    console.log('[Login] LDAP domainleri yüklendi ✓');
                    return;
                }
            } catch (err) {
                // Backend henüz hazır değil
            }

            // Süre dolmadıysa tekrar dene
            if (Date.now() - startTime < maxWaitMs) {
                if (!_domainPollTimer) {
                    _domainPollTimer = setInterval(tryLoad, intervalMs);
                }
            } else {
                if (_domainPollTimer) { clearInterval(_domainPollTimer); _domainPollTimer = null; }
                console.warn('[Login] LDAP domainleri yüklenemedi (zaman aşımı)');
            }
        }

        tryLoad();
    }

    // ---- Login ----
    async function handleLogin(e) {
        e.preventDefault();
        hideAllMessages();

        const username = document.getElementById("login-username").value.trim();
        const password = document.getElementById("login-password").value;
        const domain = document.getElementById("login-domain")?.value || '';
        const rememberMe = document.getElementById("remember-me").checked;

        if (!username || !password) {
            showError("login-error", "Lütfen tüm alanları doldurun.");
            return;
        }

        const submitBtn = loginForm.querySelector("button[type='submit']");
        submitBtn.classList.add("loading");
        submitBtn.disabled = true;

        // Body: domain boşsa null gönder (lokal auth), doluysa LDAP auth
        const loginBody = { username, password };
        if (domain) loginBody.domain = domain;

        try {
            // v3.34.0: vyraFetch — friendly Türkçe error contract'ı (502/503/504 ve
            // network failure dahil) helper içinde merkezi olarak halledilir.
            const data = await window.vyraFetch('/auth/login', {
                method: 'POST',
                body: loginBody,
                auth: false,
            });

            // Store tokens
            localStorage.setItem("access_token", data.access_token);
            localStorage.setItem("refresh_token", data.refresh_token);

            // Oturum sayacını sıfırla (her login'de yeniden başlat)
            localStorage.setItem("session_start_time", new Date().toISOString());

            if (rememberMe) {
                localStorage.setItem("remember_user", username);
            } else {
                localStorage.removeItem("remember_user");
            }

            // Redirect to home
            window.location.href = "home.html";

        } catch (error) {
            console.error("[Login] Error:", error);
            // vyraFetch zaten Türkçe mesaj üretiyor — error.message doğrudan kullanılabilir.
            showError("login-error", error.message || "Giriş başarısız");
        } finally {
            submitBtn.classList.remove("loading");
            submitBtn.disabled = false;
        }
    }

    // ---- Register ----
    async function handleRegister(e) {
        e.preventDefault();
        hideAllMessages();

        const fields = [
            { id: "register-fullname", name: "Ad Soyad" },
            { id: "register-username", name: "Kullanıcı Adı" },
            { id: "register-email", name: "E-posta" },
            { id: "register-phone", name: "Telefon" },
            { id: "register-password", name: "Şifre" },
            { id: "register-password-confirm", name: "Şifre Tekrar" }
        ];

        // Clear previous error styles
        fields.forEach(f => {
            const el = document.getElementById(f.id);
            el.style.borderColor = "";
        });

        // Check empty fields
        let hasEmpty = false;
        let emptyFields = [];
        fields.forEach(f => {
            const el = document.getElementById(f.id);
            if (!el.value.trim()) {
                el.style.borderColor = "#ef4444";
                hasEmpty = true;
                emptyFields.push(f.name);
            }
        });

        if (hasEmpty) {
            showError("register-error", `Lütfen tüm alanları doldurun: ${emptyFields.join(", ")}`);
            return;
        }

        const fullname = document.getElementById("register-fullname").value.trim();
        const username = document.getElementById("register-username").value.trim();
        const email = document.getElementById("register-email").value.trim();
        const phone = document.getElementById("register-phone").value.trim();
        const password = document.getElementById("register-password").value;
        const passwordConfirm = document.getElementById("register-password-confirm").value;

        // Email validation
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(email)) {
            document.getElementById("register-email").style.borderColor = "#ef4444";
            showError("register-error", "Geçerli bir e-posta adresi girin.");
            return;
        }

        // Phone validation (10 digits)
        if (!/^[0-9]{10}$/.test(phone)) {
            document.getElementById("register-phone").style.borderColor = "#ef4444";
            showError("register-error", "Telefon numarası 10 haneli olmalıdır.");
            return;
        }

        if (password !== passwordConfirm) {
            showError("register-error", "Şifreler eşleşmiyor.");
            return;
        }

        if (password.length < 8) {
            showError("register-error", "Şifre en az 8 karakter olmalıdır.");
            return;
        }

        const submitBtn = registerForm.querySelector("button[type='submit']");
        submitBtn.classList.add("loading");
        submitBtn.disabled = true;

        try {
            // v3.34.0: vyraFetch — friendly Türkçe error contract'ı merkezi.
            await window.vyraFetch('/auth/register', {
                method: 'POST',
                body: {
                    full_name: fullname,
                    username: username,
                    email: email,
                    phone: phone,
                    password: password,
                },
                auth: false,
            });

            // Success
            showSuccess("register-success", "Kayıt başarılı! Giriş sayfasına yönlendiriliyorsunuz...");

            // Clear form
            registerForm.reset();

            // Switch to login tab after 2 seconds
            setTimeout(() => {
                tabs[0].click();
                document.getElementById("login-username").value = username;
            }, 2000);

        } catch (error) {
            console.error("[Register] Error:", error);
            // vyraFetch zaten Türkçe mesaj üretiyor.
            showError("register-error", error.message || "Kayıt başarısız");
        } finally {
            submitBtn.classList.remove("loading");
            submitBtn.disabled = false;
        }
    }

    // ---- Load Version ----
    async function loadVersion() {
        const versionEl = document.getElementById("app-version");
        try {
            // v3.34.0: vyraFetch — non-fatal, hata durumunda catch zaten yutuyor.
            const data = await window.vyraFetch('/health', { auth: false });

            if (versionEl && data && data.version) {
                versionEl.textContent = `v${data.version}`;
            }
        } catch (error) {
            console.log("[Version] Could not load version:", error.message);
            // v2.26.0: Fallback kaldırıldı - API'den gelmezse boş bırak
            if (versionEl) {
                versionEl.textContent = "";
            }
        }
    }

    // ---- Remember Me ----
    function loadRememberedUser() {
        const remembered = localStorage.getItem("remember_user");
        if (remembered) {
            document.getElementById("login-username").value = remembered;
            document.getElementById("remember-me").checked = true;
        }
    }

    // ---- Check Auth ----
    function checkExistingAuth() {
        // v3.15.4: home.html → version_mismatch nedeniyle login'e atıldıysa
        // bir bilgilendirme mesajı göster ve auto-redirect yapma.
        try {
            const reason = sessionStorage.getItem('vyra_relogin_reason');
            if (reason === 'version_mismatch') {
                sessionStorage.removeItem('vyra_relogin_reason');
                showError(
                    "login-error",
                    "Sürüm güncellendi. Lütfen yeniden giriş yapın."
                );
                // Eski tokenler zaten home_page.js tarafından temizlenmiştir;
                // yine de güvence olarak temizle.
                localStorage.removeItem("access_token");
                localStorage.removeItem("refresh_token");
                localStorage.removeItem("session_start_time");
                return;
            }
        } catch (_) { /* sessionStorage erişim hatası — kritik değil */ }

        const token = localStorage.getItem("access_token");
        if (token) {
            // v3.34.0: vyraFetch (auth:true default) Authorization header'ı
            // localStorage'dan otomatik okur. Başarılıysa home.html'e yönlendir;
            // 401 + version_mismatch ise kullanıcıya friendly mesaj göster.
            window.vyraFetch('/auth/me')
                .then(() => {
                    window.location.href = "home.html";
                })
                .catch((error) => {
                    // Token invalid veya başka hata — login sayfasında kal.
                    if (error && error.status === 401) {
                        const detail = (error.data && error.data.detail) || '';
                        localStorage.removeItem("access_token");
                        localStorage.removeItem("refresh_token");
                        localStorage.removeItem("session_start_time");
                        if (detail === 'version_mismatch') {
                            showError(
                                "login-error",
                                "Sürüm güncellendi. Lütfen yeniden giriş yapın."
                            );
                        }
                    } else {
                        // Diğer hatalar (network, 5xx) — sessizce token'ı temizle.
                        localStorage.removeItem("access_token");
                        localStorage.removeItem("refresh_token");
                    }
                });
        }
    }

    // ---- Turkish Validation Messages ----
    function setTurkishValidation() {
        document.querySelectorAll("input, select, textarea").forEach(input => {
            // Set custom message on invalid
            input.addEventListener("invalid", (e) => {
                e.preventDefault();

                if (input.validity.valueMissing) {
                    input.setCustomValidity("Bu alan zorunludur");
                } else if (input.validity.typeMismatch) {
                    if (input.type === "email") {
                        input.setCustomValidity("Geçerli bir e-posta adresi girin");
                    } else {
                        input.setCustomValidity("Geçerli bir değer girin");
                    }
                } else if (input.validity.tooShort) {
                    input.setCustomValidity(`En az ${input.minLength} karakter giriniz`);
                } else if (input.validity.patternMismatch) {
                    input.setCustomValidity("Geçerli bir format girin");
                }

                input.reportValidity();
            });

            // Clear custom message on input
            input.addEventListener("input", () => {
                input.setCustomValidity("");
            });

            // Clear on focus
            input.addEventListener("focus", () => {
                input.setCustomValidity("");
            });
        });
    }

    // ---- Load Login Video with Retry & Cache-Busting ----
    async function loadLoginVideo() {
        const video = document.getElementById('loginVideo');
        const logo = document.getElementById('loginLogo');
        if (!video) return;

        const maxRetries = 5;
        let retryCount = 0;
        let pollInterval = null;

        // Video ve logo görünürlük yönetimi
        function showVideo() {
            if (logo) logo.classList.add('hidden');
            video.classList.remove('hidden');
        }

        function showLogo() {
            video.classList.add('hidden');
            if (logo) logo.classList.remove('hidden');
        }

        async function checkVideoExists() {
            try {
                // NOTE (v3.34.0): vyraFetch JSON yanıtı bekler; bu HEAD probe'unun
                // gövdesi yoktur (binary video kaynağına HEAD atıyoruz). Bu yüzden
                // burada raw fetch'i bilinçli olarak koruyoruz — friendly error
                // contract'a gerek yok, polling akışı zaten boolean dönüyor.
                const timestamp = Date.now();
                const response = await fetch(`${API_BASE}/api/assets/login_video?t=${timestamp}`, {
                    method: 'HEAD'
                });
                return response.ok;
            } catch {
                return false;
            }
        }

        function tryLoadVideo() {
            // Cache-busting için timestamp ekle
            const timestamp = Date.now();
            video.src = `${API_BASE}/api/assets/login_video?t=${timestamp}`;

            // Yüklendiğinde otomatik oynat
            video.onloadeddata = () => {
                console.log('[Video] Loaded successfully');
                showVideo(); // 🎬 Logo'yu gizle, video'yu göster
                video.play().catch(e => console.log('Video autoplay blocked:', e));
                // Polling'i durdur (varsa)
                if (pollInterval) {
                    clearInterval(pollInterval);
                    pollInterval = null;
                }
            };

            // Hata durumunda retry
            video.onerror = () => {
                showLogo(); // 🖼️ Video yüklenemedi, logo'yu göster
                if (retryCount < maxRetries) {
                    retryCount++;
                    console.log(`[Video] Load error, retry ${retryCount}/${maxRetries}...`);
                    setTimeout(tryLoadVideo, 1000 * retryCount);
                } else {
                    // Max retry'a ulaştı, polling başlat (2 saniyede bir kontrol)
                    console.log('[Video] Max retries reached, starting polling...');
                    startPolling();
                }
            };
        }

        function startPolling() {
            if (pollInterval) return; // Zaten çalışıyorsa tekrar başlatma

            pollInterval = setInterval(async () => {
                const exists = await checkVideoExists();
                if (exists) {
                    console.log('[Video] Video found via polling, loading...');
                    retryCount = 0;
                    tryLoadVideo();
                }
            }, 2000); // 2 saniyede bir kontrol
        }

        // Başlangıçta logo görünür (HTML'de video hidden)
        // İlk yükleme deneyi
        tryLoadVideo();
    }

    // ---- Initialize ----
    function init() {
        initTabs();
        initPasswordToggles();
        setTurkishValidation();
        loadVersion();
        loadRememberedUser();
        checkExistingAuth();
        loadLoginVideo();
        loadLdapDomains();  // 🆕 LDAP domain listesi

        loginForm.addEventListener("submit", handleLogin);
        registerForm.addEventListener("submit", handleRegister);
    }

    // Start
    document.addEventListener("DOMContentLoaded", init);
})();
