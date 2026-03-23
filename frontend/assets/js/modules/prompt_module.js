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
    async function loadPrompts(companyId) {
        const token = localStorage.getItem('access_token');
        const el = getElements();

        if (!token) {
            if (el.grid) {
                el.grid.innerHTML = '<div class="n-page-empty"><i class="fa-solid fa-lock"></i><p>Lütfen giriş yapın.</p></div>';
            }
            return;
        }

        if (!el.grid) {
            console.warn('[NGSSAI] promptGrid elementi bulunamadı');
            return;
        }

        try {
            el.grid.innerHTML = '<div style="padding:20px;color:var(--text-3);font-size:13px"><i class="fa-solid fa-spinner fa-spin" style="margin-right:8px"></i>Yükleniyor...</div>';

            const url = companyId ? '/prompts/?company_id=' + companyId : '/prompts/';
            const data = await window.VYRA_API.request(url);

            if (!data || !Array.isArray(data)) {
                console.log('[NGSSAI] Prompt verisi boş veya geçersiz:', data);
                render([]);
                return;
            }

            render(data);

        } catch (err) {
            console.error('[NGSSAI] Prompt yükleme hatası:', err);

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

            el.grid.innerHTML = `<div style="padding:20px;color:var(--red);font-size:13px"><i class="fa-solid fa-exclamation-triangle" style="margin-right:8px"></i>${errorMessage}</div>`;
        }
    }

    // --- RENDER ---
    function render(list) {
        const el = getElements();
        el.grid.innerHTML = "";

        if (!list || list.length === 0) {
            el.grid.innerHTML = '<div class="n-page-empty"><i class="fa-solid fa-wand-magic-sparkles"></i><p>Henüz prompt tanımı yok.</p></div>';
            return;
        }

        list.forEach(prompt => {
            // v2.26.0: isActive, badge, sil butonu kaldırıldı - tüm promptlar aktif
            const desc = prompt.description ? `<p class="text-gray-400 text-sm mb-4">${prompt.description}</p>` : "";

            const categoryIcon = categoryIcons[prompt.category] || 'fa-solid fa-wand-magic-sparkles';
            const categoryName = categoryNames[prompt.category] || prompt.category;

            const card = document.createElement("div");
            card.className = "card";
            card.style.marginBottom = "12px";

            card.innerHTML = `
                <div class="sec-head">
                    <div class="sec-title">
                        <i class="${categoryIcon}" style="color:var(--accent);font-size:13px"></i>
                        ${prompt.title}
                    </div>
                    <div style="display:flex;align-items:center;gap:8px">
                        <span class="badge badge-green"><span class="badge-dot"></span>Aktif</span>
                        <button class="act-btn edit" onclick="PromptModule.edit(${prompt.id})" title="Prompt'u düzenle">
                            <i class="fa-solid fa-pen"></i>
                        </button>
                    </div>
                </div>
                <div style="padding:16px 18px">
                    <div style="font-size:12px;color:var(--text-3);margin-bottom:8px">${categoryName}</div>
                    ${desc}
                    <div style="background:var(--bg-input);border:1px solid var(--border);border-radius:8px;padding:12px;font-family:'IBM Plex Mono',monospace;font-size:11.5px;color:var(--text-2);max-height:96px;overflow-y:auto;line-height:1.6">
                        ${prompt.content.substring(0, 150)}${prompt.content.length > 150 ? '...' : ''}
                    </div>
                    <div style="margin-top:8px;font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--text-3)">Oluşturma: ${new Date(prompt.created_at).toLocaleDateString('tr-TR')}</div>
                </div>
            `;
            el.grid.appendChild(card);
        });

        // Store list for edit lookup
        window._promptList = list;
    }

    // --- MODAL İŞLEMLERİ ---
    async function openModal(prompt = null) {
        const el = getElements();
        el.modal.classList.remove("hidden");
        el.form.reset();

        // Firma dropdown'ı doldur
        const compSel = document.getElementById('promptCompanyId');
        if (compSel && window.populateCompanySelect) {
            await window.populateCompanySelect(compSel, prompt ? prompt.company_id : null);
        }

        if (prompt) {
            el.modalTitle.textContent = "Prompt Düzenle";
            el.inputs.id.value = prompt.id;
            el.inputs.category.value = categoryNames[prompt.category] || prompt.category;
            el.inputs.title.value = prompt.title;
            el.inputs.content.value = prompt.content;
            el.inputs.description.value = prompt.description || "";
        } else {
            // Global selector'dan öntanımlı firma
            const globalSel = document.getElementById('globalCompanySelect');
            if (globalSel && globalSel.value && compSel) {
                compSel.value = globalSel.value;
            }
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
            VyraModal.warning({ title: 'Hata', message: 'Geçersiz prompt ID' });
            return;
        }

        // v2.26.0: Sadece content güncellenebilir
        const compSel = document.getElementById('promptCompanyId');
        const companyVal = compSel ? compSel.value : '';
        const payload = {
            content: el.inputs.content.value
        };
        if (companyVal) payload.company_id = parseInt(companyVal, 10);

        try {
            await window.VYRA_API.request(`/prompts/${id}`, {
                method: "PUT",
                body: payload
            });

            closeModal();
            loadPrompts();
            showToast('Prompt güncellendi', 'success');
        } catch (err) {
            VyraModal.error({ title: 'Hata', message: 'İşlem başarısız: ' + err.message });
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
