/**
 * VYRA — Document Enhancer Modal Module
 * =======================================
 * CatBoost + LLM doküman iyileştirme modal modülü.
 * 
 * Akış:
 * 1. analyze() → Backend'e dosya gönder
 * 2. Sonuçları diff view ile göster
 * 3. İyileştirilmiş DOCX indirme
 * 
 * Version: 1.0.0 (v2.36.0)
 */

const DocumentEnhancerModal = (function () {
    'use strict';

    // ─── State ───
    let _currentSessionId = null;
    let _currentFileName = null;
    let _overlayEl = null;

    // ─── API Base ───
    const API_BASE = window.API_BASE_URL || 'http://localhost:8002';

    // ─── Change type → Türkçe label ───
    const CHANGE_LABELS = {
        'heading_added': 'Başlık Eklendi',
        'content_restructured': 'İçerik Düzenlendi',
        'table_fixed': 'Tablo Düzeltildi',
        'encoding_fixed': 'Encoding Düzeltildi',
        'formatting_improved': 'Format İyileştirildi',
        'no_change': 'Değişiklik Yok'
    };

    // ─────────────────────────────────────────
    //  PUBLIC: Modal Oluştur & Aç
    // ─────────────────────────────────────────

    function analyze(file, maturityResult) {
        _createOverlay();
        _showLoading('Doküman analiz ediliyor...');

        _sendToBackend(file)
            .then(data => {
                if (data.error) {
                    _showError(data.error);
                    return;
                }
                _currentSessionId = data.session_id;
                _renderResults(data);
            })
            .catch(err => {
                console.error('[Enhancer] Hata:', err);
                _showError(err.message || 'Bilinmeyen bir hata oluştu.');
            });
    }

    function close() {
        if (_overlayEl) {
            _overlayEl.classList.remove('visible');
            setTimeout(() => {
                if (_overlayEl && _overlayEl.parentNode) {
                    _overlayEl.parentNode.removeChild(_overlayEl);
                }
                _overlayEl = null;
            }, 300);
        }

        // Geçici dosya temizle
        if (_currentSessionId) {
            _cleanupSession(_currentSessionId);
            _currentSessionId = null;
        }
    }

    // ─────────────────────────────────────────
    //  OVERLAY
    // ─────────────────────────────────────────

    function _createOverlay() {
        // Mevcut overlay varsa kaldır
        const existing = document.querySelector('.enhancer-modal-overlay');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.className = 'enhancer-modal-overlay visible';

        overlay.innerHTML = `
            <div class="enhancer-modal">
                <div class="enhancer-modal-header">
                    <div class="enhancer-modal-title">
                        <i class="fas fa-magic"></i>
                        <span>Doküman İyileştirme</span>
                    </div>
                    <button class="enhancer-modal-close" title="Kapat">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                <div class="enhancer-modal-body" id="enhancerModalBody">
                    <!-- İçerik buraya render edilir -->
                </div>
                <div class="enhancer-modal-footer" id="enhancerModalFooter">
                    <div class="enhancer-footer-info" id="enhancerFooterInfo"></div>
                    <div class="enhancer-footer-actions">
                        <button class="enhancer-btn enhancer-btn-cancel" id="enhancerBtnCancel">
                            <i class="fas fa-times"></i> İptal
                        </button>
                        <button class="enhancer-btn enhancer-btn-download" id="enhancerBtnDownload" disabled>
                            <i class="fas fa-download"></i> Seçilenleri Uygula & İndir
                        </button>
                        <button class="enhancer-btn enhancer-btn-upload" id="enhancerBtnUpload" disabled>
                            <i class="fas fa-cloud-upload-alt"></i> Onayla & Bilgi Tabanına Yükle
                        </button>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(overlay);
        _overlayEl = overlay;

        // Event listener'lar
        overlay.querySelector('.enhancer-modal-close').addEventListener('click', close);
        overlay.querySelector('#enhancerBtnCancel').addEventListener('click', close);

        // ESC tuşu
        document.addEventListener('keydown', _onEscKey);
    }

    function _onEscKey(e) {
        if (e.key === 'Escape' && _overlayEl) {
            close();
            document.removeEventListener('keydown', _onEscKey);
        }
    }

    // ─────────────────────────────────────────
    //  LOADING STATE
    // ─────────────────────────────────────────

    function _showLoading(stepText) {
        const body = document.getElementById('enhancerModalBody');
        if (!body) return;

        body.innerHTML = `
            <div class="enhancer-loading">
                <div class="enhancer-loading-spinner"></div>
                <div class="enhancer-loading-text">CatBoost analiz ve LLM iyileştirme süreci devam ediyor...</div>
                <div class="enhancer-loading-step">${_escapeHtml(stepText)}</div>
            </div>
        `;

        // Footer gizle
        const footer = document.getElementById('enhancerModalFooter');
        if (footer) footer.style.display = 'none';
    }

    // ─────────────────────────────────────────
    //  ERROR STATE
    // ─────────────────────────────────────────

    function _showError(message) {
        const body = document.getElementById('enhancerModalBody');
        if (!body) return;

        body.innerHTML = `
            <div class="enhancer-error">
                <div class="enhancer-error-icon"><i class="fas fa-exclamation-triangle"></i></div>
                <div class="enhancer-error-text">${_escapeHtml(message)}</div>
            </div>
        `;

        // Footer göster (sadece iptal)
        const footer = document.getElementById('enhancerModalFooter');
        if (footer) footer.style.display = 'flex';
        const downloadBtn = document.getElementById('enhancerBtnDownload');
        if (downloadBtn) downloadBtn.style.display = 'none';
    }

    // ─────────────────────────────────────────
    //  RESULT RENDERING
    // ─────────────────────────────────────────

    function _renderResults(data) {
        const body = document.getElementById('enhancerModalBody');
        if (!body) return;

        // Dosya adını sakla (download/upload için)
        _currentFileName = data.file_name || null;

        let html = '';

        // ─── Summary Cards ───
        const summary = data.catboost_summary || {};
        html += `
            <div class="enhancer-summary-row">
                <div class="enhancer-summary-card">
                    <div class="enhancer-summary-card-title">Toplam Bölüm</div>
                    <div class="enhancer-summary-card-value sections">${data.total_sections}</div>
                </div>
                <div class="enhancer-summary-card">
                    <div class="enhancer-summary-card-title">İyileştirilen</div>
                    <div class="enhancer-summary-card-value enhanced">${data.enhanced_count}</div>
                </div>
                <div class="enhancer-summary-card">
                    <div class="enhancer-summary-card-title">CatBoost Analizi</div>
                    <div class="enhancer-summary-card-value catboost">
                        ${summary.catboost_available ? '<i class="fas fa-check-circle"></i> Aktif' : '<i class="fas fa-minus-circle"></i> Heuristik'}
                    </div>
                    <div class="enhancer-summary-card-sub">
                        ${summary.high_priority_count || 0} yüksek öncelikli bölüm
                    </div>
                </div>
            </div>
        `;

        // ─── Section Cards ───
        const sections = data.sections || [];
        if (sections.length === 0) {
            html += `<div class="enhancer-error-text">Analiz edilecek bölüm bulunamadı.</div>`;
        } else {
            // Önce değişiklik olanları, sonra olmayanları göster
            const sorted = [...sections].sort((a, b) => {
                if (a.change_type === 'no_change' && b.change_type !== 'no_change') return 1;
                if (a.change_type !== 'no_change' && b.change_type === 'no_change') return -1;
                return b.priority - a.priority;
            });

            for (const section of sorted) {
                html += _renderSectionCard(section);
            }
        }

        body.innerHTML = html;

        // Footer göster
        const footer = document.getElementById('enhancerModalFooter');
        if (footer) footer.style.display = 'flex';

        // Download butonu aktifle
        const downloadBtn = document.getElementById('enhancerBtnDownload');
        if (downloadBtn && data.session_id) {
            downloadBtn.disabled = false;
            downloadBtn.style.display = 'flex';
            downloadBtn.innerHTML = '<i class="fas fa-download"></i> Seçilenleri Uygula & İndir';
            downloadBtn.addEventListener('click', () => _downloadEnhanced(data.session_id));
        }

        // Upload butonu aktifle
        const uploadBtn = document.getElementById('enhancerBtnUpload');
        if (uploadBtn && data.session_id) {
            uploadBtn.disabled = false;
            uploadBtn.style.display = 'flex';
            uploadBtn.addEventListener('click', () => _uploadToRag(data.session_id));
        }

        // Footer info
        const footerInfo = document.getElementById('enhancerFooterInfo');
        if (footerInfo) {
            footerInfo.textContent = `${data.enhanced_count} / ${data.total_sections} bölüm iyileştirildi`;
        }

        // Collapsible cards event
        body.querySelectorAll('.enhancer-section-header').forEach(header => {
            header.addEventListener('click', () => {
                const card = header.closest('.enhancer-section-card');
                if (card) card.classList.toggle('expanded');
            });
        });

        // İlk değişiklik olan kartı otomatik aç
        const firstChanged = body.querySelector('.enhancer-section-card:not(.no-change)');
        if (firstChanged) firstChanged.classList.add('expanded');
    }

    function _renderSectionCard(section) {
        const changeType = section.change_type || 'no_change';
        const isNoChange = changeType === 'no_change';
        const label = CHANGE_LABELS[changeType] || changeType;
        const priorityPercent = Math.round((section.priority || 0) * 100);

        // Orijinal ve enhanced text preview (kırpılmış)
        const origPreview = _truncateText(section.original_text, 500);
        const enhPreview = _truncateText(section.enhanced_text, 500);

        return `
            <div class="enhancer-section-card ${isNoChange ? 'no-change' : ''}" data-section-index="${section.section_index}">
                <div class="enhancer-section-header">
                    <div class="enhancer-section-header-left">
                        ${!isNoChange ? `
                            <label class="enhancer-toggle-switch" title="Bu değişikliği onayla / reddet">
                                <input type="checkbox" class="enhancer-section-checkbox" 
                                       data-index="${section.section_index}" checked />
                                <span class="enhancer-toggle-slider"></span>
                            </label>
                        ` : `
                            <i class="fas fa-check-circle enhancer-icon-unchanged"></i>
                        `}
                        <span class="enhancer-section-heading">${_escapeHtml(section.heading || 'Başlıksız Bölüm')}</span>
                    </div>
                    <div class="enhancer-section-header-right">
                        ${!isNoChange ? `<span class="enhancer-priority-badge">⚡ ${priorityPercent}%</span>` : ''}
                        <span class="enhancer-change-badge ${changeType.replace(/_/g, '-')}">${_escapeHtml(label)}</span>
                        <i class="fas fa-chevron-down enhancer-collapse-icon"></i>
                    </div>
                </div>
                <div class="enhancer-section-body">
                    ${!isNoChange ? `
                        <div class="enhancer-explanation">
                            <i class="fas fa-lightbulb"></i>
                            <span>${_escapeHtml(section.explanation || '')}</span>
                        </div>
                    ` : ''}
                    <div class="enhancer-diff-container">
                        <div class="enhancer-diff-panel enhancer-diff-panel-original">
                            <div class="enhancer-diff-label original">
                                <i class="fas fa-minus-circle"></i> Orijinal
                            </div>
                            <div class="enhancer-diff-content">${_escapeHtml(origPreview)}</div>
                        </div>
                        <div class="enhancer-diff-panel enhancer-diff-panel-enhanced">
                            <div class="enhancer-diff-label enhanced">
                                <i class="fas fa-plus-circle"></i> İyileştirilmiş
                            </div>
                            <div class="enhancer-diff-content">${_escapeHtml(enhPreview)}</div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    // ─────────────────────────────────────────
    //  API CALLS
    // ─────────────────────────────────────────

    function _sendToBackend(file) {
        const formData = new FormData();
        formData.append('file', file);

        return fetch(`${API_BASE}/api/rag/enhance-document`, {
            method: 'POST',
            headers: _authHeaders(),
            body: formData
        })
            .then(res => {
                if (!res.ok) {
                    return res.json().then(err => {
                        throw new Error(err.detail || `HTTP ${res.status}`);
                    });
                }
                return res.json();
            });
    }

    /**
     * Onaylanan section index'lerini toplar.
     */
    function _getApprovedSections() {
        const checkboxes = document.querySelectorAll('.enhancer-section-checkbox:checked');
        return Array.from(checkboxes).map(cb => parseInt(cb.dataset.index, 10));
    }

    function _downloadEnhanced(sessionId) {
        const approvedIndexes = _getApprovedSections();

        // Sections parametresini URL'e ekle
        let url = `${API_BASE}/api/rag/download-enhanced/${sessionId}`;
        if (approvedIndexes.length > 0) {
            url += `?sections=${approvedIndexes.join(',')}`;
        }

        const downloadBtn = document.getElementById('enhancerBtnDownload');
        if (downloadBtn) {
            downloadBtn.disabled = true;
            downloadBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> İndiriliyor...';
        }

        fetch(url, {
            method: 'GET',
            headers: _authHeaders()
        })
            .then(res => {
                if (!res.ok) throw new Error(`İndirme hatası: HTTP ${res.status}`);
                return res.blob();
            })
            .then(blob => {
                // Orijinal dosya adı ve formatıyla indir
                let downloadName = 'iyilestirilmis.docx';
                if (_currentFileName) {
                    const baseName = _currentFileName.replace(/\.[^.]+$/, '');
                    const ext = _currentFileName.match(/\.[^.]+$/);
                    const originalExt = ext ? ext[0] : '.docx';
                    downloadName = `${baseName}${originalExt}`;
                }

                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = downloadName;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(a.href);

                if (downloadBtn) {
                    downloadBtn.disabled = false;
                    downloadBtn.innerHTML = '<i class="fas fa-download"></i> Seçilenleri Uygula & İndir';
                }
            })
            .catch(err => {
                console.error('[Enhancer] Download hatası:', err);
                if (downloadBtn) {
                    downloadBtn.disabled = false;
                    downloadBtn.innerHTML = '<i class="fas fa-download"></i> Seçilenleri Uygula & İndir';
                }
                if (window.showToast) {
                    window.showToast('Dosya indirme sırasında hata: ' + err.message, 'error');
                }
            });
    }

    // ─────────────────────────────────────────
    //  RAG UPLOAD
    // ─────────────────────────────────────────

    function _uploadToRag(sessionId) {
        const approvedIndexes = _getApprovedSections();

        if (approvedIndexes.length === 0) {
            if (window.showToast) {
                window.showToast('Lütfen en az bir bölüm seçin.', 'warning');
            }
            return;
        }

        // SaaS confirm popup ile kullanıcıdan son onay al
        _showConfirmDialog({
            title: 'Bilgi Tabanına Yükle',
            message: `<strong>${approvedIndexes.length}</strong> iyileştirilmiş bölüm bilgi tabanına yüklenecek.<br>Aynı isimli dosya varsa güncellenecektir.`,
            confirmText: 'Yükle',
            cancelText: 'Vazgeç',
            icon: 'cloud-upload-alt',
            onConfirm: () => _executeUpload(sessionId, approvedIndexes)
        });
    }

    function _executeUpload(sessionId, approvedIndexes) {
        let url = `${API_BASE}/api/rag/upload-enhanced/${sessionId}`;
        const urlParams = [];
        if (approvedIndexes.length > 0) {
            urlParams.push(`sections=${approvedIndexes.join(',')}`);
        }
        // Seçili org gruplarını ekle (RAGUpload modülünden)
        if (window.RAGUpload && window.RAGUpload.selectedOrgIds && window.RAGUpload.selectedOrgIds.length > 0) {
            urlParams.push(`org_ids=${window.RAGUpload.selectedOrgIds.join(',')}`);
        }
        if (urlParams.length > 0) {
            url += `?${urlParams.join('&')}`;
        }

        const uploadBtn = document.getElementById('enhancerBtnUpload');
        if (uploadBtn) {
            uploadBtn.disabled = true;
            uploadBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Yükleniyor...';
        }

        fetch(url, {
            method: 'POST',
            headers: _authHeaders()
        })
            .then(res => {
                if (!res.ok) return res.json().then(d => { throw new Error(d.detail || `HTTP ${res.status}`); });
                return res.json();
            })
            .then(data => {
                if (uploadBtn) {
                    uploadBtn.innerHTML = '<i class="fas fa-check"></i> Yüklendi!';
                }

                const msg = data.message || 'Bilgi tabanına yüklendi.';
                if (window.showToast) {
                    window.showToast(msg, 'success');
                }

                // Upload sonrası download butonunu devre dışı bırak (temp dosya silindi)
                const downloadBtn = document.getElementById('enhancerBtnDownload');
                if (downloadBtn) {
                    downloadBtn.disabled = true;
                    downloadBtn.innerHTML = '<i class="fas fa-check"></i> Yüklendi';
                }

                // Bilgi Tabanı dosya listesini yenile (sayfa refresh'e gerek kalmadan)
                if (window.RAGUpload) {
                    window.RAGUpload.filesCurrentPage = 1;
                    window.RAGUpload.loadFiles();
                    window.RAGUpload.loadStats();
                }

                _currentSessionId = null;
                setTimeout(() => close(), 1500);
            })
            .catch(err => {
                console.error('[Enhancer] Upload hatası:', err);
                if (uploadBtn) {
                    uploadBtn.disabled = false;
                    uploadBtn.innerHTML = '<i class="fas fa-cloud-upload-alt"></i> Onayla & Bilgi Tabanına Yükle';
                }
                if (window.showToast) {
                    window.showToast('Yükleme sırasında hata: ' + err.message, 'error');
                }
            });
    }

    // ─────────────────────────────────────────
    //  CUSTOM CONFIRM DIALOG (SaaS Style)
    // ─────────────────────────────────────────

    function _showConfirmDialog({ title, message, confirmText, cancelText, icon, onConfirm }) {
        // Eski dialog varsa kaldır
        const existing = document.getElementById('enhancerConfirmOverlay');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.id = 'enhancerConfirmOverlay';
        overlay.className = 'enhancer-confirm-overlay';
        overlay.innerHTML = `
            <div class="enhancer-confirm-dialog">
                <div class="enhancer-confirm-icon">
                    <i class="fas fa-${icon || 'question-circle'}"></i>
                </div>
                <div class="enhancer-confirm-title">${title}</div>
                <div class="enhancer-confirm-message">${message}</div>
                <div class="enhancer-confirm-actions">
                    <button class="enhancer-confirm-btn cancel" id="enhancerConfirmCancel">
                        ${cancelText || 'Vazgeç'}
                    </button>
                    <button class="enhancer-confirm-btn confirm" id="enhancerConfirmOk">
                        <i class="fas fa-${icon || 'check'}"></i> ${confirmText || 'Onayla'}
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(overlay);
        requestAnimationFrame(() => overlay.classList.add('visible'));

        let escHandler = null;

        const closeDialog = () => {
            if (escHandler) document.removeEventListener('keydown', escHandler);
            overlay.classList.remove('visible');
            setTimeout(() => overlay.remove(), 250);
        };

        // ESC ile kapat
        escHandler = (e) => {
            if (e.key === 'Escape') closeDialog();
        };
        document.addEventListener('keydown', escHandler);

        overlay.querySelector('#enhancerConfirmCancel').addEventListener('click', closeDialog);
        overlay.querySelector('#enhancerConfirmOk').addEventListener('click', () => {
            closeDialog();
            if (onConfirm) onConfirm();
        });
    }

    function _cleanupSession(sessionId) {
        fetch(`${API_BASE}/api/rag/cleanup-enhanced/${sessionId}`, {
            method: 'DELETE',
            headers: _authHeaders()
        }).catch(() => { });
    }

    // ─────────────────────────────────────────
    //  UTILS
    // ─────────────────────────────────────────

    function _authHeaders() {
        const token = localStorage.getItem('access_token');
        const headers = {};
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        return headers;
    }

    function _escapeHtml(text) {
        if (!text) return '';
        const el = document.createElement('span');
        el.textContent = text;
        return el.innerHTML;
    }

    function _truncateText(text, maxLen) {
        if (!text) return '';
        if (text.length <= maxLen) return text;
        return text.substring(0, maxLen) + '...';
    }

    // ─── PUBLIC API ───
    return {
        analyze: analyze,
        close: close
    };

})();

// Global erişim
window.DocumentEnhancerModal = DocumentEnhancerModal;
