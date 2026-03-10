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

    // DOM elementleri
    let elements = null;

    function getElements() {
        if (!elements) {
            elements = {
                tabs: {
                    llmConfig: document.getElementById("tabLlmConfig"),
                    promptDesign: document.getElementById("tabPromptDesign"),
                    mlTraining: document.getElementById("tabMLTraining"),
                    systemReset: document.getElementById("tabSystemReset"),
                    ldapSettings: document.getElementById("tabLdapSettings"),
                    orgPermissions: document.getElementById("tabOrgPermissions"),
                },
                content: {
                    llmConfig: document.getElementById("contentLlmConfig"),
                    promptDesign: document.getElementById("contentPromptDesign"),
                    mlTraining: document.getElementById("contentMLTraining"),
                    systemReset: document.getElementById("contentSystemReset"),
                    ldapSettings: document.getElementById("contentLdapSettings"),
                    orgPermissions: document.getElementById("contentOrgPermissions"),
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
        switch (tabName) {
            case "llmConfig":
                if (el.tabs.llmConfig) el.tabs.llmConfig.classList.add("active");
                if (el.content.llmConfig) el.content.llmConfig.classList.remove("hidden");
                // LLM verilerini yükle
                if (window.LLMModule) window.LLMModule.load();
                break;

            case "promptDesign":
                if (el.tabs.promptDesign) el.tabs.promptDesign.classList.add("active");
                if (el.content.promptDesign) el.content.promptDesign.classList.remove("hidden");
                // Prompt verilerini yükle
                if (window.PromptModule) window.PromptModule.load();
                break;

            case "mlTraining":
                if (el.tabs.mlTraining) el.tabs.mlTraining.classList.add("active");
                if (el.content.mlTraining) el.content.mlTraining.classList.remove("hidden");
                // ML Training verilerini yükle
                if (window.MLTrainingModule) {
                    window.MLTrainingModule.loadStats();
                    window.MLTrainingModule.loadSchedule();
                    window.MLTrainingModule.loadHistory();
                }
                break;

            case "systemReset":
                if (el.tabs.systemReset) el.tabs.systemReset.classList.add("active");
                if (el.content.systemReset) el.content.systemReset.classList.remove("hidden");
                if (typeof window.loadSystemResetInfo === 'function') {
                    window.loadSystemResetInfo();
                }
                break;

            case "ldapSettings":
                if (el.tabs.ldapSettings) el.tabs.ldapSettings.classList.add("active");
                if (el.content.ldapSettings) el.content.ldapSettings.classList.remove("hidden");
                if (window.LdapSettingsModule) {
                    window.LdapSettingsModule.load();
                }
                break;

            case "orgPermissions":
                if (el.tabs.orgPermissions) el.tabs.orgPermissions.classList.add("active");
                if (el.content.orgPermissions) el.content.orgPermissions.classList.remove("hidden");
                if (window.OrgPermissionsModule) {
                    window.OrgPermissionsModule.load();
                }
                break;
        }
    }

    // --- Event Listeners ---
    function setupEventListeners() {
        const el = getElements();

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
    }

    // --- Init ---
    function init() {
        setupEventListeners();
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
