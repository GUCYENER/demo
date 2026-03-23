/* -------------------------------
   VYRA - Param Tabs Module
   Parametreler sekmesi tab yönetimi
-------------------------------- */

/**
 * ParamTabs modülü - LLM/Prompt/MLTraining/System Reset sekme geçişleri
 * @module ParamTabsModule
 */
window.ParamTabsModule = (function () {
    'use strict';

    const API_BASE = window.API_BASE_URL || '';
    let activeTabName = null;

    // DOM elementleri
    let elements = null;

    function getElements() {
        if (!elements) {
            elements = {
                tabs: {
                    companies: document.getElementById("tabCompanies"),
                    llmConfig: document.getElementById("tabLlmConfig"),
                    promptDesign: document.getElementById("tabPromptDesign"),
                    mlTraining: document.getElementById("tabMLTraining"),
                    systemReset: document.getElementById("tabSystemReset"),
                    ldapSettings: document.getElementById("tabLdapSettings"),
                    orgPermissions: document.getElementById("tabOrgPermissions"),
                    widgetKeys: document.getElementById("tabWidgetKeys"),
                    dataSources: document.getElementById("tabDataSources"),
                },
                content: {
                    companies: document.getElementById("contentCompanies"),
                    llmConfig: document.getElementById("contentLlmConfig"),
                    promptDesign: document.getElementById("contentPromptDesign"),
                    mlTraining: document.getElementById("contentMLTraining"),
                    systemReset: document.getElementById("contentSystemReset"),
                    ldapSettings: document.getElementById("contentLdapSettings"),
                    orgPermissions: document.getElementById("contentOrgPermissions"),
                    widgetKeys: document.getElementById("contentWidgetKeys"),
                    dataSources: document.getElementById("contentDataSources"),
                }
            };
        }
        return elements;
    }

    // --- Tab aktivasyonu ---
    function activateTab(tabName) {
        const el = getElements();

        // Tüm tabları deaktif yap
        Object.values(el.tabs).forEach(tab => {
            if (tab) tab.classList.remove("active");
        });

        // Tüm içerikleri gizle
        Object.values(el.content).forEach(content => {
            if (content) content.classList.add("hidden");
        });

        // Seçili tab ve içeriği göster
        activeTabName = tabName;
        const cid = getSelectedCompanyId();

        switch (tabName) {
            case "companies":
                if (el.tabs.companies) el.tabs.companies.classList.add("active");
                if (el.content.companies) el.content.companies.classList.remove("hidden");
                if (window.CompanyModule) window.CompanyModule.load();
                break;

            case "llmConfig":
                if (el.tabs.llmConfig) el.tabs.llmConfig.classList.add("active");
                if (el.content.llmConfig) el.content.llmConfig.classList.remove("hidden");
                if (window.LLMModule) window.LLMModule.load(cid);
                break;

            case "promptDesign":
                if (el.tabs.promptDesign) el.tabs.promptDesign.classList.add("active");
                if (el.content.promptDesign) el.content.promptDesign.classList.remove("hidden");
                if (window.PromptModule) window.PromptModule.load(cid);
                break;

            case "mlTraining":
                if (el.tabs.mlTraining) el.tabs.mlTraining.classList.add("active");
                if (el.content.mlTraining) el.content.mlTraining.classList.remove("hidden");
                if (window.MLTrainingModule) {
                    window.MLTrainingModule.loadStats(cid);
                    window.MLTrainingModule.loadSchedule(cid);
                    window.MLTrainingModule.loadHistory(cid);
                }
                break;

            case "systemReset":
                if (el.tabs.systemReset) el.tabs.systemReset.classList.add("active");
                if (el.content.systemReset) el.content.systemReset.classList.remove("hidden");
                if (typeof window.loadSystemResetInfo === 'function') {
                    window.loadSystemResetInfo(cid);
                }
                break;

            case "ldapSettings":
                if (el.tabs.ldapSettings) el.tabs.ldapSettings.classList.add("active");
                if (el.content.ldapSettings) el.content.ldapSettings.classList.remove("hidden");
                if (window.LdapSettingsModule) {
                    window.LdapSettingsModule.load(cid);
                }
                break;

            case "orgPermissions":
                if (el.tabs.orgPermissions) el.tabs.orgPermissions.classList.add("active");
                if (el.content.orgPermissions) el.content.orgPermissions.classList.remove("hidden");
                if (window.OrgPermissionsModule) {
                    window.OrgPermissionsModule.load(cid);
                }
                break;

            case "widgetKeys":
                if (el.tabs.widgetKeys) el.tabs.widgetKeys.classList.add("active");
                if (el.content.widgetKeys) el.content.widgetKeys.classList.remove("hidden");
                if (window.widgetModule) {
                    window.widgetModule.init(cid);
                }
                break;

            case "dataSources":
                if (el.tabs.dataSources) el.tabs.dataSources.classList.add("active");
                if (el.content.dataSources) el.content.dataSources.classList.remove("hidden");
                if (window.DataSourcesModule) {
                    window.DataSourcesModule.load(cid);
                }
                break;
        }
    }

    // --- Event Listeners ---
    function setupEventListeners() {
        const el = getElements();

        if (el.tabs.companies) {
            el.tabs.companies.addEventListener("click", () => activateTab("companies"));
        }

        if (el.tabs.llmConfig) {
            el.tabs.llmConfig.addEventListener("click", () => activateTab("llmConfig"));
        }

        if (el.tabs.promptDesign) {
            el.tabs.promptDesign.addEventListener("click", () => activateTab("promptDesign"));
        }

        if (el.tabs.mlTraining) {
            el.tabs.mlTraining.addEventListener("click", () => activateTab("mlTraining"));
        }

        if (el.tabs.systemReset) {
            el.tabs.systemReset.addEventListener("click", () => activateTab("systemReset"));
        }

        if (el.tabs.ldapSettings) {
            el.tabs.ldapSettings.addEventListener("click", () => activateTab("ldapSettings"));
        }

        if (el.tabs.orgPermissions) {
            el.tabs.orgPermissions.addEventListener("click", () => activateTab("orgPermissions"));
        }

        if (el.tabs.widgetKeys) {
            el.tabs.widgetKeys.addEventListener("click", () => activateTab("widgetKeys"));
        }

        if (el.tabs.dataSources) {
            el.tabs.dataSources.addEventListener("click", () => activateTab("dataSources"));
        }

        // Yeni Kaynak Ekle butonu
        const btnNew = document.getElementById('btnNewDataSource');
        if (btnNew) {
            btnNew.addEventListener('click', () => {
                if (window.DataSourcesModule) window.DataSourcesModule.openModal();
            });
        }
    }

    // --- Firma Selector Logic (v2.54.0) ---

    function getSelectedCompanyId() {
        const sel = document.getElementById('globalCompanySelect');
        return sel && sel.value ? parseInt(sel.value, 10) : null;
    }

    async function loadCompanySelector() {
        const select = document.getElementById('globalCompanySelect');
        const nameSpan = document.getElementById('globalCompanyName');
        if (!select) return;

        // Admin tespiti — init ile aynı yöntem
        const companiesTab = document.getElementById("tabCompanies");
        const isAdmin = companiesTab && !companiesTab.classList.contains("hidden")
                      && getComputedStyle(companiesTab).display !== "none";

        try {
            const token = localStorage.getItem('access_token') || '';
            const res = await fetch(API_BASE + '/api/companies', {
                headers: { 'Authorization': 'Bearer ' + token }
            });
            if (!res.ok) return;
            const companies = await res.json();

            if (isAdmin) {
                // Admin: dropdown göster, span gizle
                if (nameSpan) nameSpan.style.display = 'none';
                select.innerHTML = '<option value="">Tüm Firmalar</option>';
                companies.forEach(c => {
                    const opt = document.createElement('option');
                    opt.value = c.id;
                    opt.textContent = c.name;
                    select.appendChild(opt);
                });

                // Firma değişince aktif sekmeyi yeniden yükle
                select.addEventListener('change', () => {
                    if (activeTabName) activateTab(activeTabName);
                });
            } else if (nameSpan) {
                // Non-admin: select gizle, firma adı göster
                select.style.display = 'none';
                if (companies.length > 0) {
                    nameSpan.textContent = companies[0].name;
                }
            }
        } catch (err) {
            console.warn('[ParamTabs] Firma selector yüklenemedi:', err);
        }
    }

    // --- Init ---
    function init() {
        setupEventListeners();

        // DOM tam render olduktan sonra varsayılan tab'ı aç
        requestAnimationFrame(() => {
            const companiesTab = document.getElementById("tabCompanies");
            const isAdmin = companiesTab && !companiesTab.classList.contains("hidden")
                          && getComputedStyle(companiesTab).display !== "none";

            // Firma selector'ı yükle
            loadCompanySelector();

            if (isAdmin) {
                activateTab("companies");
            } else {
                activateTab("llmConfig");
            }
        });
    }

    // Public API
    return {
        init: init,
        activateTab: activateTab
    };
})();

// Otomatik init
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', window.ParamTabsModule.init);
} else {
    window.ParamTabsModule.init();
}

/**
 * Global yardımcı: Modal'lardaki firma select dropdown'ını doldurur.
 * Tüm modüller (LLM, Prompt, LDAP, Widget) bu fonksiyonu kullanır.
 * @param {HTMLSelectElement} selectEl - Doldurulacak select element
 * @param {number|null} selectedId - Öntanımlı seçilecek firma ID'si
 */
async function populateCompanySelect(selectEl, selectedId) {
    if (!selectEl) return;
    const API_BASE = window.API_BASE_URL || '';
    try {
        const token = localStorage.getItem('access_token') || '';
        const res = await fetch(API_BASE + '/api/companies', {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        if (!res.ok) return;
        const companies = await res.json();
        selectEl.innerHTML = '<option value="">Firma seçin...</option>';
        companies.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.id;
            opt.textContent = c.name;
            if (selectedId && c.id === selectedId) opt.selected = true;
            selectEl.appendChild(opt);
        });
    } catch (err) {
        console.warn('[populateCompanySelect] Firmalar yüklenemedi:', err);
    }
}
window.populateCompanySelect = populateCompanySelect;
