/**
 * VYRA — DS Enrichment Module (v3.0.0)
 * Admin tablo etiketleme ve onay paneli
 *
 * Özellikler:
 * - Enrichment istatistikleri
 * - Onay bekleyen tablo listesi
 * - Inline edit + onaylama
 * - Sütun detay görüntüleme
 * - Schema geçmişi
 */

const DSEnrichmentModule = (() => {
    'use strict';

    let _currentSourceId = null;
    let _pendingData = [];
    let _editingId = null;
    
    // Pagination State
    let _filteredData = [];
    let _currentPage = 1;
    let _pageSize = 50;
    let _searchQuery = '';

    // ============================================
    // Panel Aç/Kapat
    // ============================================

    function openPanel(sourceId) {
        _currentSourceId = sourceId;
        _pendingData = [];
        _editingId = null;

        // Overlay oluştur
        _createOverlay();

        // Verileri yükle
        _loadData();
    }

    function closePanel() {
        const overlay = document.getElementById('dsEnrichOverlay');
        if (overlay) {
            overlay.classList.remove('active');
            setTimeout(() => overlay.remove(), 300);
        }
        _currentSourceId = null;
        _pendingData = [];
    }

    // ============================================
    // Overlay Oluşturma
    // ============================================

    function _createOverlay() {
        // Mevcut varsa kaldır
        const existing = document.getElementById('dsEnrichOverlay');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.id = 'dsEnrichOverlay';
        overlay.className = 'ds-enrich-overlay';
        overlay.style.zIndex = '99999'; // FORCE en üstte olması için
        overlay.innerHTML = `
            <div class="ds-enrich-modal">
                <div class="ds-enrich-header">
                    <div class="ds-enrich-title">
                        <i class="fa-solid fa-tags"></i>
                        <span>Tablo Etiketleme & Onay Paneli</span>
                    </div>
                    <div style="display:flex; align-items:center; gap:8px;">
                        <button class="ds-enrich-close" id="dsEnrichRefreshBtn" title="Verileri Yenile">
                            <i class="fa-solid fa-sync"></i>
                        </button>
                        <button class="ds-enrich-close" id="dsEnrichCloseBtn" title="Kapat (ESC)">
                            <i class="fa-solid fa-xmark"></i>
                        </button>
                    </div>
                </div>
                <div id="dsEnrichStatsBar" class="ds-enrich-stats">
                    <div class="ds-enrich-loading">
                        <i class="fa-solid fa-spinner fa-spin"></i>
                        <p>İstatistikler yükleniyor...</p>
                    </div>
                </div>
                <div class="ds-enrich-body" id="dsEnrichBody">
                    <div class="ds-enrich-loading">
                        <i class="fa-solid fa-spinner fa-spin"></i>
                        <p>Tablo listesi yükleniyor...</p>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(overlay);

        // Animasyon
        requestAnimationFrame(() => overlay.classList.add('active'));

        // Event listeners
        document.getElementById('dsEnrichCloseBtn').addEventListener('click', closePanel);
        document.getElementById('dsEnrichRefreshBtn').addEventListener('click', _loadData);

        // ESC tuşu
        const escHandler = (e) => {
            if (e.key === 'Escape') {
                e.stopImmediatePropagation();
                closePanel();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler, true); // true for capturing phase
    }

    // ============================================
    // Veri Yükleme
    // ============================================

    async function _loadData() {
        try {
            const token = localStorage.getItem('access_token');
            const headers = { 'Authorization': `Bearer ${token}` };

            // Stats ve pending paralel yükle
            const [statsRes, pendingRes] = await Promise.all([
                fetch(`/api/data-sources/${_currentSourceId}/enrichment-stats`, { headers }),
                fetch(`/api/data-sources/${_currentSourceId}/enrichment-pending`, { headers })
            ]);

            const stats = await statsRes.json();
            const pending = await pendingRes.json();

            _pendingData = pending.pending || [];
            _filteredData = [..._pendingData];
            _currentPage = 1;

            _renderStats(stats);
            _renderTable();

        } catch (err) {
            console.error('[DSEnrich] Veri yükleme hatası:', err);
            document.getElementById('dsEnrichBody').innerHTML = `
                <div class="ds-enrich-empty">
                    <i class="fa-solid fa-triangle-exclamation"></i>
                    <h4>Yükleme Hatası</h4>
                    <p>${err.message || 'Veriler yüklenemedi'}</p>
                </div>
            `;
        }
    }

    // ============================================
    // Stats Render
    // ============================================

    function _renderStats(stats) {
        const bar = document.getElementById('dsEnrichStatsBar');
        if (!bar) return;

        const total = stats.total || 0;
        const approved = stats.approved || 0;
        const pending = stats.pending_review || 0;
        const avgScore = stats.avg_score || 0;

        bar.innerHTML = `
            <div class="ds-enrich-stat">
                <span class="ds-enrich-stat-num">${total}</span>
                <span class="ds-enrich-stat-label">Toplam Tablo</span>
            </div>
            <div class="ds-enrich-stat success">
                <span class="ds-enrich-stat-num">${approved}</span>
                <span class="ds-enrich-stat-label">Onaylı</span>
            </div>
            <div class="ds-enrich-stat warning">
                <span class="ds-enrich-stat-num">${pending}</span>
                <span class="ds-enrich-stat-label">Onay Bekliyor</span>
            </div>
            <div class="ds-enrich-stat">
                <span class="ds-enrich-stat-num">${avgScore.toFixed(2)}</span>
                <span class="ds-enrich-stat-label">Ort. Skor</span>
            </div>
        `;
    }

    // ============================================
    // Tablo Render
    // ============================================

    function _renderTable() {
        const body = document.getElementById('dsEnrichBody');
        if (!body) return;

        if (!_pendingData || _pendingData.length === 0) {
            const total = parseInt(document.querySelector('.ds-enrich-stat-num')?.textContent || "0");
            if (total === 0) {
                body.innerHTML = `
                    <div class="ds-enrich-empty">
                        <i class="fa-solid fa-database"></i>
                        <h4>Enrichment Bekleniyor</h4>
                        <p>Bu veri kaynağı için henüz AI Tablo Öğrenimi (Enrichment) çalıştırılmamış. Lütfen veri kaynağı ayarlarından 'Öğrenmeyi Başlat' butonuna tıklayın.</p>
                    </div>
                `;
            } else {
                body.innerHTML = `
                    <div class="ds-enrich-empty">
                        <i class="fa-solid fa-circle-check" style="color: #4cd964;"></i>
                        <h4>Onay Bekleyen Tablo Yok</h4>
                        <p>Harika! Tespit edilen tüm tablolar incelendi ve onaylandı.</p>
                    </div>
                `;
            }
            return;
        }

        body.innerHTML = `
            <div class="ds-enrich-filter-bar" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem; flex-wrap:wrap; gap:10px;">
                <div style="flex:1; max-width:400px; display:flex; gap:0.5rem;">
                    <div style="position:relative; flex:1;">
                        <i class="fa-solid fa-search" style="position:absolute; left:12px; top:10px; color:#888;"></i>
                        <input type="text" id="dsTableSearch" placeholder="Tablo veya iş adı ara..." value="${_searchQuery}"
                            style="width:100%; padding:8px 32px; border-radius:6px; border:1px solid rgba(255,255,255,0.15); background:rgba(0,0,0,0.2); color:#fff; outline:none;" 
                            onkeyup="DSEnrichmentModule.filterTables(this.value)">
                    </div>
                    <button onclick="document.getElementById('dsTableSearch').value=''; DSEnrichmentModule.filterTables('');"
                        style="padding:8px 16px; border-radius:6px; border:none; background:rgba(255,255,255,0.1); color:#fff; cursor:pointer;" title="Aramayı Temizle">
                        <i class="fa-solid fa-eraser"></i>
                    </button>
                </div>
                <div style="display:flex; align-items:center; gap:1rem;">
                    <button id="dsBulkApproveBtn" onclick="DSEnrichmentModule.bulkApprove()" 
                            style="display:none; padding:8px 16px; border-radius:6px; border:none; background:var(--primary-color, #4f46e5); color:#fff; cursor:pointer; font-weight:600;">
                        <i class="fa-solid fa-check-double mr-2"></i> <span id="dsBulkApproveCount">0</span> Kaydı Onayla
                    </button>
                </div>
            </div>
            <div class="ds-enrich-table-wrap" id="dsMainTableWrap">
                <table class="ds-enrich-table">
                    <thead>
                        <tr>
                            <th style="width: 40px; text-align: center;">
                                <input type="checkbox" id="dsSelectAllChk" onchange="DSEnrichmentModule.toggleAllBulk(this.checked)" class="cursor-pointer" title="Filtrelenmiş tümünü seç">
                            </th>
                            <th>Tablo</th>
                            <th>İş Adı (TR)</th>
                            <th>Kategori</th>
                            <th>Skor</th>
                            <th>Açıklama</th>
                            <th>İşlem</th>
                        </tr>
                    </thead>
                    <tbody id="dsEnrichTableBody">
                    </tbody>
                </table>
            </div>
            <div id="dsEnrichPagination" style="display:flex; justify-content:space-between; align-items:center; margin-top:1rem; color:var(--text-secondary, #94a3b8); font-size:0.9rem;">
            </div>
        `;
        
        _renderRows();
    }

    function _renderRows() {
        const tbody = document.getElementById('dsEnrichTableBody');
        const pagination = document.getElementById('dsEnrichPagination');
        if (!tbody || !pagination) return;
        
        const totalItems = _filteredData.length;
        const totalPages = Math.ceil(totalItems / _pageSize) || 1;
        if (_currentPage > totalPages) _currentPage = totalPages;
        
        const startIdx = (_currentPage - 1) * _pageSize;
        const endIdx = startIdx + _pageSize;
        const pageItems = _filteredData.slice(startIdx, endIdx);

        let rows = '';
        for (const item of pageItems) {
            const scoreClass = item.enrichment_score >= 0.7 ? 'high' :
                               item.enrichment_score >= 0.4 ? 'medium' : 'low';
            const catClass = item.category || 'other';
            const tableName = item.schema_name ? `${item.schema_name}.${item.table_name}` : item.table_name;

            rows += `
                <tr data-id="${item.id}" class="ds-enrich-data-row">
                    <td style="width: 40px; text-align: center;">
                        <input type="checkbox" class="ds-bulk-chk cursor-pointer" value="${item.id}" onchange="DSEnrichmentModule.updateBulkCount()">
                    </td>
                    <td class="ds-searchable-cell" data-search="${tableName.toLowerCase()}">
                        <strong>${tableName}</strong>
                    </td>
                    <td class="ds-searchable-cell" data-search="${(item.business_name_tr || '').toLowerCase()}">
                        ${item.business_name_tr || '<em class="ds-enrich-no-label">—</em>'}
                    </td>
                    <td>
                        <span class="ds-cat-badge ${catClass}">${catClass}</span>
                    </td>
                    <td>
                        <span class="ds-score-badge ${scoreClass}">
                            <i class="fa-solid fa-${scoreClass === 'high' ? 'check' : scoreClass === 'medium' ? 'info' : 'warning'}"></i>
                            ${(item.enrichment_score || 0).toFixed(2)}
                        </span>
                    </td>
                    <td title="${item.description_tr || ''}" class="ds-searchable-cell" data-search="${(item.description_tr || '').toLowerCase()}">
                        ${(item.description_tr || '').substring(0, 60)}${(item.description_tr || '').length > 60 ? '...' : ''}
                    </td>
                    <td>
                        <div class="ds-enrich-actions">
                            <button class="ds-enrich-btn approve"
                                    onclick="DSEnrichmentModule.quickApprove(${item.id})"
                                    title="Direkt onayla">
                                <i class="fa-solid fa-check"></i>
                            </button>
                            <button class="ds-enrich-btn edit"
                                    onclick="DSEnrichmentModule.toggleEdit(${item.id})"
                                    title="Düzenle ve onayla">
                                <i class="fa-solid fa-pen"></i>
                            </button>
                            <button class="ds-enrich-btn columns"
                                    onclick="DSEnrichmentModule.showColumns(${item.id})"
                                    title="Sütunları göster">
                                <i class="fa-solid fa-table-columns"></i>
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        }
        
        if (pageItems.length === 0) {
            rows = `<tr><td colspan="7" style="text-align:center; padding:1.5rem;">Arama sonucu bulunamadı.</td></tr>`;
        }

        tbody.innerHTML = rows;

        // Render Pagination Controls
        pagination.innerHTML = `
            <div>
                Gösterilen: <strong>${totalItems === 0 ? 0 : startIdx + 1}-${Math.min(endIdx, totalItems)}</strong> / Toplam: <strong>${totalItems}</strong> kayıt
                <span style="margin-left:1rem;">Sayfa Boyutu: 
                    <select onchange="DSEnrichmentModule.changePageSize(this.value)" style="background:rgba(0,0,0,0.2); border:1px solid rgba(255,255,255,0.1); color:#fff; border-radius:4px; padding:2px 4px; outline:none; font-size:13px;">
                        <option value="20" ${_pageSize == 20 ? 'selected' : ''}>20</option>
                        <option value="50" ${_pageSize == 50 ? 'selected' : ''}>50</option>
                        <option value="100" ${_pageSize == 100 ? 'selected' : ''}>100</option>
                        <option value="500" ${_pageSize == 500 ? 'selected' : ''}>500</option>
                    </select>
                </span>
            </div>
            <div style="display:flex; gap:0.5rem; align-items:center;">
                <button onclick="DSEnrichmentModule.changePage(${_currentPage - 1})" ${_currentPage <= 1 ? 'disabled style="opacity:0.5;cursor:not-allowed;"' : 'style="cursor:pointer;"'} class="ds-wizard-btn secondary" style="padding:4px 10px; min-width:80px;">
                    <i class="fa-solid fa-chevron-left"></i> Önceki
                </button>
                <div style="padding:4px 12px; background:var(--surface-secondary, rgba(255,255,255,0.05)); border:1px solid rgba(255,255,255,0.1); border-radius:6px; font-weight:600;">Sayfa ${_currentPage} / ${totalPages}</div>
                <button onclick="DSEnrichmentModule.changePage(${_currentPage + 1})" ${_currentPage >= totalPages ? 'disabled style="opacity:0.5;cursor:not-allowed;"' : 'style="cursor:pointer;"'} class="ds-wizard-btn secondary" style="padding:4px 10px; min-width:80px;">
                    Sonraki <i class="fa-solid fa-chevron-right"></i>
                </button>
            </div>
        `;
        
        // Tabloyu render ettikten sonra scroll'u tepeye çek
        const tableWrap = document.getElementById('dsMainTableWrap');
        if (tableWrap) tableWrap.scrollTop = 0;
        
        updateBulkCount();
    }
    
    function changePage(newPage) {
        if (newPage < 1) newPage = 1;
        _currentPage = newPage;
        _renderRows();
    }
    
    function changePageSize(newSize) {
        _pageSize = parseInt(newSize);
        _currentPage = 1;
        _renderRows();
    }

    // ============================================
    // Quick Approve
    // ============================================

    async function quickApprove(enrichmentId) {
        try {
            const token = localStorage.getItem('access_token');
            const res = await fetch(
                `/api/data-sources/${_currentSourceId}/enrichment-approve/${enrichmentId}`,
                {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({})
                }
            );
            const data = await res.json();

            if (data.success) {
                // Filtrelenmiş veri havuzundan ve asıl veriden temizle
                _pendingData = _pendingData.filter(p => p.id !== enrichmentId);
                _filteredData = _filteredData.filter(p => p.id !== enrichmentId);
                
                const row = document.querySelector(`tr[data-id="${enrichmentId}"]`);
                if (row) {
                    row.style.transition = 'opacity 0.3s, transform 0.3s';
                    row.style.opacity = '0';
                    row.style.transform = 'translateX(30px)';
                    setTimeout(() => {
                        row.remove();
                        _updateStatsAfterApprove();
                        _renderRows(); // Paginated listeyi tekrar onar
                    }, 300);
                }
                _showToast('Tablo onaylandı', 'success');
            } else {
                _showToast(data.message || 'Onay başarısız', 'error');
            }
        } catch (err) {
            console.error('[DSEnrich] Onay hatası:', err);
            _showToast('Onay sırasında hata oluştu', 'error');
        }
    }

    // ============================================
    // Edit Toggle
    // ============================================

    function toggleEdit(enrichmentId) {
        const tbody = document.getElementById('dsEnrichTableBody');
        if (!tbody) return;

        // Önceki edit satırını kapat
        const prevEdit = tbody.querySelector('.ds-enrich-edit-row');
        if (prevEdit) prevEdit.remove();

        if (_editingId === enrichmentId) {
            _editingId = null;
            return;
        }
        _editingId = enrichmentId;

        const item = _pendingData.find(p => p.id === enrichmentId);
        if (!item) return;

        const row = tbody.querySelector(`tr[data-id="${enrichmentId}"]`);
        if (!row) return;

        const editRow = document.createElement('tr');
        editRow.className = 'ds-enrich-edit-row';
        editRow.innerHTML = `
            <td colspan="6">
                <div class="ds-enrich-edit-form">
                    <div>
                        <label>Türkçe İş Adı</label>
                        <input type="text" id="dsEditLabel" value="${item.business_name_tr || ''}"
                               placeholder="Örn: Fatura, Müşteri, Sipariş">
                    </div>
                    <div>
                        <label>Admin Notu</label>
                        <textarea id="dsEditNotes" placeholder="Opsiyonel: Düzeltme gerekçesi veya ek bilgi">${item.admin_notes || ''}</textarea>
                    </div>
                    <div class="ds-enrich-edit-actions">
                        <button class="save-btn" onclick="DSEnrichmentModule.saveEdit(${enrichmentId})">
                            <i class="fa-solid fa-check"></i> Kaydet & Onayla
                        </button>
                        <button class="cancel-btn" onclick="DSEnrichmentModule.toggleEdit(${enrichmentId})">
                            İptal
                        </button>
                    </div>
                </div>
            </td>
        `;

        row.insertAdjacentElement('afterend', editRow);

        // Focus
        setTimeout(() => {
            const input = document.getElementById('dsEditLabel');
            if (input) input.focus();
        }, 100);
    }

    // ============================================
    // Save Edit (Approve with custom label)
    // ============================================

    async function saveEdit(enrichmentId) {
        const label = document.getElementById('dsEditLabel')?.value?.trim() || null;
        const notes = document.getElementById('dsEditNotes')?.value?.trim() || null;

        try {
            const token = localStorage.getItem('access_token');
            const res = await fetch(
                `/api/data-sources/${_currentSourceId}/enrichment-approve/${enrichmentId}`,
                {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        admin_label_tr: label,
                        admin_notes: notes
                    })
                }
            );
            const data = await res.json();

            if (data.success) {
                _pendingData = _pendingData.filter(p => p.id !== enrichmentId);
                _editingId = null;

                // Edit satırını ve veri satırını kaldır
                const editRow = document.querySelector('.ds-enrich-edit-row');
                const dataRow = document.querySelector(`tr[data-id="${enrichmentId}"]`);
                if (editRow) editRow.remove();
                if (dataRow) {
                    dataRow.style.transition = 'opacity 0.3s';
                    dataRow.style.opacity = '0';
                    setTimeout(() => {
                        dataRow.remove();
                        _updateStatsAfterApprove();
                    }, 300);
                }
                _showToast('Etiket kaydedildi ve onaylandı', 'success');
            } else {
                _showToast(data.message || 'Kaydetme başarısız', 'error');
            }
        } catch (err) {
            console.error('[DSEnrich] Kaydetme hatası:', err);
            _showToast('Kaydetme sırasında hata oluştu', 'error');
        }
    }

    // ============================================
    // Show Columns
    // ============================================

    async function showColumns(enrichmentId) {
        try {
            const token = localStorage.getItem('access_token');
            const res = await fetch(
                `/api/data-sources/enrichment/${enrichmentId}/columns`,
                { headers: { 'Authorization': `Bearer ${token}` } }
            );
            const data = await res.json();

            if (!data.success || !data.columns || data.columns.length === 0) {
                _showToast('Sütun verisi bulunamadı', 'warning');
                return;
            }

            // Sütun detaylarını mini modal olarak göster
            const item = _pendingData.find(p => p.id === enrichmentId);
            const tableName = item ? (item.schema_name ? `${item.schema_name}.${item.table_name}` : item.table_name) : '';

            let colRows = '';
            for (const col of data.columns) {
                const keyIcon = col.is_key_column ? '<i class="fa-solid fa-key" style="color: #f59e0b;"></i> ' : '';
                colRows += `
                    <tr>
                        <td>${keyIcon}${col.column_name}</td>
                        <td><code>${col.data_type}</code></td>
                        <td>${col.business_name_tr || '—'}</td>
                        <td>${col.semantic_type || '—'}</td>
                        <td>${col.description_tr || '—'}</td>
                    </tr>
                `;
            }

            const body = document.getElementById('dsEnrichBody');
            if (!body) return;

            // Tablo üstüne mini breadcrumb ile sütun tablosu göster
            const colSection = document.createElement('div');
            colSection.id = 'dsColumnDetail';
            colSection.innerHTML = `
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.75rem;">
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <button class="ds-enrich-btn edit" onclick="
                            const p=document.getElementById('dsColumnDetail'); if(p)p.remove(); 
                            const w=document.getElementById('dsMainTableWrap'); if(w)w.style.display='';
                            const b=document.querySelector('.ds-enrich-filter-bar'); if(b)b.style.display='flex';
                        " style="padding:4px 10px;">
                            <i class="fa-solid fa-arrow-left"></i> Geri Dön
                        </button>
                        <span style="font-weight: 600; color: var(--text-primary); font-size:1.1rem; margin-left:10px;">
                            <i class="fa-solid fa-table"></i> ${tableName} — Sütun Etiketleri
                        </span>
                    </div>
                </div>
                <div class="ds-enrich-table-wrap">
                    <table class="ds-enrich-table">
                        <thead>
                            <tr>
                                <th>Sütun</th>
                                <th>Veri Tipi</th>
                                <th>İş Adı (TR)</th>
                                <th>Semantic Tip</th>
                                <th>Açıklama</th>
                            </tr>
                        </thead>
                        <tbody>${colRows}</tbody>
                    </table>
                </div>
            `;

            // Mevcut tabloyu gizle, sütun detaylarını göster
            const wrap = document.getElementById('dsMainTableWrap');
            const filterBar = body.querySelector('.ds-enrich-filter-bar');
            if (wrap) wrap.style.display = 'none';
            if (filterBar) filterBar.style.display = 'none';

            body.appendChild(colSection);

        } catch (err) {
            console.error('[DSEnrich] Sütun yükleme hatası:', err);
            _showToast('Sütun bilgileri yüklenemedi', 'error');
        }
    }

    // ============================================
    // Bulk Operations & Filter
    // ============================================

    function filterTables(query) {
        _searchQuery = query.toLowerCase().trim();
        
        if (!_searchQuery) {
            _filteredData = [..._pendingData];
        } else {
            _filteredData = _pendingData.filter(item => {
                const tableName = (item.schema_name ? `${item.schema_name}.${item.table_name}` : item.table_name).toLowerCase();
                const businessName = (item.business_name_tr || '').toLowerCase();
                const desc = (item.description_tr || '').toLowerCase();
                return tableName.includes(_searchQuery) || businessName.includes(_searchQuery) || desc.includes(_searchQuery);
            });
        }
        
        _currentPage = 1;
        _renderRows();
    }

    function toggleAllBulk(checked) {
        const rows = document.querySelectorAll('.ds-enrich-data-row');
        rows.forEach(row => {
            if (row.style.display !== 'none') {
                const chk = row.querySelector('.ds-bulk-chk');
                if (chk) chk.checked = checked;
            }
        });
        updateBulkCount();
    }

    function updateBulkCount() {
        const checked = document.querySelectorAll('.ds-bulk-chk:checked').length;
        const btn = document.getElementById('dsBulkApproveBtn');
        const countSpan = document.getElementById('dsBulkApproveCount');
        
        if (btn && countSpan) {
            countSpan.textContent = checked;
            btn.style.display = checked > 0 ? 'inline-block' : 'none';
        }
        
        const allVisibleRows = Array.from(document.querySelectorAll('.ds-enrich-data-row')).filter(r => r.style.display !== 'none');
        const allVisibleChecked = allVisibleRows.filter(r => {
            const c = r.querySelector('.ds-bulk-chk');
            return c && c.checked;
        });
        
        const mainChk = document.getElementById('dsSelectAllChk');
        if (mainChk) {
            mainChk.checked = allVisibleRows.length > 0 && allVisibleRows.length === allVisibleChecked.length;
        }
    }

    async function bulkApprove() {
        const checkedBoxes = Array.from(document.querySelectorAll('.ds-bulk-chk:checked'));
        if (checkedBoxes.length === 0) return;
        
        const btn = document.getElementById('dsBulkApproveBtn');
        if(btn) {
           btn.disabled=true; 
           btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin mr-2"></i> Onaylanıyor...';
        }

        try {
            const token = localStorage.getItem('access_token');
            const promises = checkedBoxes.map(chk => {
                const enrichmentId = chk.value;
                return fetch(
                    `/api/data-sources/${_currentSourceId}/enrichment-approve/${enrichmentId}`,
                    {
                        method: 'POST',
                        headers: {
                            'Authorization': `Bearer ${token}`,
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({})
                    }
                ).then(res => res.json()).then(data => ({id: enrichmentId, success: data.success}));
            });

            const results = await Promise.all([...promises]);
            const successIds = results.filter(r => r.success).map(r => r.id);
            
            if (successIds.length > 0) {
                _pendingData = _pendingData.filter(p => !successIds.includes(p.id.toString()) && !successIds.includes(parseInt(p.id)));
                _filteredData = _filteredData.filter(p => !successIds.includes(p.id.toString()) && !successIds.includes(parseInt(p.id)));
                
                successIds.forEach(id => {
                    const row = document.querySelector(`tr[data-id="${id}"]`);
                    if (row) {
                        row.style.transition = 'opacity 0.3s, transform 0.3s';
                        row.style.opacity = '0';
                        row.style.transform = 'translateX(30px)';
                        setTimeout(() => row.remove(), 300);
                    }
                });
                
                setTimeout(() => {
                    _updateStatsAfterApprove();
                    _renderRows(); // Pagination sayfasını (öğe sayısını ve html'i) dengele
                }, 350);
                
                _showToast(`${successIds.length} tablo onaylandı`, 'success');
            } else {
                _showToast('Toplu onay başarısız', 'error');
            }
        } catch (err) {
            console.error('[DSEnrich] Toplu onay hatası:', err);
            _showToast('Onay sırasında hata oluştu', 'error');
        } finally {
            if(btn) {
                btn.disabled=false; 
                btn.innerHTML = '<i class="fa-solid fa-check-double mr-2"></i> <span id="dsBulkApproveCount">0</span> Kaydı Onayla';
                updateBulkCount();
            }
        }
    }

    // ============================================
    // Helpers
    // ============================================

    function _updateStatsAfterApprove() {
        const token = localStorage.getItem('access_token');
        fetch(`/api/data-sources/${_currentSourceId}/enrichment-stats`, {
            headers: { 'Authorization': `Bearer ${token}` }
        })
        .then(r => r.json())
        .then(stats => _renderStats(stats))
        .catch(() => {});

        if (_pendingData.length === 0) {
            _renderTable(); // Boş durumu otomatik yakalayacaktır
        }
    }

    function _showToast(message, type) {
        if (typeof showToast === 'function') {
            showToast(message, type);
            return;
        }
        console.log(`[Toast:${type}] ${message}`);
    }

    // ============================================
    // Public API
    // ============================================

    return {
        openPanel,
        closePanel,
        quickApprove,
        toggleEdit,
        saveEdit,
        showColumns,
        filterTables,
        toggleAllBulk,
        updateBulkCount,
        bulkApprove,
        changePage,
        changePageSize
    };
})();

// Global erişim
window.DSEnrichmentModule = DSEnrichmentModule;
