/* ─────────────────────────────────────────────
   NGSSAI — RAG File List Module
   v2.30.1 · rag_upload.js'den ayrıştırıldı
   Dosya listesi, sayfalama, arama, önizleme
   ───────────────────────────────────────────── */

window.RAGFileList = {
    API_BASE: (window.API_BASE_URL || 'http://localhost:8002') + '/api',

    /**
     * Dosya listesini yükler
     */
    async loadFiles() {
        try {
            const token = localStorage.getItem('access_token');

            const params = new URLSearchParams({
                page: this.filesCurrentPage,
                per_page: this.filesPerPage
            });
            if (this.filesSearchTerm) {
                params.append('search', this.filesSearchTerm);
            }

            // Firma bazlı filtreleme
            const compSel = document.getElementById('ragCompanySelect');
            if (compSel && compSel.value) {
                params.append('company_id', compSel.value);
            }

            const response = await fetch(`${this.API_BASE}/rag/files?${params}`, {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (!response.ok) {
                throw new Error('Dosya listesi alınamadı');
            }

            const data = await response.json();
            this.files = data.files || [];
            this.filesTotalCount = data.total || 0;

            this.renderFilesList();
            this.updateFileCount(data.total);
            this.renderFilesPagination(data.total, data.page || 1, data.per_page || 10);
            this.updateFilesTotalCount(data.total);

        } catch (error) {
            console.error('[RAGUpload] Dosya listesi hatası:', error);
        }
    },

    /**
     * Files için pagination render
     */
    renderFilesPagination(total, page, perPage) {
        const container = document.getElementById('rag-files-pagination');
        if (!container) return;

        const totalPages = Math.ceil(total / perPage) || 1;

        let html = `
            <button class="pg-btn" onclick="RAGUpload.goToFilesPage(${page - 1})" ${page === 1 ? 'disabled' : ''}>
                <i class="fa-solid fa-chevron-left pg-icon"></i>
            </button>
            <button class="pg-btn pg-cur">${page} / ${totalPages}</button>
            <button class="pg-btn" onclick="RAGUpload.goToFilesPage(${page + 1})" ${page >= totalPages ? 'disabled' : ''}>
                <i class="fa-solid fa-chevron-right pg-icon"></i>
            </button>
        `;
        container.innerHTML = html;
    },

    goToFilesPage(page) {
        this.filesCurrentPage = page;
        this.loadFiles();
    },

    updateFilesTotalCount(total) {
        const el = document.getElementById('rag-files-total-count');
        if (el) el.textContent = `Toplam: ${total} dosya`;
    },

    // Debounce timer
    filesSearchDebounceTimer: null,

    // Input değiştiğinde çağrılır (debounce ile arama)
    onFilesSearchInput(input) {
        // X butonunu göster/gizle
        const clearBtn = document.getElementById('rag-files-search-clear');
        if (clearBtn) {
            clearBtn.classList.toggle('hidden', !input.value);
        }

        // Debounce ile arama (150ms)
        clearTimeout(this.filesSearchDebounceTimer);
        this.filesSearchDebounceTimer = setTimeout(() => {
            this.handleFilesSearch();
        }, 150);
    },

    handleFilesSearch() {
        const input = document.getElementById('rag-files-search');
        if (!input) return;

        this.filesSearchTerm = input.value.trim();
        this.filesCurrentPage = 1; // Reset sayfa
        this.loadFiles();

        // Temizleme butonu göster/gizle
        const clearBtn = document.getElementById('rag-files-search-clear');
        if (clearBtn) {
            clearBtn.classList.toggle('hidden', !this.filesSearchTerm);
        }
    },

    clearFilesSearch() {
        const input = document.getElementById('rag-files-search');
        if (input) input.value = '';

        this.filesSearchTerm = '';
        this.filesCurrentPage = 1;
        this.loadFiles();

        const clearBtn = document.getElementById('rag-files-search-clear');
        if (clearBtn) clearBtn.classList.add('hidden');
    },

    /**
     * İstatistikleri yükler
     */
    async loadStats() {
        try {
            const token = localStorage.getItem('access_token');
            let statsUrl = `${this.API_BASE}/rag/stats`;

            // Firma bazlı filtreleme
            const compSel = document.getElementById('ragCompanySelect');
            if (compSel && compSel.value) {
                statsUrl += `?company_id=${compSel.value}`;
            }

            const response = await fetch(statsUrl, {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (!response.ok) {
                throw new Error('İstatistikler alınamadı');
            }

            const stats = await response.json();
            this.updateStatsUI(stats);

        } catch (error) {
            console.error('[RAGUpload] Stats hatası:', error);
        }
    },

    /**
     * Vektör veritabanını yeniden oluşturur
     */
    async rebuildVectorstore() {
        const btn = document.getElementById('btn-rebuild-vectorstore');
        if (!btn) return;

        btn.disabled = true;
        btn.classList.add('loading');
        btn.innerHTML = '<i class="fas fa-sync-alt"></i> Yenileniyor...';

        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`${this.API_BASE}/rag/rebuild`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Rebuild hatası');
            }

            const result = await response.json();

            if (result.success) {
                this.showToast(
                    `Vektör DB güncellendi: ${result.processed_files} dosya, ${result.total_chunks} chunk`,
                    'success'
                );
                // Notification'a da ekle
                if (window.NgssNotification) {
                    NgssNotification.success('Vektör DB Güncellendi', `${result.processed_files} dosya, ${result.total_chunks} chunk işlendi`);
                }
            } else {
                this.showToast(
                    `Kısmi hata: ${result.errors.join(', ')}`,
                    'warning'
                );
                if (window.NgssNotification) {
                    NgssNotification.warning('Kısmi Hata', result.errors.join(', '));
                }
            }

            await this.loadStats();

        } catch (error) {
            console.error('[RAGUpload] Rebuild hatası:', error);
            this.showToast(error.message || 'Rebuild hatası', 'error');
        } finally {
            btn.disabled = false;
            btn.classList.remove('loading');
            btn.innerHTML = '<i class="fas fa-sync-alt"></i> Yeniden Oluştur';
        }
    },

    /**
     * Dosya siler
     */
    async deleteFile(fileId, fileName) {
        VyraModal.danger({
            title: 'Dosyayı Sil',
            message: `"${fileName}" dosyasını silmek istediğinize emin misiniz? Bu işlem geri alınamaz.`,
            confirmText: 'Sil',
            cancelText: 'İptal',
            onConfirm: async () => {
                try {
                    const token = localStorage.getItem('access_token');
                    const response = await fetch(`${this.API_BASE}/rag/files/${fileId}`, {
                        method: 'DELETE',
                        headers: {
                            'Authorization': `Bearer ${token}`
                        }
                    });

                    if (!response.ok) {
                        const error = await response.json();
                        throw new Error(error.detail || 'Silme hatası');
                    }

                    this.showToast(`"${fileName}" silindi`, 'success');
                    if (window.NgssNotification) {
                        NgssNotification.info('Dosya Silindi', `"${fileName}" bilgi tabanından kaldırıldı`);
                    }
                    await this.loadFiles();
                    await this.loadStats();

                } catch (error) {
                    console.error('[RAGUpload] Silme hatası:', error);
                    this.showToast(error.message || 'Dosya silme hatası', 'error');
                }
            }
        });
    },

    /**
     * Dosya listesini render eder
     */
    renderFilesList() {
        const container = document.getElementById('rag-files-list');
        const rebuildBtn = document.getElementById('btn-rebuild-vectorstore');
        if (!container) return;

        // Dosya yoksa rebuild butonunu gizle
        if (rebuildBtn) {
            if (this.files.length === 0) {
                rebuildBtn.style.display = 'none';
            } else {
                rebuildBtn.style.display = '';
            }
        }

        if (this.files.length === 0) {
            container.innerHTML = `
                <div class="rag-empty-state" style="padding:40px;text-align:center">
                    <i class="fas fa-folder-open" style="font-size:32px;color:var(--text-3);margin-bottom:12px;display:block"></i>
                    <h4 style="font-size:14px;color:var(--text-1);margin-bottom:6px">Henüz dosya yok</h4>
                    <p style="font-size:12.5px;color:var(--text-3)">Bilgi tabanınıza doküman eklemek için yukarıdaki alana dosya sürükleyin.</p>
                </div>
            `;
            return;
        }

        const tableHTML = `
            <table class="data-table">
                <thead>
                    <tr>
                        <th style="width: 40px;">
                            <input type="checkbox" id="rag-select-all" class="rag-checkbox" title="Tümünü seç">
                        </th>
                        <th>Dosya Adı</th>
                        <th>Boyut</th>
                        <th>Olgunluk</th>
                        <th>Yüklenme Tarihi</th>
                        <th>Ekleyen</th>
                        <th>Veri Kaynağı</th>
                        <th>Org Grupları</th>
                        <th>İşlem</th>
                    </tr>
                </thead>
                <tbody>
                    ${this.files.map(file => this.renderFileRow(file)).join('')}
                </tbody>
            </table>
        `;

        container.innerHTML = tableHTML;

        // Select all checkbox
        const selectAllCheckbox = document.getElementById('rag-select-all');
        if (selectAllCheckbox) {
            selectAllCheckbox.addEventListener('change', (e) => {
                const checkboxes = container.querySelectorAll('.rag-file-checkbox');
                checkboxes.forEach(cb => cb.checked = e.target.checked);
                this.updateSelectedCount();
            });
        }

        // File checkboxes
        container.querySelectorAll('.rag-file-checkbox').forEach(cb => {
            cb.addEventListener('change', () => this.updateSelectedCount());
        });

        // Delete butonlarına event listener ekle
        container.querySelectorAll('.btn-delete-file').forEach(btn => {
            btn.addEventListener('click', () => {
                const fileId = btn.dataset.fileId;
                const fileName = btn.dataset.fileName;
                this.deleteFile(fileId, fileName);
            });
        });

        // Dosya adına tıklama event listener
        container.querySelectorAll('.file-name-link').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const fileId = link.dataset.fileId;
                this.openFile(fileId);
            });
        });

        // Org düzenleme butonlarına event listener ekle
        const editBtns = container.querySelectorAll('.btn-edit-file-org');
        console.log('[RAGUpload] Edit org buttons found:', editBtns.length);
        editBtns.forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const fileId = btn.dataset.fileId;
                const fileName = btn.dataset.fileName;
                const currentOrgs = JSON.parse(btn.dataset.currentOrgs || '[]');
                console.log('[RAGUpload] Edit org clicked:', fileId, fileName, currentOrgs);
                this.openFileOrgEditModal(fileId, fileName, currentOrgs);
            });
        });

        // Retry butonlarına event listener ekle
        container.querySelectorAll('.btn-retry-file').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const fileId = btn.dataset.fileId;
                const fileName = btn.dataset.fileName;
                this.retryFile(fileId, fileName);
            });
        });
    },

    /**
     * Seçili dosya sayısını günceller
     */
    updateSelectedCount() {
        const checkboxes = document.querySelectorAll('.rag-file-checkbox:checked');
        const selectedCount = checkboxes.length;

        // Seçili dosya sayısını göster (opsiyonel UI güncelleme)
        const rebuildBtn = document.getElementById('btn-rebuild-vectorstore');
        if (rebuildBtn && selectedCount > 0) {
            rebuildBtn.innerHTML = `<i class="fas fa-sync-alt"></i> ${selectedCount} Dosyayı Yeniden Oluştur`;
        } else if (rebuildBtn) {
            rebuildBtn.innerHTML = '<i class="fas fa-sync-alt"></i> Yeniden Oluştur';
        }

        return selectedCount;
    },

    /**
     * Seçili dosya ID'lerini döndürür
     */
    getSelectedFileIds() {
        const checkboxes = document.querySelectorAll('.rag-file-checkbox:checked');
        return Array.from(checkboxes).map(cb => parseInt(cb.dataset.fileId));
    },


    /**
     * Dosyayı yeni sekmede açar
     */
    async openFile(fileId) {
        const token = localStorage.getItem('access_token');
        const url = `${this.API_BASE}/rag/files/${fileId}/download`;

        try {
            console.log('[RAGUpload] Dosya açılıyor:', url);

            const response = await fetch(url, {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            console.log('[RAGUpload] Response status:', response.status);

            if (!response.ok) {
                const errorText = await response.text();
                console.error('[RAGUpload] API Hatası:', errorText);
                throw new Error(`Dosya yüklenemedi (${response.status})`);
            }

            const contentType = response.headers.get('content-type') || 'application/pdf';
            const blob = await response.blob();

            console.log('[RAGUpload] Blob oluşturuldu:', blob.size, 'bytes, type:', blob.type);

            // Blob URL oluştur
            const blobUrl = URL.createObjectURL(new Blob([blob], { type: contentType }));

            // Yeni pencere aç
            const newWindow = window.open(blobUrl, '_blank');

            // Popup engellenmiş olabilir
            if (!newWindow || newWindow.closed || typeof newWindow.closed === 'undefined') {
                console.warn('[RAGUpload] Popup engellendi, indirme linki oluşturuluyor...');

                // Indirme linki oluştur
                const link = document.createElement('a');
                link.href = blobUrl;
                link.download = `dosya_${fileId}.pdf`;
                link.click();

                this.showToast('Popup engellendi, dosya indiriliyor...', 'warning');
            }

        } catch (error) {
            console.error('[RAGUpload] Dosya açma hatası:', error);
            this.showToast(`Dosya açılırken hata: ${error.message}`, 'error');
        }
    },

    /**
     * Tek dosya satırını render eder
     */
    renderFileRow(file) {
        const fileType = file.file_type.replace('.', '');
        const iconClass = this.getFileIconClass(fileType);
        const fileSize = this.formatFileSize(file.file_size_bytes);
        const uploadDate = this.formatDate(file.uploaded_at);

        // v2.39.0: Status gösterimi
        const isProcessing = file.status === 'processing';
        const isFailed = file.status === 'failed';
        const rowClass = isProcessing ? 'rag-row-processing' : (isFailed ? 'rag-row-failed' : '');

        // Status badge
        let statusBadge = '';
        if (isProcessing) {
            statusBadge = '<span class="rag-status-badge processing"><i class="fas fa-spinner fa-spin"></i> İşleniyor</span>';
        } else if (isFailed) {
            statusBadge = '<span class="rag-status-badge failed"><i class="fas fa-exclamation-triangle"></i> Hata</span>';
        }

        return `
            <tr class="${rowClass}">
                <td>
                    <input type="checkbox" class="rag-file-checkbox rag-checkbox" data-file-id="${file.id}" ${isProcessing ? 'disabled' : ''}>
                </td>
                <td>
                    <div class="file-name-cell">
                        <div class="file-icon ${fileType}">
                            <i class="${iconClass}"></i>
                        </div>
                        <div class="file-info">
                            <a href="#" class="file-name-link" data-file-id="${file.id}" title="Dosyayı görüntüle">
                                ${this.escapeHtml(file.file_name)}
                            </a>
                            <div class="file-type">${fileType.toUpperCase()} ${statusBadge}</div>
                        </div>
                    </div>
                </td>
                <td class="file-size">${fileSize}</td>
                <td class="file-maturity">${window.MaturityScoreModal ? MaturityScoreModal.renderBadge(file.maturity_score) : '-'}</td>
                <td class="file-date">${uploadDate}</td>
                <td class="file-uploader">${file.uploaded_by_name || '-'}</td>
                <td class="file-source">
                    ${typeof this.renderSourceBadge === 'function' ? this.renderSourceBadge(file) : '<span class="ds-source-badge ds-badge-manual">📄 Manuel</span>'}
                </td>
                <td class="file-orgs">
                    ${file.org_groups && file.org_groups.length > 0
                ? file.org_groups.map(orgCode => {
                    const orgDetails = this.orgs.find(o => o.org_code === orgCode);
                    const orgName = orgDetails ? orgDetails.org_name : orgCode;
                    return `<span class="org-badge-sm" title="${orgName}">${orgCode}</span>`;
                }).join(' ')
                : '<span class="text-muted">-</span>'
            }
                </td>
                <td>
                    <div class="file-actions">
                        ${isFailed ? `<button class="btn-retry-file" data-file-id="${file.id}" data-file-name="${this.escapeHtml(file.file_name)}" title="Yeniden işle">
                            <i class="fas fa-rotate-right"></i>
                        </button>` : ''}
                        <button class="btn-edit-file-org" data-file-id="${file.id}" data-file-name="${this.escapeHtml(file.file_name)}" data-current-orgs='${JSON.stringify(file.org_groups || [])}' title="Org gruplarını düzenle" ${isProcessing ? 'disabled' : ''}>
                            <i class="fas fa-pen-to-square"></i>
                        </button>
                        <button class="btn-delete-file" data-file-id="${file.id}" data-file-name="${this.escapeHtml(file.file_name)}" title="Dosyayı sil" ${isProcessing ? 'disabled' : ''}>
                            <i class="fas fa-trash-alt"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    },

    /**
     * Dosya tipi için ikon class'ı döndürür
     */
    getFileIconClass(fileType) {
        const icons = {
            'pdf': 'fas fa-file-pdf',
            'docx': 'fas fa-file-word',
            'doc': 'fas fa-file-word',
            'xlsx': 'fas fa-file-excel',
            'xls': 'fas fa-file-excel',
            'pptx': 'fas fa-file-powerpoint',
            'ppt': 'fas fa-file-powerpoint',
            'txt': 'fas fa-file-alt',
            'csv': 'fas fa-file-csv'
        };
        return icons[fileType] || 'fas fa-file';
    },

    /**
     * Dosyanın veri kaynağı badge'ini render eder
     */
    renderSourceBadge(file) {
        // Şimdilik seçili kaynağı dropdown'dan kontrol et
        const select = document.getElementById('rag-data-source-select');
        const selectedOpt = select ? select.options[select.selectedIndex] : null;
        const label = selectedOpt ? selectedOpt.textContent.trim() : 'Manuel Dosya';

        // Kaynak tipi belirle
        const sourceType = file.data_source_type || 'manual_file';
        const TYPE_CONFIG = {
            'manual_file': { icon: 'fa-solid fa-file-arrow-up', label: '📄 Manuel', cls: 'ds-badge-manual' },
            'database':    { icon: 'fa-solid fa-database',      label: '🗄 Veritabanı', cls: 'ds-badge-db' },
            'file_server': { icon: 'fa-solid fa-server',        label: '🖥 File Server', cls: 'ds-badge-fs' },
            'ftp':         { icon: 'fa-solid fa-arrow-right-arrow-left', label: '🔀 FTP', cls: 'ds-badge-ftp' },
            'sharepoint':  { icon: 'fa-brands fa-microsoft',    label: '🟦 SharePoint', cls: 'ds-badge-sp' }
        };
        const cfg = TYPE_CONFIG[sourceType] || TYPE_CONFIG['manual_file'];
        return `<span class="ds-source-badge ${cfg.cls}">${cfg.label}</span>`;
    },

    /**
     * Başarısız dosyayı yeniden işleme alır
     */
    async retryFile(fileId, fileName) {
        // Çift tıklama koruması — buton disabled yapılır
        const retryBtn = document.querySelector(`.btn-retry-file[data-file-id="${fileId}"]`);
        if (retryBtn) {
            retryBtn.disabled = true;
            retryBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> İşleniyor...';
        }

        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`${this.API_BASE}/rag/retry-file/${fileId}`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Yeniden işleme hatası');
            }

            this.showToast(`"${fileName}" yeniden işleniyor...`, 'success');
            if (window.NgssNotification) {
                NgssNotification.info('Dosya Yeniden İşleniyor', `"${fileName}" arkaplanda işleniyor`);
            }

            // Dosya listesini yenile (processing durumunu görmek için)
            await this.loadFiles();

        } catch (error) {
            console.error('[RAGUpload] Retry hatası:', error);
            this.showToast(error.message || 'Yeniden işleme hatası', 'error');
            // Hata durumunda butonu tekrar aktif et
            if (retryBtn) {
                retryBtn.disabled = false;
                retryBtn.innerHTML = '<i class="fa-solid fa-rotate-right"></i> Tekrar Dene';
            }
        }
    },

    /**
     * v3.2.0: WebSocket progress dinleyicisini başlat
     * rag_upload_progress ve rag_upload_complete event'lerini dinler
     */
    initProgressListener() {
        // Progress event — dosya bazlı ilerleme
        window.addEventListener('vyra:rag_upload_progress', (e) => {
            const { current, total, file_name, percentage } = e.detail;
            this._showUploadProgress(current, total, file_name, percentage);
        });

        // Upload complete — işlem bitti, listeyi yenile
        window.addEventListener('vyra:rag_upload_complete', () => {
            this._hideUploadProgress();
            this.loadFiles();
        });

        // Upload failed — hata durumu, listeyi yenile
        window.addEventListener('vyra:rag_upload_failed', () => {
            this._hideUploadProgress();
            this.loadFiles();
        });
    },

    /**
     * Dosya tablosu üstünde progress bar gösterir
     */
    _showUploadProgress(current, total, fileName, percentage) {
        let bar = document.getElementById('ragUploadProgressBar');
        if (!bar) {
            const container = document.querySelector('.rag-file-list-container') ||
                              document.querySelector('#ragFileListBody')?.closest('.card-body');
            if (!container) return;

            bar = document.createElement('div');
            bar.id = 'ragUploadProgressBar';
            bar.className = 'rag-upload-progress-bar';
            bar.innerHTML = `
                <div class="rag-progress-info">
                    <i class="fa-solid fa-spinner fa-spin"></i>
                    <span class="rag-progress-text"></span>
                </div>
                <div class="rag-progress-track">
                    <div class="rag-progress-fill"></div>
                </div>
            `;
            container.insertBefore(bar, container.firstChild);
        }

        bar.style.display = 'flex';
        bar.querySelector('.rag-progress-text').textContent =
            `${current}/${total} dosya işlendi: ${fileName}`;
        bar.querySelector('.rag-progress-fill').style.width = `${percentage}%`;
    },

    /**
     * Progress bar'ı gizler
     */
    _hideUploadProgress() {
        const bar = document.getElementById('ragUploadProgressBar');
        if (bar) {
            bar.style.display = 'none';
        }
    },

};

// v3.2.0: Sayfa yüklendiğinde progress listener'ı başlat
document.addEventListener('DOMContentLoaded', () => {
    if (window.RAGFileList) {
        window.RAGFileList.initProgressListener();
    }
});
