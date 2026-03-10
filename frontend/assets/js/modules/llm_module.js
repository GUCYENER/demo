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
                el.grid.innerHTML = '<div class="text-gray-500">Lütfen giriş yapın.</div>';
            }
            return;
        }

        if (!el.grid) {
            console.warn('[NGSSAI] llmGrid elementi bulunamadı');
            return;
        }

        try {
            el.grid.innerHTML = '<div class="text-gray-400"><i class="fa-solid fa-spinner fa-spin mr-2"></i>Yükleniyor...</div>';

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

            el.grid.innerHTML = `<div class="${messageClass}"><i class="fa-solid fa-exclamation-triangle mr-2"></i>${errorMessage}</div>`;
        }
    }

    // --- RENDER ---
    function render(list) {
        const el = getElements();
        el.grid.innerHTML = "";

        if (!list || list.length === 0) {
            el.grid.innerHTML = '<div class="text-gray-500">Henüz LLM tanımı yok.</div>';
            return;
        }

        list.forEach(llm => {
            const isActive = llm.is_active === true || llm.is_active === 1;
            const activeClass = isActive ? "border-green-500 border-2" : "border-gray-700 border";
            const badge = isActive
                ? `<span class="bg-green-600 text-white text-xs px-2 py-1 rounded-full absolute top-4 right-4 shadow-sm"><i class="fa-solid fa-check mr-1"></i>Aktif</span>`
                : ``;

            const desc = llm.description ? `<p class="text-gray-400 text-sm mb-4">${llm.description}</p>` : "";
            const deleteStyle = isActive ? "opacity-30 cursor-not-allowed" : "hover:bg-white/5 hover:text-red-300";

            const card = document.createElement("div");
            card.className = `bg-[#1a1d24] rounded-xl p-6 relative hover:shadow-lg transition ${activeClass}`;

            card.innerHTML = `
                ${badge}
                <div class="flex items-center space-x-4 mb-4">
                    <div class="bg-blue-900/40 p-3 rounded-lg text-blue-400">
                        <i class="fa-solid fa-robot text-2xl"></i>
                    </div>
                    <div>
                        <h4 class="font-bold text-lg text-white">${llm.provider}</h4>
                        <p class="text-indigo-300 text-sm font-mono">${llm.model_name}</p>
                    </div>
                </div>
                
                ${desc}

                <div class="space-y-2 text-sm text-gray-400 mb-6">
                     <div class="flex justify-between">
                        <span>Vendor:</span>
                        <span class="text-gray-200">${llm.vendor_code}</span>
                    </div>
                     <div class="flex justify-between">
                        <span>Temp / TopP:</span>
                        <span class="text-gray-200">${llm.temperature} / ${llm.top_p}</span>
                    </div>
                </div>

                <div class="flex items-center justify-between border-t border-gray-700 pt-4 mt-auto">
                    <label class="flex items-center cursor-pointer space-x-2">
                        <input type="radio" name="active_llm" class="form-radio text-green-500 focus:ring-green-500 h-4 w-4" 
                               ${isActive ? "checked" : ""} 
                               onclick="LLMModule.activate(${llm.id})">
                        <span class="text-sm text-gray-300">Aktif Kullan</span>
                    </label>
                    
                    <div class="space-x-2">
                        <button class="text-blue-400 hover:text-blue-300 p-2 rounded hover:bg-white/5 transition" onclick="LLMModule.edit(${llm.id})">
                            <i class="fa-solid fa-pen"></i>
                        </button>
                        
                        <button class="text-red-400 p-2 rounded transition ${deleteStyle}" onclick="LLMModule.delete(${llm.id}, ${isActive})">
                            <i class="fa-solid fa-trash"></i>
                        </button>
                    </div>
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
