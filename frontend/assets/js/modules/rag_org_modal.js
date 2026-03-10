/* ─────────────────────────────────────────────
   NGSSAI — RAG Org Modal Module
   v2.30.1 · rag_upload.js'den ayrıştırıldı
   Org gruplarını yükleme, modal açma/kapama, seçim
   ───────────────────────────────────────────── */

window.RAGOrgModal = {
    API_BASE: (window.API_BASE_URL || 'http://localhost:8002') + '/api',

    /**
     * Org gruplarını yükler
     */
    async loadOrgs() {
        const token = localStorage.getItem('access_token');
        if (!token) return;

        try {
            const response = await fetch(`${this.API_BASE}/organizations`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!response.ok) throw new Error('Org yüklenemedi');
            const data = await response.json();
            this.orgs = (data.organizations || []).filter(o => o.is_active);

            // SessionStorage'dan önceki seçimi yükle (varsa)
            const savedOrgs = sessionStorage.getItem('rag_selected_org_ids');
            if (savedOrgs) {
                try {
                    this.selectedOrgIds = JSON.parse(savedOrgs);
                    console.log('[RAGUpload] SessionStorage\'dan yüklendi:', this.selectedOrgIds);
                } catch {
                    this.selectedOrgIds = [];
                }
            } else {
                // Sayfa ilk açılışında boş başla
                this.selectedOrgIds = [];
            }

            this.renderOrgBadges();
            this.setupOrgEditButton();
        } catch (error) {
            console.error('[RAGUpload] Org load error:', error);
            this.orgs = [];
        }
    },

    /**
     * Seçilen org id'lerini sessionStorage'a kaydet
     */
    saveSelectedOrgsToStorage() {
        sessionStorage.setItem('rag_selected_org_ids', JSON.stringify(this.selectedOrgIds));
    },

    /**
     * Kalem ikonu event listener
     */
    setupOrgEditButton() {
        const btn = document.getElementById('btn-rag-edit-orgs');
        if (btn) {
            btn.addEventListener('click', () => this.openOrgModal());
        }
    },

    /**
     * Seçili org badge'larını render eder
     */
    renderOrgBadges() {
        const container = document.getElementById('rag-org-badges');
        if (!container) return;

        if (this.selectedOrgIds.length === 0) {
            container.innerHTML = '<span class="rag-org-empty">Org seçilmedi</span>';
            return;
        }

        const selectedOrgCodes = this.selectedOrgIds.map(id => {
            const org = this.orgs.find(o => o.id === id);
            return org ? org.org_code : '';
        }).filter(Boolean);

        container.innerHTML = selectedOrgCodes.map(code =>
            `<span class="rag-org-badge-selected">${code}</span>`
        ).join('');
    },

    /**
     * Org seçim modal'ını aç
     */
    openOrgModal() {
        // Mevcut modal varsa kapat
        document.getElementById('ragOrgModal')?.remove();

        // Modal state - mevcut seçimleri koru
        this.modalSelectedIds = [...this.selectedOrgIds];
        this.modalSearchText = '';
        this.modalPage = 1;
        this.showSelectedOnly = false;

        console.log('[RAGUpload] Opening modal with selectedOrgIds:', this.selectedOrgIds, 'modalSelectedIds:', this.modalSelectedIds);

        const modalHtml = `
            <div id="ragOrgModal" class="org-modal-overlay">
                <div class="org-modal-container">
                    <div class="org-modal-header">
                        <h3><i class="fa-solid fa-building"></i> Org Grupları Seç</h3>
                        <div class="org-modal-header-filters">
                            <label class="org-modal-filter-checkbox">
                                <input type="checkbox" id="ragOrgSelectAll">
                                <span>Tümünü Seç</span>
                            </label>
                            <label class="org-modal-filter-checkbox">
                                <input type="checkbox" id="ragOrgShowSelected">
                                <span>Sadece seçili</span>
                            </label>
                        </div>
                        <button class="org-modal-close" id="ragOrgModalClose">
                            <i class="fa-solid fa-times"></i>
                        </button>
                    </div>
                    
                    <div class="org-modal-search">
                        <div class="org-search-box">
                            <i class="fa-solid fa-search"></i>
                            <input type="text" id="ragOrgModalSearch" placeholder="Org kodu veya adı ile ara...">
                            <button id="ragOrgModalSearchClear" class="org-search-clear hidden">
                                <i class="fa-solid fa-times-circle"></i>
                            </button>
                        </div>
                    </div>
                    
                    <div class="org-modal-list" id="ragOrgModalList">
                        <div class="org-loading">
                            <i class="fa-solid fa-spinner fa-spin"></i> Yükleniyor...
                        </div>
                    </div>
                    
                    <div class="org-modal-pagination" id="ragOrgModalPagination"></div>
                    
                    <div class="org-modal-footer">
                        <div class="org-modal-footer-left">
                            <span class="org-total-count" id="ragOrgModalTotalCount">Toplam: 0 kayıt</span>
                            <span class="org-selected-count" id="ragOrgModalSelectedCount">0 seçili</span>
                        </div>
                        <div class="org-modal-actions">
                            <button class="btn-org-cancel" id="ragOrgModalCancel">İptal</button>
                            <button class="btn-org-confirm" id="ragOrgModalConfirm">
                                <i class="fa-solid fa-check"></i> Ekle
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHtml);

        // Event listeners
        document.getElementById('ragOrgModalClose').addEventListener('click', () => this.closeOrgModal());
        document.getElementById('ragOrgModalCancel').addEventListener('click', () => this.closeOrgModal());
        document.getElementById('ragOrgModalConfirm').addEventListener('click', () => this.confirmOrgSelection());

        // "Tümünü Seç" checkbox
        const selectAllCheckbox = document.getElementById('ragOrgSelectAll');
        selectAllCheckbox.addEventListener('change', (e) => {
            const activeOrgs = this.orgs.filter(o => o.is_active);
            if (e.target.checked) {
                // Tüm aktif org'ları seç
                this.modalSelectedIds = activeOrgs.map(o => o.id);
            } else {
                // Tümünü kaldır
                this.modalSelectedIds = [];
            }
            this.renderModalList();
        });

        // "Sadece seçili" checkbox
        const showSelectedCheckbox = document.getElementById('ragOrgShowSelected');
        showSelectedCheckbox.addEventListener('change', (e) => {
            this.showSelectedOnly = e.target.checked;
            this.modalPage = 1;
            this.renderModalList();
        });

        const searchInput = document.getElementById('ragOrgModalSearch');
        const clearBtn = document.getElementById('ragOrgModalSearchClear');

        searchInput.addEventListener('input', (e) => {
            this.modalSearchText = e.target.value;
            clearBtn.classList.toggle('hidden', !this.modalSearchText);
            this.modalPage = 1;
            this.renderModalList();
        });

        clearBtn.addEventListener('click', () => {
            searchInput.value = '';
            this.modalSearchText = '';
            clearBtn.classList.add('hidden');
            this.modalPage = 1;
            this.renderModalList();
        });

        // ESC key
        this.escHandler = (e) => { if (e.key === 'Escape') this.closeOrgModal(); };
        document.addEventListener('keydown', this.escHandler);

        // Render list
        this.renderModalList();
    },

    closeOrgModal() {
        document.getElementById('ragOrgModal')?.remove();
        if (this.escHandler) {
            document.removeEventListener('keydown', this.escHandler);
        }

        // Eğer iptal edildiyse pending state'leri temizle (sadece modal kapatıldıysa)
        // Ancak confirmOrgSelection içinde işlem yapılıyorsa temizleme orada yapılır
        // Bu fonksiyon hem X butonu hem Cancel butonu hem de Confirm sonrası çağrıldığı için
        // burada temizlik yapmıyoruz, state yönetimi caller'a ait olabilir.
        // Ancak kullanıcı X ile kapatırsa pendingFiles yüklenmez, bu beklenen davranıştır.
    },

    renderModalList() {
        const container = document.getElementById('ragOrgModalList');
        if (!container) return;

        // Filter
        let filteredOrgs = this.orgs.filter(o => o.is_active);

        // "Sadece seçili" filtresi
        if (this.showSelectedOnly) {
            filteredOrgs = filteredOrgs.filter(o => this.modalSelectedIds.includes(o.id));
        }

        if (this.modalSearchText) {
            const search = this.modalSearchText.toLowerCase();
            filteredOrgs = filteredOrgs.filter(o =>
                o.org_code.toLowerCase().includes(search) ||
                o.org_name.toLowerCase().includes(search)
            );
        }

        // Pagination
        const perPage = 5;
        const totalPages = Math.ceil(filteredOrgs.length / perPage);
        const startIdx = (this.modalPage - 1) * perPage;
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
                           ${this.modalSelectedIds.includes(org.id) ? 'checked' : ''}>
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
                        if (!this.modalSelectedIds.includes(id)) {
                            this.modalSelectedIds.push(id);
                        }
                    } else {
                        this.modalSelectedIds = this.modalSelectedIds.filter(x => x !== id);
                    }
                    this.updateModalCounts(filteredOrgs.length);
                });
            });
        }

        // Pagination buttons
        const pagContainer = document.getElementById('ragOrgModalPagination');
        if (totalPages > 1) {
            let pagHtml = '';
            for (let i = 1; i <= totalPages; i++) {
                pagHtml += `<button class="org-pag-btn ${i === this.modalPage ? 'active' : ''}" data-page="${i}">${i}</button>`;
            }
            pagContainer.innerHTML = pagHtml;
            pagContainer.querySelectorAll('.org-pag-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    this.modalPage = parseInt(btn.dataset.page);
                    this.renderModalList();
                });
            });
        } else {
            pagContainer.innerHTML = '';
        }

        this.updateModalCounts(filteredOrgs.length);

        // "Tümünü Seç" checkbox senkronizasyonu
        const selectAllCb = document.getElementById('ragOrgSelectAll');
        if (selectAllCb) {
            const activeOrgs = this.orgs.filter(o => o.is_active);
            selectAllCb.checked = activeOrgs.length > 0 && activeOrgs.every(o => this.modalSelectedIds.includes(o.id));
        }
    },

    updateModalCounts(total) {
        const countEl = document.getElementById('ragOrgModalSelectedCount');
        const totalEl = document.getElementById('ragOrgModalTotalCount');
        if (countEl) countEl.textContent = `${this.modalSelectedIds.length} seçili`;
        if (totalEl) totalEl.textContent = `Toplam: ${total} kayıt`;
    },

    confirmOrgSelection() {
        if (this.modalSelectedIds.length === 0) {
            this.showToast('En az bir org grubu seçin', 'warning');
            return;
        }

        this.selectedOrgIds = [...this.modalSelectedIds];
        this.saveSelectedOrgsToStorage();  // SessionStorage'a kaydet
        this.renderOrgBadges();
        this.closeOrgModal();
        this.showToast(`${this.selectedOrgIds.length} org grubu seçildi`, 'success');
        console.log('[RAGUpload] Selected orgs:', this.selectedOrgIds);

        // Bekleyen aksiyonlar
        if (this.pendingFiles && this.pendingFiles.length > 0) {
            console.log('[RAGUpload] Bekleyen dosyalar yükleniyor:', this.pendingFiles.length);
            const filesToUpload = this.pendingFiles;
            this.pendingFiles = null; // Reset
            this.handleFiles(filesToUpload); // Yeniden handle et (şimdi org seçili)
        }
        else {
            // Org seçildikten sonra HER ZAMAN dosya diyaloğu aç - kullanıcı kolaylığı
            console.log('[RAGUpload] Dosya diyaloğu otomatik açılıyor...');
            this.shouldOpenFileDialogAfterOrg = false; // Reset (eğer set edilmişse)
            const fileInput = document.getElementById('rag-file-input');
            if (fileInput) fileInput.click();
        }
    },

};
