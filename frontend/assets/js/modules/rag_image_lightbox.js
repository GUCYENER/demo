/**
 * VYRA — RAG Image Lightbox Module
 * Doküman görsellerinin büyütülmüş gösterimi.
 * Inline görsellere tıklandığında lightbox açılır.
 * 
 * Version: 1.0.0
 */

(function () {
    'use strict';

    let lightboxOverlay = null;

    /**
     * Lightbox DOM yapısını oluştur (lazy init).
     */
    function _ensureLightbox() {
        if (lightboxOverlay) return;

        lightboxOverlay = document.createElement('div');
        lightboxOverlay.className = 'rag-lightbox-overlay';
        lightboxOverlay.innerHTML = `
            <span class="rag-lightbox-close">&times;</span>
            <img class="rag-lightbox-image" src="" alt="Büyütülmüş görsel" />
        `;

        document.body.appendChild(lightboxOverlay);

        // Overlay'e tıklayınca kapat
        lightboxOverlay.addEventListener('click', (e) => {
            if (e.target === lightboxOverlay || e.target.classList.contains('rag-lightbox-close')) {
                _closeLightbox();
            }
        });

        // ESC tuşu ile kapat
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && lightboxOverlay.classList.contains('visible')) {
                _closeLightbox();
            }
        });
    }

    /**
     * Lightbox'ı aç.
     */
    function _openLightbox(imageSrc, altText) {
        _ensureLightbox();
        const img = lightboxOverlay.querySelector('.rag-lightbox-image');
        img.src = imageSrc;
        img.alt = altText || 'Doküman görseli';
        lightboxOverlay.classList.add('visible');
    }

    /**
     * Lightbox'ı kapat.
     */
    function _closeLightbox() {
        if (lightboxOverlay) {
            lightboxOverlay.classList.remove('visible');
        }
    }

    /**
     * Chat body içindeki rag-inline-image'lere tıklama dinleyicisi ekle.
     * MutationObserver ile yeni eklenen görseller de yakalanır.
     */
    function init() {
        // Mevcut görsellere bağla
        _bindImages(document);

        // Dinamik eklenen görseller için observer
        const chatBody = document.getElementById('dialogChatBody') || document.body;
        const observer = new MutationObserver((mutations) => {
            for (const mutation of mutations) {
                for (const node of mutation.addedNodes) {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        _bindImages(node);
                    }
                }
            }
        });
        observer.observe(chatBody, { childList: true, subtree: true });
    }

    /**
     * Container içindeki tüm rag-inline-image'lere click event bağla.
     */
    function _bindImages(container) {
        const images = container.querySelectorAll
            ? container.querySelectorAll('.rag-inline-image')
            : [];

        images.forEach(img => {
            if (img.dataset.lightboxBound) return;
            img.dataset.lightboxBound = 'true';

            img.addEventListener('click', () => {
                _openLightbox(img.src, img.alt);
            });
        });
    }

    // Auto-init on DOMContentLoaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Public API
    window.RAGImageLightbox = { init, open: _openLightbox, close: _closeLightbox };
})();
