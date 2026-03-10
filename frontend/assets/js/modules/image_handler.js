/* -------------------------------
   VYRA - Image Handler Module
   Çoklu görsel yükleme, yapıştırma ve sürükle-bırak
   v2.0 - Multiple Image Support
-------------------------------- */

/**
 * Image Handler modülü - Textarea'ya çoklu görsel ekleme işlemleri
 * @module ImageHandler
 */
window.ImageHandler = (function () {
    'use strict';

    // Eklenen görseller listesi
    let attachedImages = [];
    const MAX_IMAGES = 5; // Maksimum görsel sayısı

    // DOM elementleri (lazy load)
    let elements = null;

    function getElements() {
        if (!elements) {
            elements = {
                attachBtn: document.getElementById("attachImageBtn"),
                input: document.getElementById("imageInput"),
                previewContainer: document.getElementById("imagePreviewContainer"),
                previewGrid: document.getElementById("imagePreviewGrid"),
                textarea: document.getElementById("problemText")
            };
        }
        return elements;
    }

    // --- GÖRSEL EKLEME ---
    function addImage(file) {
        if (!file || !file.type.startsWith('image/')) return false;

        // Maksimum kontrol
        if (attachedImages.length >= MAX_IMAGES) {
            if (typeof VyraToast !== 'undefined') {
                VyraToast.warning(`En fazla ${MAX_IMAGES} görsel eklenebilir`);
            }
            return false;
        }

        // Duplicate kontrol
        const isDuplicate = attachedImages.some(img =>
            img.name === file.name && img.size === file.size
        );
        if (isDuplicate) {
            if (typeof VyraToast !== 'undefined') {
                VyraToast.info('Bu görsel zaten eklendi');
            }
            return false;
        }

        const reader = new FileReader();
        reader.onload = (event) => {
            const imageData = {
                id: Date.now() + Math.random().toString(36).substr(2, 9),
                name: file.name,
                size: file.size,
                type: file.type,
                dataUrl: event.target.result,
                file: file
            };

            attachedImages.push(imageData);
            renderPreviews();
            updateHiddenInput();
        };
        reader.readAsDataURL(file);
        return true;
    }

    // --- ÖNİZLEME RENDER ---
    function renderPreviews() {
        const el = getElements();
        if (!el.previewGrid || !el.previewContainer) return;

        el.previewGrid.innerHTML = '';

        if (attachedImages.length === 0) {
            el.previewContainer.classList.add('hidden');
            return;
        }

        el.previewContainer.classList.remove('hidden');

        attachedImages.forEach((img, index) => {
            const item = document.createElement('div');
            item.className = 'image-preview-item';
            item.dataset.imageId = img.id;

            item.innerHTML = `
                <img src="${img.dataUrl}" alt="${img.name}" class="preview-thumb" />
                <button type="button" class="btn-remove-single" title="Kaldır" data-index="${index}">
                    <i class="fa-solid fa-xmark"></i>
                </button>
                <span class="preview-name">${truncateName(img.name, 15)}</span>
            `;

            // Kaldır butonu event
            item.querySelector('.btn-remove-single').addEventListener('click', (e) => {
                e.stopPropagation();
                removeImage(index);
            });

            el.previewGrid.appendChild(item);
        });
    }

    // --- GÖRSEL KALDIRMA ---
    function removeImage(index) {
        attachedImages.splice(index, 1);
        renderPreviews();
        updateHiddenInput();
    }

    // --- TÜM GÖRSELLERİ TEMİZLE ---
    function clearAllImages() {
        attachedImages = [];
        renderPreviews();
        updateHiddenInput();
    }

    // --- HIDDEN INPUT GÜNCELLEME (Backend için) ---
    function updateHiddenInput() {
        const el = getElements();
        if (!el.input) return;

        const dataTransfer = new DataTransfer();
        attachedImages.forEach(img => {
            dataTransfer.items.add(img.file);
        });
        el.input.files = dataTransfer.files;
    }

    // --- YARDIMCI: İsim kısaltma ---
    function truncateName(name, maxLen) {
        if (name.length <= maxLen) return name;
        const ext = name.split('.').pop();
        const baseName = name.substring(0, maxLen - ext.length - 4);
        return `${baseName}...${ext}`;
    }

    // --- YAPISTIRMA (Ctrl+V) ---
    let pasteDebounceTimer = null;
    let lastPasteTime = 0;

    function handlePaste(e) {
        // Debounce: 500ms içinde gelen tekrar paste'leri engelle
        const now = Date.now();
        if (now - lastPasteTime < 500) {
            console.log('[ImageHandler] Duplicate paste engellendi');
            e.preventDefault();
            return;
        }
        lastPasteTime = now;

        const items = e.clipboardData?.items;
        if (!items) return;

        for (let i = 0; i < items.length; i++) {
            if (items[i].type.startsWith('image/')) {
                e.preventDefault();
                const file = items[i].getAsFile();
                if (addImage(file)) {
                    if (typeof VyraToast !== 'undefined') {
                        VyraToast.success('Görsel yapıştırıldı');
                    }
                }
                break;
            }
        }
    }

    // --- SÜRÜKLE-BIRAK ---
    function handleDragOver(e) {
        e.preventDefault();
        e.currentTarget.classList.add('drag-over');
    }

    function handleDragLeave(e) {
        e.preventDefault();
        e.currentTarget.classList.remove('drag-over');
    }

    function handleDrop(e) {
        e.preventDefault();
        e.currentTarget.classList.remove('drag-over');

        const files = e.dataTransfer?.files;
        if (files && files.length > 0) {
            let addedCount = 0;
            for (let i = 0; i < files.length; i++) {
                if (addImage(files[i])) {
                    addedCount++;
                }
            }
            if (addedCount > 0 && typeof VyraToast !== 'undefined') {
                VyraToast.success(`${addedCount} görsel eklendi`);
            }
        }
    }

    // --- EKLENEN GÖRSELLERİ AL ---
    function getImages() {
        return attachedImages;
    }

    function getFiles() {
        return attachedImages.map(img => img.file);
    }

    // --- INIT ---
    function init() {
        const el = getElements();

        // Attach button
        if (el.attachBtn && el.input) {
            el.attachBtn.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopPropagation();
                el.input.click();
            });

            // Multiple file support
            el.input.setAttribute('multiple', 'multiple');

            el.input.addEventListener("change", (e) => {
                const files = e.target.files;
                if (files && files.length > 0) {
                    let addedCount = 0;
                    for (let i = 0; i < files.length; i++) {
                        if (addImage(files[i])) {
                            addedCount++;
                        }
                    }
                    if (addedCount > 0 && typeof VyraToast !== 'undefined') {
                        VyraToast.success(`${addedCount} görsel eklendi`);
                    }
                }
                // Input'u sıfırla (aynı dosyayı tekrar seçebilmek için)
                el.input.value = '';
            });
        }

        // Textarea events (paste, drag, drop)
        if (el.textarea) {
            el.textarea.addEventListener('paste', handlePaste);
            el.textarea.addEventListener('dragover', handleDragOver);
            el.textarea.addEventListener('dragleave', handleDragLeave);
            el.textarea.addEventListener('drop', handleDrop);
        }

        // Tümünü Kaldır butonu
        const clearAllBtn = document.getElementById('clearAllImagesBtn');
        if (clearAllBtn) {
            clearAllBtn.addEventListener('click', clearAllImages);
        }

        console.log('[ImageHandler] Çoklu görsel desteği başlatıldı (max: ' + MAX_IMAGES + ')');
    }

    // Public API
    return {
        init: init,
        addImage: addImage,
        removeImage: removeImage,
        clearAll: clearAllImages,
        getImages: getImages,
        getFiles: getFiles
    };
})();

// Otomatik init (DOM hazır olduğunda)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', window.ImageHandler.init);
} else {
    window.ImageHandler.init();
}
