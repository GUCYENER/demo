/* ─────────────────────────────────────────────
   VYRA — Data Sources Module
   v2.55.0 · Veri kaynakları yönetimi (Parametreler sekmesi)
   ───────────────────────────────────────────── */

window.DataSourcesModule = (function () {
    'use strict';

    const API_BASE = (window.API_BASE_URL || '') + '/api/data-sources';
    // v3.34.0: vyraFetch /api prefix'i kendi ekliyor — path bu prefix'ten başlar.
    const VF_BASE = '/data-sources';
    let sources = [];

    // v3.37.7 → v3.37.8 post-review (finding N3): defense-in-depth.
    // BE SSOT: `app/services/db_smart/dialect_constants.HOST_VALUE_CANARIES`.
    // **MANUEL SYNC GEREKLİ** — BE listesi büyürse bu array da güncellenmeli;
    // BE primary validator olduğu için drift FE'de zararsız sessiz silent-pass
    // demek (UI'da FE uyarısı yok, BE 422 döner). Sonraki sprintte GET
    // /api/db-smart/canary-set veya build-time inject ile auto-sync planlanır.
    const _HOST_VALUE_CANARIES = [
        'host', 'port', 'db_type', 'db_name', 'db_user',
        'db_password', 'db_password_encrypted', 'id',
    ];
    function _isInvalidHostValue(v) {
        if (typeof v !== 'string') return false;
        return _HOST_VALUE_CANARIES.indexOf(v.trim().toLowerCase()) !== -1;
    }

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
            // v3.34.0: vyraFetch — Auth + JSON + friendly error helper'da.
            let path = VF_BASE;
            if (companyId) path += `?company_id=${companyId}`;
            sources = await window.vyraFetch(path);
            renderGrid();
        } catch (error) {
            console.error('[DataSources] Load error:', error);
            sources = [];
            renderGrid();
        }
    }

    async function save(formData) {
        try {
            const isEdit = !!formData.id;
            const path = isEdit ? `${VF_BASE}/${formData.id}` : VF_BASE;
            const method = isEdit ? 'PUT' : 'POST';

            const body = { ...formData };
            delete body.id; // ID body'de olmamalı

            // v3.34.0: vyraFetch — Auth + JSON + friendly error helper'da.
            const result = await window.vyraFetch(path, { method, body });
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
                    // v3.34.0: vyraFetch — Auth + JSON + friendly error helper'da.
                    await window.vyraFetch(`${VF_BASE}/${id}`, { method: 'DELETE' });
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
        // Tablo Etiketleme butonu
        grid.querySelectorAll('.ds-btn-enrich').forEach(btn => {
            btn.addEventListener('click', () => {
                if (window.DSEnrichmentModule) {
                    DSEnrichmentModule.openPanel(parseInt(btn.dataset.id));
                }
            });
        });
        // v3.27.0 — DB Öğrenme Loop butonu
        grid.querySelectorAll('.ds-btn-dbloop').forEach(btn => {
            btn.addEventListener('click', () => {
                if (window.DSLearningModule && DSLearningModule.openDbLearningLoop) {
                    DSLearningModule.openDbLearningLoop(parseInt(btn.dataset.id), btn.dataset.name);
                }
            });
        });
        // Yetki butonu (v3.17.0)
        grid.querySelectorAll('.ds-btn-perm').forEach(btn => {
            btn.addEventListener('click', () => {
                openPermissionModal(parseInt(btn.dataset.id), btn.dataset.name);
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
                        <button class="ds-btn-test" data-id="${source.id}" data-name="${_escapeHtml(source.name)}" aria-label="Bağlantı testi: ${_escapeHtml(source.name)}" data-tooltip="Bağlantı Testi">
                            <i class="fa-solid fa-plug-circle-check"></i>
                        </button>
                        ${source.source_type === 'database' ? `<button class="ds-card-discover-btn ds-btn-discover" data-id="${source.id}" data-name="${_escapeHtml(source.name)}" aria-label="DB keşfet: ${_escapeHtml(source.name)}" data-tooltip="DB Keşfet">
                            <i class="fa-solid fa-magnifying-glass-chart"></i>
                        </button>
                        <button class="ds-card-history-btn ds-btn-history" data-id="${source.id}" data-name="${_escapeHtml(source.name)}" aria-label="Öğrenme geçmişi: ${_escapeHtml(source.name)}" data-tooltip="Öğrenme Geçmişi">
                            <i class="fa-solid fa-brain"></i>
                        </button>
                        <button class="ds-card-enrich-btn ds-btn-enrich" data-id="${source.id}" data-name="${_escapeHtml(source.name)}" aria-label="Tablo etiketleme: ${_escapeHtml(source.name)}" data-tooltip="Tablo Etiketleme">
                            <i class="fa-solid fa-tags"></i>
                        </button>
                        <button class="ds-card-dbloop-btn ds-btn-dbloop" data-id="${source.id}" data-name="${_escapeHtml(source.name)}" aria-label="DB öğrenme loop: ${_escapeHtml(source.name)}" data-tooltip="DB Öğrenme Loop (v3.27)">
                            <i class="fa-solid fa-robot"></i>
                        </button>` : ''}
                        <button class="ds-btn-edit" data-id="${source.id}" aria-label="Kaynağı düzenle: ${_escapeHtml(source.name)}" data-tooltip="Düzenle">
                            <i class="fa-solid fa-pen"></i>
                        </button>
                        <button class="ds-btn-delete" data-id="${source.id}" data-name="${_escapeHtml(source.name)}" aria-label="Kaynağı sil: ${_escapeHtml(source.name)}" data-tooltip="Sil">
                            <i class="fa-solid fa-trash-alt"></i>
                        </button>
                        <button class="ds-btn-perm" data-id="${source.id}" data-name="${_escapeHtml(source.name)}" aria-label="Yetkilendirme: ${_escapeHtml(source.name)}" data-tooltip="Yetkilendirme">
                            <i class="fa-solid fa-shield-halved"></i>
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

        const _dsModalTitleId = 'dsModalTitle';
        const _dsModalReturnFocus = document.activeElement;
        const modalHtml = `
            <div id="dsModal" class="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="${_dsModalTitleId}">
                <div class="modal-box ds-modal-box">
                    <div class="modal-header">
                        <h3 id="${_dsModalTitleId}"><i class="fa-solid fa-plug-circle-plus"></i> ${title}</h3>
                        <button class="modal-close" id="dsModalClose" aria-label="Kapat" data-tooltip="Kapat (Esc)"><i class="fa-solid fa-xmark"></i></button>
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
        const _overlayEl = document.getElementById('dsModal');
        const _closeAndReturnFocus = () => {
            closeModal();
            if (_dsModalReturnFocus && typeof _dsModalReturnFocus.focus === 'function') {
                try { _dsModalReturnFocus.focus(); } catch (_) {}
            }
        };
        document.getElementById('dsModalClose').addEventListener('click', _closeAndReturnFocus);
        document.getElementById('dsModalCancel').addEventListener('click', _closeAndReturnFocus);
        document.getElementById('dsModalSave').addEventListener('click', () => handleSave(source));

        // Click-outside → kapat
        _overlayEl.addEventListener('mousedown', (e) => {
            if (e.target === _overlayEl) _closeAndReturnFocus();
        });

        // ESC ile kapat
        const escHandler = (e) => {
            if (e.key === 'Escape') {
                _closeAndReturnFocus();
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
            if (_isInvalidHostValue(host)) { showToast('Sunucu adresi kolon adı olamaz (örn. localhost, 10.0.0.5, mssql.firma.local)', 'warning'); return; }
            if (!port) { showToast('Port numarası zorunludur', 'warning'); return; }
            if (!dbName) { showToast('Veritabanı adı zorunludur', 'warning'); return; }
            // v3.37.8 bulgu #3: scope genişletme — diğer credential field'lar
            if (_isInvalidHostValue(dbName)) { showToast('Veritabanı adı kolon adı olamaz (gerçek bir DB adı girin)', 'warning'); return; }
            if (!dbUser) { showToast('Kullanıcı adı zorunludur', 'warning'); return; }
            if (_isInvalidHostValue(dbUser)) { showToast('Kullanıcı adı kolon adı olamaz (gerçek bir DB kullanıcısı girin)', 'warning'); return; }
            if (!existingSource?.id && !dbPassword) { showToast('Şifre zorunludur', 'warning'); return; }
            if (dbPassword && _isInvalidHostValue(dbPassword)) { showToast('Şifre kolon adı olamaz — gerçek bir parola girin', 'warning'); return; }

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
            if (_isInvalidHostValue(host)) { showToast('Sunucu adresi kolon adı olamaz (örn. ftp.firma.com, 10.0.0.5)', 'warning'); return; }
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
            // v3.37.8 bulgu #12: SharePoint mesajını semantik düzelt — kanary kontrolü
            // DB-host placeholder'larını (literal "host", "port" vb.) yakalar; SharePoint
            // tenant'ı için legitimacy değil sadece kötü-placeholder reddi.
            if (_isInvalidHostValue(tenantId)) { showToast('Tenant ID kolon adı/placeholder olamaz — gerçek tenant (GUID veya *.onmicrosoft.com) girin', 'warning'); return; }
            if (!clientId) { showToast('Client ID zorunludur', 'warning'); return; }
            if (_isInvalidHostValue(clientId)) { showToast('Client ID kolon adı/placeholder olamaz — gerçek Azure AD app ID girin', 'warning'); return; }
            if (!existingSource?.id && !clientSecret) { showToast('Client Secret zorunludur', 'warning'); return; }
            if (clientSecret && _isInvalidHostValue(clientSecret)) { showToast('Client Secret kolon adı olamaz — gerçek Azure AD app secret girin', 'warning'); return; }

            formData.file_server_path = siteUrl;
            formData.host = tenantId;
            formData.db_user = clientId;
            if (clientSecret) formData.db_password = clientSecret;
            if (docLibrary) formData.db_name = docLibrary;
        }

        save(formData);
    }

    // --- Permission Modal (v3.17.0) ---

    let permState = {
        sourceId: null,
        sourceName: '',
        activeTab: 'user',     // 'user' | 'org'
        users: [],
        orgs: [],
        viewUserIds: new Set(),
        viewOrgIds: new Set(),
        execUserIds: new Set(),
        execOrgIds: new Set(),
        searchText: '',
        // v3.38.0: per-subject tablo kapsamı. Anahtar: 'user:5' | 'org:3'
        //   { mode:'all'|'restricted', tables:Set<'schema table'> }
        scopeBySubject: {},
        // schema-tree cache (modal açılışında bir kez çekilir)
        schemaTree: null,            // { discovered:bool, schemas:[{schema, tables:[]}] }
        schemaTreeLoaded: false,
        // açık kapsam panelleri (subjectKey) + açık akordion (subjectKey schema)
        scopeOpen: new Set(),
        accordionOpen: new Set(),
        scopeSearch: {},             // subjectKey -> arama metni
    };

    // table key helper — schema + table'ı ayraçla birleştir.
    // v3.38.2: ayraç = U+001F (unit separator). Boşluk/nokta gibi karakterler DB
    // tanımlayıcılarında (tırnaklı identifier) geçebilir → ÇAKIŞIR; U+001F gerçek
    // tanımlayıcılarda bulunmaz. join (_tblKey) ve split AYNI sabiti kullanır →
    // ayraç sapması imkânsız. (Önceki NUL 0x00 ayracı PG'ye gidince 500 veriyordu.)
    const _TBL_SEP = '\u001f';
    function _tblKey(schema, table) { return (schema || '') + _TBL_SEP + (table || ''); }
    function _subjectKey(type, id) { return type + ':' + id; }

    async function openPermissionModal(sourceId, sourceName) {
        permState.sourceId = sourceId;
        permState.sourceName = sourceName || '';
        permState.activeTab = 'user';
        permState.searchText = '';
        permState.users = [];
        permState.orgs = [];
        permState.viewUserIds = new Set();
        permState.viewOrgIds = new Set();
        permState.execUserIds = new Set();
        permState.execOrgIds = new Set();
        permState.scopeBySubject = {};
        permState.schemaTree = null;
        permState.schemaTreeLoaded = false;
        permState.scopeOpen = new Set();
        permState.accordionOpen = new Set();
        permState.scopeSearch = {};

        _closePermissionModal();
        // A11y: kapanınca odağı buraya geri ver
        permState._returnFocusEl = document.activeElement;

        const titleId = 'dsPermModalTitle';
        const modalHtml = `
            <div id="dsPermModal" class="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="${titleId}">
                <div class="modal-box ds-perm-modal-box">
                    <div class="modal-header">
                        <h3 id="${titleId}"><i class="fa-solid fa-shield-halved"></i> Yetkilendirme — ${_escapeHtml(sourceName || '')}</h3>
                        <button class="modal-close" id="dsPermClose" aria-label="Kapat" data-tooltip="Kapat (Esc)"><i class="fa-solid fa-xmark"></i></button>
                    </div>
                    <div class="modal-body ds-perm-modal-body">
                        <div class="ds-perm-tabs" role="tablist">
                            <button class="ds-perm-tab active" data-tab="user" role="tab" aria-selected="true">
                                <i class="fa-solid fa-user"></i> Kullanıcılar
                            </button>
                            <button class="ds-perm-tab" data-tab="org" role="tab" aria-selected="false">
                                <i class="fa-solid fa-users"></i> Org Grupları
                            </button>
                        </div>
                        <div class="ds-perm-search">
                            <i class="fa-solid fa-search"></i>
                            <input type="text" id="dsPermSearch" placeholder="Ara..." aria-label="Kullanıcı veya org ara">
                            <button type="button" id="dsPermSearchClear" class="ds-search-clear" aria-label="Aramayı temizle" data-tooltip="Temizle" hidden><i class="fa-solid fa-xmark" aria-hidden="true"></i></button>
                        </div>
                        <div class="ds-perm-list" id="dsPermList">
                            <div class="ds-perm-loading">
                                <i class="fa-solid fa-spinner fa-spin"></i> Yükleniyor...
                            </div>
                        </div>
                        <div class="ds-perm-legend">
                            <span><i class="fa-solid fa-eye"></i> Görüntüleme</span>
                            <span><i class="fa-solid fa-bolt"></i> Çalıştırma (SQL)</span>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn" id="dsPermCancel">İptal</button>
                        <button class="btn primary" id="dsPermSave">
                            <i class="fa-solid fa-save"></i> Kaydet
                        </button>
                    </div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', modalHtml);

        const overlay = document.getElementById('dsPermModal');
        // Click-outside → kapat
        overlay.addEventListener('mousedown', (e) => {
            if (e.target === overlay) _closePermissionModal();
        });
        // ESC → kapat
        permState._escHandler = (e) => {
            if (e.key === 'Escape') _closePermissionModal();
        };
        document.addEventListener('keydown', permState._escHandler);

        document.getElementById('dsPermClose').addEventListener('click', _closePermissionModal);
        document.getElementById('dsPermCancel').addEventListener('click', _closePermissionModal);
        document.getElementById('dsPermSave').addEventListener('click', _savePermissions);

        // İlk açılışta arama input'una odak
        setTimeout(() => {
            const search = document.getElementById('dsPermSearch');
            if (search) search.focus();
        }, 50);
        document.querySelectorAll('#dsPermModal .ds-perm-tab').forEach(t => {
            t.addEventListener('click', () => {
                permState.activeTab = t.dataset.tab;
                document.querySelectorAll('#dsPermModal .ds-perm-tab').forEach(x => x.classList.toggle('active', x === t));
                _renderPermissionList();
            });
        });
        const _permSearchInput = document.getElementById('dsPermSearch');
        const _permSearchClear = document.getElementById('dsPermSearchClear');
        const _syncPermClear = () => {
            if (_permSearchClear) _permSearchClear.hidden = !(_permSearchInput && _permSearchInput.value);
        };
        _permSearchInput.addEventListener('input', (e) => {
            permState.searchText = e.target.value.toLowerCase();
            _syncPermClear();
            _renderPermissionList();
        });
        if (_permSearchClear) {
            _permSearchClear.addEventListener('click', () => {
                _permSearchInput.value = '';
                permState.searchText = '';
                _syncPermClear();
                _renderPermissionList();
                _permSearchInput.focus();
            });
        }

        // Veri yükle (subjects + current permissions paralel)
        try {
            // v3.34.0: vyraFetch — Auth + JSON + friendly error helper'da.
            const companyId = _getSelectedCompanyId();
            const subjectsPath = `${VF_BASE}/permissions/subjects${companyId ? '?company_id=' + companyId : ''}`;
            const [subjects, perms, tree] = await Promise.all([
                window.vyraFetch(subjectsPath),
                window.vyraFetch(`${VF_BASE}/${sourceId}/permissions`),
                // schema-tree başarısızsa modal yine açılsın → catch ile null'a düş
                window.vyraFetch(`${VF_BASE}/${sourceId}/schema-tree`).catch(() => null)
            ]);
            permState.users = subjects.users || [];
            permState.orgs = subjects.orgs || [];
            permState.viewUserIds = new Set(perms.user_ids || []);
            permState.viewOrgIds = new Set(perms.org_ids || []);
            permState.execUserIds = new Set(perms.can_execute_user_ids || []);
            permState.execOrgIds = new Set(perms.can_execute_org_ids || []);

            // v3.38.0: schema-tree cache + discovered durumu
            permState.schemaTree = (tree && tree.success && tree.discovered)
                ? { discovered: true, schemas: Array.isArray(tree.schemas) ? tree.schemas : [] }
                : { discovered: false, schemas: [] };
            permState.schemaTreeLoaded = true;

            // v3.38.0: scopes → scopeBySubject (Set'e dönüştür)
            (perms.scopes || []).forEach(sc => {
                if (!sc || (sc.subject_type !== 'user' && sc.subject_type !== 'org')) return;
                const sid = parseInt(sc.subject_id, 10);
                if (Number.isNaN(sid)) return;
                const tbls = new Set();
                (sc.tables || []).forEach(t => {
                    if (t && typeof t.table === 'string') tbls.add(_tblKey(t.schema, t.table));
                });
                permState.scopeBySubject[_subjectKey(sc.subject_type, sid)] = {
                    mode: sc.scope_mode === 'restricted' ? 'restricted' : 'all',
                    tables: tbls,
                };
            });
            _renderPermissionList();
        } catch (error) {
            console.error('[DataSources] Permission modal load error:', error);
            if (typeof showToast === 'function') showToast(error.message || 'Yetki ekranı yüklenemedi', 'error');
            _closePermissionModal();
        }
    }

    function _closePermissionModal() {
        const m = document.getElementById('dsPermModal');
        if (m) m.remove();
        if (permState._escHandler) {
            document.removeEventListener('keydown', permState._escHandler);
            permState._escHandler = null;
        }
        // A11y: return-focus
        if (permState._returnFocusEl && typeof permState._returnFocusEl.focus === 'function') {
            try { permState._returnFocusEl.focus(); } catch (_) {}
            permState._returnFocusEl = null;
        }
    }

    function _renderPermissionList() {
        const container = document.getElementById('dsPermList');
        if (!container) return;
        const isUserTab = permState.activeTab === 'user';
        const items = isUserTab ? permState.users : permState.orgs;
        const viewSet = isUserTab ? permState.viewUserIds : permState.viewOrgIds;
        const execSet = isUserTab ? permState.execUserIds : permState.execOrgIds;
        const q = permState.searchText;

        const filtered = items.filter(it => {
            if (!q) return true;
            if (isUserTab) {
                return (it.full_name || '').toLowerCase().includes(q)
                    || (it.username || '').toLowerCase().includes(q)
                    || (it.email || '').toLowerCase().includes(q);
            }
            return (it.org_code || '').toLowerCase().includes(q)
                || (it.org_name || '').toLowerCase().includes(q);
        });

        if (filtered.length === 0) {
            container.innerHTML = `<div class="ds-perm-empty"><i class="fa-solid fa-folder-open"></i><p>Kayıt bulunamadı</p></div>`;
            return;
        }

        const subjType = isUserTab ? 'user' : 'org';
        container.innerHTML = filtered.map(it => {
            const label = isUserTab
                ? `${_escapeHtml(it.full_name || it.username || '')} <span class="ds-perm-sub">${_escapeHtml(it.email || '')}</span>`
                : `<span class="ds-perm-code">${_escapeHtml(it.org_code || '')}</span> ${_escapeHtml(it.org_name || '')}`;
            const vChecked = viewSet.has(it.id) ? 'checked' : '';
            const eChecked = execSet.has(it.id) ? 'checked' : '';
            const scopeBlock = viewSet.has(it.id)
                ? _renderScopeBlock(subjType, it.id)
                : '';
            return `
                <div class="ds-perm-row-wrap">
                    <div class="ds-perm-row">
                        <div class="ds-perm-label">${label}</div>
                        <div class="ds-perm-controls">
                            <label class="ds-perm-chk" title="Görüntüleme">
                                <input type="checkbox" class="ds-perm-view" data-id="${it.id}" ${vChecked}>
                                <i class="fa-solid fa-eye"></i>
                            </label>
                            <label class="ds-perm-chk" title="Çalıştırma">
                                <input type="checkbox" class="ds-perm-exec" data-id="${it.id}" ${eChecked}>
                                <i class="fa-solid fa-bolt"></i>
                            </label>
                        </div>
                    </div>
                    ${scopeBlock}
                </div>
            `;
        }).join('');

        container.querySelectorAll('.ds-perm-view').forEach(cb => {
            cb.addEventListener('change', (e) => {
                // FIX (v3.27.5): checkbox.value boş ise tarayıcı "on" döner → parseInt("on")=NaN
                // → set NaN birikir → JSON.stringify(null) → backend 422 "Input should be a valid integer".
                // Sadece data-id güvenilir kaynak.
                const id = parseInt(e.target.dataset.id, 10);
                if (Number.isNaN(id)) return;
                const set = isUserTab ? permState.viewUserIds : permState.viewOrgIds;
                const execS = isUserTab ? permState.execUserIds : permState.execOrgIds;
                if (e.target.checked) {
                    set.add(id);
                } else {
                    set.delete(id);
                    execS.delete(id); // view kapatılırsa exec da düşer
                    // v3.38.0: view kapanınca subject kapsamı sıfırlanır (all)
                    const sk = _subjectKey(isUserTab ? 'user' : 'org', id);
                    delete permState.scopeBySubject[sk];
                    permState.scopeOpen.delete(sk);
                    Object.keys(permState.scopeSearch).forEach(k => {
                        if (k === sk) delete permState.scopeSearch[k];
                    });
                }
                // scope bloğunu göster/gizle için satır listesini yeniden çiz
                _renderPermissionList();
            });
        });
        container.querySelectorAll('.ds-perm-exec').forEach(cb => {
            cb.addEventListener('change', (e) => {
                const id = parseInt(e.target.dataset.id, 10);
                if (Number.isNaN(id)) return;
                const set = isUserTab ? permState.execUserIds : permState.execOrgIds;
                const viewS = isUserTab ? permState.viewUserIds : permState.viewOrgIds;
                if (e.target.checked) {
                    set.add(id);
                    viewS.add(id); // exec açılırsa view zorunlu
                    // view yeni açıldı → scope bloğunu göstermek için yeniden çiz
                    _renderPermissionList();
                } else {
                    set.delete(id);
                }
            });
        });

        _bindScopeEvents(container, subjType);
    }

    // v3.38.0: bir subject için tablo-kapsamı bloğu (toggle + akordion)
    function _renderScopeBlock(subjType, subjectId) {
        const sk = _subjectKey(subjType, subjectId);
        const sc = permState.scopeBySubject[sk] || { mode: 'all', tables: new Set() };
        const mode = sc.mode === 'restricted' ? 'restricted' : 'all';
        const tree = permState.schemaTree || { discovered: false, schemas: [] };
        const radioName = `dsScopeMode_${subjType}_${subjectId}`;

        const toggle = `
            <div class="ds-scope-toggle" role="radiogroup" aria-label="Tablo kapsamı">
                <label class="ds-scope-opt">
                    <input type="radio" name="${radioName}" class="ds-scope-mode" data-sk="${sk}" value="all" ${mode === 'all' ? 'checked' : ''}>
                    <span>Tüm tablolar</span>
                </label>
                <label class="ds-scope-opt">
                    <input type="radio" name="${radioName}" class="ds-scope-mode" data-sk="${sk}" value="restricted" ${mode === 'restricted' ? 'checked' : ''}>
                    <span>Seçili tablolar</span>
                </label>
            </div>
        `;

        if (mode !== 'restricted') {
            return `<div class="ds-perm-scope" data-sk="${sk}">${toggle}</div>`;
        }

        // restricted → akordion gövdesi
        if (!tree.discovered || !tree.schemas.length) {
            return `
                <div class="ds-perm-scope" data-sk="${sk}">
                    ${toggle}
                    <div class="ds-scope-empty">
                        <i class="fa-solid fa-circle-info" aria-hidden="true"></i>
                        Önce kaynağı keşfedin (Adım 2)
                    </div>
                </div>
            `;
        }

        const q = (permState.scopeSearch[sk] || '').toLowerCase();
        const selected = sc.tables;
        // v3.43.2: "Seçilenleri Göster" — yalnız seçili tabloları listele.
        const onlySel = !!(permState.scopeOnlySelected && permState.scopeOnlySelected[sk]);
        const accParts = [];
        let visibleCount = 0;

        tree.schemas.forEach((schObj, idx) => {
            const schema = schObj.schema || '';
            const allTables = Array.isArray(schObj.tables) ? schObj.tables : [];
            let tables = q ? allTables.filter(t => (t || '').toLowerCase().includes(q)) : allTables;
            if (onlySel) tables = tables.filter(t => selected.has(_tblKey(schema, t)));
            if (!tables.length) return;
            visibleCount += tables.length;

            const accKey = sk + '|' + schema;
            const isOpen = permState.accordionOpen.has(accKey) || !!q || onlySel;
            const panelId = `dsScopeAcc_${subjType}_${subjectId}_${idx}`;
            const headerId = `dsScopeAccHdr_${subjType}_${subjectId}_${idx}`;
            const schemaLabel = schema === '' ? '(varsayılan şema)' : _escapeHtml(schema);
            const selInSchema = allTables.filter(t => selected.has(_tblKey(schema, t))).length;

            const rows = tables.map(t => {
                const key = _tblKey(schema, t);
                const checked = selected.has(key) ? 'checked' : '';
                return `
                    <label class="ds-scope-tbl">
                        <input type="checkbox" class="ds-scope-tbl-chk" data-sk="${sk}" data-key="${_escapeHtml(key)}" ${checked}>
                        <span>${_escapeHtml(t)}</span>
                    </label>
                `;
            }).join('');

            accParts.push(`
                <div class="ds-scope-acc${isOpen ? ' is-open' : ''}" data-acc="${_escapeHtml(accKey)}">
                    <div class="ds-scope-acc-head">
                        <button type="button" class="ds-scope-acc-toggle" id="${headerId}"
                            aria-expanded="${isOpen ? 'true' : 'false'}" aria-controls="${panelId}"
                            data-acc="${_escapeHtml(accKey)}">
                            <span class="ds-scope-acc-caret" aria-hidden="true">▸</span>
                            <span class="ds-scope-acc-title">${schemaLabel}</span>
                            <span class="ds-scope-acc-count">${selInSchema}/${allTables.length}</span>
                        </button>
                        <button type="button" class="ds-scope-acc-all" data-sk="${sk}" data-schema-idx="${idx}"
                            aria-label="${schemaLabel} şemasındaki tüm tabloları seç/temizle"
                            data-tooltip="Tümünü seç / temizle">
                            <i class="fa-solid fa-list-check" aria-hidden="true"></i>
                        </button>
                    </div>
                    <div class="ds-scope-acc-body" id="${panelId}" role="region" aria-labelledby="${headerId}" ${isOpen ? '' : 'hidden'}>
                        ${rows}
                    </div>
                </div>
            `);
        });

        const _scopeQ = permState.scopeSearch[sk] || '';
        const searchBox = `
            <div class="ds-scope-search">
                <i class="fa-solid fa-search" aria-hidden="true"></i>
                <input type="text" class="ds-scope-search-input" data-sk="${sk}"
                    value="${_escapeHtml(_scopeQ)}"
                    placeholder="Tablo ara..." aria-label="Tablo ara">
                <button type="button" class="ds-search-clear ds-scope-search-clear" data-sk="${sk}"
                    aria-label="Aramayı temizle" data-tooltip="Temizle" ${_scopeQ ? '' : 'hidden'}>
                    <i class="fa-solid fa-xmark" aria-hidden="true"></i>
                </button>
            </div>
        `;

        // v3.43.2: global "Tümünü Temizle" + "Seçilenleri Göster" kontrolleri (HEBE)
        const selectedTotal = (selected instanceof Set) ? selected.size : 0;
        const controlsBar = `
            <div class="ds-scope-controls">
                <label class="ds-scope-only-selected" data-tooltip="Yalnız seçili tabloları göster">
                    <input type="checkbox" class="ds-scope-only-selected-chk" data-sk="${sk}" ${onlySel ? 'checked' : ''}>
                    <span>Seçilenleri Göster (${selectedTotal})</span>
                </label>
                <button type="button" class="ds-scope-clear-all" data-sk="${sk}"
                    aria-label="Tüm seçili tabloları temizle" data-tooltip="Tüm seçimleri temizle"
                    ${selectedTotal ? '' : 'disabled'}>
                    <i class="fa-solid fa-broom" aria-hidden="true"></i> Tümünü Temizle
                </button>
            </div>
        `;

        const emptyMsg = onlySel
            ? `<div class="ds-scope-empty"><i class="fa-solid fa-folder-open" aria-hidden="true"></i> Seçili tablo yok</div>`
            : `<div class="ds-scope-empty"><i class="fa-solid fa-folder-open" aria-hidden="true"></i> Eşleşen tablo yok</div>`;
        const body = accParts.length ? accParts.join('') : emptyMsg;

        return `
            <div class="ds-perm-scope" data-sk="${sk}">
                ${toggle}
                ${searchBox}
                ${controlsBar}
                <div class="ds-scope-tree">${body}</div>
            </div>
        `;
    }

    // Tek-tablo toggle sonrası şema sayaç rozetlerini (n/total) re-render'sız güncelle.
    function _updateScopeCounts(container, sk) {
        const cur = permState.scopeBySubject[sk];
        const sel = (cur && cur.tables instanceof Set) ? cur.tables : new Set();
        const tree = permState.schemaTree || { schemas: [] };
        (tree.schemas || []).forEach(schObj => {
            const schema = schObj.schema || '';
            const accKey = sk + '|' + schema;
            const all = Array.isArray(schObj.tables) ? schObj.tables : [];
            container.querySelectorAll('.ds-scope-acc').forEach(acc => {
                if (acc.getAttribute('data-acc') !== accKey) return;
                const n = all.filter(t => sel.has(_tblKey(schema, t))).length;
                const badge = acc.querySelector('.ds-scope-acc-count');
                if (badge) badge.textContent = `${n}/${all.length}`;
            });
        });
    }

    function _bindScopeEvents(container, subjType) {
        // mode radio
        container.querySelectorAll('.ds-scope-mode').forEach(r => {
            r.addEventListener('change', (e) => {
                const sk = e.target.dataset.sk;
                if (!sk) return;
                const cur = permState.scopeBySubject[sk] || { mode: 'all', tables: new Set() };
                cur.mode = e.target.value === 'restricted' ? 'restricted' : 'all';
                if (!(cur.tables instanceof Set)) cur.tables = new Set();
                permState.scopeBySubject[sk] = cur;
                if (cur.mode === 'restricted') permState.scopeOpen.add(sk);
                _renderPermissionList();
            });
        });

        // akordion toggle (click)
        container.querySelectorAll('.ds-scope-acc-toggle').forEach(btn => {
            btn.addEventListener('click', () => {
                const acc = btn.dataset.acc;
                if (!acc) return;
                if (permState.accordionOpen.has(acc)) permState.accordionOpen.delete(acc);
                else permState.accordionOpen.add(acc);
                _renderPermissionList();
            });
            btn.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
                    e.preventDefault();
                    btn.click();
                }
            });
        });

        // tablo checkbox — IN-PLACE güncelleme (re-render YOK).
        // Önceki full re-render, native checkbox toggle'ı ile çakışıp işaretin
        // görünmemesine yol açabiliyordu; burada sadece state + sayaç güncellenir,
        // checkbox'ın native checked durumu olduğu gibi kalır.
        container.querySelectorAll('.ds-scope-tbl-chk').forEach(cb => {
            cb.addEventListener('change', (e) => {
                const sk = e.target.dataset.sk;
                const key = e.target.dataset.key;
                if (!sk || !key) return;
                const cur = permState.scopeBySubject[sk] || { mode: 'restricted', tables: new Set() };
                if (!(cur.tables instanceof Set)) cur.tables = new Set(Array.isArray(cur.tables) ? cur.tables : []);
                if (e.target.checked) cur.tables.add(key);
                else cur.tables.delete(key);
                cur.mode = 'restricted';
                permState.scopeBySubject[sk] = cur;
                _updateScopeCounts(container, sk);
            });
        });

        // şema "tümünü seç/temizle"
        container.querySelectorAll('.ds-scope-acc-all').forEach(btn => {
            btn.addEventListener('click', () => {
                const sk = btn.dataset.sk;
                const idx = parseInt(btn.dataset.schemaIdx, 10);
                const tree = permState.schemaTree;
                if (!sk || Number.isNaN(idx) || !tree || !tree.schemas[idx]) return;
                const schObj = tree.schemas[idx];
                const schema = schObj.schema || '';
                const tables = Array.isArray(schObj.tables) ? schObj.tables : [];
                const cur = permState.scopeBySubject[sk] || { mode: 'restricted', tables: new Set() };
                if (!(cur.tables instanceof Set)) cur.tables = new Set();
                const allSelected = tables.every(t => cur.tables.has(_tblKey(schema, t)));
                tables.forEach(t => {
                    const k = _tblKey(schema, t);
                    if (allSelected) cur.tables.delete(k);
                    else cur.tables.add(k);
                });
                cur.mode = 'restricted';
                permState.scopeBySubject[sk] = cur;
                _renderPermissionList();
            });
        });

        // scope arama temizle (X)
        container.querySelectorAll('.ds-scope-search-clear').forEach(btn => {
            btn.addEventListener('click', () => {
                const sk = btn.dataset.sk;
                if (!sk) return;
                delete permState.scopeSearch[sk];
                _renderPermissionList();
                const again = container.querySelector(`.ds-scope-search-input[data-sk="${sk}"]`);
                if (again) again.focus();
            });
        });

        // arama (re-render odak kaybettirmesin → değeri state'e yaz, sonra odağı geri al)
        container.querySelectorAll('.ds-scope-search-input').forEach(inp => {
            inp.addEventListener('input', (e) => {
                const sk = e.target.dataset.sk;
                if (!sk) return;
                permState.scopeSearch[sk] = e.target.value;
                const caret = e.target.selectionStart;
                _renderPermissionList();
                const again = container.querySelector(`.ds-scope-search-input[data-sk="${sk}"]`);
                if (again) {
                    again.focus();
                    try { again.setSelectionRange(caret, caret); } catch (_) {}
                }
            });
        });

        // v3.43.2: "Seçilenleri Göster" toggle — yalnız seçili tabloları listele
        container.querySelectorAll('.ds-scope-only-selected-chk').forEach(cb => {
            cb.addEventListener('change', (e) => {
                const sk = e.target.dataset.sk;
                if (!sk) return;
                if (!permState.scopeOnlySelected) permState.scopeOnlySelected = {};
                permState.scopeOnlySelected[sk] = !!e.target.checked;
                _renderPermissionList();
            });
        });

        // v3.43.2: "Tümünü Temizle" — bu subject'in TÜM seçili tablolarını temizle (mode restricted kalır)
        container.querySelectorAll('.ds-scope-clear-all').forEach(btn => {
            btn.addEventListener('click', () => {
                const sk = btn.dataset.sk;
                if (!sk) return;
                const cur = permState.scopeBySubject[sk] || { mode: 'restricted', tables: new Set() };
                if (!(cur.tables instanceof Set)) cur.tables = new Set();
                cur.tables.clear();
                cur.mode = 'restricted';
                permState.scopeBySubject[sk] = cur;
                // seçim kalmadı → "Seçilenleri Göster" açıksa kapat (boş liste göstermesin)
                if (permState.scopeOnlySelected) permState.scopeOnlySelected[sk] = false;
                _renderPermissionList();
            });
        });
    }

    async function _savePermissions() {
        const saveBtn = document.getElementById('dsPermSave');
        const originalHtml = saveBtn ? saveBtn.innerHTML : '';
        if (saveBtn) {
            saveBtn.disabled = true;
            saveBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Kaydediliyor...';
        }
        try {
            // FIX (v3.27.5): NaN/non-integer guard — JSON.stringify NaN'ı null'a çevirir,
            // backend 422 "Input should be a valid integer" verirdi.
            const _toIntArr = (s) => Array.from(s).filter(v => Number.isInteger(v));
            const viewUsers = _toIntArr(permState.viewUserIds);
            const viewOrgs = _toIntArr(permState.viewOrgIds);

            // v3.38.0: scopes — yalnız view-yetkili subject'ler için.
            // mode 'all' → tables boş; 'restricted' → seçili tablolar (boş olabilir, geçerli).
            const scopes = [];
            const _buildScope = (subjType, ids) => {
                ids.forEach(id => {
                    const sk = _subjectKey(subjType, id);
                    const sc = permState.scopeBySubject[sk];
                    if (!sc || sc.mode !== 'restricted') {
                        scopes.push({ subject_type: subjType, subject_id: id, scope_mode: 'all', tables: [] });
                        return;
                    }
                    const tables = Array.from(sc.tables instanceof Set ? sc.tables : []).map(k => {
                        // _tblKey: schema + _TBL_SEP + table. schema boş olabilir.
                        const sp = k.indexOf(_TBL_SEP);
                        const schema = sp >= 0 ? k.slice(0, sp) : '';
                        const table = sp >= 0 ? k.slice(sp + _TBL_SEP.length) : k;
                        return { schema, table };
                    });
                    scopes.push({ subject_type: subjType, subject_id: id, scope_mode: 'restricted', tables });
                });
            };
            _buildScope('user', viewUsers);
            _buildScope('org', viewOrgs);

            const body = {
                user_ids: viewUsers,
                org_ids: viewOrgs,
                can_execute_user_ids: _toIntArr(permState.execUserIds),
                can_execute_org_ids: _toIntArr(permState.execOrgIds),
                scopes,
            };
            // v3.34.0: vyraFetch — Auth + JSON + friendly error helper'da.
            // FastAPI 422 detail array'i için manuel flattening korunur.
            try {
                await window.vyraFetch(`${VF_BASE}/${permState.sourceId}/permissions`, {
                    method: 'PUT',
                    body
                });
            } catch (vfErr) {
                let msg = (vfErr && vfErr.data && (vfErr.data.detail || vfErr.data.message)) || vfErr.message || 'Yetkiler kaydedilemedi';
                if (Array.isArray(msg)) {
                    msg = msg.map(d => (d && d.msg) ? `${(d.loc || []).slice(-1)[0] || '?'}: ${d.msg}` : JSON.stringify(d)).join('; ');
                } else if (typeof msg === 'object') {
                    msg = JSON.stringify(msg);
                }
                throw new Error(msg);
            }
            if (typeof window.showToast === 'function') window.showToast('Yetkiler kaydedildi', 'success');
            _closePermissionModal();
        } catch (error) {
            console.error('[DataSources] Save permissions error:', error);
            if (typeof window.showToast === 'function') window.showToast(error.message || 'Kaydetme hatası', 'error');
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.innerHTML = originalHtml;
            }
        }
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
            // v3.34.0: vyraFetch — Auth + JSON + friendly error helper'da.
            const result = await window.vyraFetch(`${VF_BASE}/${id}/test-connection`, {
                method: 'POST'
            });
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
    return { load, openModal, deleteSource, closeModal, testConnection, openPermissionModal };
})();
