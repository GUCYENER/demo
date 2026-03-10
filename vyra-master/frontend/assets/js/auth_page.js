// frontend/assets/js/auth_page.js
(function () {
    console.log("[VYRA] auth_page.js loaded");

    function $(sel) {
        return document.querySelector(sel);
    }

    function clearMessage() {
        const box = $("#auth-message");
        if (!box) return;
        box.textContent = "";
        box.style.display = "none";
        box.className = "auth-message";
    }

    function showMessage(type, text) {
        const box = $("#auth-message");
        if (!box) {
            alert(text);
            return;
        }
        box.textContent = text;
        box.style.display = "block";
        box.className = "auth-message auth-message--" + type;
    }

    function switchTab(target) {
        const tabLogin = $("#tab-login");
        const tabRegister = $("#tab-register");
        const loginForm = $("#login-form");
        const registerForm = $("#register-form");

        if (target === "login") {
            tabLogin.classList.add("auth-tab--active");
            tabRegister.classList.remove("auth-tab--active");
            loginForm.classList.add("auth-form--active");
            registerForm.classList.remove("auth-form--active");
        } else {
            tabRegister.classList.add("auth-tab--active");
            tabLogin.classList.remove("auth-tab--active");
            registerForm.classList.add("auth-form--active");
            loginForm.classList.remove("auth-form--active");
        }
        clearMessage();
    }

    document.addEventListener("DOMContentLoaded", () => {
        console.log("[VYRA] auth_page DOMContentLoaded");

        const tabLogin = $("#tab-login");
        const tabRegister = $("#tab-register");
        const loginForm = $("#login-form");
        const registerForm = $("#register-form");

        if (!loginForm || !registerForm) {
            console.warn("[VYRA] login/register form bulunamadı");
        }

        // TAB EVENTS
        if (tabLogin) {
            tabLogin.addEventListener("click", (e) => {
                e.preventDefault();
                switchTab("login");
            });
        }

        if (tabRegister) {
            tabRegister.addEventListener("click", (e) => {
                e.preventDefault();
                switchTab("register");
            });
        }

        // LOGIN SUBMIT
        if (loginForm) {
            loginForm.addEventListener("submit", async (e) => {
                e.preventDefault();
                clearMessage();

                const phone = $("#login-phone")?.value.trim();
                const password = $("#login-password")?.value;

                if (!phone || !password) {
                    showMessage("error", "Telefon ve şifre zorunlu.");
                    return;
                }

                try {
                    console.log("[VYRA] login request", { phone });
                    const data = await window.VYRA_API.login(phone, password);
                    console.log("[VYRA] login response", data);

                    showMessage(
                        "success",
                        "Giriş başarılı. Yönlendiriliyorsunuz..."
                    );
                    localStorage.setItem("vyra_user_phone", phone);

                    setTimeout(() => {
                        // Dashboard sayfasına yönlendir
                        window.location.href = "home.html";
                    }, 800);
                } catch (err) {
                    console.error("[VYRA] login error", err);
                    showMessage(
                        "error",
                        err.message || "Giriş sırasında bir hata oluştu."
                    );
                }
            });
        }

        // REGISTER SUBMIT
        if (registerForm) {
            registerForm.addEventListener("submit", async (e) => {
                e.preventDefault();
                clearMessage();

                const fullName = $("#register-fullname")?.value.trim();
                const phone = $("#register-phone")?.value.trim();
                const password = $("#register-password")?.value;

                if (!fullName || !phone || !password) {
                    showMessage("error", "Tüm alanlar zorunlu.");
                    return;
                }

                try {
                    console.log("[VYRA] register request", { fullName, phone });
                    const data = await window.VYRA_API.registerUser(
                        fullName,
                        phone,
                        password,
                        "user"
                    );
                    console.log("[VYRA] register response", data);

                    showMessage(
                        "success",
                        "Kayıt başarılı. Şimdi giriş yapabilirsiniz."
                    );
                    switchTab("login");
                } catch (err) {
                    console.error("[VYRA] register error", err);
                    showMessage(
                        "error",
                        err.message ||
                            "Kayıt sırasında bir hata oluştu."
                    );
                }
            });
        }
    });
})();
