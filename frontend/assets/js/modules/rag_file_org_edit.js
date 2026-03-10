/* ─────────────────────────────────────────────
   VYRA – RAG File Org Edit Module
   v2.30.1 · rag_upload.js'den ayrıştırıldı
   Dosya org grupları düzenleme
   ───────────────────────────────────────────── */

window.RAGFileOrgEdit = {
    API_BASE: (window.API_BASE_URL || 'http://localhost:8002') + '/api',

    // State
    fileOrgEditId: null,
    fileOrgEditSelectedIds: [],
    fileOrgSearchText: '',
    fileOrgPage: 1,
    fileOrgPerPage: 5,

    /**
     * Dosya org gruplarını düzenleme modal'ı
     * v2.42.0: this.orgs boşsa fallback API fetch ile org listesi yüklenir
     */
    async openFileOrgEditModal(fileId, fileName, currentOrgCodes) {
        this.fileOrgEditId = fileId;
        this.fileOrgSearchText = '';
        this.fileOrgPage = 1;
        this.fileOrgPerPage = this.fileOrgPerPage || 5;

        // 🛡️ v2.42.0: Fallback — this.orgs boş/undefined ise API'den yükle
        if (!this.orgs || this.orgs.length === 0) {
            console.warn('[RAGUpload] this.orgs boş — fallback API fetch başlatılıyor...');
            try {
                const token = localStorage.getItem('access_token');
                const response = await fetch(`${this.API_BASE}/organizations`, {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                if (response.ok) {
                    const data = await response.json();
                    this.orgs = (data.organizations || []).filter(o => o.is_active);
                    console.log('[RAGUpload] Fallback org fetch başarılı:', this.orgs.length, 'org yüklendi');
                } else {
                    console.error('[RAGUpload] Fallback org fetch başarısız:', response.status);
                    this.orgs = [];
                }
            } catch (err) {
                console.error('[RAGUpload] Fallback org fetch hatası:', err);
                this.orgs = [];
            }
        }

        // Mevcut org kodlarını id'lere çevir
        this.fileOrgEditSelectedIds = currentOrgCodes.map(code => {
            const org = this.orgs.find(o => o.org_code === code);
            return org ? org.id : null;
        }).filter(id => id !== null);

        console.log('[RAGUpload] File org edit:', fileId, fileName, currentOrgCodes, '->', this.fileOrgEditSelectedIds);

        // Modal HTML - Modern SaaS tasarım
        const modalHtml = `
            <div id="fileOrgEditModal" class="org-modal-overlay">
                <div class="org-modal-container">
                    <div class="org-modal-header">
                        <h3><i class="fas fa-file-pen"></i> Doküman Org Grupları</h3>
                        <button class="org-modal-close" id="fileOrgModalClose"><i class="fas fa-times"></i></button>
                    </div>
                    
                    <!-- Dosya Bilgisi -->
                    <div class="file-org-edit-info">
                        <i class="fas fa-file"></i> <strong>${this.escapeHtml(fileName)}</strong>
                    </div>
                    
                    <!-- Arama Kutusu -->
                    <div class="org-modal-search">
                        <div class="org-search-box">
                            <i class="fa-solid fa-search"></i>
                            <input type="text" id="fileOrgModalSearch" placeholder="Org kodu veya adı ile ara...">
                            <button id="fileOrgModalSearchClear" class="org-search-clear hidden">
                                <i class="fa-solid fa-times-circle"></i>
                            </button>
                        </div>
                    </div>
                    
                    <!-- Org Listesi -->
                    <div id="fileOrgModalList" class="org-modal-list"></div>
                    
                    <!-- Footer - Stat ve Pagination -->
                    <div class="org-modal-footer-stats">
                        <div class="org-modal-footer-left">
                            <span class="org-total-count" id="fileOrgModalTotalCount">Toplam: 0 kayıt</span>
                            <span class="org-selected-count" id="fileOrgModalCount">${this.fileOrgEditSelectedIds.length} seçili</span>
                        </div>
                        <div id="fileOrgModalPagination" class="org-modal-pagination"></div>
                    </div>
                    
                    <!-- Footer - Buttons -->
                    <div class="org-modal-footer org-modal-footer-buttons">
                        <button id="fileOrgModalCancel" class="btn-org-cancel">İptal</button>
                        <button id="fileOrgModalConfirm" class="btn-org-confirm"><i class="fas fa-check"></i> Kaydet</button>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHtml);
        this.renderFileOrgModalList();
        this.setupFileOrgModalEvents();
    },

    renderFileOrgModalList() {
        const container = document.getElementById('fileOrgModalList');
        if (!container) return;

        // Filter orgs by search
        let filteredOrgs = (this.orgs || []).filter(o => o.is_active);

        if (this.fileOrgSearchText) {
            const search = this.fileOrgSearchText.toLowerCase();
            filteredOrgs = filteredOrgs.filter(o =>
                o.org_code.toLowerCase().includes(search) ||
                o.org_name.toLowerCase().includes(search)
            );
        }

        // Pagination
        const perPage = this.fileOrgPerPage || 5;
        const totalPages = Math.ceil(filteredOrgs.length / perPage) || 1;
        const startIdx = (this.fileOrgPage - 1) * perPage;
        const pagedOrgs = filteredOrgs.slice(startIdx, startIdx + perPage);

        if (pagedOrgs.length === 0) {
            container.innerHTML = `
                <div class="org-empty">
                    <i class="fa-solid fa-folder-open"></i>
                    <p>Organizasyon bulunamadı</p>
                </div>
            `;
        } else {
            container.innerHTML = pagedOrgs.map(org => `
                <label class="org-modal-item">
                    <input type="checkbox" class="org-modal-checkbox" value="${org.id}" 
                           ${this.fileOrgEditSelectedIds.includes(org.id) ? 'checked' : ''}>
                    <div class="org-modal-item-content">
                        <span class="org-modal-code">${org.org_code}</span>
                        <span class="org-modal-name">${org.org_name}</span>
                    </div>
                </label>
            `).join('');

            // Checkbox events
            container.querySelectorAll('.org-modal-checkbox').forEach(cb => {
                cb.addEventListener('change', (e) => {
                    const id = parseInt(e.target.value);
                    if (e.target.checked) {
                        if (!this.fileOrgEditSelectedIds.includes(id)) {
                            this.fileOrgEditSelectedIds.push(id);
                        }
                    } else {
                        this.fileOrgEditSelectedIds = this.fileOrgEditSelectedIds.filter(x => x !== id);
                    }
                    this.updateFileOrgModalCounts(filteredOrgs.length);
                });
            });
        }

        // Render pagination
        this.renderFileOrgPagination(totalPages);
        this.updateFileOrgModalCounts(filteredOrgs.length);
    },

    renderFileOrgPagination(totalPages) {
        const container = document.getElementById('fileOrgModalPagination');
        if (!container) return;

        // Tek sayfa bile olsa pagination göster
        let pagHtml = '';
        for (let i = 1; i <= totalPages; i++) {
            pagHtml += `<button class="org-pag-btn ${i === this.fileOrgPage ? 'active' : ''}" data-page="${i}">${i}</button>`;
        }
        container.innerHTML = pagHtml;

        container.querySelectorAll('.org-pag-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.fileOrgPage = parseInt(btn.dataset.page);
                this.renderFileOrgModalList();
            });
        });
    },

    updateFileOrgModalCounts(total) {
        const countEl = document.getElementById('fileOrgModalCount');
        const totalEl = document.getElementById('fileOrgModalTotalCount');
        if (countEl) countEl.textContent = `${this.fileOrgEditSelectedIds.length} seçili`;
        if (totalEl) totalEl.textContent = `Toplam: ${total} kayıt`;
    },

    setupFileOrgModalEvents() {
        document.getElementById('fileOrgModalClose')?.addEventListener('click', () => this.closeFileOrgModal());
        document.getElementById('fileOrgModalCancel')?.addEventListener('click', () => this.closeFileOrgModal());
        document.getElementById('fileOrgModalConfirm')?.addEventListener('click', () => this.confirmFileOrgEdit());

        // Arama kutusu event'leri
        const searchInput = document.getElementById('fileOrgModalSearch');
        const clearBtn = document.getElementById('fileOrgModalSearchClear');

        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this.fileOrgSearchText = e.target.value;
                clearBtn?.classList.toggle('hidden', !this.fileOrgSearchText);
                this.fileOrgPage = 1;
                this.renderFileOrgModalList();
            });
        }

        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                searchInput.value = '';
                this.fileOrgSearchText = '';
                clearBtn.classList.add('hidden');
                this.fileOrgPage = 1;
                this.renderFileOrgModalList();
            });
        }

        // ESC key
        document.addEventListener('keydown', this.handleFileOrgModalEsc = (e) => {
            if (e.key === 'Escape') this.closeFileOrgModal();
        });
    },

    closeFileOrgModal() {
        document.getElementById('fileOrgEditModal')?.remove();
        document.removeEventListener('keydown', this.handleFileOrgModalEsc);
        // State reset
        this.fileOrgSearchText = '';
        this.fileOrgPage = 1;
    },

    async confirmFileOrgEdit() {
        if (this.fileOrgEditSelectedIds.length === 0) {
            this.showToast('En az bir org grubu seçin', 'warning');
            return;
        }

        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`${this.API_BASE}/rag/files/${this.fileOrgEditId}/organizations`, {
                method: 'PATCH',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ org_ids: this.fileOrgEditSelectedIds })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Güncelleme hatası');
            }

            this.showToast('Org grupları güncellendi', 'success');
            this.closeFileOrgModal();
            await this.loadFiles(); // Listeyi yenile

        } catch (error) {
            console.error('[RAGUpload] Org update error:', error);
            this.showToast(error.message || 'Güncelleme hatası', 'error');
        }
    }

};
