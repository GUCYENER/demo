/* -------------------------------
   VYRA - Sidebar Module
   Sidebar navigasyon ve section yönetimi
-------------------------------- */

/**
 * Sidebar modülü - Menü navigasyonu ve section geçişleri
 * @module SidebarModule
 */
window.SidebarModule = (function () {
    'use strict';

    // DOM elementleri (lazy load)
    let elements = null;

    function getElements() {
        if (!elements) {
            elements = {
                sidebar: {
                    newTicket: document.getElementById("menuNewTicket"),
                    history: document.getElementById("menuHistory"),
                    parameters: document.getElementById("menuParameters"),
                    knowledgeBase: document.getElementById("menuKnowledgeBase"),
                    authorization: document.getElementById("menuAuthorization"),
                    organizations: document.getElementById("menuOrganizations"),
                    profile: document.getElementById("menuProfile"),
                    logout: document.getElementById("logoutBtn"),
                },
                mainTabs: {
                    container: document.querySelector(".space-x-8.border-b"),

                    history: document.getElementById("tabHistory"),
                    knowledgeBase: document.getElementById("tabKnowledgeBase"),
                },
                sections: {

                    history: document.getElementById("sectionHistory"),
                    parameters: document.getElementById("sectionParameters"),
                    knowledgeBase: document.getElementById("sectionKnowledgeBase"),
                    authorization: document.getElementById("sectionAuthorization"),
                    organizations: document.getElementById("sectionOrganizations"),
                    profile: document.getElementById("sectionProfile"),
                },
                homeHeader: document.getElementById("homeHeader"),
                mainTabBar: document.getElementById("mainTabBar"),
                topLogoArea: document.getElementById("topLogoArea"),
                topBar: document.getElementById("topBar"),
            };
        }
        return elements;
    }

    // --- Sidebar item aktivasyonu ---
    function activateItem(item) {
        const el = getElements();
        Object.values(el.sidebar).forEach(menuItem => {
            if (menuItem) menuItem.classList.remove("active");
        });
        if (item) item.classList.add("active");
    }

    // --- Section gösterimi ---
    function showSection(sectionName) {
        const el = getElements();

        // Tüm sectionları gizle
        Object.values(el.sections).forEach(section => {
            if (section) section.classList.add("hidden");
        });

        // Tab'ları deaktif yap

        if (el.mainTabs.history) el.mainTabs.history.classList.remove("active");
        if (el.mainTabs.knowledgeBase) el.mainTabs.knowledgeBase.classList.remove("active");

        // Home elementlerini göster/gizle
        const showHomeElements = ["history", "dialog"].includes(sectionName);
        if (el.homeHeader) el.homeHeader.classList.toggle("hidden", !showHomeElements);
        if (el.mainTabBar) el.mainTabBar.classList.toggle("hidden", !showHomeElements);
        if (el.topLogoArea) el.topLogoArea.classList.toggle("hidden", !showHomeElements);
        if (el.topBar) el.topBar.classList.toggle("hidden", !showHomeElements);

        // Section'a göre işlem yap
        switch (sectionName) {

            case "history":
                el.sections.history.classList.remove("hidden");
                if (el.mainTabs.history) el.mainTabs.history.classList.add("active");
                // Ticket history yükle
                if (typeof window.loadTicketHistoryDebounced === 'function') {
                    window.loadTicketHistoryDebounced();
                }
                break;

            case "parameters":
                el.sections.parameters.classList.remove("hidden");
                // LLM ve Prompt verilerini yükle
                if (window.LLMModule) window.LLMModule.load();
                if (window.PromptModule) window.PromptModule.load();
                break;

            case "knowledgeBase":
                el.sections.knowledgeBase.classList.remove("hidden");
                if (el.mainTabs.knowledgeBase) el.mainTabs.knowledgeBase.classList.add("active");
                // RAG modülünü başlat
                if (window.RAGUpload && typeof window.RAGUpload.init === 'function') {
                    window.RAGUpload.init();
                }
                break;

            case "authorization":
                el.sections.authorization.classList.remove("hidden");
                // Yetkilendirme modülünü yükle
                if (window.authorizationModule) {
                    window.authorizationModule.loadAuthData();
                }
                break;

            case "organizations":
                el.sections.organizations.classList.remove("hidden");
                // Organizasyon modülünü yükle
                if (window.orgModule) {
                    window.orgModule.loadOrganizations();
                }
                break;

            case "profile":
                // Element'i her zaman yeniden bul (cache sorunu önleme)
                const profileSection = document.getElementById("sectionProfile");
                console.log('[Sidebar] Profile section element:', profileSection);
                if (profileSection) {
                    profileSection.classList.remove("hidden");
                    console.log('[Sidebar] Profile section shown');
                } else {
                    console.error('[Sidebar] sectionProfile element NOT FOUND!');
                }
                // Profil modülünü yükle
                if (window.authorizationModule) {
                    window.authorizationModule.loadProfile();
                }
                break;
        }
    }

    // --- Logout ---
    function logout() {
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
        localStorage.removeItem("session_start_time");
        window.location.href = "login.html";
    }

    // --- Event Listeners ---
    function setupEventListeners() {
        const el = getElements();

        // Sidebar items
        if (el.sidebar.newTicket) {
            el.sidebar.newTicket.addEventListener("click", () => {
                activateItem(el.sidebar.newTicket);
                // Favori tab'a göre section göster
                const favTab = (typeof getFavoriteTab === 'function')
                    ? getFavoriteTab()
                    : (localStorage.getItem('vyra_favorite_tab') || 'dialog');
                showSection(favTab);
            });
        }

        if (el.sidebar.history) {
            el.sidebar.history.addEventListener("click", () => {
                activateItem(el.sidebar.history);
                showSection("history");
            });
        }

        if (el.sidebar.parameters) {
            el.sidebar.parameters.addEventListener("click", () => {
                activateItem(el.sidebar.parameters);
                showSection("parameters");
            });
        }

        if (el.sidebar.knowledgeBase) {
            el.sidebar.knowledgeBase.addEventListener("click", () => {
                activateItem(el.sidebar.knowledgeBase);
                showSection("knowledgeBase");
            });
        }

        if (el.sidebar.authorization) {
            el.sidebar.authorization.addEventListener("click", () => {
                activateItem(el.sidebar.authorization);
                showSection("authorization");
            });
        }

        if (el.sidebar.organizations) {
            el.sidebar.organizations.addEventListener("click", () => {
                activateItem(el.sidebar.organizations);
                showSection("organizations");
            });
        }

        if (el.sidebar.profile) {
            el.sidebar.profile.addEventListener("click", () => {
                activateItem(el.sidebar.profile);
                showSection("profile");
            });
        }

        if (el.sidebar.logout) {
            el.sidebar.logout.addEventListener("click", logout);
        }

        // Main tabs

        if (el.mainTabs.history) {
            el.mainTabs.history.addEventListener("click", () => showSection("history"));
        }
        if (el.mainTabs.knowledgeBase) {
            el.mainTabs.knowledgeBase.addEventListener("click", () => showSection("knowledgeBase"));
        }
    }

    // --- Init ---
    function init() {
        setupEventListeners();
        applyUserPermissions();
    }

    // --- Kullanıcı yetkilerini uygula ---
    async function applyUserPermissions() {
        try {
            const result = await window.VYRA_API?.request('/permissions/my/permissions');
            if (!result || !result.success) {
                console.log('[Sidebar] Permissions API not available, using JWT fallback');
                if (window.authorizationModule && window.authorizationModule.checkAdminAccess()) {
                    const el = getElements();
                    if (el.sidebar.authorization) el.sidebar.authorization.classList.remove('hidden');
                    if (el.sidebar.organizations) el.sidebar.organizations.classList.remove('hidden');
                }
                return;
            }

            const permissions = result.permissions;
            const isAdmin = result.is_admin;

            // Admin tüm yetkilere sahip
            if (isAdmin) {
                console.log('[Sidebar] Admin detected, all permissions granted');
                return;
            }

            const el = getElements();

            // Menü görünürlüklerini ayarla
            const menuMap = {
                'menuNewTicket': el.sidebar.newTicket,
                'menuParameters': el.sidebar.parameters,
                'menuKnowledgeBase': el.sidebar.knowledgeBase,
                'menuAuthorization': el.sidebar.authorization,
                'menuOrganizations': el.sidebar.organizations,
                'menuProfile': el.sidebar.profile
            };

            Object.entries(menuMap).forEach(([resourceId, menuElement]) => {
                if (!menuElement) return;

                const perm = permissions[resourceId];
                if (!perm || !perm.can_view) {
                    menuElement.classList.add('hidden');
                    console.log(`[Sidebar] Menu hidden: ${resourceId}`);
                } else {
                    menuElement.classList.remove('hidden');
                }
            });

            console.log('[Sidebar] Permissions applied', permissions);

        } catch (error) {
            console.error('[Sidebar] Permission check error:', error);
        }
    }

    // Public API
    return {
        init: init,
        showSection: showSection,
        activateItem: activateItem,
        logout: logout,
        applyUserPermissions: applyUserPermissions
    };
})();

// Otomatik init
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', window.SidebarModule.init);
} else {
    window.SidebarModule.init();
}
