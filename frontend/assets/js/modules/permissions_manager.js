/**
 * Permissions Manager Module
 * Rol bazlı yetki yönetimi için frontend modülü
 * @version 2.20.0
 */

(function () {
    'use strict';

    // ============================================
    // State Management
    // ============================================

    let currentRole = 'user';  // Varsayılan: user
    let resources = [];        // Tüm kaynaklar (hiyerarşik)
    let permissions = {};      // Mevcut yetkiler
    let originalPermissions = {}; // Değişiklik takibi için

    // ============================================
    // DOM Elements
    // ============================================

    function getElements() {
        return {
            // Tab and content
            tabRolePermissions: document.getElementById('tabRolePermissions'),
            contentRolePermissions: document.getElementById('contentRolePermissions'),

            // Role selector
            roleSelectorBtns: document.querySelectorAll('.role-selector-btn'),

            // Permission tree
            permissionTree: document.getElementById('permissionTree'),

            // Actions
            btnSavePermissions: document.getElementById('btnSavePermissions'),
            btnResetPermissions: document.getElementById('btnResetPermissions'),

            // Loading
            permissionsLoading: document.getElementById('permissionsLoading')
        };
    }

    // ============================================
    // API Calls
    // ============================================

    async function fetchResources() {
        try {
            if (!window.VYRA_API) {
                console.error('[Permissions] VYRA_API not available');
                return [];
            }
            const result = await window.VYRA_API.request('/permissions/resources');
            if (result && result.success) {
                resources = result.resources;
                return resources;
            }
        } catch (error) {
            console.error('[Permissions] Resources fetch error:', error);
        }
        return [];
    }

    async function fetchRolePermissions(roleName) {
        try {
            if (!window.VYRA_API) {
                console.error('[Permissions] VYRA_API not available');
                return {};
            }
            const result = await window.VYRA_API.request(`/permissions/${roleName}`);
            if (result && result.success) {
                permissions = result.permissions;
                originalPermissions = JSON.parse(JSON.stringify(permissions));
                return permissions;
            }
        } catch (error) {
            console.error('[Permissions] Permissions fetch error:', error);
        }
        return {};
    }

    async function savePermissions(roleName, permissionData) {
        try {
            if (!window.VYRA_API) {
                console.error('[Permissions] VYRA_API not available');
                throw new Error('API bağlantısı sağlanamadı');
            }
            const result = await window.VYRA_API.request(`/permissions/${roleName}`, {
                method: 'POST',
                body: { permissions: permissionData }  // api_client.js stringify yapıyor, tekrar stringify yapmıyoruz
            });
            return result;
        } catch (error) {
            console.error('[Permissions] Save error:', error);
            throw error;
        }
    }

    // ============================================
    // Render Functions
    // ============================================

    function renderPermissionTree() {
        const el = getElements();
        if (!el.permissionTree) return;

        let html = '';

        resources.forEach(menu => {
            const menuPerm = permissions[menu.id] || {};
            const hasChildren = menu.children && menu.children.length > 0;

            html += `
                <div class="permission-category">
                    <div class="permission-item menu-item">
                        <div class="permission-info">
                            <i class="fa-solid ${menu.icon}"></i>
                            <span class="permission-label">${menu.label}</span>
                            <span class="permission-type-badge menu">Menü</span>
                        </div>
                        <div class="permission-checkboxes">
                            ${renderCheckboxes(menu.id, 'menu', menuPerm)}
                        </div>
                    </div>
                    
                    ${hasChildren ? `
                        <div class="permission-children">
                            ${menu.children.map(tab => {
                const tabPerm = permissions[tab.id] || {};
                return `
                                    <div class="permission-item tab-item">
                                        <div class="permission-info">
                                            <i class="fa-solid ${tab.icon}"></i>
                                            <span class="permission-label">${tab.label}</span>
                                            <span class="permission-type-badge tab">Sekme</span>
                                        </div>
                                        <div class="permission-checkboxes">
                                            ${renderCheckboxes(tab.id, 'tab', tabPerm)}
                                        </div>
                                    </div>
                                `;
            }).join('')}
                        </div>
                    ` : ''}
                </div>
            `;
        });

        el.permissionTree.innerHTML = html;

        // Checkbox event listeners
        el.permissionTree.querySelectorAll('.perm-checkbox').forEach(checkbox => {
            checkbox.addEventListener('change', handleCheckboxChange);
        });
    }

    function renderCheckboxes(resourceId, resourceType, perm) {
        const isAdmin = currentRole === 'admin';
        const disabled = isAdmin ? 'disabled' : '';
        const checked = {
            view: perm.can_view ? 'checked' : '',
            create: perm.can_create ? 'checked' : '',
            update: perm.can_update ? 'checked' : '',
            delete: perm.can_delete ? 'checked' : ''
        };

        return `
            <label class="perm-checkbox-label" title="Görüntüleme yetkisi">
                <input type="checkbox" class="perm-checkbox" 
                       data-resource="${resourceId}" 
                       data-type="${resourceType}" 
                       data-action="view" 
                       ${checked.view} ${disabled}>
                <span class="perm-checkbox-text">Görüntüle</span>
            </label>
            <label class="perm-checkbox-label" title="Oluşturma yetkisi">
                <input type="checkbox" class="perm-checkbox" 
                       data-resource="${resourceId}" 
                       data-type="${resourceType}" 
                       data-action="create" 
                       ${checked.create} ${disabled}>
                <span class="perm-checkbox-text">Oluştur</span>
            </label>
            <label class="perm-checkbox-label" title="Düzenleme yetkisi">
                <input type="checkbox" class="perm-checkbox" 
                       data-resource="${resourceId}" 
                       data-type="${resourceType}" 
                       data-action="update" 
                       ${checked.update} ${disabled}>
                <span class="perm-checkbox-text">Düzenle</span>
            </label>
            <label class="perm-checkbox-label" title="Silme yetkisi">
                <input type="checkbox" class="perm-checkbox" 
                       data-resource="${resourceId}" 
                       data-type="${resourceType}" 
                       data-action="delete" 
                       ${checked.delete} ${disabled}>
                <span class="perm-checkbox-text">Sil</span>
            </label>
        `;
    }

    // ============================================
    // Event Handlers
    // ============================================

    function handleCheckboxChange(e) {
        const checkbox = e.target;
        const resourceId = checkbox.dataset.resource;
        const action = checkbox.dataset.action;

        if (!permissions[resourceId]) {
            permissions[resourceId] = {
                resource_type: checkbox.dataset.type,
                resource_id: resourceId,
                can_view: false,
                can_create: false,
                can_update: false,
                can_delete: false
            };
        }

        permissions[resourceId][`can_${action}`] = checkbox.checked;

        updateSaveButtonState();
    }

    function handleRoleChange(roleName) {
        currentRole = roleName;

        // Update role selector UI
        const el = getElements();
        el.roleSelectorBtns.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.role === roleName);
        });

        // Admin uyarısını göster/gizle
        const adminWarning = document.getElementById('adminPermWarning');
        if (adminWarning) {
            adminWarning.classList.toggle('hidden', roleName !== 'admin');
        }

        // Yetkileri yükle
        loadRolePermissions(roleName);
    }

    async function handleSave() {
        const el = getElements();

        if (currentRole === 'admin') {
            VyraToast.warning('Admin yetkileri değiştirilemez');
            return;
        }

        // Kaydet butonunu disable et
        if (el.btnSavePermissions) {
            el.btnSavePermissions.disabled = true;
            el.btnSavePermissions.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Kaydediliyor...';
        }

        try {
            // Permissions'ı API formatına dönüştür
            // Resource metadata'yı resources array'den al
            const permissionData = Object.entries(permissions).map(([resourceId, perm]) => {
                // Resource bilgisini bul
                let resourceInfo = null;
                for (const menu of resources) {
                    if (menu.id === resourceId) {
                        resourceInfo = { type: 'menu', label: menu.label, parent: null };
                        break;
                    }
                    if (menu.children) {
                        for (const tab of menu.children) {
                            if (tab.id === resourceId) {
                                resourceInfo = { type: 'tab', label: tab.label, parent: menu.id };
                                break;
                            }
                        }
                    }
                }

                return {
                    resource_type: resourceInfo?.type || perm.resource_type || 'menu',
                    resource_id: resourceId,
                    resource_label: resourceInfo?.label || perm.resource_label || null,
                    parent_resource_id: resourceInfo?.parent || perm.parent_resource_id || null,
                    can_view: perm.can_view || false,
                    can_create: perm.can_create || false,
                    can_update: perm.can_update || false,
                    can_delete: perm.can_delete || false
                };
            });

            console.log('[Permissions] Sending data:', { role: currentRole, permissionData });
            const result = await savePermissions(currentRole, permissionData);

            if (result.success) {
                showToast('Yetkiler başarıyla kaydedildi!', 'success');
                originalPermissions = JSON.parse(JSON.stringify(permissions));
                updateSaveButtonState();
            } else {
                showToast('Kaydetme hatası: ' + (result.message || 'Bilinmeyen hata'), 'error');
            }

        } catch (error) {
            showToast('Kaydetme hatası: ' + error.message, 'error');
        } finally {
            if (el.btnSavePermissions) {
                el.btnSavePermissions.disabled = false;
                el.btnSavePermissions.innerHTML = '<i class="fa-solid fa-save"></i> Kaydet';
            }
        }
    }

    function handleReset() {
        permissions = JSON.parse(JSON.stringify(originalPermissions));
        renderPermissionTree();
        updateSaveButtonState();
        showToast('Değişiklikler geri alındı', 'info');
    }

    // ============================================
    // Helper Functions
    // ============================================

    function updateSaveButtonState() {
        const el = getElements();
        if (!el.btnSavePermissions) return;

        const hasChanges = JSON.stringify(permissions) !== JSON.stringify(originalPermissions);
        const isAdmin = currentRole === 'admin';

        el.btnSavePermissions.disabled = !hasChanges || isAdmin;
        el.btnSavePermissions.classList.toggle('btn-disabled', !hasChanges || isAdmin);
    }

    function showLoading(show) {
        const el = getElements();
        if (el.permissionsLoading) {
            el.permissionsLoading.classList.toggle('hidden', !show);
        }
        if (el.permissionTree) {
            el.permissionTree.classList.toggle('hidden', show);
        }
    }

    // ============================================
    // Initialization
    // ============================================

    async function loadRolePermissions(roleName) {
        showLoading(true);

        await fetchRolePermissions(roleName);
        renderPermissionTree();
        updateSaveButtonState();

        showLoading(false);
    }

    // Duplicate init kontrolü
    let isInitialized = false;

    async function init() {
        // Duplicate event listener önleme
        if (isInitialized) {
            console.log('[Permissions] Already initialized, skipping');
            return;
        }

        const el = getElements();

        // Tab yoksa çık
        if (!el.tabRolePermissions) return;

        isInitialized = true;

        // Kaynakları yükle
        await fetchResources();

        // Event listeners
        el.roleSelectorBtns.forEach(btn => {
            btn.addEventListener('click', () => handleRoleChange(btn.dataset.role));
        });

        if (el.btnSavePermissions) {
            el.btnSavePermissions.addEventListener('click', handleSave);
        }

        if (el.btnResetPermissions) {
            el.btnResetPermissions.addEventListener('click', handleReset);
        }

        // Tab activated event
        el.tabRolePermissions.addEventListener('click', async () => {
            if (!permissions || Object.keys(permissions).length === 0) {
                await loadRolePermissions(currentRole);
            }
        });

        console.log('[Permissions] Module initialized');
    }

    // ============================================
    // Public API
    // ============================================

    window.PermissionsManager = {
        init,
        loadRolePermissions,
        getCurrentRole: () => currentRole
    };

    // Auto-init on DOMContentLoaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
