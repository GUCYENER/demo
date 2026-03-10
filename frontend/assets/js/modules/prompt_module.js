/* -------------------------------
   VYRA - Prompt Module
   Prompt şablon yönetimi (CRUD)
-------------------------------- */

/**
 * Prompt modülü - Parametreler sekmesinde prompt şablonları yönetimi
 * @module PromptModule
 */
window.PromptModule = (function () {
    'use strict';

    // DOM elementleri (lazy load)
    let elements = null;

    function getElements() {
        if (!elements) {
            elements = {
                grid: document.getElementById("promptGrid"),
                modal: document.getElementById("promptModal"),
                // v2.26.0: btnNew kaldırıldı
                btnClose: document.getElementById("closePromptModal"),
                btnCancel: document.getElementById("btnCancelPrompt"),
                form: document.getElementById("promptForm"),
                modalTitle: document.getElementById("promptModalTitle"),
                inputs: {
                    id: document.getElementById("promptId"),
                    category: document.getElementById("promptCategory"),
                    title: document.getElementById("promptTitle"),
                    content: document.getElementById("promptContent"),
                    description: document.getElementById("promptDescription"),
                }
            };
        }
        return elements;
    }

    // Kategori mapping - v2.26.0: Tüm DB kategorileri
    const categoryIcons = {
        'system': 'fa-solid fa-cog',
        'corpix_l1': 'fa-solid fa-robot',
        'ticket_summary': 'fa-solid fa-ticket',
        'technical_support': 'fa-solid fa-headset',
        'general': 'fa-solid fa-comment-dots'
    };

    const categoryNames = {
        'system': 'Sistem',
        'corpix_l1': 'Corpix L1',
        'ticket_summary': 'Çağrı Özeti',
        'technical_support': 'Teknik Destek',
        'general': 'Genel'
    };

    // --- YÜKLEME ---
    async function loadPrompts() {
        const token = localStorage.getItem('access_token');
        const el = getElements();

        if (!token) {
            if (el.grid) {
                el.grid.innerHTML = '<div class="text-gray-500">Lütfen giriş yapın.</div>';
            }
            return;
        }

        if (!el.grid) {
            console.warn('[VYRA] promptGrid elementi bulunamadı');
            return;
        }

        try {
            el.grid.innerHTML = '<div class="text-gray-400"><i class="fa-solid fa-spinner fa-spin mr-2"></i>Yükleniyor...</div>';

            const data = await window.VYRA_API.request("/prompts/");

            if (!data || !Array.isArray(data)) {
                console.log('[VYRA] Prompt verisi boş veya geçersiz:', data);
                render([]);
                return;
            }

            render(data);

        } catch (err) {
            console.error('[VYRA] Prompt yükleme hatası:', err);

            let errorMessage = 'Prompt listesi yüklenemedi.';
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
                errorMessage = 'Prompt endpoint bulunamadı.';
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
            el.grid.innerHTML = '<div class="text-gray-500">Henüz prompt tanımı yok.</div>';
            return;
        }

        list.forEach(prompt => {
            // v2.26.0: isActive, badge, sil butonu kaldırıldı - tüm promptlar aktif
            const desc = prompt.description ? `<p class="text-gray-400 text-sm mb-4">${prompt.description}</p>` : "";

            const categoryIcon = categoryIcons[prompt.category] || 'fa-solid fa-wand-magic-sparkles';
            const categoryName = categoryNames[prompt.category] || prompt.category;

            const card = document.createElement("div");
            card.className = `bg-[#1a1d24] rounded-xl p-6 hover:shadow-lg transition border-green-500 border-2`;

            card.innerHTML = `
                <div class="flex items-start justify-between mb-4">
                    <div class="flex items-center space-x-4 flex-1 min-w-0">
                        <div class="bg-purple-900/40 p-3 rounded-lg text-purple-400 flex-shrink-0">
                            <i class="${categoryIcon} text-2xl"></i>
                        </div>
                        <div class="min-w-0">
                            <h4 class="font-bold text-lg text-white truncate">${prompt.title}</h4>
                            <p class="text-purple-300 text-sm font-mono">${categoryName}</p>
                        </div>
                    </div>
                    <span class="prompt-active-badge"><i class="fa-solid fa-check mr-1"></i>Aktif</span>
                </div>
                
                ${desc}

                <div class="space-y-2 text-sm text-gray-400 mb-4">
                    <div class="flex justify-between">
                        <span>Oluşturma:</span>
                        <span class="text-gray-200">${new Date(prompt.created_at).toLocaleDateString('tr-TR')}</span>
                    </div>
                </div>

                <div class="bg-[#0f1116] p-3 rounded-lg text-xs font-mono text-gray-400 max-h-24 overflow-y-auto mb-4">
                    ${prompt.content.substring(0, 150)}${prompt.content.length > 150 ? '...' : ''}
                </div>

                <div class="flex items-center justify-end border-t border-gray-700 pt-4 mt-auto">
                    <button class="text-blue-400 hover:text-blue-300 p-2 rounded hover:bg-white/5 transition" onclick="PromptModule.edit(${prompt.id})" title="Prompt'u düzenle">
                        <i class="fa-solid fa-pen"></i> Düzenle
                    </button>
                </div>
            `;
            el.grid.appendChild(card);
        });

        // Store list for edit lookup
        window._promptList = list;
    }

    // --- MODAL İŞLEMLERİ ---
    function openModal(prompt = null) {
        const el = getElements();
        el.modal.classList.remove("hidden");
        el.form.reset();

        if (prompt) {
            el.modalTitle.textContent = "Prompt Düzenle";
            el.inputs.id.value = prompt.id;
            // v2.26.0: Kategoriyi okunabilir ad olarak göster
            el.inputs.category.value = categoryNames[prompt.category] || prompt.category;
            el.inputs.title.value = prompt.title;
            el.inputs.content.value = prompt.content;
            el.inputs.description.value = prompt.description || "";
        }
        // v2.26.0: Yeni prompt ekleme devre dışı
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
        if (!id) {
            alert('Geçersiz prompt ID');
            return;
        }

        // v2.26.0: Sadece content güncellenebilir
        const payload = {
            content: el.inputs.content.value
        };

        try {
            await window.VYRA_API.request(`/prompts/${id}`, {
                method: "PUT",
                body: payload
            });

            closeModal();
            loadPrompts();
            showToast('success', 'Prompt güncellendi');
        } catch (err) {
            alert("İşlem başarısız: " + err.message);
        }
    }

    // v2.26.0: deletePrompt ve activatePrompt kaldırıldı - tüm promptlar aktif ve silme yok

    function editPrompt(id) {
        const prompt = window._promptList?.find(p => p.id === id);
        if (prompt) {
            openModal(prompt);
        }
    }

    // --- ESC TUŞU İLE KAPATMA ---
    function handleEscape(e) {
        const el = getElements();
        if (e.key === "Escape" && el.modal && !el.modal.classList.contains("hidden")) {
            closeModal();
        }
    }

    // --- INIT ---
    function init() {
        const el = getElements();

        // v2.26.0: btnNew kaldırıldı
        if (el.btnClose) el.btnClose.addEventListener("click", closeModal);
        if (el.btnCancel) el.btnCancel.addEventListener("click", closeModal);
        if (el.form) el.form.addEventListener("submit", handleSubmit);

        document.addEventListener("keydown", handleEscape);
    }

    // Public API
    return {
        init: init,
        load: loadPrompts,
        edit: editPrompt,
        // v2.26.0: activate ve delete kaldırıldı
        openModal: openModal,
        closeModal: closeModal
    };
})();

// Otomatik init (DOM hazır olduğunda)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', window.PromptModule.init);
} else {
    window.PromptModule.init();
}
