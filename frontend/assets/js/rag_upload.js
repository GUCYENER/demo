/**
 * RAG Upload Module
 * Dosya yükleme ve bilgi tabanı yönetimi
 */

const RAGUpload = {
    // API Base URL
    API_BASE: (window.API_BASE_URL || 'http://localhost:8002') + '/api',

    // State
    isUploading: false,
    files: [],
    stats: {
        fileCount: 0,
        chunkCount: 0,
        status: 'Hazır'
    },
    selectedOrgIds: [],  // Seçilen org grupları
    orgs: [],            // Tüm org grupları

    // Upload Flow States
    pendingFiles: null,              // Org seçimi bekleyen dosyalar
    shouldOpenFileDialogAfterOrg: false, // Org seçiminden sonra dosya diyaloğu açılsın mı?

    // Files pagination & search
    filesCurrentPage: 1,
    filesPerPage: 10,
    filesTotalCount: 0,
    filesSearchTerm: '',

    /**
     * Modülü başlatır
     */
    async init() {
        console.log('[RAGUpload] Modül başlatılıyor...');

        this.setupDragAndDrop();
        this.setupFileInput();
        this.setupEventListeners();

        await this.loadCompanySelector();
        await this.loadOrgs();   // Org gruplarını yükle
        await this.loadMaturityThreshold(); // Eşik değerini yükle
        await this.loadDataSources(); // v2.55.0: Veri kaynağı seçici
        await this.loadFiles();
        await this.loadStats();
        this.loadEnhancementHistory();  // v3.4.4: Enhancement geçmişi widget (async, non-blocking)

        console.log('[RAGUpload] Modül hazır.');
    },

    /**
     * Drag & Drop işlevselliği
     */
    setupDragAndDrop() {
        const dropZone = document.getElementById('rag-upload-zone');
        if (!dropZone) return;

        // Duplicate listener koruması - init() birden fazla çağrılsa bile tekrar ekleme
        if (dropZone.hasAttribute('data-drop-listener-added')) return;
        dropZone.setAttribute('data-drop-listener-added', 'true');

        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
            });
        });

        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => {
                dropZone.classList.add('drag-over');
            });
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => {
                dropZone.classList.remove('drag-over');
            });
        });

        dropZone.addEventListener('drop', (e) => {
            const files = e.dataTransfer.files;
            if (files.length) {
                // 🔒 Firma kontrolü (drop)
                if (!this._checkCompanySelected()) return;
                this.handleFiles(files);
            }
        });

        // dropZone tıklandığında - ÖNCELİKLE FİRMA VE ORG KONTROLÜ YAP
        dropZone.addEventListener('click', (e) => {
            // File input element'ine veya içine tıklandıysa native davranış devam etsin
            if (e.target.closest('#rag-file-input') || e.target.id === 'rag-file-input') {
                return;
            }

            // 🔒 FİRMA KONTROLÜ - Firma seçilmeden işlem yapılamaz
            if (!this._checkCompanySelected()) {
                e.preventDefault();
                e.stopPropagation();
                return;
            }

            // 🔒 ORG KONTROLÜ - En başta tek yerde yap
            if (!this.selectedOrgIds || this.selectedOrgIds.length === 0) {
                e.preventDefault();
                e.stopPropagation();
                // Toast kaldırıldı - Sadece modal açılacak
                this.shouldOpenFileDialogAfterOrg = true; // Org seçiminden sonra dialog aç
                this.openOrgModal();
                return;
            }

            // Org seçiliyse file input'u programatik tetikle
            const fileInput = document.getElementById('rag-file-input');
            if (fileInput) {
                fileInput.click();
            }
        });
    },

    /**
     * File input işlevselliği
     */
    setupFileInput() {
        const fileInput = document.getElementById('rag-file-input');
        if (!fileInput) return;

        // Event listener zaten ekliyse tekrar ekleme
        if (fileInput.hasAttribute('data-listener-added')) return;
        fileInput.setAttribute('data-listener-added', 'true');

        // Org kontrolü handleFiles'da yapılıyor, burada tekrar yapmıyoruz
        fileInput.addEventListener('change', (e) => {
            if (e.target.files && e.target.files.length > 0) {
                this.handleFiles(e.target.files);
            }
        });
    },

    /**
     * Event listener'lar (sadece bir kez bağlanır)
     */
    setupEventListeners() {
        // Duplicate protection — init() her tab geçişinde çağrılıyor
        if (this._listenersAttached) return;
        this._listenersAttached = true;

        // Rebuild butonu
        const rebuildBtn = document.getElementById('btn-rebuild-vectorstore');
        if (rebuildBtn) {
            rebuildBtn.addEventListener('click', () => this.rebuildVectorstore());
        }

        // Maturity threshold slider
        const thresholdSlider = document.getElementById('rag-maturity-threshold');
        if (thresholdSlider) {
            thresholdSlider.addEventListener('input', (e) => {
                const val = e.target.value;
                const label = document.getElementById('rag-threshold-value');
                if (label) label.textContent = val;
            });
            thresholdSlider.addEventListener('change', (e) => {
                this.saveMaturityThreshold(parseInt(e.target.value, 10));
            });
        }
    },

    // --- ORG MODAL ---
    // v2.30.1: modules/rag_org_modal.js modülüne taşındı.
    // Delegation: window.RAGOrgModal
    loadOrgs() { if (window.RAGOrgModal) window.RAGOrgModal.loadOrgs.call(this); },
    saveSelectedOrgsToStorage() { if (window.RAGOrgModal) window.RAGOrgModal.saveSelectedOrgsToStorage.call(this); },
    setupOrgEditButton() { if (window.RAGOrgModal) window.RAGOrgModal.setupOrgEditButton.call(this); },
    renderOrgBadges() { if (window.RAGOrgModal) window.RAGOrgModal.renderOrgBadges.call(this); },
    openOrgModal() { if (window.RAGOrgModal) window.RAGOrgModal.openOrgModal.call(this); },
    closeOrgModal() { if (window.RAGOrgModal) window.RAGOrgModal.closeOrgModal.call(this); },
    renderModalList() { if (window.RAGOrgModal) window.RAGOrgModal.renderModalList.call(this); },
    updateModalCounts(t) { if (window.RAGOrgModal) window.RAGOrgModal.updateModalCounts.call(this, t); },
    confirmOrgSelection() { if (window.RAGOrgModal) window.RAGOrgModal.confirmOrgSelection.call(this); },


    /**
     * Dosyaları işler ve yükler
     */
    async handleFiles(fileList) {
        if (this.isUploading) {
            this.showToast('Yükleme devam ediyor, lütfen bekleyin...', 'warning');
            return;
        }

        // Not: Firma kontrolü burada yapılmaz — çağrı noktalarında (dropZone click/drop, orgModal) kontrol edilir.
        const files = Array.from(fileList);

        // Hedef org seçili mi kontrol et
        if (!this.selectedOrgIds || this.selectedOrgIds.length === 0) {
            // Toast kaldırıldı
            // Dosyaları beklemeye al (Org seçimi sonrası yüklenecek)
            this.pendingFiles = files;
            console.log('[RAGUpload] Pending files set:', this.pendingFiles.length);

            // Org seçim modalını aç
            this.openOrgModal();
            return;
        }

        const supportedExtensions = ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', '.txt', '.csv'];

        // Dosya validasyonu
        const invalidFiles = files.filter(file => {
            const ext = '.' + file.name.split('.').pop().toLowerCase();
            return !supportedExtensions.includes(ext);
        });

        if (invalidFiles.length > 0) {
            this.showToast(
                `Desteklenmeyen dosya formatı: ${invalidFiles.map(f => f.name).join(', ')}`,
                'error'
            );
            return;
        }

        // Dosya boyutu kontrolü (50MB)
        const maxSize = 50 * 1024 * 1024;
        const largeFiles = files.filter(f => f.size > maxSize);
        if (largeFiles.length > 0) {
            this.showToast(
                `Dosya çok büyük (max 50MB): ${largeFiles.map(f => f.name).join(', ')}`,
                'error'
            );
            return;
        }

        // 🆕 Maturity Score analizi — yüklemeden önce kullanıcıdan onay al
        if (window.MaturityScoreModal) {
            MaturityScoreModal.analyze(
                files,
                (confirmedFiles, scores) => {
                    // Kullanıcı onayladı → skorlarla birlikte yükle
                    this.uploadFiles(confirmedFiles, scores);
                },
                () => {
                    // Kullanıcı iptal etti
                    console.log('[RAGUpload] Kullanıcı yüklemeyi iptal etti (maturity)');
                }
            );
        } else {
            // MaturityScoreModal yüklenmemişse doğrudan yükle
            await this.uploadFiles(files);
        }
    },

    /**
     * Dosyaları sunucuya yükler
     * v2.39.0: Asenkron akış — dosya kaydı senkron, processing arkaplanda.
     * İşlem tamamlanınca WebSocket ile bildirim gelir.
     */
    async uploadFiles(files, maturityScores) {
        this.isUploading = true;
        this.setUploadingState(true);  // UI disable
        this.showProgress(true);
        this.updateProgress(0, 'Dosyalar hazırlanıyor...');

        const formData = new FormData();
        const fileNames = files.map(f => f.name);
        files.forEach(file => {
            formData.append('files', file);
        });

        try {
            this.updateProgress(5, 'Dosyalar yükleniyor...');

            const token = localStorage.getItem('access_token');

            // URL'e org_ids parametresi ekle
            let uploadUrl = `${this.API_BASE}/rag/upload-files`;
            const urlParams = [];
            if (this.selectedOrgIds && this.selectedOrgIds.length > 0) {
                urlParams.push(`org_ids=${this.selectedOrgIds.join(',')}`);
                console.log('[RAGUpload] Uploading with org_ids:', this.selectedOrgIds);
            }
            if (maturityScores && maturityScores.length > 0) {
                urlParams.push(`maturity_scores=${maturityScores.join(',')}`);
                console.log('[RAGUpload] Uploading with maturity_scores:', maturityScores);
            }
            if (urlParams.length > 0) {
                uploadUrl += `?${urlParams.join('&')}`;
            }

            // Firma ID ekle
            const compSel = document.getElementById('ragCompanySelect');
            if (compSel && compSel.value) {
                const sep = uploadUrl.includes('?') ? '&' : '?';
                uploadUrl += `${sep}company_id=${compSel.value}`;
            }

            // v3.4.4: XMLHttpRequest ile gerçek upload progress
            const result = await new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest();
                xhr.open('POST', uploadUrl, true);
                xhr.setRequestHeader('Authorization', `Bearer ${token}`);
                
                // Gerçek upload ilerleme ölçümü
                xhr.upload.onprogress = (e) => {
                    if (e.lengthComputable) {
                        const pct = Math.round((e.loaded / e.total) * 90) + 5;  // 5-95 arası
                        const loaded = (e.loaded / (1024 * 1024)).toFixed(1);
                        const total = (e.total / (1024 * 1024)).toFixed(1);
                        this.updateProgress(pct, `Yükleniyor... ${loaded}/${total} MB`);
                    }
                };
                
                xhr.onload = () => {
                    if (xhr.status >= 200 && xhr.status < 300) {
                        try {
                            resolve(JSON.parse(xhr.responseText));
                        } catch (e) {
                            reject(new Error('Geçersiz sunucu yanıtı'));
                        }
                    } else {
                        try {
                            const err = JSON.parse(xhr.responseText);
                            reject(new Error(err.detail || `HTTP ${xhr.status}`));
                        } catch (e) {
                            reject(new Error(`Yükleme hatası (HTTP ${xhr.status})`));
                        }
                    }
                };
                
                xhr.onerror = () => reject(new Error('Ağ bağlantı hatası'));
                xhr.ontimeout = () => reject(new Error('Yükleme zaman aşımına uğradı'));
                xhr.timeout = 300000; // 5 dakika
                
                xhr.send(formData);
            });

            // v2.39.0: Dosya kaydedildi, processing arkaplanda devam ediyor
            this.updateProgress(100, 'Dosya kaydedildi, işleniyor...');

            // Kısa bildirim — detaylı bildirim WebSocket'ten veya polling'den gelecek
            const fileList = fileNames.length <= 3
                ? fileNames.join(', ')
                : `${fileNames.slice(0, 2).join(', ')} ve ${fileNames.length - 2} dosya daha`;

            if (window.NgssNotification) {
                NgssNotification.info('📄 Dosya Yüklendi', `${fileList} — işlem arkaplanda devam ediyor...`);
            } else {
                this.showToast(`${result.uploaded_count} dosya kaydedildi, işleniyor...`, 'info');
            }

            // Listeyi güncelle — processing durumundaki dosyaları görmek için
            console.log('[RAGUpload] Dosya kaydı başarılı, liste yenileniyor...');
            this.filesCurrentPage = 1;
            await this.loadFiles();
            await this.loadStats();

            // Dosya listesine scroll — kullanıcı yeni dosyayı görsün
            const fileListEl = document.getElementById('rag-files-list');
            if (fileListEl) {
                fileListEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }

            // v3.3.1: Processing polling başlat — WS çalışmasa bile tamamlanma bildirimi gelsin
            this._startProcessingPoll(fileNames);

            // v3.4.4: Org sıfırlama kaldırıldı — ardışık yüklemelerde seçim korunsun
            // Kullanıcı farklı org'a yüklemek isterse manuel değiştirir

        } catch (error) {
            console.error('[RAGUpload] Yükleme hatası:', error);

            if (window.NgssNotification) {
                NgssNotification.error('Yükleme Hatası', error.message || 'Dosya yüklenirken bir hata oluştu');
            } else {
                this.showToast(error.message || 'Dosya yükleme hatası', 'error');
            }
        } finally {
            this.isUploading = false;
            this.setUploadingState(false);  // UI enable
            setTimeout(() => this.showProgress(false), 1500);

            // File input'u sıfırla
            const fileInput = document.getElementById('rag-file-input');
            if (fileInput) fileInput.value = '';
        }
    },

    /**
     * v3.3.1: Processing dosyalar için REST polling.
     * BackGround işlem bittikten sonra dosya listesini yeniler ve bildirim yazar.
     * WS çalışmasa bile garanti bildirim sağlar.
     */
    _processingPollTimer: null,
    _processingPollCount: 0,
    _notifiedFiles: new Set(),  // v3.4.4: Çift bildirim engelleme
    _startProcessingPoll(uploadedFileNames) {
        // Önceki polling varsa durdur
        if (this._processingPollTimer) {
            clearInterval(this._processingPollTimer);
        }

        this._processingPollCount = 0;
        const maxPolls = 60;  // 5s × 60 = 5 dakika max
        const self = this;

        this._processingPollTimer = setInterval(async () => {
            self._processingPollCount++;

            if (self._processingPollCount >= maxPolls) {
                clearInterval(self._processingPollTimer);
                self._processingPollTimer = null;
                console.warn('[RAGUpload] Processing polling timeout — max süre aşıldı');
                return;
            }

            try {
                const token = localStorage.getItem('access_token');
                // v3.4.4: Tüm dosya listesi yerine sadece processing dosyaları sorgula
                const resp = await fetch(`${self.API_BASE}/rag/files?page=1&per_page=10&status=processing`, {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                if (!resp.ok) return;

                const data = await resp.json();
                const files = data.files || [];

                // Yüklenen dosyalar arasında hâlâ processing olan var mı?
                const processingFiles = files.filter(f =>
                    uploadedFileNames.includes(f.file_name) && f.status === 'processing'
                );

                if (processingFiles.length === 0) {
                    // İşlem tamamlandı — listeyi yenile + bildirim yaz
                    clearInterval(self._processingPollTimer);
                    self._processingPollTimer = null;

                    console.log('[RAGUpload] Processing tamamlandı, liste yenileniyor...');
                    await self.loadFiles();
                    await self.loadStats();

                    // v3.4.4: Çift bildirim engelleme — WS'ten zaten bildirilen dosyaları atla
                    const newNames = uploadedFileNames.filter(n => !self._notifiedFiles.has(n));
                    if (newNames.length > 0) {
                        const completedNames = newNames.length <= 3
                            ? newNames.join(', ')
                            : `${newNames.slice(0, 2).join(', ')} ve ${newNames.length - 2} dosya daha`;

                        if (window.NgssNotification) {
                            NgssNotification.add('success', '✅ Dosya İşleme Tamamlandı',
                                `${completedNames} — bilgi tabanına başarıyla eklendi.`, null, 'rag');
                        }
                        newNames.forEach(n => self._notifiedFiles.add(n));
                    }

                    // 30 sn sonra notified set'i temizle (memory leak önleme)
                    setTimeout(() => {
                        uploadedFileNames.forEach(n => self._notifiedFiles.delete(n));
                    }, 30000);
                }
            } catch (err) {
                console.warn('[RAGUpload] Processing poll hatası:', err);
            }
        }, 5000);  // 5 saniyede bir kontrol
    },

    // --- FILE LIST ---
    // v2.30.1: modules/rag_file_list.js modülüne taşındı.
    // Delegation: window.RAGFileList
    loadFiles() { if (window.RAGFileList) window.RAGFileList.loadFiles.call(this); },
    renderFilesPagination(t, p, pp) { if (window.RAGFileList) window.RAGFileList.renderFilesPagination.call(this, t, p, pp); },
    goToFilesPage(p) { if (window.RAGFileList) window.RAGFileList.goToFilesPage.call(this, p); },
    updateFilesTotalCount(t) { if (window.RAGFileList) window.RAGFileList.updateFilesTotalCount.call(this, t); },
    onFilesSearchInput(i) { if (window.RAGFileList) window.RAGFileList.onFilesSearchInput.call(this, i); },
    handleFilesSearch() { if (window.RAGFileList) window.RAGFileList.handleFilesSearch.call(this); },
    clearFilesSearch() { if (window.RAGFileList) window.RAGFileList.clearFilesSearch.call(this); },
    loadStats() { if (window.RAGFileList) window.RAGFileList.loadStats.call(this); },
    rebuildVectorstore() { if (window.RAGFileList) window.RAGFileList.rebuildVectorstore.call(this); },
    deleteFile(id, name) { if (window.RAGFileList) window.RAGFileList.deleteFile.call(this, id, name); },
    renderFilesList() { if (window.RAGFileList) window.RAGFileList.renderFilesList.call(this); },
    updateSelectedCount() { if (window.RAGFileList) window.RAGFileList.updateSelectedCount.call(this); },
    getSelectedFileIds() { if (window.RAGFileList) return window.RAGFileList.getSelectedFileIds.call(this); return []; },
    openFile(id) { if (window.RAGFileList) window.RAGFileList.openFile.call(this, id); },
    renderFileRow(f) { if (window.RAGFileList) return window.RAGFileList.renderFileRow.call(this, f); return ''; },
    getFileIconClass(t) { if (window.RAGFileList) return window.RAGFileList.getFileIconClass.call(this, t); return ''; },

    /**
     * v3.4.4: Enhancement geçmişi widget'ı yükler
     */
    async loadEnhancementHistory() {
        const container = document.getElementById('rag-enhancement-history');
        if (!container) return;

        try {
            const token = localStorage.getItem('access_token');
            const resp = await fetch(`${this.API_BASE}/rag/enhancement-impact?limit=5`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!resp.ok) { container.innerHTML = ''; return; }

            const data = await resp.json();
            const summary = data.summary || {};
            const items = data.items || [];

            if (items.length === 0) {
                container.innerHTML = '';
                return;
            }

            let html = `
                <div class="rag-enhance-history-card">
                    <div class="rag-enhance-history-header">
                        <h4><i class="fas fa-chart-line"></i> İyileştirme Geçmişi</h4>
                        <span class="rag-enhance-history-count">${summary.total_enhancements || 0} toplam</span>
                    </div>
                    <div class="rag-enhance-history-summary">
                        <div class="rag-enhance-stat">
                            <span class="rag-enhance-stat-label">Ort. Öncesi</span>
                            <span class="rag-enhance-stat-value before">${summary.avg_score_before ?? '-'}</span>
                        </div>
                        <div class="rag-enhance-stat">
                            <span class="rag-enhance-stat-label">Ort. Sonrası</span>
                            <span class="rag-enhance-stat-value after">${summary.avg_score_after ?? '-'}</span>
                        </div>
                        <div class="rag-enhance-stat">
                            <span class="rag-enhance-stat-label">İyileşme</span>
                            <span class="rag-enhance-stat-value improvement">+${summary.avg_improvement ?? 0}</span>
                        </div>
                    </div>
                    <div class="rag-enhance-history-items">
            `;
            for (const item of items.slice(0, 5)) {
                const scoreClass = (item.improvement && item.improvement > 0) ? 'positive' : 'neutral';
                html += `
                    <div class="rag-enhance-history-item">
                        <span class="rag-enhance-item-name" title="${item.file_name}">${item.file_name}</span>
                        <span class="rag-enhance-item-scores">
                            ${item.score_before ?? '-'} → ${item.score_after ?? '-'}
                            ${item.improvement ? `<span class="rag-enhance-item-diff ${scoreClass}">+${item.improvement}</span>` : ''}
                        </span>
                    </div>
                `;
            }
            html += '</div></div>';
            container.innerHTML = html;
        } catch (err) {
            console.warn('[RAGUpload] Enhancement history yüklenemedi:', err);
            container.innerHTML = '';
        }
    },


    /**
     * Dosya boyutunu formatlar
     */
    formatFileSize(bytes) {
        if (!bytes) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB'];
        let unitIndex = 0;
        let size = bytes;

        while (size >= 1024 && unitIndex < units.length - 1) {
            size /= 1024;
            unitIndex++;
        }

        return `${size.toFixed(1)} ${units[unitIndex]}`;
    },

    /**
     * Tarihi formatlar
     */
    formatDate(dateStr) {
        if (!dateStr) return '-';
        const date = new Date(dateStr);
        return date.toLocaleDateString('tr-TR', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    },

    /**
     * Stats UI'ı günceller
     */
    updateStatsUI(stats) {
        // Backend döner: { total_chunks, embedded_chunks, file_count, storage, embedding_model, embedding_dim }
        const chunkCount = document.getElementById('rag-chunk-count');
        if (chunkCount) {
            // Backend'den gelen doğru field: total_chunks
            chunkCount.textContent = stats.total_chunks || stats.embedded_chunks || 0;
        }

        const statusEl = document.getElementById('rag-status');
        if (statusEl) {
            const hasChunks = (stats.total_chunks || 0) > 0;
            statusEl.textContent = hasChunks ? 'Aktif' : 'Boş';
        }
    },

    /**
     * Dosya sayısını günceller
     */
    updateFileCount(count) {
        const fileCount = document.getElementById('rag-file-count');
        if (fileCount) {
            fileCount.textContent = count || 0;
        }

        const badge = document.querySelector('.files-count-badge');
        if (badge) {
            badge.textContent = count || 0;
        }
    },

    /**
     * Progress bar'ı gösterir/gizler
     */
    showProgress(show) {
        const container = document.querySelector('.upload-progress-container');
        if (container) {
            container.classList.toggle('active', show);
        }
    },

    /**
     * Yükleme sırasında UI elementlerini disable/enable eder
     */
    setUploadingState(isUploading) {
        // Kalem butonu (Org düzenleme)
        const editOrgBtn = document.getElementById('btn-rag-edit-orgs');
        if (editOrgBtn) {
            editOrgBtn.disabled = isUploading;
            editOrgBtn.classList.toggle('disabled', isUploading);
            editOrgBtn.style.pointerEvents = isUploading ? 'none' : '';
            editOrgBtn.style.opacity = isUploading ? '0.5' : '';
        }

        // Drop zone
        const dropZone = document.getElementById('rag-upload-zone');
        if (dropZone) {
            dropZone.classList.toggle('disabled', isUploading);
            dropZone.style.pointerEvents = isUploading ? 'none' : '';
            dropZone.style.opacity = isUploading ? '0.6' : '';
        }

        // File input
        const fileInput = document.getElementById('rag-file-input');
        if (fileInput) {
            fileInput.disabled = isUploading;
        }

        // Rebuild butonu
        const rebuildBtn = document.getElementById('btn-rebuild-vectorstore');
        if (rebuildBtn) {
            rebuildBtn.disabled = isUploading;
        }

        console.log('[RAGUpload] Uploading state:', isUploading ? 'DISABLED' : 'ENABLED');
    },

    /**
     * Progress'i günceller
     */
    updateProgress(percent, text) {
        const fill = document.querySelector('.upload-progress-fill');
        const textEl = document.querySelector('.upload-progress-status');

        if (fill) fill.style.width = `${percent}%`;
        if (textEl) textEl.textContent = text;
    },

    /**
     * Toast mesajı gösterir
     */
    showToast(message, type = 'info') {
        // Global toast fonksiyonu varsa kullan
        if (typeof VyraToast !== 'undefined' && VyraToast[type]) {
            VyraToast[type](message);
        } else if (typeof showToast === 'function') {
            showToast(message, type);
        } else {
            console.log(`[${type.toUpperCase()}] ${message}`);
        }
        // NgssNotification artık doğrudan çağrılıyor - showToast'tan kaldırıldı
    },

    /**
     * HTML escape
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },
    // --- FILE ORG EDIT ---
    // v2.30.1: modules/rag_file_org_edit.js modülüne taşındı.
    // Delegation: window.RAGFileOrgEdit
    async openFileOrgEditModal(id, name, codes) { if (window.RAGFileOrgEdit) await window.RAGFileOrgEdit.openFileOrgEditModal.call(this, id, name, codes); },
    renderFileOrgModalList() { if (window.RAGFileOrgEdit) window.RAGFileOrgEdit.renderFileOrgModalList.call(this); },
    renderFileOrgPagination(tp) { if (window.RAGFileOrgEdit) window.RAGFileOrgEdit.renderFileOrgPagination.call(this, tp); },
    updateFileOrgModalCounts(t) { if (window.RAGFileOrgEdit) window.RAGFileOrgEdit.updateFileOrgModalCounts.call(this, t); },
    setupFileOrgModalEvents() { if (window.RAGFileOrgEdit) window.RAGFileOrgEdit.setupFileOrgModalEvents.call(this); },
    closeFileOrgModal() { if (window.RAGFileOrgEdit) window.RAGFileOrgEdit.closeFileOrgModal.call(this); },
    confirmFileOrgEdit() { if (window.RAGFileOrgEdit) window.RAGFileOrgEdit.confirmFileOrgEdit.call(this); },

    // ── Maturity Threshold ──

    /**
     * Maturity iyileştirme eşik değerini API'den yükler
     */
    async loadMaturityThreshold() {
        try {
            const res = await fetch(`${this.API_BASE}/system/maturity-threshold`, {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });
            if (!res.ok) return;
            const data = await res.json();
            const threshold = data.threshold ?? 80;

            // Slider ve label güncelle
            const slider = document.getElementById('rag-maturity-threshold');
            const label = document.getElementById('rag-threshold-value');
            if (slider) slider.value = threshold;
            if (label) label.textContent = threshold;

            // Global paylaşım (maturity modal okuyacak)
            window._maturityEnhanceThreshold = threshold;
        } catch (err) {
            console.error('[RAGUpload] Threshold yükleme hatası:', err);
            window._maturityEnhanceThreshold = 80;
        }
    },

    /**
     * Maturity iyileştirme eşik değerini API'ye kaydeder
     */
    async saveMaturityThreshold(value) {
        try {
            const res = await fetch(`${this.API_BASE}/system/maturity-threshold?threshold=${value}`, {
                method: 'PUT',
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });
            if (res.ok) {
                window._maturityEnhanceThreshold = value;
                this.showToast(`İyileştirme eşik değeri ${value} olarak güncellendi.`, 'success');
            } else {
                this.showToast('Eşik değeri kaydedilemedi.', 'error');
            }
        } catch (err) {
            console.error('[RAGUpload] Threshold kayıt hatası:', err);
            this.showToast('Eşik değeri kaydedilemedi.', 'error');
        }
    },

    // --- Firma Selector ---
    async loadCompanySelector() {
        const select = document.getElementById('ragCompanySelect');
        if (!select) return;

        try {
            const token = localStorage.getItem('access_token') || '';
            const headers = { 'Authorization': 'Bearer ' + token };

            // Kullanıcı bilgisini al (is_admin, company_id)
            let userProfile = null;
            try {
                const meRes = await fetch(this.API_BASE + '/users/me', { headers });
                if (meRes.ok) userProfile = await meRes.json();
            } catch (e) {
                console.warn('[RAGUpload] Kullanıcı profili alınamadı:', e);
            }

            const isAdmin = userProfile && (userProfile.is_admin === true || userProfile.role_name === 'admin');
            const userCompanyId = userProfile ? userProfile.company_id : null;

            // Firma listesini yükle
            const res = await fetch(this.API_BASE + '/companies', { headers });
            if (!res.ok) return;
            const companies = await res.json();

            if (isAdmin) {
                // Admin: Firma seçimi zorunlu, tüm firmalar listelenir
                select.innerHTML = '<option value="" disabled selected>Firma Seçiniz...</option>';
                companies.forEach(c => {
                    const opt = document.createElement('option');
                    opt.value = c.id;
                    opt.textContent = c.name;
                    select.appendChild(opt);
                });
                select.disabled = false;
            } else {
                // Normal kullanıcı: Kendi firması otomatik seçili, değiştiremesin
                select.innerHTML = '';
                if (userCompanyId) {
                    const userCompany = companies.find(c => c.id === userCompanyId);
                    if (userCompany) {
                        const opt = document.createElement('option');
                        opt.value = userCompany.id;
                        opt.textContent = userCompany.name;
                        opt.selected = true;
                        select.appendChild(opt);
                    } else {
                        // Firma listede bulunamazsa fallback
                        const opt = document.createElement('option');
                        opt.value = userCompanyId;
                        opt.textContent = 'Firma #' + userCompanyId;
                        opt.selected = true;
                        select.appendChild(opt);
                    }
                    select.disabled = true;
                } else if (companies.length === 1) {
                    // Kullanıcının company_id'si yoksa ama tek firma varsa onu seç
                    const opt = document.createElement('option');
                    opt.value = companies[0].id;
                    opt.textContent = companies[0].name;
                    opt.selected = true;
                    select.appendChild(opt);
                    select.disabled = true;
                } else {
                    // Birden fazla firma var, hangi firmanın seçileceği belli değil
                    select.innerHTML = '<option value="" disabled selected>Firma Seçiniz...</option>';
                    companies.forEach(c => {
                        const opt = document.createElement('option');
                        opt.value = c.id;
                        opt.textContent = c.name;
                        select.appendChild(opt);
                    });
                    select.disabled = false;
                }
            }

            // Firma değişince dosya listesi, stats ve veri kaynaklarını yeniden yükle
            select.addEventListener('change', () => {
                this.filesCurrentPage = 1;
                this.loadFiles();
                this.loadStats();
                this.loadDataSources(); // v2.55.0: Kaynak listesini yenile
            });
        } catch (err) {
            console.warn('[RAGUpload] Firma selector yüklenemedi:', err);
        }
    },

    /**
     * Firma seçimi yapılmış mı kontrol eder.
     * Seçilmemişse uyarı gösterir ve dropdown'ı vurgular.
     * @returns {boolean} Firma seçili ise true, değilse false
     */
    _checkCompanySelected() {
        const compSel = document.getElementById('ragCompanySelect');
        if (!compSel) return true; // Selector yoksa engelleme

        if (!compSel.value) {
            // 🔔 Anlık görünür toast uyarısı göster
            if (typeof VyraToast !== 'undefined') {
                VyraToast.warning('Dosya yüklemek için önce bir firma seçmelisiniz.');
            } else if (typeof showToast === 'function') {
                showToast('Dosya yüklemek için önce bir firma seçmelisiniz.', 'warning');
            }

            // Dropdown'ı vurgula (kısa animasyon)
            compSel.classList.add('inp-error-flash');
            compSel.focus();
            setTimeout(() => compSel.classList.remove('inp-error-flash'), 2000);

            return false;
        }
        return true;
    },

    // ─── v2.55.0: Veri Kaynağı Seçici ──────────────────────

    /**
     * Firma bazlı veri kaynaklarını dropdown'a yükler
     */
    async loadDataSources() {
        const select = document.getElementById('rag-data-source-select');
        if (!select) return;

        // Duplicate listener koruması
        if (!select.hasAttribute('data-ds-listener')) {
            select.setAttribute('data-ds-listener', 'true');
            select.addEventListener('change', () => this.handleDataSourceChange());
        }

        try {
            const companyId = this._getCompanyId();
            if (!companyId) {
                select.innerHTML = '<option value="manual_file">📄 Manuel Dosya Ekleme</option>';
                return;
            }

            const token = localStorage.getItem('access_token') || '';
            const res = await fetch(
                this.API_BASE.replace('/api', '') + '/api/data-sources?company_id=' + companyId,
                { headers: { 'Authorization': 'Bearer ' + token } }
            );

            if (!res.ok) {
                select.innerHTML = '<option value="manual_file">📄 Manuel Dosya Ekleme</option>';
                return;
            }

            const sources = await res.json();
            select.innerHTML = '<option value="manual_file">📄 Manuel Dosya Ekleme</option>';

            const TYPE_EMOJI = { 'database': '🗄', 'file_server': '🖥', 'ftp': '🔀', 'sharepoint': '🟦', 'manual_file': '📄' };
            sources.filter(s => s.is_active).forEach(s => {
                const opt = document.createElement('option');
                opt.value = s.source_type + ':' + s.id;
                opt.textContent = (TYPE_EMOJI[s.source_type] || '📦') + ' ' + s.name;
                select.appendChild(opt);
            });
        } catch (err) {
            console.warn('[RAGUpload] Veri kaynakları yüklenemedi:', err);
        }
    },

    /**
     * Veri kaynağı seçimi değiştiğinde UI'yı günceller
     */
    async handleDataSourceChange() {
        const select = document.getElementById('rag-data-source-select');
        const dropZone = document.getElementById('rag-upload-zone');
        const placeholder = document.getElementById('rag-source-placeholder');
        if (!select) return;

        const val = select.value;
        const isManual = (val === 'manual_file');

        if (dropZone) dropZone.classList.toggle('hidden', !isManual);
        if (placeholder) placeholder.classList.toggle('hidden', isManual);

        // Eğer veritabanı kaynağı seçildiyse (type:id) onaylı tabloları getir
        if (!isManual && val.includes(':')) {
            const wrap = document.getElementById('rag-approved-tables-wrap');
            if (wrap) {
                wrap.innerHTML = `
                    <div style="text-align:center;padding:20px;color:var(--text-3);font-size:12px;">
                        <i class="fa-solid fa-spinner fa-spin" style="margin-bottom:8px;font-size:16px;"></i><br>
                        Onaylı Tablolar Yükleniyor...
                    </div>
                `;
            }

            const [sourceType, sourceId] = val.split(':');
            
            try {
                const token = localStorage.getItem('access_token') || '';
                const res = await fetch(
                    this.API_BASE.replace('/api', '') + '/api/data-sources/' + sourceId + '/enrichment-approved',
                    { headers: { 'Authorization': 'Bearer ' + token } }
                );
                
                const data = await res.json();
                
                if (wrap) {
                    if (data.success && data.approved && data.approved.length > 0) {
                        RAGUpload._approvedTablesFull = data.approved;
                        RAGUpload._renderApprovedTablesPage(1);
                    } else {
                        wrap.innerHTML = `
                            <div style="text-align:center;padding:30px 20px;color:var(--text-3);background:var(--bg-chip);border-radius:8px;">
                                <i class="fa-solid fa-circle-exclamation" style="font-size:24px;margin-bottom:10px;opacity:0.6;"></i><br>
                                <span style="font-size:13px;font-weight:500;">Onaylanmış Tablo Yok</span><br>
                                <span style="font-size:11.5px;opacity:0.8;margin-top:4px;display:block;">Bu veri kaynağı için zenginleştirilmiş ve RAG sistemine dahil edilen bir tablo bulunamadı. Parametreler panelinden devam edebilirsiniz.</span>
                            </div>
                        `;
                    }
                }
            } catch (err) {
                console.warn('[RAGUpload] Onaylı tablolar çekilemedi:', err);
                if (wrap) wrap.innerHTML = `<div style="padding:15px;color:var(--red);font-size:12px;text-align:center;">Veri çekilirken hata oluştu.</div>`;
            }
        }
    },

    _renderApprovedTablesPage(page) {
        const wrap = document.getElementById('rag-approved-tables-wrap');
        if (!wrap || !RAGUpload._approvedTablesFull) return;

        const limit = 5; // Sayfa basina 5 tablo goster (Ekran temiz kalsin)
        const total = RAGUpload._approvedTablesFull.length;
        const totalPages = Math.ceil(total / limit);
        
        if (page < 1) page = 1;
        if (page > totalPages) page = totalPages;
        
        const start = (page - 1) * limit;
        const end = start + limit;
        const items = RAGUpload._approvedTablesFull.slice(start, end);

        let html = '<div style="display:flex;flex-direction:column;gap:8px;margin-bottom:12px;">';
        items.forEach(tbl => {
            const nameHtml = tbl.admin_label_tr || tbl.business_name_tr || tbl.table_name;
            const descHtml = tbl.description_tr || 'Açıklama girilmemiş.';
            const catHtml = tbl.category || 'other';
            const dbNameHtml = tbl.schema_name ? (tbl.schema_name+'.'+tbl.table_name) : tbl.table_name;
            html += `
                <div style="display:flex;flex-direction:column;gap:4px;padding:12px;border:1px solid var(--border);border-radius:6px;background:var(--bg-card);transition:all 0.2s;">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <div style="font-size:13px;font-weight:600;color:var(--text-1);">
                            <i class="fa-solid fa-table" style="color:var(--accent);margin-right:6px;"></i>
                            ${nameHtml}
                        </div>
                        <span class="badge badge-green" style="font-size:10px;">
                            <i class="fa-solid fa-check"></i> Onaylı
                        </span>
                    </div>
                    <div style="font-size:11.5px;color:var(--text-3);margin-top:2px;">
                        <span style="font-family:'IBM Plex Mono',monospace;color:var(--text-2);background:var(--bg-chip);padding:2px 4px;border-radius:3px;">${dbNameHtml}</span> &nbsp; ${descHtml}
                    </div>
                </div>
            `;
        });
        html += '</div>';

        // Paging UI
        if (totalPages > 1) {
            html += `
                <div style="display:flex; justify-content:space-between; align-items:center; border-top:1px solid var(--border-light); padding-top:10px;">
                    <div style="font-size:11px; color:var(--text-3);">
                        Toplam: <strong>${total}</strong> | Sayfa: <strong>${page}/${totalPages}</strong>
                    </div>
                    <div style="display:flex; gap:5px;">
                        <button class="btn btn-sm btn-outline" style="padding:4px 8px; font-size:11px;" onclick="RAGUpload._renderApprovedTablesPage(${page - 1})" ${page === 1 ? 'disabled' : ''}>
                            <i class="fa-solid fa-chevron-left"></i> Önceki
                        </button>
                        <button class="btn btn-sm btn-outline" style="padding:4px 8px; font-size:11px;" onclick="RAGUpload._renderApprovedTablesPage(${page + 1})" ${page === totalPages ? 'disabled' : ''}>
                            Sonraki <i class="fa-solid fa-chevron-right"></i>
                        </button>
                    </div>
                </div>
            `;
        }
        wrap.innerHTML = html;
    },

    /**
     * Firma ID'sini RAG company select'ten alır
     */
    _getCompanyId() {
        const sel = document.getElementById('ragCompanySelect');
        return sel && sel.value ? sel.value : null;
    },

};

// Global erişim için
window.RAGUpload = RAGUpload;
