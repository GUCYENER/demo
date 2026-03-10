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
            <button onclick="RAGUpload.goToFilesPage(1)" 
                style="padding: 8px 14px; border-radius: 6px; border: none; cursor: pointer;
                ${page === 1 ? 'opacity: 0.5; cursor: not-allowed;' : ''} 
                background: rgba(255,255,255,0.1); color: #9ca3af;"
                ${page === 1 ? 'disabled' : ''}>
                <i class="fa-solid fa-angles-left"></i>
            </button>
            <button onclick="RAGUpload.goToFilesPage(${page - 1})" 
                style="padding: 8px 14px; border-radius: 6px; border: none; cursor: pointer;
                ${page === 1 ? 'opacity: 0.5; cursor: not-allowed;' : ''} 
                background: rgba(255,255,255,0.1); color: #9ca3af;"
                ${page === 1 ? 'disabled' : ''}>
                <i class="fa-solid fa-chevron-left"></i>
            </button>
            <span style="padding: 8px 14px; color: #a5b4fc; font-weight: 600;">
                ${page} / ${totalPages}
            </span>
            <button onclick="RAGUpload.goToFilesPage(${page + 1})" 
                style="padding: 8px 14px; border-radius: 6px; border: none; cursor: pointer;
                ${page >= totalPages ? 'opacity: 0.5; cursor: not-allowed;' : ''} 
                background: rgba(255,255,255,0.1); color: #9ca3af;"
                ${page >= totalPages ? 'disabled' : ''}>
                <i class="fa-solid fa-chevron-right"></i>
            </button>
            <button onclick="RAGUpload.goToFilesPage(${totalPages})" 
                style="padding: 8px 14px; border-radius: 6px; border: none; cursor: pointer;
                ${page >= totalPages ? 'opacity: 0.5; cursor: not-allowed;' : ''} 
                background: rgba(255,255,255,0.1); color: #9ca3af;"
                ${page >= totalPages ? 'disabled' : ''}>
                <i class="fa-solid fa-angles-right"></i>
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
            const response = await fetch(`${this.API_BASE}/rag/stats`, {
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
                <div class="rag-empty-state">
                    <i class="fas fa-folder-open"></i>
                    <h4>Henüz dosya yok</h4>
                    <p>Bilgi tabanınıza doküman eklemek için yukarıdaki alana dosya sürükleyin.</p>
                </div>
            `;
            return;
        }

        const tableHTML = `
            <table class="rag-files-table">
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
            'txt': 'fas fa-file-alt'
        };
        return icons[fileType] || 'fas fa-file';
    },

};
