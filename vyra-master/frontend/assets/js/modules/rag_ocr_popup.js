/**
 * VYRA — RAG OCR Popup Module
 * Görsellerdeki OCR metnini popup ile gösterir.
 * Inline görsellere hover'da "📝 Metin" butonu eklenir.
 * 
 * Version: 1.0.0
 */

(function () {
    'use strict';

    // v2.48.0: Merkezi config.js'ten dinamik URL
    const API_BASE = window.API_BASE_URL || 'http://localhost:8002';
    let popupOverlay = null;

    /**
     * Popup DOM yapısını oluştur (lazy init).
     */
    function _ensurePopup() {
        if (popupOverlay) return;

        popupOverlay = document.createElement('div');
        popupOverlay.className = 'rag-ocr-popup-overlay';
        popupOverlay.innerHTML = `
            <div class="rag-ocr-popup-container">
                <div class="rag-ocr-popup-header">
                    <span class="rag-ocr-popup-title">📝 Görseldeki Metin (OCR)</span>
                    <div class="rag-ocr-popup-actions">
                        <button class="rag-ocr-copy-btn" title="Metni kopyala">
                            <i class="fas fa-copy"></i> Kopyala
                        </button>
                        <span class="rag-ocr-popup-close">&times;</span>
                    </div>
                </div>
                <div class="rag-ocr-popup-body">
                    <div class="rag-ocr-popup-loading">
                        <i class="fas fa-spinner fa-spin"></i> OCR metni yükleniyor...
                    </div>
                    <pre class="rag-ocr-popup-text"></pre>
                    <div class="rag-ocr-popup-empty">
                        Bu görselde okunabilir metin bulunamadı.
                    </div>
                </div>
                <div class="rag-ocr-popup-footer">
                    <small>EasyOCR ile çıkarılmıştır • Türkçe + İngilizce</small>
                </div>
            </div>
        `;

        document.body.appendChild(popupOverlay);

        // Close butonu
        popupOverlay.querySelector('.rag-ocr-popup-close').addEventListener('click', _closePopup);

        // Overlay tıklama — container dışına tıklayınca KAPATMA (kural: overlay koruması)
        // Sadece close butonu veya ESC ile kapanır

        // Kopyala butonu
        popupOverlay.querySelector('.rag-ocr-copy-btn').addEventListener('click', () => {
            const text = popupOverlay.querySelector('.rag-ocr-popup-text').textContent;
            if (text) {
                navigator.clipboard.writeText(text).then(() => {
                    const btn = popupOverlay.querySelector('.rag-ocr-copy-btn');
                    btn.innerHTML = '<i class="fas fa-check"></i> Kopyalandı!';
                    setTimeout(() => {
                        btn.innerHTML = '<i class="fas fa-copy"></i> Kopyala';
                    }, 2000);
                });
            }
        });

        // ESC desteği
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && popupOverlay.classList.contains('visible')) {
                _closePopup();
            }
        });
    }

    /**
     * OCR popup'ını aç ve API'den metin çek.
     */
    async function _openPopup(imageId) {
        _ensurePopup();

        const loading = popupOverlay.querySelector('.rag-ocr-popup-loading');
        const textEl = popupOverlay.querySelector('.rag-ocr-popup-text');
        const emptyEl = popupOverlay.querySelector('.rag-ocr-popup-empty');

        loading.style.display = 'flex';
        textEl.style.display = 'none';
        emptyEl.style.display = 'none';
        textEl.textContent = '';

        popupOverlay.classList.add('visible');

        try {
            const resp = await fetch(`${API_BASE}/api/rag/images/${imageId}/ocr`);
            const data = await resp.json();

            loading.style.display = 'none';

            if (data.has_text && data.ocr_text) {
                textEl.textContent = data.ocr_text;
                textEl.style.display = 'block';
            } else {
                emptyEl.style.display = 'block';
            }
        } catch (err) {
            loading.style.display = 'none';
            emptyEl.textContent = 'OCR verisi yüklenirken hata oluştu.';
            emptyEl.style.display = 'block';
        }
    }

    /**
     * Popup'ı kapat.
     */
    function _closePopup() {
        if (popupOverlay) {
            popupOverlay.classList.remove('visible');
        }
    }

    /**
     * Inline görsellere OCR butonu ekle.
     * X-Has-OCR header'ı kontrol edilir (image load sonrası).
     */
    function _addOcrButton(imgElement) {
        if (imgElement.dataset.ocrBound) return;
        imgElement.dataset.ocrBound = 'true';

        const imageId = imgElement.dataset.imageId;
        if (!imageId) return;

        // Wrapper oluştur
        const wrapper = document.createElement('span');
        wrapper.className = 'rag-image-ocr-wrapper';

        // OCR buton
        const ocrBtn = document.createElement('button');
        ocrBtn.className = 'rag-ocr-trigger-btn';
        ocrBtn.innerHTML = '📝 <span>Metin</span>';
        ocrBtn.title = 'Görseldeki metni göster (OCR)';

        ocrBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            _openPopup(parseInt(imageId, 10));
        });

        // img'yi wrapper'a taşı
        imgElement.parentNode.insertBefore(wrapper, imgElement);
        wrapper.appendChild(imgElement);
        wrapper.appendChild(ocrBtn);

        // 🆕 v2.37.0: Hover tooltip - OCR metnini prefetch et
        _prefetchOcrTooltip(wrapper, imageId);
    }

    /**
     * 🆕 v2.37.0 → v2.45.0: Görsel için OCR metnini API'den çekip tooltip olarak ekle.
     * Tooltip, body'ye eklenir (overflow:hidden parent'lar tarafından kesilmesin).
     * Görselin üzerine gelindiğinde konumlanarak gösterilir.
     */
    async function _prefetchOcrTooltip(wrapper, imageId) {
        try {
            const resp = await fetch(`${API_BASE}/api/rag/images/${imageId}/ocr`);
            if (!resp.ok) return;

            const data = await resp.json();
            if (data.has_text && data.ocr_text) {
                // Tooltip'i body'ye ekle (overflow:hidden sorununu aş)
                const tooltip = document.createElement('div');
                tooltip.className = 'rag-image-ocr-tooltip';

                // Header
                const header = document.createElement('div');
                header.className = 'rag-image-ocr-tooltip-header';
                header.textContent = '📝 OCR Metin';
                tooltip.appendChild(header);

                // İçerik
                const content = document.createElement('span');
                const maxLen = 500;
                content.textContent = data.ocr_text.length > maxLen
                    ? data.ocr_text.substring(0, maxLen) + '...'
                    : data.ocr_text;
                tooltip.appendChild(content);

                document.body.appendChild(tooltip);
                wrapper.classList.add('has-ocr-tooltip');

                // mouseenter → tooltip göster + konumla
                wrapper.addEventListener('mouseenter', () => {
                    const rect = wrapper.getBoundingClientRect();
                    tooltip.style.display = 'block';
                    tooltip.style.position = 'fixed';
                    tooltip.style.left = rect.left + (rect.width / 2) + 'px';
                    tooltip.style.bottom = (window.innerHeight - rect.top + 8) + 'px';
                    tooltip.style.transform = 'translateX(-50%)';

                    // Ekran dışına taşma kontrolü
                    requestAnimationFrame(() => {
                        const tipRect = tooltip.getBoundingClientRect();
                        if (tipRect.left < 8) {
                            tooltip.style.left = '8px';
                            tooltip.style.transform = 'none';
                        } else if (tipRect.right > window.innerWidth - 8) {
                            tooltip.style.left = (window.innerWidth - tipRect.width - 8) + 'px';
                            tooltip.style.transform = 'none';
                        }
                        // Yukarı taşma → aşağı göster
                        if (tipRect.top < 8) {
                            tooltip.style.bottom = 'auto';
                            tooltip.style.top = (rect.bottom + 8) + 'px';
                        }
                    });
                });

                // mouseleave → gizle
                wrapper.addEventListener('mouseleave', () => {
                    tooltip.style.display = 'none';
                });
            }
        } catch (err) {
            // Tooltip yüklenemezse sessizce geç
        }
    }

    /**
     * Container içindeki tüm rag-inline-image'lere OCR buton bağla.
     */
    function _bindImages(container) {
        const images = container.querySelectorAll
            ? container.querySelectorAll('.rag-inline-image[data-image-id]')
            : [];

        images.forEach(img => _addOcrButton(img));
    }

    /**
     * Init — MutationObserver ile dinamik görselleri yakala.
     */
    function init() {
        _bindImages(document);

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

    // Auto-init
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.RAGOCRPopup = { init, open: _openPopup, close: _closePopup };
})();
