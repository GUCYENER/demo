/* ─────────────────────────────────────────────
   VYRA — Data Sources Module
   v2.55.0 · Veri kaynakları yönetimi (Parametreler sekmesi)
   ───────────────────────────────────────────── */

window.DataSourcesModule = (function () {
    'use strict';

    const API_BASE = (window.API_BASE_URL || '') + '/api/data-sources';
    let sources = [];

    // Kaynak Tipi Etiketleri
    const SOURCE_TYPE_LABELS = {
        'database': 'Veri Tabanı',
        'file_server': 'File Server',
        'ftp': 'FTP / SFTP',
        'sharepoint': 'SharePoint',
        'manual_file': 'Manuel Dosya Ekleme'
    };

    const SOURCE_TYPE_ICONS = {
        'database': 'fa-solid fa-database',
        'file_server': 'fa-solid fa-server',
        'ftp': 'fa-solid fa-arrow-right-arrow-left',
        'sharepoint': 'fa-brands fa-microsoft',
        'manual_file': 'fa-solid fa-file-arrow-up'
    };

    const DB_TYPE_LABELS = {
        'postgresql': 'PostgreSQL',
        'mssql': 'Microsoft SQL Server',
        'mysql': 'MySQL',
        'oracle': 'Oracle DB'
    };

    // --- API ---

    async function load(companyId) {
        try {
            const token = localStorage.getItem('access_token') || '';
            let url = API_BASE;
            if (companyId) url += `?company_id=${companyId}`;

            const res = await fetch(url, {
                headers: { 'Authorization': 'Bearer ' + token }
            });
            if (!res.ok) throw new Error('Kaynak listesi alınamadı');

            sources = await res.json();
            renderGrid();
        } catch (error) {
            console.error('[DataSources] Load error:', error);
            sources = [];
            renderGrid();
        }
    }

    async function save(formData) {
        try {
            const token = localStorage.getItem('access_token') || '';
            const isEdit = !!formData.id;
            const url = isEdit ? `${API_BASE}/${formData.id}` : API_BASE;
            const method = isEdit ? 'PUT' : 'POST';

            const body = { ...formData };
            delete body.id; // ID body'de olmamalı

            const res = await fetch(url, {
                method,
                headers: {
                    'Authorization': 'Bearer ' + token,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(body)
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Kaydetme hatası');
            }

            const result = await res.json();
            if (typeof showToast === 'function') {
                showToast(isEdit ? 'Kaynak güncellendi' : 'Yeni kaynak eklendi', 'success');
            }
            closeModal();

            // Listeyi yenile
            const companyId = _getSelectedCompanyId();
            await load(companyId);
            return result;
        } catch (error) {
            console.error('[DataSources] Save error:', error);
            if (typeof showToast === 'function') {
                showToast(error.message || 'Kaydetme hatası', 'error');
            }
        }
    }

    async function deleteSource(id, name) {
        if (!window.VyraModal) return;
        VyraModal.danger({
            title: 'Kaynağı Sil',
            message: `"${name}" kaynağını silmek istediğinize emin misiniz?`,
            confirmText: 'Sil',
            cancelText: 'İptal',
            onConfirm: async () => {
                try {
                    const token = localStorage.getItem('access_token') || '';
                    const res = await fetch(`${API_BASE}/${id}`, {
                        method: 'DELETE',
                        headers: { 'Authorization': 'Bearer ' + token }
                    });
                    if (!res.ok) {
                        const err = await res.json();
                        throw new Error(err.detail || 'Silme hatası');
                    }
                    if (typeof showToast === 'function') {
                        showToast(`"${name}" silindi`, 'success');
                    }
                    const companyId = _getSelectedCompanyId();
                    await load(companyId);
                } catch (error) {
                    console.error('[DataSources] Delete error:', error);
                    if (typeof showToast === 'function') {
                        showToast(error.message || 'Silme hatası', 'error');
                    }
                }
            }
        });
    }

    // --- UI: Kart listesi ---

    function renderGrid() {
        const grid = document.getElementById('dataSourcesGrid');
        if (!grid) return;

        if (sources.length === 0) {
            grid.innerHTML = `
                <div class="ds-empty-state">
                    <div class="ds-empty-icon">
                        <i class="fa-solid fa-plug-circle-plus"></i>
                    </div>
                    <h3>Henüz veri kaynağı tanımlanmadı</h3>
                    <p>Yeni bir veri kaynağı ekleyerek RAG sistemine veri akışı sağlayın.</p>
                </div>
            `;
            return;
        }

        grid.innerHTML = sources.map(s => renderCard(s)).join('');

        // Event listener'lar
        grid.querySelectorAll('.ds-btn-test').forEach(btn => {
            btn.addEventListener('click', () => {
                testConnection(parseInt(btn.dataset.id), btn.dataset.name);
            });
        });
        grid.querySelectorAll('.ds-btn-edit').forEach(btn => {
            btn.addEventListener('click', () => {
                const id = parseInt(btn.dataset.id);
                const source = sources.find(s => s.id === id);
                if (source) openModal(source);
            });
        });
        grid.querySelectorAll('.ds-btn-delete').forEach(btn => {
            btn.addEventListener('click', () => {
                deleteSource(parseInt(btn.dataset.id), btn.dataset.name);
            });
        });
        // DB Keşif butonu
        grid.querySelectorAll('.ds-btn-discover').forEach(btn => {
            btn.addEventListener('click', () => {
                if (window.DSLearningModule) {
                    DSLearningModule.openWizard(parseInt(btn.dataset.id), btn.dataset.name);
                }
            });
        });
        // Öğrenme Geçmişi butonu
        grid.querySelectorAll('.ds-btn-history').forEach(btn => {
            btn.addEventListener('click', () => {
                if (window.DSLearningModule) {
                    DSLearningModule.showLearningHistory(parseInt(btn.dataset.id), btn.dataset.name);
                }
            });
        });
    }

    function renderCard(source) {
        const typeLabel = SOURCE_TYPE_LABELS[source.source_type] || source.source_type;
        const typeIcon = SOURCE_TYPE_ICONS[source.source_type] || 'fa-solid fa-plug';
        const dbLabel = source.db_type ? DB_TYPE_LABELS[source.db_type] || source.db_type : '';
        const statusClass = source.is_active ? 'ds-status-active' : 'ds-status-inactive';
        const statusText = source.is_active ? 'Aktif' : 'Pasif';

        let detailHtml = '';
        if (source.source_type === 'database') {
            detailHtml = `
                <div class="ds-card-detail">
                    <span class="ds-detail-label">Tip</span>
                    <span class="ds-detail-value">${dbLabel}</span>
                </div>
                <div class="ds-card-detail">
                    <span class="ds-detail-label">Sunucu</span>
                    <span class="ds-detail-value">${source.host || '-'}${source.port ? ':' + source.port : ''}</span>
                </div>
                <div class="ds-card-detail">
                    <span class="ds-detail-label">Veritabanı</span>
                    <span class="ds-detail-value">${source.db_name || '-'}</span>
                </div>
            `;
        } else if (source.source_type === 'file_server') {
            detailHtml = `
                <div class="ds-card-detail">
                    <span class="ds-detail-label">Yol</span>
                    <span class="ds-detail-value">${source.file_server_path || '-'}</span>
                </div>
            `;
        } else if (source.source_type === 'ftp') {
            const ftpProto = source.db_type ? source.db_type.toUpperCase() : 'FTP';
            detailHtml = `
                <div class="ds-card-detail">
                    <span class="ds-detail-label">Protokol</span>
                    <span class="ds-detail-value">${ftpProto}</span>
                </div>
                <div class="ds-card-detail">
                    <span class="ds-detail-label">Sunucu</span>
                    <span class="ds-detail-value">${source.host || '-'}${source.port ? ':' + source.port : ''}</span>
                </div>
            `;
        } else if (source.source_type === 'sharepoint') {
            detailHtml = `
                <div class="ds-card-detail">
                    <span class="ds-detail-label">Site URL</span>
                    <span class="ds-detail-value">${source.file_server_path || '-'}</span>
                </div>
                <div class="ds-card-detail">
                    <span class="ds-detail-label">Tenant</span>
                    <span class="ds-detail-value">${source.host || '-'}</span>
                </div>
            `;
        } else {
            detailHtml = `
                <div class="ds-card-detail">
                    <span class="ds-detail-label">Açıklama</span>
                    <span class="ds-detail-value">${source.description || 'Manuel dosya yükleme'}</span>
                </div>
            `;
        }

        return `
            <div class="ds-card">
                <div class="ds-card-header">
                    <div class="ds-card-type">
                        <div class="ds-type-icon"><i class="${typeIcon}"></i></div>
                        <div>
                            <div class="ds-card-name">${_escapeHtml(source.name)}</div>
                            <div class="ds-card-type-label">${typeLabel}</div>
                        </div>
                    </div>
                    <div class="ds-card-actions">
                        <span class="ds-status ${statusClass}">${statusText}</span>
                        <button class="ds-btn-test" data-id="${source.id}" data-name="${_escapeHtml(source.name)}" title="Bağlantı Testi">
                            <i class="fa-solid fa-plug-circle-check"></i>
                        </button>
                        ${source.source_type === 'database' ? `<button class="ds-card-discover-btn ds-btn-discover" data-id="${source.id}" data-name="${_escapeHtml(source.name)}" title="DB Keşfet">
                            <i class="fa-solid fa-magnifying-glass-chart"></i>
                        </button>
                        <button class="ds-card-history-btn ds-btn-history" data-id="${source.id}" data-name="${_escapeHtml(source.name)}" title="Öğrenme Geçmişi">
                            <i class="fa-solid fa-brain"></i>
                        </button>` : ''}
                        <button class="ds-btn-edit" data-id="${source.id}" title="Düzenle">
                            <i class="fa-solid fa-pen"></i>
                        </button>
                        <button class="ds-btn-delete" data-id="${source.id}" data-name="${_escapeHtml(source.name)}" title="Sil">
                            <i class="fa-solid fa-trash-alt"></i>
                        </button>
                    </div>
                </div>
                <div class="ds-card-body">
                    ${detailHtml}
                </div>
            </div>
        `;
    }

    // --- Modal ---

    function openModal(source) {
        // Firma seçili mi?
        const companyId = _getSelectedCompanyId();
        if (!companyId) {
            if (typeof showToast === 'function') {
                showToast('Önce bir firma seçin', 'warning');
            }
            return;
        }

        closeModal(); // Önceki modal varsa kapat

        const isEdit = !!source;
        const title = isEdit ? 'Kaynağı Düzenle' : 'Yeni Kaynak Ekle';
        const s = source || {};

        const modalHtml = `
            <div id="dsModal" class="modal-overlay">
                <div class="modal-box ds-modal-box">
                    <div class="modal-header">
                        <h3><i class="fa-solid fa-plug-circle-plus"></i> ${title}</h3>
                        <button class="modal-close" id="dsModalClose"><i class="fa-solid fa-xmark"></i></button>
                    </div>
                    <div class="modal-body ds-modal-body">
                        <div class="ds-form-group">
                            <label class="ds-label">Kaynak Adı <span class="ds-required">*</span></label>
                            <input class="inp" type="text" id="dsName" value="${_escapeHtml(s.name || '')}" placeholder="Örn: Ana Veritabanı">
                        </div>

                        <div class="ds-form-group">
                            <label class="ds-label">Kaynak Tipi <span class="ds-required">*</span></label>
                            <select class="inp" id="dsSourceType">
                                <option value="">— Seçin —</option>
                                <option value="database" ${s.source_type === 'database' ? 'selected' : ''}>🗄 Veri Tabanı</option>
                                <option value="file_server" ${s.source_type === 'file_server' ? 'selected' : ''}>🖥 File Server</option>
                                <option value="ftp" ${s.source_type === 'ftp' ? 'selected' : ''}>🔀 FTP / SFTP</option>
                                <option value="sharepoint" ${s.source_type === 'sharepoint' ? 'selected' : ''}>🟦 SharePoint</option>
                                <option value="manual_file" ${s.source_type === 'manual_file' ? 'selected' : ''}>📄 Manuel Dosya Ekleme</option>
                            </select>
                        </div>

                        <!-- Dinamik Alanlar -->
                        <div id="dsDynamicFields"></div>

                        <div class="ds-form-group">
                            <label class="ds-label">Açıklama</label>
                            <textarea class="inp" id="dsDescription" rows="2" placeholder="Opsiyonel açıklama">${_escapeHtml(s.description || '')}</textarea>
                        </div>

                        <div class="ds-form-row">
                            <label class="ds-label">Aktif</label>
                            <label class="saas-toggle">
                                <input type="checkbox" id="dsIsActive" ${s.is_active !== false ? 'checked' : ''}>
                                <span class="saas-toggle-track"></span>
                            </label>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn" id="dsModalCancel">İptal</button>
                        <button class="btn primary" id="dsModalSave">
                            <i class="fa-solid fa-save"></i> Kaydet
                        </button>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHtml);

        // Event listeners
        document.getElementById('dsModalClose').addEventListener('click', closeModal);
        document.getElementById('dsModalCancel').addEventListener('click', closeModal);
        document.getElementById('dsModalSave').addEventListener('click', () => handleSave(source));

        // ESC ile kapat
        const escHandler = (e) => {
            if (e.key === 'Escape') {
                closeModal();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);

        // Source type change → dinamik alanlar
        const typeSelect = document.getElementById('dsSourceType');
        typeSelect.addEventListener('change', () => renderDynamicFields(typeSelect.value, s));

        // İlk render
        if (s.source_type) {
            renderDynamicFields(s.source_type, s);
        }
    }

    function closeModal() {
        const modal = document.getElementById('dsModal');
        if (modal) modal.remove();
    }

    function renderDynamicFields(sourceType, source) {
        const container = document.getElementById('dsDynamicFields');
        if (!container) return;

        const s = source || {};

        switch (sourceType) {
            case 'database':
                container.innerHTML = `
                    <div class="ds-form-section">
                        <div class="ds-section-title">
                            <i class="fa-solid fa-database"></i> Bağlantı Bilgileri
                        </div>
                        <div class="ds-form-group">
                            <label class="ds-label">Veritabanı Tipi <span class="ds-required">*</span></label>
                            <select class="inp" id="dsDbType">
                                <option value="">— Seçin —</option>
                                <option value="postgresql" ${s.db_type === 'postgresql' ? 'selected' : ''}>PostgreSQL</option>
                                <option value="mssql" ${s.db_type === 'mssql' ? 'selected' : ''}>Microsoft SQL Server</option>
                                <option value="mysql" ${s.db_type === 'mysql' ? 'selected' : ''}>MySQL</option>
                                <option value="oracle" ${s.db_type === 'oracle' ? 'selected' : ''}>Oracle DB</option>
                            </select>
                        </div>
                        <div class="ds-form-row-2col">
                            <div class="ds-form-group">
                                <label class="ds-label">Sunucu Adresi <span class="ds-required">*</span></label>
                                <input class="inp" type="text" id="dsHost" value="${_escapeHtml(s.host || '')}" placeholder="192.168.1.100">
                            </div>
                            <div class="ds-form-group">
                                <label class="ds-label">Port <span class="ds-required">*</span></label>
                                <input class="inp" type="number" id="dsPort" value="${s.port || ''}" placeholder="5432" min="1" max="65535">
                            </div>
                        </div>
                        <div class="ds-form-group">
                            <label class="ds-label">Veritabanı Adı <span class="ds-required">*</span></label>
                            <input class="inp" type="text" id="dsDbName" value="${_escapeHtml(s.db_name || '')}" placeholder="mydb">
                        </div>
                        <div class="ds-form-row-2col">
                            <div class="ds-form-group">
                                <label class="ds-label">Kullanıcı Adı <span class="ds-required">*</span></label>
                                <input class="inp" type="text" id="dsDbUser" value="${_escapeHtml(s.db_user || '')}" placeholder="db_user">
                            </div>
                            <div class="ds-form-group">
                                <label class="ds-label">Şifre ${s.id ? '' : '<span class="ds-required">*</span>'}</label>
                                <input class="inp" type="password" id="dsDbPassword" placeholder="${s.id ? 'Değiştirmek için yeni şifre girin' : 'Şifre'}">
                            </div>
                        </div>
                    </div>
                `;
                break;

            case 'file_server':
                container.innerHTML = `
                    <div class="ds-form-section">
                        <div class="ds-section-title">
                            <i class="fa-solid fa-server"></i> Dosya Sunucu Bilgileri
                        </div>
                        <div class="ds-form-group">
                            <label class="ds-label">Dosya Yolu <span class="ds-required">*</span></label>
                            <input class="inp" type="text" id="dsFilePath" value="${_escapeHtml(s.file_server_path || '')}" placeholder="\\\\server\\share\\docs veya /mnt/data">
                        </div>
                        <div class="ds-form-row-2col">
                            <div class="ds-form-group">
                                <label class="ds-label">Kullanıcı Adı</label>
                                <input class="inp" type="text" id="dsDbUser" value="${_escapeHtml(s.db_user || '')}" placeholder="Opsiyonel">
                            </div>
                            <div class="ds-form-group">
                                <label class="ds-label">Şifre</label>
                                <input class="inp" type="password" id="dsDbPassword" placeholder="Opsiyonel">
                            </div>
                        </div>
                    </div>
                `;
                break;

            case 'ftp':
                container.innerHTML = `
                    <div class="ds-form-section">
                        <div class="ds-section-title">
                            <i class="fa-solid fa-arrow-right-arrow-left"></i> FTP / SFTP Bağlantı Bilgileri
                        </div>
                        <div class="ds-form-group">
                            <label class="ds-label">Protokol <span class="ds-required">*</span></label>
                            <select class="inp" id="dsFtpProtocol">
                                <option value="ftp" ${(s.db_type === 'ftp' || !s.db_type) ? 'selected' : ''}>FTP</option>
                                <option value="ftps" ${s.db_type === 'ftps' ? 'selected' : ''}>FTPS (SSL/TLS)</option>
                                <option value="sftp" ${s.db_type === 'sftp' ? 'selected' : ''}>SFTP (SSH)</option>
                            </select>
                        </div>
                        <div class="ds-form-row-2col">
                            <div class="ds-form-group">
                                <label class="ds-label">Sunucu Adresi <span class="ds-required">*</span></label>
                                <input class="inp" type="text" id="dsHost" value="${_escapeHtml(s.host || '')}" placeholder="ftp.example.com">
                            </div>
                            <div class="ds-form-group">
                                <label class="ds-label">Port <span class="ds-required">*</span></label>
                                <input class="inp" type="number" id="dsPort" value="${s.port || 21}" placeholder="21" min="1" max="65535">
                            </div>
                        </div>
                        <div class="ds-form-group">
                            <label class="ds-label">Uzak Dizin Yolu</label>
                            <input class="inp" type="text" id="dsFilePath" value="${_escapeHtml(s.file_server_path || '')}" placeholder="/docs veya /uploads">
                        </div>
                        <div class="ds-form-row-2col">
                            <div class="ds-form-group">
                                <label class="ds-label">Kullanıcı Adı <span class="ds-required">*</span></label>
                                <input class="inp" type="text" id="dsDbUser" value="${_escapeHtml(s.db_user || '')}" placeholder="ftp_user">
                            </div>
                            <div class="ds-form-group">
                                <label class="ds-label">Şifre ${s.id ? '' : '<span class="ds-required">*</span>'}</label>
                                <input class="inp" type="password" id="dsDbPassword" placeholder="${s.id ? 'Değiştirmek için yeni şifre girin' : 'Şifre'}">
                            </div>
                        </div>
                    </div>
                `;
                break;

            case 'sharepoint':
                container.innerHTML = `
                    <div class="ds-form-section">
                        <div class="ds-section-title">
                            <i class="fa-brands fa-microsoft"></i> SharePoint Bağlantı Bilgileri
                        </div>
                        <div class="ds-form-group">
                            <label class="ds-label">Site URL <span class="ds-required">*</span></label>
                            <input class="inp" type="text" id="dsFilePath" value="${_escapeHtml(s.file_server_path || '')}" placeholder="https://company.sharepoint.com/sites/docs">
                        </div>
                        <div class="ds-form-row-2col">
                            <div class="ds-form-group">
                                <label class="ds-label">Tenant ID <span class="ds-required">*</span></label>
                                <input class="inp" type="text" id="dsHost" value="${_escapeHtml(s.host || '')}" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx">
                            </div>
                            <div class="ds-form-group">
                                <label class="ds-label">Client ID <span class="ds-required">*</span></label>
                                <input class="inp" type="text" id="dsDbUser" value="${_escapeHtml(s.db_user || '')}" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx">
                            </div>
                        </div>
                        <div class="ds-form-group">
                            <label class="ds-label">Client Secret ${s.id ? '' : '<span class="ds-required">*</span>'}</label>
                            <input class="inp" type="password" id="dsDbPassword" placeholder="${s.id ? 'Değiştirmek için yeni secret girin' : 'Client Secret'}">
                        </div>
                        <div class="ds-form-group">
                            <label class="ds-label">Doküman Kitaplığı</label>
                            <input class="inp" type="text" id="dsDbName" value="${_escapeHtml(s.db_name || '')}" placeholder="Shared Documents">
                        </div>
                    </div>
                `;
                break;

            case 'manual_file':
                container.innerHTML = `
                    <div class="ds-form-section">
                        <div class="ds-section-title">
                            <i class="fa-solid fa-file-arrow-up"></i> Manuel Dosya Ekleme
                        </div>
                        <div class="ds-info-box">
                            <i class="fa-solid fa-circle-info"></i>
                            <span>Bu kaynak tipi, Bilgi Tabanı ekranından dosya sürükle-bırak veya tıklayarak yükleme yapmanızı sağlar.</span>
                        </div>
                    </div>
                `;
                break;

            default:
                container.innerHTML = '';
        }
    }

    function handleSave(existingSource) {
        const name = document.getElementById('dsName')?.value.trim();
        const sourceType = document.getElementById('dsSourceType')?.value;
        const description = document.getElementById('dsDescription')?.value.trim();
        const isActive = document.getElementById('dsIsActive')?.checked;

        // Validasyon
        if (!name) {
            if (typeof showToast === 'function') showToast('Kaynak adı zorunludur', 'warning');
            return;
        }
        if (!sourceType) {
            if (typeof showToast === 'function') showToast('Kaynak tipi seçin', 'warning');
            return;
        }

        const companyId = _getSelectedCompanyId();
        if (!companyId) {
            if (typeof showToast === 'function') showToast('Firma seçilmedi', 'warning');
            return;
        }

        const formData = {
            company_id: parseInt(companyId),
            name,
            source_type: sourceType,
            description: description || null,
            is_active: isActive
        };

        if (existingSource?.id) formData.id = existingSource.id;

        // Source type bazlı alanlar
        if (sourceType === 'database') {
            const dbType = document.getElementById('dsDbType')?.value;
            const host = document.getElementById('dsHost')?.value.trim();
            const port = document.getElementById('dsPort')?.value;
            const dbName = document.getElementById('dsDbName')?.value.trim();
            const dbUser = document.getElementById('dsDbUser')?.value.trim();
            const dbPassword = document.getElementById('dsDbPassword')?.value;

            if (!dbType) { showToast('Veritabanı tipi seçin', 'warning'); return; }
            if (!host) { showToast('Sunucu adresi zorunludur', 'warning'); return; }
            if (!port) { showToast('Port numarası zorunludur', 'warning'); return; }
            if (!dbName) { showToast('Veritabanı adı zorunludur', 'warning'); return; }
            if (!dbUser) { showToast('Kullanıcı adı zorunludur', 'warning'); return; }
            if (!existingSource?.id && !dbPassword) { showToast('Şifre zorunludur', 'warning'); return; }

            formData.db_type = dbType;
            formData.host = host;
            formData.port = parseInt(port);
            formData.db_name = dbName;
            formData.db_user = dbUser;
            if (dbPassword) formData.db_password = dbPassword;

        } else if (sourceType === 'file_server') {
            const filePath = document.getElementById('dsFilePath')?.value.trim();
            if (!filePath) { showToast('Dosya yolu zorunludur', 'warning'); return; }
            formData.file_server_path = filePath;
            const dbUser = document.getElementById('dsDbUser')?.value.trim();
            const dbPassword = document.getElementById('dsDbPassword')?.value;
            if (dbUser) formData.db_user = dbUser;
            if (dbPassword) formData.db_password = dbPassword;
        } else if (sourceType === 'ftp') {
            const ftpProtocol = document.getElementById('dsFtpProtocol')?.value;
            const host = document.getElementById('dsHost')?.value.trim();
            const port = document.getElementById('dsPort')?.value;
            const filePath = document.getElementById('dsFilePath')?.value.trim();
            const dbUser = document.getElementById('dsDbUser')?.value.trim();
            const dbPassword = document.getElementById('dsDbPassword')?.value;

            if (!host) { showToast('Sunucu adresi zorunludur', 'warning'); return; }
            if (!port) { showToast('Port numarası zorunludur', 'warning'); return; }
            if (!dbUser) { showToast('Kullanıcı adı zorunludur', 'warning'); return; }
            if (!existingSource?.id && !dbPassword) { showToast('Şifre zorunludur', 'warning'); return; }

            formData.db_type = ftpProtocol || 'ftp';
            formData.host = host;
            formData.port = parseInt(port);
            if (filePath) formData.file_server_path = filePath;
            formData.db_user = dbUser;
            if (dbPassword) formData.db_password = dbPassword;

        } else if (sourceType === 'sharepoint') {
            const siteUrl = document.getElementById('dsFilePath')?.value.trim();
            const tenantId = document.getElementById('dsHost')?.value.trim();
            const clientId = document.getElementById('dsDbUser')?.value.trim();
            const clientSecret = document.getElementById('dsDbPassword')?.value;
            const docLibrary = document.getElementById('dsDbName')?.value.trim();

            if (!siteUrl) { showToast('Site URL zorunludur', 'warning'); return; }
            if (!tenantId) { showToast('Tenant ID zorunludur', 'warning'); return; }
            if (!clientId) { showToast('Client ID zorunludur', 'warning'); return; }
            if (!existingSource?.id && !clientSecret) { showToast('Client Secret zorunludur', 'warning'); return; }

            formData.file_server_path = siteUrl;
            formData.host = tenantId;
            formData.db_user = clientId;
            if (clientSecret) formData.db_password = clientSecret;
            if (docLibrary) formData.db_name = docLibrary;
        }

        save(formData);
    }

    // --- Connection Test ---

    async function testConnection(id, name) {
        // Test başlatma — buton spinnerı
        const btn = document.querySelector(`.ds-btn-test[data-id="${id}"]`);
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
            btn.classList.add('ds-btn-testing');
        }

        try {
            const token = localStorage.getItem('access_token') || '';
            const res = await fetch(`${API_BASE}/${id}/test-connection`, {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + token }
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'Bağlantı testi başarısız');
            }

            const result = await res.json();
            _showTestResultModal(name, result);

        } catch (error) {
            console.error('[DataSources] Test connection error:', error);
            _showTestResultModal(name, {
                success: false,
                message: error.message || 'Bağlantı testi sırasında hata oluştu'
            });
        } finally {
            // Buton state geri yükle
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-plug-circle-check"></i>';
                btn.classList.remove('ds-btn-testing');
            }
        }
    }

    function _showTestResultModal(sourceName, result) {
        // Eski modal varsa kaldır
        const existing = document.getElementById('dsTestResultModal');
        if (existing) existing.remove();

        const isSuccess = result.success;
        const statusIcon = isSuccess ? 'fa-circle-check' : 'fa-circle-xmark';
        const statusClass = isSuccess ? 'ds-test-success' : 'ds-test-fail';
        const statusText = isSuccess ? 'Bağlantı Başarılı' : 'Bağlantı Başarısız';

        // Detay satırları
        let detailRows = '';
        if (result.message) {
            detailRows += `
                <div class="ds-test-detail-row">
                    <span class="ds-test-detail-label">
                        <i class="fa-solid fa-message"></i> Mesaj
                    </span>
                    <span class="ds-test-detail-value">${_escapeHtml(result.message)}</span>
                </div>
            `;
        }
        if (result.server_info) {
            detailRows += `
                <div class="ds-test-detail-row">
                    <span class="ds-test-detail-label">
                        <i class="fa-solid fa-server"></i> Sunucu Bilgisi
                    </span>
                    <span class="ds-test-detail-value ds-test-server-info">${_escapeHtml(result.server_info)}</span>
                </div>
            `;
        }
        if (result.elapsed_ms !== undefined && result.elapsed_ms !== null) {
            detailRows += `
                <div class="ds-test-detail-row">
                    <span class="ds-test-detail-label">
                        <i class="fa-solid fa-stopwatch"></i> Süre
                    </span>
                    <span class="ds-test-detail-value">${result.elapsed_ms} ms</span>
                </div>
            `;
        }

        const modalHtml = `
            <div id="dsTestResultModal" class="modal-overlay">
                <div class="modal-box ds-test-modal-box">
                    <div class="ds-test-modal-header">
                        <button class="modal-close" id="dsTestModalClose">
                            <i class="fa-solid fa-xmark"></i>
                        </button>
                    </div>
                    <div class="ds-test-modal-body">
                        <div class="ds-test-icon-wrap ${statusClass}">
                            <i class="fa-solid ${statusIcon}"></i>
                        </div>
                        <h3 class="ds-test-title ${statusClass}">${statusText}</h3>
                        <p class="ds-test-source-name">${_escapeHtml(sourceName)}</p>
                        <div class="ds-test-details">
                            ${detailRows}
                        </div>
                    </div>
                    <div class="ds-test-modal-footer">
                        <button class="btn primary" id="dsTestModalOk">
                            <i class="fa-solid fa-check"></i> Tamam
                        </button>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHtml);

        // Event listeners
        const closeTest = () => {
            const m = document.getElementById('dsTestResultModal');
            if (m) {
                m.classList.add('ds-test-modal-closing');
                setTimeout(() => m.remove(), 200);
            }
        };
        document.getElementById('dsTestModalClose').addEventListener('click', closeTest);
        document.getElementById('dsTestModalOk').addEventListener('click', closeTest);

        // ESC ile kapat
        const escHandler = (e) => {
            if (e.key === 'Escape') {
                closeTest();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);

        // Animasyonlu giriş
        requestAnimationFrame(() => {
            const modal = document.getElementById('dsTestResultModal');
            if (modal) modal.classList.add('ds-test-modal-visible');
        });
    }

    // --- Helpers ---

    function _getSelectedCompanyId() {
        const sel = document.getElementById('globalCompanySelect');
        return sel ? sel.value : null;
    }

    function _escapeHtml(str) {
        if (!str) return '';
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // --- Public API ---
    return { load, openModal, deleteSource, closeModal, testConnection };
})();
