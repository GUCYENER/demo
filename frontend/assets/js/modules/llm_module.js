/* -------------------------------
   VYRA - LLM Module
   LLM konfigürasyon yönetimi (CRUD)
-------------------------------- */

/**
 * LLM modülü - Parametreler sekmesinde LLM konfigürasyonları yönetimi
 * @module LLMModule
 */
window.LLMModule = (function() {
    'use strict';

    // DOM elementleri (lazy load)
    let elements = null;

    function getElements() {
        if (!elements) {
            elements = {
                grid: document.getElementById("llmGrid"),
                modal: document.getElementById("llmModal"),
                btnNew: document.getElementById("btnNewLLM"),
                btnClose: document.getElementById("closeLlmModal"),
                btnCancel: document.getElementById("btnCancelLlm"),
                form: document.getElementById("llmForm"),
                modalTitle: document.getElementById("llmModalTitle"),
                inputs: {
                    id: document.getElementById("llmId"),
                    vendor: document.getElementById("llmVendor"),
                    provider: document.getElementById("llmProvider"),
                    model: document.getElementById("llmModel"),
                    apiUrl: document.getElementById("llmApiUrl"),
                    token: document.getElementById("llmToken"),
                    desc: document.getElementById("llmDesc"),
                    temp: document.getElementById("llmTemp"),
                    topP: document.getElementById("llmTopP"),
                    timeout: document.getElementById("llmTimeout"),
                }
            };
        }
        return elements;
    }

    // --- YÜKLEMESİ ---
    async function loadConfigs() {
        const token = localStorage.getItem('access_token');
        const el = getElements();
        
        if (!token) {
            if (el.grid) {
                el.grid.innerHTML = '<div class="n-page-empty"><i class="fa-solid fa-lock"></i><p>Lütfen giriş yapın.</p></div>';
            }
            return;
        }

        if (!el.grid) {
            console.warn('[NGSSAI] llmGrid elementi bulunamadı');
            return;
        }

        try {
            el.grid.innerHTML = '<div style="padding:20px;color:var(--text-3);font-size:13px"><i class="fa-solid fa-spinner fa-spin" style="margin-right:8px"></i>Yükleniyor...</div>';

            const data = await window.VYRA_API.request("/llm-config/");

            if (!data || !Array.isArray(data)) {
                console.log('[NGSSAI] LLM config verisi boş veya geçersiz:', data);
                render([]);
                return;
            }

            render(data);

        } catch (err) {
            console.error('[NGSSAI] LLM config yükleme hatası:', err);

            let errorMessage = 'LLM listesi yüklenemedi.';
            let messageClass = 'text-red-500';

            if (err.message && err.message.includes('Failed to fetch')) {
                errorMessage = 'Sunucuya bağlanılamadı. Backend çalışıyor mu kontrol edin.';
            } else if (err.status === 401) {
                errorMessage = 'Oturum süresi dolmuş. Lütfen tekrar giriş yapın.';
                messageClass = 'text-yellow-500';
            } else if (err.status === 403) {
                errorMessage = 'Bu bölüme erişim için admin yetkisi gereklidir.';
                messageClass = 'text-yellow-500';
            } else if (err.status === 404) {
                errorMessage = 'LLM endpoint bulunamadı.';
            } else if (err.message) {
                errorMessage = `Hata: ${err.message}`;
            }

            el.grid.innerHTML = `<div style="padding:20px;color:var(--red);font-size:13px"><i class="fa-solid fa-exclamation-triangle" style="margin-right:8px"></i>${errorMessage}</div>`;
        }
    }

    // --- RENDER ---
    function render(list) {
        const el = getElements();
        el.grid.innerHTML = "";

        if (!list || list.length === 0) {
            el.grid.innerHTML = '<div class="n-page-empty"><i class="fa-solid fa-robot"></i><p>Henüz LLM tanımı yok.</p></div>';
            return;
        }

        list.forEach(llm => {
            const isActive = llm.is_active === true || llm.is_active === 1;
            const activeClass = isActive ? "border-green-500 border-2" : "border-gray-700 border";
            const badge = isActive
                ? `<span class="badge badge-green"><span class="badge-dot"></span>Aktif</span>`
                : ``;

            const desc = llm.description ? `<div class="model-tag"><i class="fa-solid fa-info-circle" style="font-size:11px;color:var(--text-3)"></i> ${llm.description}</div>` : "";
            const deleteDisabled = isActive ? 'style="opacity:.3;cursor:not-allowed"' : '';

            const card = document.createElement("div");
            card.className = "model-card";

            card.innerHTML = `
                <div class="model-card-icon">
                    <i class="fa-solid fa-robot"></i>
                </div>
                <div class="model-info">
                    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
                        <div class="model-name">${llm.provider}</div>
                        ${badge}
                    </div>
                    <div class="model-id">${llm.model_name}</div>
                    ${desc}
                    <div class="model-meta">
                        <div class="mm-item"><span class="mm-key">Vendor</span><span class="mm-val">${llm.vendor_code}</span></div>
                        <div class="mm-item"><span class="mm-key">Temp / TopP</span><span class="mm-val">${llm.temperature} / ${llm.top_p}</span></div>
                    </div>
                </div>
                <div class="model-actions">
                    <div class="toggle-wrap">
                        <div class="toggle ${isActive ? 'on' : ''}" onclick="LLMModule.activate(${llm.id})"></div>
                        <span class="toggle-lbl" style="font-size:11px;color:var(--text-3)">Aktif Kullan</span>
                    </div>
                    <button class="act-btn edit" onclick="LLMModule.edit(${llm.id})" title="Düzenle">
                        <i class="fa-solid fa-pen"></i>
                    </button>
                    <button class="act-btn del" ${deleteDisabled} onclick="LLMModule.delete(${llm.id}, ${isActive})" title="Sil">
                        <i class="fa-solid fa-trash"></i>
                    </button>
                </div>
            `;
            el.grid.appendChild(card);
        });

        // Store list for edit lookup
        window._llmList = list;
    }

    // --- MODAL İŞLEMLERİ ---
    function openModal(llm = null) {
        const el = getElements();
        el.modal.classList.remove("hidden");
        el.form.reset();

        if (llm) {
            el.modalTitle.textContent = "LLM Düzenle";
            el.inputs.id.value = llm.id;
            el.inputs.vendor.value = llm.vendor_code || "12000533461";
            el.inputs.provider.value = llm.provider;
            el.inputs.model.value = llm.model_name;
            el.inputs.apiUrl.value = llm.api_url;
            el.inputs.desc.value = llm.description || "";
            el.inputs.temp.value = llm.temperature;
            el.inputs.topP.value = llm.top_p;
            el.inputs.timeout.value = llm.timeout_seconds || 60;
        } else {
            el.modalTitle.textContent = "Yeni LLM Ekle";
            el.inputs.id.value = "";
        }
    }

    function closeModal() {
        const el = getElements();
        el.modal.classList.add("hidden");
    }

    // --- FORM SUBMIT ---
    async function handleSubmit(e) {
        e.preventDefault();
        const el = getElements();

        const id = el.inputs.id.value;
        const payload = {
            vendor_code: el.inputs.vendor.value,
            provider: el.inputs.provider.value,
            model_name: el.inputs.model.value,
            api_url: el.inputs.apiUrl.value,
            description: el.inputs.desc.value,
            temperature: parseFloat(el.inputs.temp.value),
            top_p: parseFloat(el.inputs.topP.value),
            timeout_seconds: parseInt(el.inputs.timeout.value) || 60,
        };

        const tokenVal = el.inputs.token.value.trim();
        if (tokenVal) {
            payload.api_token = tokenVal;
        }

        if (!payload.provider || !payload.model_name || !payload.api_url) {
            if (typeof VyraToast !== 'undefined') {
                VyraToast.warning('Lütfen zorunlu alanları doldurun: Provider, Model ve API URL');
            } else {
                alert('Lütfen zorunlu alanları doldurun: Provider, Model ve API URL');
            }
            return;
        }

        try {
            console.log('[NGSSAI] LLM kayıt işlemi başlatılıyor...', { id, payload: { ...payload, api_token: payload.api_token ? '***' : null } });

            if (id && id.trim() !== '') {
                await window.VYRA_API.request(`/llm-config/${id}`, {
                    method: "PUT",
                    body: payload
                });
                if (typeof VyraToast !== 'undefined') {
                    VyraToast.success('LLM konfigürasyonu güncellendi');
                }
            } else {
                await window.VYRA_API.request("/llm-config/", {
                    method: "POST",
                    body: payload
                });
                if (typeof VyraToast !== 'undefined') {
                    VyraToast.success('Yeni LLM konfigürasyonu eklendi');
                }
            }

            closeModal();
            loadConfigs();

        } catch (err) {
            console.error('[NGSSAI] LLM kayıt hatası:', err);

            let errorMsg = 'İşlem başarısız';
            if (err.message && err.message.includes('Failed to fetch')) {
                errorMsg = 'Sunucuya bağlanılamadı. Backend çalışıyor mu kontrol edin.';
            } else if (err.message) {
                errorMsg = err.message;
            }

            if (typeof VyraModal !== 'undefined') {
                VyraModal.error({
                    title: 'Hata',
                    message: errorMsg
                });
            } else {
                alert("İşlem başarısız: " + errorMsg);
            }
        }
    }

    // --- CRUD ---
    async function deleteConfig(id, isActive) {
        if (isActive) {
            VyraModal.warning({
                title: 'Uyarı',
                message: "Aktif olan LLM konfigürasyonu silinemez! Lütfen önce başka bir LLM'i aktif edin."
            });
            return;
        }
        VyraModal.danger({
            title: 'LLM Konfigürasyonunu Sil',
            message: 'Bu LLM konfigürasyonunu silmek istediğinize emin misiniz?',
            confirmText: 'Sil',
            cancelText: 'İptal',
            onConfirm: async () => {
                try {
                    await window.VYRA_API.request(`/llm-config/${id}`, { method: "DELETE" });
                    loadConfigs();
                } catch (err) {
                    VyraModal.error({ title: 'Hata', message: 'Silme başarısız: ' + err.message });
                }
            }
        });
    }

    async function activateConfig(id) {
        try {
            await window.VYRA_API.request(`/llm-config/${id}/activate`, { method: "POST" });
            loadConfigs();
        } catch (err) {
            alert("Aktif etme başarısız: " + err.message);
            loadConfigs();
        }
    }

    function editConfig(id) {
        const llm = window._llmList?.find(l => l.id === id);
        if (llm) {
            openModal(llm);
        }
    }

    // --- INIT ---
    function init() {
        const el = getElements();
        
        if (el.btnNew) el.btnNew.addEventListener("click", () => openModal(null));
        if (el.btnClose) el.btnClose.addEventListener("click", closeModal);
        if (el.btnCancel) el.btnCancel.addEventListener("click", closeModal);
        if (el.form) el.form.addEventListener("submit", handleSubmit);
    }

    // Public API
    return {
        init: init,
        load: loadConfigs,
        edit: editConfig,
        delete: deleteConfig,
        activate: activateConfig,
        openModal: openModal,
        closeModal: closeModal
    };
})();

// Otomatik init (DOM hazır olduğunda)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', window.LLMModule.init);
} else {
    window.LLMModule.init();
}
