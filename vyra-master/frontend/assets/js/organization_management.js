/**
 * VYRA L1 Support API - Organization Management Module
 * ====================================================
 * Organizasyon grupları yönetimi (Admin Only)
 * - CRUD işlemleri
 * - Pagination & Search
 * - Modern SaaS UI
 */

class OrganizationManager {
    constructor() {
        this.currentPage = 1;
        this.perPage = 10;
        this.searchTerm = '';
        this.filterActive = null; // null = all, true = active, false = inactive

        this.modal = null;
        this.editingOrgId = null;
    }

    async init() {
        this.setupEventListeners();
        await this.loadOrganizations();
    }

    setupEventListeners() {
        // Search input
        const searchInput = document.getElementById('org-search-input');
        const clearBtn = document.getElementById('org-search-clear');

        if (searchInput) {
            searchInput.addEventListener('input', debounce((e) => {
                this.searchTerm = e.target.value;
                this.currentPage = 1;
                this.loadOrganizations();

                // Toggle clear button visibility
                if (clearBtn) {
                    clearBtn.classList.toggle('hidden', !this.searchTerm);
                }
            }, 150));  // Daha hızlı tepki: 300ms -> 150ms
        }

        // Search clear button
        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                searchInput.value = '';
                this.searchTerm = '';
                clearBtn.classList.add('hidden');
                this.currentPage = 1;
                this.loadOrganizations();
            });
        }

        // Filter buttons
        document.querySelectorAll('.org-filter-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.org-filter-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');

                const filter = e.target.dataset.filter;
                this.filterActive = filter === 'all' ? null : (filter === 'active');
                this.currentPage = 1;
                this.loadOrganizations();
            });
        });

        // New organization button
        const newBtn = document.getElementById('new-org-btn');
        if (newBtn) {
            newBtn.addEventListener('click', () => this.openCreateModal());
        }
    }

    async loadOrganizations() {
        try {
            showLoading('org-list-container');

            const params = new URLSearchParams({
                page: this.currentPage,
                per_page: this.perPage
            });

            if (this.searchTerm) params.append('search', this.searchTerm);
            if (this.filterActive !== null) params.append('is_active', this.filterActive);

            const response = await makeAuthRequest(`/api/organizations?${params}`);

            this.renderOrganizations(response.organizations);
            this.renderPagination(response.total, response.page, response.per_page);
            this.updateTotalCount(response.total);

        } catch (error) {
            console.error('Org load error:', error);
            showToast('Organizasyonlar yüklenemedi: ' + error.message, 'error');
        } finally {
            hideLoading('org-list-container');
        }
    }

    updateTotalCount(total) {
        const el = document.getElementById('org-total-count');
        if (el) {
            el.textContent = `Toplam: ${total} kayıt`;
        }
    }

    renderOrganizations(organizations) {
        const container = document.getElementById('org-list-container');

        if (organizations.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-building fa-3x"></i>
                    <p>Organizasyon bulunamadı</p>
                </div>
            `;
            return;
        }

        const rows = organizations.map(org => `
            <tr data-org-id="${org.id}">
                <td>
                    <div class="org-code-badge">${escapeHtml(org.org_code)}</div>
                </td>
                <td>
                    <div class="org-name">${escapeHtml(org.org_name)}</div>
                    ${org.description ? `<div class="org-desc">${escapeHtml(org.description)}</div>` : ''}
                </td>
                <td>
                    <span class="badge badge-${org.is_active ? 'success' : 'secondary'}">
                        ${org.is_active ? '✓ Aktif' : '✗ Pasif'}
                    </span>
                </td>
                <td>
                    <div class="org-stats">
                        <span class="stat-item">
                            <i class="fas fa-users"></i> ${org.user_count}
                        </span>
                        <span class="stat-item">
                            <i class="fas fa-file"></i> ${org.document_count}
                        </span>
                    </div>
                </td>
                <td>
                    <div class="action-buttons">
                        <button class="btn btn-sm btn-icon" onclick="orgManager.openEditModal(${org.id})" title="Düzenle">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="btn btn-sm btn-icon btn-danger" onclick="orgManager.deleteOrganization(${org.id}, '${escapeHtml(org.org_code)}')" title="Sil"
                            ${['ORG-DEFAULT', 'ORG-ADMIN'].includes(org.org_code) ? 'disabled' : ''}>
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `).join('');

        container.innerHTML = `
            <table class="org-table">
                <thead>
                    <tr>
                        <th>Org Kodu</th>
                        <th>Org Adı</th>
                        <th>Durum</th>
                        <th>İstatistik</th>
                        <th>İşlemler</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows}
                </tbody>
            </table>
        `;
    }

    renderPagination(total, page, perPage) {
        const totalPages = Math.ceil(total / perPage);
        const container = document.getElementById('org-pagination');

        if (totalPages <= 1) {
            container.innerHTML = '';
            return;
        }

        let pages = '';
        for (let i = 1; i <= totalPages; i++) {
            if (i === 1 || i === totalPages || (i >= page - 2 && i <= page + 2)) {
                pages += `
                    <button class="page-btn ${i === page ? 'active' : ''}" 
                            onclick="orgManager.goToPage(${i})">
                        ${i}
                    </button>
                `;
            } else if (i === page - 3 || i === page + 3) {
                pages += '<span class="page-dots">...</span>';
            }
        }

        container.innerHTML = `
            <div class="pagination">
                <button class="page-btn" ${page === 1 ? 'disabled' : ''} 
                        onclick="orgManager.goToPage(${page - 1})">
                    <i class="fas fa-chevron-left"></i>
                </button>
                ${pages}
                <button class="page-btn" ${page === totalPages ? 'disabled' : ''} 
                        onclick="orgManager.goToPage(${page + 1})">
                    <i class="fas fa-chevron-right"></i>
                </button>
            </div>
        `;
    }

    goToPage(page) {
        this.currentPage = page;
        this.loadOrganizations();
    }

    openCreateModal() {
        this.editingOrgId = null;

        const modalHtml = `
            <div class="modal-overlay" id="org-modal-overlay">
                <div class="modal-container modern-modal">
                    <div class="modal-header">
                        <h3><i class="fas fa-building"></i> Yeni Organizasyon Grubu</h3>
                        <button class="modal-close" onclick="orgManager.closeModal()">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                    <div class="modal-body">
                        <form id="org-form" onsubmit="orgManager.saveOrganization(event)">
                            <div class="form-group">
                                <label>Org Kodu *</label>
                                <input type="text" id="org-code" class="form-control" 
                                       placeholder="ORG-IT" required pattern="[A-Z0-9\\-]+" 
                                       title="Sadece büyük harf, rakam ve tire">
                                <small class="form-hint">Örn: ORG-IT, ORG-FINANS</small>
                            </div>
                            <div class="form-group">
                                <label>Org Adı *</label>
                                <input type="text" id="org-name" class="form-control" 
                                       placeholder="IT Destek" required>
                            </div>
                            <div class="form-group">
                                <label>Açıklama</label>
                                <textarea id="org-description" class="form-control" rows="3" 
                                          placeholder="Organizasyon grubu açıklaması..."></textarea>
                            </div>
                            <div class="form-group">
                                <label class="checkbox-label">
                                    <input type="checkbox" id="org-active" checked>
                                    <span>Aktif</span>
                                </label>
                            </div>
                            <div class="modal-actions">
                                <button type="button" class="btn btn-secondary" onclick="orgManager.closeModal()">
                                    İptal
                                </button>
                                <button type="submit" class="btn btn-primary">
                                    <i class="fas fa-save"></i> Kaydet
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHtml);
        this.modal = document.getElementById('org-modal-overlay');

        // ESC key support
        document.addEventListener('keydown', this.handleEscKey = (e) => {
            if (e.key === 'Escape') this.closeModal();
        });
    }

    async openEditModal(orgId) {
        this.editingOrgId = orgId;

        try {
            const org = await makeAuthRequest(`/api/organizations/${orgId}`);

            const modalHtml = `
                <div class="modal-overlay" id="org-modal-overlay">
                    <div class="modal-container modern-modal">
                        <div class="modal-header">
                            <h3><i class="fas fa-edit"></i> Organizasyon Düzenle</h3>
                            <button class="modal-close" onclick="orgManager.closeModal()">
                                <i class="fas fa-times"></i>
                            </button>
                        </div>
                        <div class="modal-body">
                            <form id="org-form" onsubmit="orgManager.saveOrganization(event)">
                                <div class="form-group">
                                    <label>Org Kodu</label>
                                    <input type="text" class="form-control" value="${escapeHtml(org.org_code)}" disabled>
                                    <small class="form-hint">Org kodu değiştirilemez</small>
                                </div>
                                <div class="form-group">
                                    <label>Org Adı *</label>
                                    <input type="text" id="org-name" class="form-control" 
                                           value="${escapeHtml(org.org_name)}" required>
                                </div>
                                <div class="form-group">
                                    <label>Açıklama</label>
                                    <textarea id="org-description" class="form-control" rows="3">${escapeHtml(org.description || '')}</textarea>
                                </div>
                                <div class="form-group">
                                    <label class="checkbox-label">
                                        <input type="checkbox" id="org-active" ${org.is_active ? 'checked' : ''}>
                                        <span>Aktif</span>
                                    </label>
                                </div>
                                <div class="modal-actions">
                                    <button type="button" class="btn btn-secondary" onclick="orgManager.closeModal()">
                                        İptal
                                    </button>
                                    <button type="submit" class="btn btn-primary">
                                        <i class="fas fa-save"></i> Güncelle
                                    </button>
                                </div>
                            </form>
                        </div>
                    </div>
                </div>
            `;

            document.body.insertAdjacentHTML('beforeend', modalHtml);
            this.modal = document.getElementById('org-modal-overlay');

            document.addEventListener('keydown', this.handleEscKey = (e) => {
                if (e.key === 'Escape') this.closeModal();
            });

        } catch (error) {
            showToast('Organizasyon yüklenemedi: ' + error.message, 'error');
        }
    }

    closeModal() {
        if (this.modal) {
            this.modal.remove();
            this.modal = null;
        }
        if (this.handleEscKey) {
            document.removeEventListener('keydown', this.handleEscKey);
            this.handleEscKey = null;
        }
    }

    async saveOrganization(event) {
        event.preventDefault();

        const orgName = document.getElementById('org-name').value.trim();
        const orgDescription = document.getElementById('org-description').value.trim();
        const isActive = document.getElementById('org-active').checked;

        const payload = {
            org_name: orgName,
            description: orgDescription || null,
            is_active: isActive
        };

        try {
            if (this.editingOrgId) {
                // Update
                await makeAuthRequest(`/api/organizations/${this.editingOrgId}`, {
                    method: 'PUT',
                    body: JSON.stringify(payload)
                });
                showToast('Organizasyon güncellendi', 'success');
            } else {
                // Create
                const orgCode = document.getElementById('org-code').value.trim().toUpperCase();
                payload.org_code = orgCode;

                await makeAuthRequest('/api/organizations', {
                    method: 'POST',
                    body: JSON.stringify(payload)
                });
                showToast('Organizasyon oluşturuldu', 'success');
            }

            this.closeModal();
            await this.loadOrganizations();

        } catch (error) {
            showToast('Hata: ' + error.message, 'error');
        }
    }

    async deleteOrganization(orgId, orgCode) {
        if (['ORG-DEFAULT', 'ORG-ADMIN'].includes(orgCode)) {
            showToast('Varsayılan organizasyonlar silinemez', 'error');
            return;
        }

        if (!confirm(`"${orgCode}" organizasyonunu silmek istediğinize emin misiniz?\n\nBu işlem geri alınamaz ve tüm kullanıcı/doküman ilişkileri silinecektir.`)) {
            return;
        }

        try {
            await makeAuthRequest(`/api/organizations/${orgId}`, { method: 'DELETE' });
            showToast('Organizasyon silindi', 'success');
            await this.loadOrganizations();
        } catch (error) {
            showToast('Silme hatası: ' + error.message, 'error');
        }
    }
}

// Utility functions
function debounce(func, wait) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Global instance
let orgManager = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('organization-management-page')) {
        orgManager = new OrganizationManager();
        orgManager.init();
    }
});
