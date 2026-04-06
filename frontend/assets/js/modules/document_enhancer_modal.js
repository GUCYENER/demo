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
    let _progressListener = null;  // v3.3.0 [C5]: WebSocket progress listener reference

    // ─── API Base ───
    const API_BASE = window.API_BASE_URL || 'http://localhost:8002';

    // ─── Change type → Türkçe label ───
    const CHANGE_LABELS = {
        'heading_added': 'Başlık Eklendi',
        'content_restructured': 'İçerik Düzenlendi',
        'table_fixed': 'Tablo Düzeltildi',
        'encoding_fixed': 'Encoding Düzeltildi',
        'formatting_improved': 'Format İyileştirildi',
        'no_change': 'Değişiklik Yok',
        'llm_error': '⚠ LLM Hatası',
        'integrity_failed': '⚠ Bütünlük Hatası'
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

        // v3.3.0 [C5]: Progress listener temizle
        if (_progressListener) {
            window.removeEventListener('vyra:enhancement_progress', _progressListener);
            _progressListener = null;
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
                <div class="enhancer-loading-step" id="enhancerProgressStep">${_escapeHtml(stepText)}</div>
                <div class="enhancer-progress-bar-container" id="enhancerProgressBarContainer">
                    <div class="enhancer-progress-bar" id="enhancerProgressBar"></div>
                </div>
                <div class="enhancer-progress-detail" id="enhancerProgressDetail"></div>
            </div>
        `;

        // Footer gizle
        const footer = document.getElementById('enhancerModalFooter');
        if (footer) footer.classList.add('hidden');

        // v3.3.0 [C5]: WebSocket progress listener — canlı ilerleme
        _progressListener = function (e) {
            const { current, total, heading, status, percentage, message } = e.detail || {};
            const stepEl = document.getElementById('enhancerProgressStep');
            const barEl = document.getElementById('enhancerProgressBar');
            const detailEl = document.getElementById('enhancerProgressDetail');
            const barContainer = document.getElementById('enhancerProgressBarContainer');

            if (stepEl && message) {
                stepEl.textContent = message;
            }
            if (barEl && percentage != null) {
                barEl.style.width = `${percentage}%`;
            }
            if (barContainer) {
                barContainer.classList.add('active');
            }
            if (detailEl) {
                const icon = status === 'processing' ? '⚡' : status === 'skipped' ? '✓' : '⚠';
                detailEl.textContent = `${icon} ${current || 0}/${total || 0} bölüm işlendi`;
            }
        };
        window.addEventListener('vyra:enhancement_progress', _progressListener);
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
        if (footer) footer.classList.remove('hidden');
        const downloadBtn = document.getElementById('enhancerBtnDownload');
        if (downloadBtn) downloadBtn.classList.add('hidden');
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
                        ${summary.catboost_available
                            ? `${summary.high_priority_count || 0} yüksek öncelikli bölüm`
                            : `${summary.high_priority_count || 0} bölüm · Önceliklendirme yaklaşık`}
                    </div>
                </div>
            </div>
        `;

        // ─── Section Cards ───
        const sections = data.sections || [];
        if (sections.length === 0) {
            html += `<div class="enhancer-error-text">Analiz edilecek bölüm bulunamadı.</div>`;
        } else {
            // Önce başarılı değişiklikler, sonra hatalar/değişiklik olmayanlar
            const skipTypes = ['no_change', 'llm_error', 'integrity_failed'];
            const sorted = [...sections].sort((a, b) => {
                const aSkip = skipTypes.includes(a.change_type);
                const bSkip = skipTypes.includes(b.change_type);
                if (aSkip && !bSkip) return 1;
                if (!aSkip && bSkip) return -1;
                return b.priority - a.priority;
            });

            for (const section of sorted) {
                html += _renderSectionCard(section);
            }
        }

        body.innerHTML = html;

        // Footer göster
        const footer = document.getElementById('enhancerModalFooter');
        if (footer) footer.classList.remove('hidden');

        // Download butonu aktifle — v3.2.1: onclick ile listener birikimi önlenir
        const downloadBtn = document.getElementById('enhancerBtnDownload');
        if (downloadBtn && data.session_id) {
            downloadBtn.disabled = false;
            downloadBtn.classList.remove('hidden');
            downloadBtn.innerHTML = '<i class="fas fa-download"></i> Seçilenleri Uygula & İndir';
            downloadBtn.onclick = () => _downloadEnhanced(data.session_id);
        }

        // Upload butonu aktifle — v3.2.1: onclick ile listener birikimi önlenir
        const uploadBtn = document.getElementById('enhancerBtnUpload');
        if (uploadBtn && data.session_id) {
            uploadBtn.disabled = false;
            uploadBtn.classList.remove('hidden');
            uploadBtn.onclick = () => _uploadToRag(data.session_id);
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
        const isError = changeType === 'llm_error';
        const isIntegrityFail = changeType === 'integrity_failed';
        const isSkipped = isNoChange || isError || isIntegrityFail;
        
        // Pipe-separated change type'ları Türkçe badge'lere çevir
        const changeTypes = changeType.toLowerCase().split('|').map(t => t.trim());
        const labels = changeTypes
            .map(t => CHANGE_LABELS[t])
            .filter(Boolean);
        const label = labels.length > 0
            ? (labels.length <= 2 ? labels.join(' + ') : labels.slice(0, 2).join(' + ') + ` +${labels.length - 2}`)
            : (CHANGE_LABELS[changeType] || changeType);
        
        const priorityPercent = Math.round((section.priority || 0) * 100);
        const integrityScore = section.integrity_score != null ? Math.round(section.integrity_score * 100) : null;

        // Orijinal ve enhanced text preview (kırpılmış)
        const origPreview = _truncateText(section.original_text, 500);
        const enhPreview = _truncateText(section.enhanced_text, 500);

        return `
            <div class="enhancer-section-card ${isNoChange ? 'no-change' : ''} ${isError ? 'llm-error' : ''} ${isIntegrityFail ? 'integrity-failed' : ''}" data-section-index="${section.section_index}">
                <div class="enhancer-section-header">
                    <div class="enhancer-section-header-left">
                        <label class="enhancer-toggle-switch" title="${isSkipped ? 'Orijinal içerikle yükle' : 'Bu değişikliği onayla / reddet'}">
                            <input type="checkbox" class="enhancer-section-checkbox" 
                                   data-index="${section.section_index}" ${!isSkipped ? 'checked' : ''} />
                            <span class="enhancer-toggle-slider"></span>
                        </label>
                        ${isSkipped ? `<i class="fas ${isIntegrityFail ? 'fa-shield-alt enhancer-icon-integrity' : isError ? 'fa-exclamation-circle enhancer-icon-error' : 'fa-check-circle enhancer-icon-unchanged'}"></i>` : ''}
                        <span class="enhancer-section-heading">${_escapeHtml(section.heading || 'Başlıksız Bölüm')}</span>
                    </div>
                    <div class="enhancer-section-header-right">
                        ${!isSkipped ? `<span class="enhancer-priority-badge">⚡ ${priorityPercent}%</span>` : ''}
                        ${integrityScore != null && !isSkipped ? `<span class="enhancer-integrity-badge" title="Bütünlük skoru">🛡️ ${integrityScore}%</span>` : ''}
                        <span class="enhancer-change-badge ${changeType.replace(/_/g, '-')}">${_escapeHtml(label)}</span>
                        <i class="fas fa-chevron-down enhancer-collapse-icon"></i>
                    </div>
                </div>
                <div class="enhancer-section-body">
                    ${isIntegrityFail ? `
                        <div class="enhancer-explanation enhancer-integrity-warning">
                            <i class="fas fa-shield-alt"></i>
                            <span>${_escapeHtml(section.explanation || 'Bütünlük doğrulaması başarısız')}</span>
                        </div>
                    ` : isError ? `
                        <div class="enhancer-explanation enhancer-llm-error">
                            <i class="fas fa-exclamation-triangle"></i>
                            <span>${_escapeHtml(section.explanation || 'LLM bağlantı hatası')}</span>
                        </div>
                    ` : !isNoChange ? `
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
                            <div class="enhancer-diff-content">${_wordDiff(origPreview, enhPreview).original}</div>
                        </div>
                        <div class="enhancer-diff-panel enhancer-diff-panel-enhanced">
                            <div class="enhancer-diff-label enhanced">
                                <i class="fas fa-plus-circle"></i> İyileştirilmiş
                            </div>
                            <div class="enhancer-diff-content">${_wordDiff(origPreview, enhPreview).enhanced}</div>
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

        // v3.4.4: Timeout artırıldı — büyük dosyalarda LLM pipeline 3+ dakika sürebilir
        const ENHANCEMENT_TIMEOUT_MS = 300000; // 5 dakika
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), ENHANCEMENT_TIMEOUT_MS);

        return fetch(`${API_BASE}/api/rag/enhance-document`, {
            method: 'POST',
            headers: _authHeaders(),
            body: formData,
            signal: controller.signal
        })
            .then(res => {
                clearTimeout(timeoutId);
                if (!res.ok) {
                    return res.json().then(err => {
                        throw new Error(err.detail || `HTTP ${res.status}`);
                    });
                }
                return res.json();
            })
            .catch(err => {
                clearTimeout(timeoutId);
                if (err.name === 'AbortError') {
                    throw new Error('İyileştirme işlemi zaman aşımına uğradı (5 dk). Büyük dosyaları bölerek deneyebilirsiniz.');
                }
                throw err;
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
            // v3.4.4: Hiç iyileştirme onaylanmamış — orijinal dosyayı yükle seçeneği sun
            _showConfirmDialog({
                title: 'Orijinal Dosyayı Yükle',
                message: 'Hiçbir iyileştirme seçilmedi. Dosyayı <strong>orijinal haliyle</strong> bilgi tabanına yüklemek ister misiniz?',
                confirmText: 'Orijinal Yükle',
                cancelText: 'Vazgeç',
                icon: 'file-upload',
                onConfirm: () => _executeUpload(sessionId, [])
            });
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
        // Firma ID'sini ekle
        if (window.RAGUpload && typeof window.RAGUpload._getCompanyId === 'function') {
            const compId = window.RAGUpload._getCompanyId();
            if (compId) {
                urlParams.push(`company_id=${compId}`);
            }
        }
        if (urlParams.length > 0) {
            url += `?${urlParams.join('&')}`;
        }

        // Upload butonunu "Yükleniyor" durumuna al
        const uploadBtn = document.getElementById('enhancerBtnUpload');
        if (uploadBtn) {
            uploadBtn.disabled = true;
            uploadBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Yükleniyor...';
        }

        // v3.4.5: API yanıtını BEKLE (dosya DB'ye kaydedilsin)
        // Yanıt gelince HEMEN modal kapat — normal upload akışıyla tutarlı
        fetch(url, {
            method: 'POST',
            headers: _authHeaders()
        })
            .then(res => {
                if (!res.ok) return res.json().then(d => { throw new Error(d.detail || `HTTP ${res.status}`); });
                return res.json();
            })
            .then(data => {
                // ─── Dosya DB'ye kaydedildi, background processing başladı ───
                // HEMEN modal kapat (bekleme yok)
                _currentSessionId = null;
                close();

                // Bildirim — normal upload ile tutarlı
                const fileName = data.file_name || _currentFileName || 'Dosya';
                if (window.NgssNotification) {
                    NgssNotification.info('📄 İyileştirilmiş Dosya Yüklendi',
                        `${fileName} — işlem arkaplanda devam ediyor...`);
                } else if (window.showToast) {
                    window.showToast(data.message || 'Dosya kaydedildi, işleniyor...', 'info');
                }

                // Dosya listesini yenile — "İşleniyor" durumunu göster
                if (window.RAGUpload) {
                    window.RAGUpload.filesCurrentPage = 1;
                    window.RAGUpload.loadFiles();
                    window.RAGUpload.loadStats();

                    // Processing polling başlat — tamamlanma bildirimi için
                    const uploadedName = data.file_name || '';
                    if (uploadedName) {
                        window.RAGUpload._startProcessingPoll([uploadedName]);
                    }
                }

                // Dosya listesine scroll + ilk satırı vurgula
                setTimeout(() => {
                    const filesList = document.getElementById('rag-files-list');
                    if (filesList) {
                        filesList.scrollIntoView({ behavior: 'smooth', block: 'start' });
                        const firstRow = filesList.querySelector('tbody tr:first-child');
                        if (firstRow) {
                            firstRow.classList.add('rag-row-highlight');
                            setTimeout(() => firstRow.classList.remove('rag-row-highlight'), 3000);
                        }
                    }
                }, 500);
            })
            .catch(err => {
                console.error('[Enhancer] Upload hatası:', err);
                // Hata durumunda butonu geri aç
                if (uploadBtn) {
                    uploadBtn.disabled = false;
                    uploadBtn.innerHTML = '<i class="fas fa-cloud-upload-alt"></i> Onayla & Bilgi Tabanına Yükle';
                }
                if (window.NgssNotification) {
                    NgssNotification.error('Yükleme Hatası', err.message || 'Dosya yüklenirken hata oluştu');
                } else if (window.showToast) {
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

    /**
     * v3.4.4: Word-level diff — basit LCS tabanlı kelime karşılaştırma
     * Returns: { original: html, enhanced: html }
     */
    function _wordDiff(origText, enhText) {
        if (!origText && !enhText) return { original: '', enhanced: '' };
        if (!origText) return { original: '', enhanced: `<span class="diff-added">${_escapeHtml(enhText)}</span>` };
        if (!enhText) return { original: `<span class="diff-removed">${_escapeHtml(origText)}</span>`, enhanced: '' };

        const origWords = origText.split(/\s+/);
        const enhWords = enhText.split(/\s+/);
        
        // Simple LCS-based diff
        const m = origWords.length, n = enhWords.length;
        // For very large texts, fallback to plain
        if (m > 500 || n > 500) {
            return { original: _escapeHtml(origText), enhanced: _escapeHtml(enhText) };
        }
        
        const dp = Array.from({length: m + 1}, () => new Uint16Array(n + 1));
        for (let i = 1; i <= m; i++) {
            for (let j = 1; j <= n; j++) {
                dp[i][j] = origWords[i-1] === enhWords[j-1]
                    ? dp[i-1][j-1] + 1
                    : Math.max(dp[i-1][j], dp[i][j-1]);
            }
        }
        
        // Backtrack
        const origParts = [], enhParts = [];
        let i = m, j = n;
        const origResult = [], enhResult = [];
        while (i > 0 || j > 0) {
            if (i > 0 && j > 0 && origWords[i-1] === enhWords[j-1]) {
                origResult.unshift({ type: 'same', word: origWords[i-1] });
                enhResult.unshift({ type: 'same', word: enhWords[j-1] });
                i--; j--;
            } else if (j > 0 && (i === 0 || dp[i][j-1] >= dp[i-1][j])) {
                enhResult.unshift({ type: 'added', word: enhWords[j-1] });
                j--;
            } else {
                origResult.unshift({ type: 'removed', word: origWords[i-1] });
                i--;
            }
        }
        
        // Render
        let origHtml = '', enhHtml = '';
        origResult.forEach(r => {
            origHtml += r.type === 'removed'
                ? `<span class="diff-removed">${_escapeHtml(r.word)}</span> `
                : `${_escapeHtml(r.word)} `;
        });
        enhResult.forEach(r => {
            enhHtml += r.type === 'added'
                ? `<span class="diff-added">${_escapeHtml(r.word)}</span> `
                : `${_escapeHtml(r.word)} `;
        });
        
        return { original: origHtml.trim(), enhanced: enhHtml.trim() };
    }

    // ─── PUBLIC API ───
    return {
        analyze: analyze,
        close: close
    };

})();

// Global erişim
window.DocumentEnhancerModal = DocumentEnhancerModal;
