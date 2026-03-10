/* ─────────────────────────────────────────────
   NGSSAI — Dialog Images Module
   v2.30.1 · dialog_chat.js'den ayrıştırıldı
   Görsel yapıştırma, dosya seçme, önizleme
   ───────────────────────────────────────────── */

window.DialogImagesModule = (function () {
    'use strict';

    let pendingImages = [];


    // escapeForJs → DialogChatUtils'e taşındı (dialog_chat_utils.js)

    // =============================================================================
    // IMAGE HANDLING
    // =============================================================================

    function handlePaste(e) {
        const items = e.clipboardData?.items;
        if (!items) return;

        for (const item of items) {
            if (item.type.startsWith('image/')) {
                e.preventDefault();
                const file = item.getAsFile();
                addImage(file);
                break;
            }
        }
    }

    function handleFileSelect(e) {
        const files = e.target.files;
        for (const file of files) {
            if (file.type.startsWith('image/')) {
                addImage(file);
            }
        }
        e.target.value = '';
    }

    function addImage(file) {
        if (pendingImages.length >= 5) {
            showToast('warning', 'Maksimum 5 görsel ekleyebilirsiniz');
            return;
        }

        const reader = new FileReader();
        reader.onload = (e) => {
            const base64 = e.target.result;
            pendingImages.push({ file, base64, preview: base64 });
            renderImagePreviews();
            // dialog_chat.js scope'undaki pendingImages'ı da senkronize et
            if (window.DialogChatModule?._syncPendingImages) {
                window.DialogChatModule._syncPendingImages(pendingImages);
            }
        };
        reader.readAsDataURL(file);
    }

    function removeImage(index) {
        pendingImages.splice(index, 1);
        renderImagePreviews();
        // dialog_chat.js scope'undaki pendingImages'ı da senkronize et
        if (window.DialogChatModule?._syncPendingImages) {
            window.DialogChatModule._syncPendingImages(pendingImages);
        }
    }

    function clearPendingImages() {
        pendingImages = [];
        renderImagePreviews();
    }

    function renderImagePreviews() {
        let container = document.getElementById('dialogImagePreview');

        if (pendingImages.length === 0) {
            if (container) container.remove();
            return;
        }

        if (!container) {
            const inputArea = document.querySelector('.dialog-input-area');
            if (!inputArea) return;

            container = document.createElement('div');
            container.id = 'dialogImagePreview';
            container.className = 'dialog-image-preview';
            inputArea.insertAdjacentElement('beforebegin', container);
        }

        container.innerHTML = pendingImages.map((img, i) => `
            <div class="dialog-preview-item">
                <img src="${img.preview}" alt="Preview">
                <button class="dialog-preview-remove" onclick="DialogChatModule.removeImage(${i})">×</button>
            </div>
        `).join('');
    }


    return {
        handlePaste,
        handleFileSelect,
        addImage,
        removeImage,
        clearPendingImages,
        renderImagePreviews,
        getPendingImages: function () { return pendingImages; },
        setPendingImages: function (v) { pendingImages = v; }
    };
})();
