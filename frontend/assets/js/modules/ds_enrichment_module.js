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
    let _filteredData = [];
    let _editingId = null;
    let _onCloseCallback = null;
    let _currentPage = 1;
    let _pageSize = 10;
    let _searchQuery = '';
    let _searchTimer = null;
    let _filterLowScore = false;
    let _showApproved = false;
    let _selectedIds = new Set();
    let _pollingTimer = null;
    let _isPolling = false;
    let _filterPendingApproval = false;

    // ============================================
    // Panel Aç/Kapat
    // ============================================

    function openPanel(sourceId, onCloseCallback) {
        if (_pollingTimer) clearInterval(_pollingTimer);
        _isPolling = false;
        _currentSourceId = sourceId;
        _pendingData = [];
        _filteredData = [];
        _editingId = null;
        _currentPage = 1;
        _searchQuery = '';
        _filterLowScore = false;
        _showApproved = false;
        _filterPendingApproval = false;
        _selectedIds.clear();
        _onCloseCallback = onCloseCallback || null;

        // Overlay oluştur
        _createOverlay();

        // Verileri yükle
        _loadData();
        _pollingTimer = setInterval(_loadDataSilently, 10000);
    }

    function closePanel() {
        if (_pollingTimer) clearInterval(_pollingTimer);
        const overlay = document.getElementById('dsEnrichOverlay');
        if (overlay) {
            overlay.classList.remove('active');
            setTimeout(() => {
                overlay.remove();
                // Wizard'a geri dön callback'i
                if (_onCloseCallback) {
                    _onCloseCallback();
                    _onCloseCallback = null;
                }
            }, 300);
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
        overlay.innerHTML = `
            <div class="ds-enrich-modal" style="display:flex;flex-direction:column;height:90vh;max-height:90vh;overflow:hidden;">
                <div class="ds-enrich-header" style="flex-shrink:0;">
                    <div class="ds-enrich-title">
                        <i class="fa-solid fa-tags"></i>
                        <span>Tablo Etiketleme & Onay Paneli</span>
                    </div>
                    <button class="ds-enrich-close" id="dsEnrichCloseBtn" title="Kapat (ESC)">
                        <i class="fa-solid fa-xmark"></i>
                    </button>
                </div>
                <div id="dsEnrichStatsBar" class="ds-enrich-stats" style="flex-shrink:0;">
                    <div class="ds-enrich-loading">
                        <i class="fa-solid fa-spinner fa-spin"></i>
                        <p>İstatistikler yükleniyor...</p>
                    </div>
                </div>
                <div class="ds-enrich-body" id="dsEnrichBody" style="flex:1;display:flex;flex-direction:column;overflow:hidden;min-height:0;padding:16px;">
                    <div class="ds-enrich-loading" style="margin: auto;">
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

        // ESC tuşu
        const escHandler = (e) => {
            if (e.key === 'Escape') {
                closePanel();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);
    }

    // ============================================
    // Veri Yükleme
    // ============================================

    async function _loadData() {
        try {
            const token = localStorage.getItem('access_token');
            const headers = { 'Authorization': `Bearer ${token}` };

            const [statsRes, allRes] = await Promise.all([
                fetch(`/api/data-sources/${_currentSourceId}/enrichment-stats`, { headers }),
                fetch(`/api/data-sources/${_currentSourceId}/enrichment-all`, { headers })
            ]);

            const stats = await statsRes.json();
            const allData = await allRes.json();

            _pendingData = (allData.tables || []).map(x => {
                return {
                    ...x,
                    id: x.object_id, // Map object_id to id for UI functions
                    is_approved: !!x.admin_approved
                };
            });

            _renderStats(stats);
            applyFilterAndRender();
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

        async function _loadDataSilently() {
        if (!_currentSourceId || _isPolling) return;
        _isPolling = true;
        try {
            const token = localStorage.getItem('access_token');
            const headers = { 'Authorization': `Bearer ${token}` };
            const [statsRes, allRes] = await Promise.all([
                fetch(`/api/data-sources/${_currentSourceId}/enrichment-stats`, { headers }),
                fetch(`/api/data-sources/${_currentSourceId}/enrichment-all`, { headers })
            ]);
            const stats = await statsRes.json();
            const allData = await allRes.json();
            const newPending = (allData.tables || []).map(x => ({
                ...x, id: x.object_id, is_approved: !!x.admin_approved
            }));
            
            // Sadece anlamlı alan değişikliği varsa listeyi yenile (performans)
            // Karşılaştırma: enrichment_id, is_approved, enrichment_score
            let changed = false;
            if (newPending.length !== _pendingData.length) {
                changed = true;
            } else {
                // İndeks yerine id bazlı karşılaştır (sıra değişmiş olabilir)
                const prevMap = new Map(_pendingData.map(x => [x.id, x]));
                for (const newItem of newPending) {
                    const prev = prevMap.get(newItem.id);
                    if (!prev ||
                        newItem.enrichment_id !== prev.enrichment_id ||
                        newItem.is_approved !== prev.is_approved ||
                        (newItem.enrichment_score || 0).toFixed(4) !== (prev.enrichment_score || 0).toFixed(4)) {
                        changed = true;
                        break;
                    }
                }
            }
            if(changed) {
                // Yeni keşfedilen tabloları tespit et (enrichment_id yeni eklendiyse)
                const prevDiscoveredIds = new Set(_pendingData.filter(x => x.enrichment_id).map(x => x.id));
                const newlyDiscovered = newPending.filter(x => x.enrichment_id && !prevDiscoveredIds.has(x.id));

                _pendingData = newPending;
                _renderStats(stats);

                // Yeni keşfedilen tablo varsa sayfa 1'e dön + toast göster
                if (newlyDiscovered.length > 0) {
                    _currentPage = 1;
                    applyFilterAndRender();
                    _showToast(`${newlyDiscovered.length} tablo keşfedildi. Onay Bekliyor durumuna geçti!`, 'success');
                } else {
                    // Sayfa ve arama korunarak sadece render güncellenir
                    applyFilterAndRender();
                }
            } else {
                _renderStats(stats); // İstatistikler güncellendi, liste aynı
            }
        } catch(e) { console.warn('[DSEnrich] Polling hatası:', e); }
        finally { _isPolling = false; }
    }

    function _renderStats(stats) {
        const bar = document.getElementById('dsEnrichStatsBar');
        if (!bar) return;

        const total = stats.total || 0;
        const approved = stats.approved || 0;
        const pending = stats.pending_review || 0;
        const avgScore = stats.avg_score || 0;
        const unprocessed = stats.unprocessed || 0;

        bar.innerHTML = `
            <div class="ds-enrich-stat" title="Henüz LLM tarafından incelenmeyen tablo sayısı">
                <span class="ds-enrich-stat-num" style="color: #a78bfa;">${unprocessed}</span>
                <span class="ds-enrich-stat-label">LLM Bekleyen</span>
            </div>
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

    // ============================================
    // Filter & Render & Pagination
    // ============================================

    function applyFilterAndRender() {
        const body = document.getElementById('dsEnrichBody');
        if (!body) return;

        // Filtreleme işlemleri
        _filteredData = _pendingData.filter(item => {
            const query = _searchQuery.toLowerCase().trim();
            let textMatch = true;
            if (query) {
                const tableName = (item.schema_name ? item.schema_name + '.' + item.table_name : item.table_name).toLowerCase();
                const businessName = (item.business_name_tr || '').toLowerCase();
                const desc = (item.description_tr || '').toLowerCase();
                if (!tableName.includes(query) && !businessName.includes(query) && !desc.includes(query)) {
                    textMatch = false;
                }
            }

            let scoreMatch = true;
            if (_filterLowScore) {
                if (item.enrichment_score >= 0.7 && item.business_name_tr) {
                    scoreMatch = false;
                }
            }
            
            let approvalMatch = true;
            if (!_showApproved && item.is_approved) {
                approvalMatch = false;
            }

            return textMatch && scoreMatch && approvalMatch;
        });

        // Onay bekleyen filtresi (sadece kesfedilmis ama onayla beklenenler)
        if (_filterPendingApproval) {
            _filteredData = _filteredData.filter(item => item.enrichment_id && !item.is_approved);
        }

        // Siralama: Onay bekleyenler once, (eğer seciliyse onaylılar), sonra kesif bekleyenler
        _filteredData.sort((a, b) => {
            const rank = x => {
                if (x.enrichment_id && !x.is_approved) return 0;
                if (x.is_approved) return _showApproved ? 1 : 2;
                if (!x.enrichment_id) return _showApproved ? 2 : 1;
                return 3;
            };
            if (rank(a) !== rank(b)) return rank(a) - rank(b);
            // Sonra skora gore (buyukten kucuge)
            if ((b.enrichment_score || 0) !== (a.enrichment_score || 0)) {
                return (b.enrichment_score || 0) - (a.enrichment_score || 0);
            }
            // Sonra isme gore
            const nameA = a.table_name || '';
            const nameB = b.table_name || '';
            return nameA.localeCompare(nameB);
        });

        // Sayfalama hesaplamaları
        const totalItems = _filteredData.length;
        const totalPages = Math.ceil(totalItems / _pageSize) || 1;
        if (_currentPage > totalPages) _currentPage = totalPages;

        const startIndex = (_currentPage - 1) * _pageSize;
        const endIndex = startIndex + _pageSize;
        const pageData = _filteredData.slice(startIndex, endIndex);

        _renderUIPartial(body, pageData, totalItems, totalPages, startIndex, endIndex);
    }

    function _renderUIPartial(body, items, totalItems, totalPages, startIndex, endIndex) {
        const wasSearchFocused = document.activeElement && document.activeElement.id === 'dsSearchInput';

        if (_filteredData.length === 0 && _searchQuery === '' && !_filterLowScore) {
            const total = parseInt(document.querySelector('.ds-enrich-stat-num')?.textContent || "0");
            const pendingCount = _pendingData.filter(x => !x.is_approved).length;
            
            // Eğer gösterilecek onaylılar yoksa veya _showApproved kapalıysa tam ekran boş durumları göster.
            if ((pendingCount === 0 && !_showApproved) || (_pendingData.length === 0)) {
                if (total === 0) {
                    body.innerHTML = `
                        <div class="ds-enrich-empty">
                            <i class="fa-solid fa-database"></i>
                            <h4>Enrichment Bekleniyor</h4>
                            <p>Bu veri kaynağı için henüz AI Tablo Öğrenimi (Enrichment) çalıştırılmamış.</p>
                        </div>
                    `;
                } else {
                    body.innerHTML = `
                        <div class="ds-enrich-empty">
                            <i class="fa-solid fa-circle-check" style="color: #4cd964;"></i>
                            <h4>Onay Bekleyen Tablo Yok</h4>
                            <p>Harika! Tespit edilen tüm tablolar incelendi ve onaylandı.</p>
                            <button class="ds-enrich-btn" style="margin-top:20px;width:auto;padding:8px 16px;" onclick="document.querySelector('#dsShowApprovedChk').click()">
                                Onaylıları Gözden Geçir
                            </button>
                        </div>
                    `;
                }
                return;
            }
        }

        let rows = '';
        if (items.length === 0) {
            rows = `<tr><td colspan="7" class="text-center" style="padding:2rem;color:#aaa;">Bu filtrelere uygun tablo bulunamadı.</td></tr>`;
        } else {
            for (const item of items) {
                const scoreClass = item.enrichment_score >= 0.7 ? 'high' :
                                   item.enrichment_score >= 0.4 ? 'medium' : 'low';
                const catClass = item.category || 'other';
                const tableName = item.schema_name ? `${item.schema_name}.${item.table_name}` : item.table_name;
                const isChecked = _selectedIds.has(item.id.toString()) ? 'checked' : '';
                const approvedAttr = item.is_approved ? 'disabled title="Zaten onaylandı"' : '';
                const rowOpacity = item.is_approved ? 'opacity: 0.7;' : '';
                const rowHighlight = (item.enrichment_id && !item.is_approved) ? 'background:rgba(245,158,11,0.05);border-left:3px solid rgba(245,158,11,0.4);' : '';

                rows += `
                    <tr data-id="${item.id}" class="ds-enrich-data-row" style="${rowOpacity}${rowHighlight}">
                        <td style="text-align: center;">
                            <input type="checkbox" class="ds-bulk-chk ${item.is_approved ? '' : 'cursor-pointer'}" value="${item.id}" ${isChecked} ${approvedAttr} onchange="DSEnrichmentModule.toggleCheckbox(this)">
                        </td>
                        <td class="ds-table-name-cell" title="${tableName}">
                            <strong>${tableName}</strong>
                        </td>
                        <td>
                            ${item.business_name_tr || '<em class="ds-enrich-no-label">—</em>'}
                        </td>
                        <td style="text-align:center;">
                            <span class="ds-cat-badge ${catClass}">${catClass}</span>
                        </td>
                        <td style="text-align:center;">
                            <span class="ds-score-badge ${scoreClass}">
                                <i class="fa-solid fa-${scoreClass === 'high' ? 'check' : scoreClass === 'medium' ? 'info' : 'warning'}"></i>
                                ${(item.enrichment_score || 0).toFixed(2)}
                            </span>
                        </td>
                        <td class="ds-desc-cell" title="${item.description_tr || '(Açıklama yok)'}">
                            ${(item.description_tr || '').substring(0, 60)}${(item.description_tr || '').length > 60 ? '...' : ''}
                        </td>
                        <td class="ds-action-cell">
                            <div class="ds-enrich-actions ds-action-nowrap">
                                ${!item.enrichment_id ? `
                                <span class="ds-status-badge ds-status-pending-disc"><i class="fa-solid fa-hourglass-half"></i> Keşif Bekliyor</span>
                                ` : (!item.is_approved ? `
                                <span class="ds-status-badge ds-status-pending-appr"><i class="fa-solid fa-clock"></i> Onay Bekliyor</span>
                                <button class="ds-enrich-btn approve" onclick="DSEnrichmentModule.quickApprove(${item.id})" title="Direkt onayla" style="background:rgba(245,158,11,0.15);color:#f59e0b;border:1px solid rgba(245,158,11,0.3);">
                                    <i class="fa-solid fa-check"></i>
                                </button>
                                ` : '<span class="ds-status-badge ds-status-approved"><i class="fa-solid fa-check-double"></i> Onaylı</span>')}
                                ${item.enrichment_id ? `
                                <button class="ds-enrich-btn edit" onclick="DSEnrichmentModule.toggleEdit(${item.id})" title="Düzenle">
                                    <i class="fa-solid fa-pen"></i>
                                </button>
                                <button class="ds-enrich-btn columns" onclick="DSEnrichmentModule.showColumns(${item.id})" title="Sütunları göster">
                                    <i class="fa-solid fa-table-columns"></i>
                                </button>
                                ` : ''}
                            </div>
                        </td>
                    </tr>
                `;
            }
        }

        const isAllSelected = items.length > 0 && items.every(i => _selectedIds.has(i.id.toString()));

        // Build pagination wrapper
        let pageBtns = '';
        for (let p = 1; p <= totalPages; p++) {
            if (p === 1 || p === totalPages || (p >= _currentPage - 1 && p <= _currentPage + 1)) {
                if (p === _currentPage) {
                    pageBtns += `<button class="ds-enrich-page-btn active">${p}</button>`;
                } else {
                    pageBtns += `<button class="ds-enrich-page-btn" onclick="DSEnrichmentModule.changePage(${p})">${p}</button>`;
                }
            } else if (p === _currentPage - 2 || p === _currentPage + 2) {
                pageBtns += `<span style="color:#888;">...</span>`;
            }
        }

        // ---- Buton disabled state hesaplamaları ----
        const _btnUndiscoveredCount = _pendingData.filter(x => !x.enrichment_id).length;
        const _btnSelUndiscovered   = Array.from(_selectedIds).filter(id => { const r = _pendingData.find(x => x.id == id); return r && !r.enrichment_id; }).length;
        const _btnSelApprovable     = Array.from(_selectedIds).filter(id => { const r = _pendingData.find(x => x.id == id); return r && r.enrichment_id && !r.is_approved; }).length;
        const _btnAllApprovable     = _pendingData.filter(x => x.enrichment_id && !x.is_approved).length;
        const _btnDiscoverAllDis    = _btnUndiscoveredCount === 0;
        const _btnDiscoverSelDis    = _btnSelUndiscovered === 0;
        const _btnApproveSelDis     = _btnSelApprovable === 0;
        const _btnApproveAllDis     = _btnAllApprovable === 0;
        // Tooltip metinleri
        const _ttDiscoverAll  = _pendingData.length === 0
            ? 'Tablolar yükleniyor...'
            : (_btnDiscoverAllDis ? 'Tüm tablolar zaten keşfedilmiş' : 'Keşfedilmemiş tüm tabloları keşfet');
        const _ttDiscoverSel  = (_btnSelUndiscovered === 0 && _selectedIds.size > 0) ? 'Seçili tablolar zaten keşfedilmiş' : 'Seçili keşfedilmemiş tabloları keşfet';
        const _ttApproveSel   = _btnApproveSelDis ? (_btnSelUndiscovered > 0 ? 'Seçili tablolar henüz keşfedilmemiş, önce keşfedin' : 'Onaylanacak seçili tablo yok') : 'Seçili keşfedilmiş tabloları onayla';
        const _ttApproveAll   = _btnApproveAllDis ? (_btnUndiscoveredCount > 0 ? 'Önce tüm tabloları keşfedin' : 'Onaylanacak tablo yok') : `${_btnAllApprovable} keşfedilmiş tabloyu onayla`;

        body.innerHTML = `
            <div class="ds-enrich-filter-bar" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem; flex-wrap:wrap; gap:10px; flex-shrink:0;">
                <div style="flex:1; max-width:650px; display:flex; gap:0.5rem; align-items:center;">
                    <button onclick="DSEnrichmentModule.refreshData()" style="padding:8px 14px; border-radius:6px; border:none; background:rgba(255,255,255,0.1); color:#fff; cursor:pointer;" title="Verileri Yenile">
                        <i class="fa-solid fa-sync"></i>
                    </button>
                    <div style="position:relative; flex:1;">
                        <i class="fa-solid fa-search" style="position:absolute; left:12px; top:10px; color:#888;"></i>
                        <input type="text" id="dsSearchInput" value="${_searchQuery}" placeholder="Tablo veya iş adı ara..." 
                            style="width:100%; padding:8px 32px; border-radius:6px; border:1px solid rgba(255,255,255,0.15); background:rgba(0,0,0,0.2); color:#fff; outline:none;" 
                            oninput="DSEnrichmentModule.filterTables(this.value)" autocomplete="off">
                    </div>
                    <label style="display:flex; align-items:center; gap:6px; color:#ddd; font-size:0.85rem; cursor:pointer; white-space:nowrap;">
                        <input type="checkbox" ${_filterLowScore ? 'checked' : ''} onchange="DSEnrichmentModule.toggleLowScoreFilter(this.checked)" style="width: 16px; height: 16px; accent-color: var(--primary-color, #4f46e5);"> 
                        Düşük Skor / İsimsizleri Göster
                    </label>
                    <label style="display:flex; align-items:center; gap:6px; color:#ddd; font-size:0.85rem; cursor:pointer; white-space:nowrap;">
                        <input id="dsShowApprovedChk" type="checkbox" ${_showApproved ? 'checked' : ''} onchange="DSEnrichmentModule.toggleShowApprovedFilter(this.checked)" style="width: 16px; height: 16px; accent-color: #34d399;"> 
                        Onaylıları Göster
                    </label>
                    <button onclick="DSEnrichmentModule.togglePendingApprovalFilter()" 
                            style="padding:5px 10px; border-radius:6px; border:1px solid ${_filterPendingApproval ? 'rgba(245,158,11,0.6)' : 'rgba(255,255,255,0.15)'}; background:${_filterPendingApproval ? 'rgba(245,158,11,0.2)' : 'transparent'}; color:${_filterPendingApproval ? '#f59e0b' : '#aaa'}; cursor:pointer; font-size:0.82rem; font-weight:600; white-space:nowrap; transition:all 0.2s;" title="Keşfedilmiş ama onaylanmamış tablolar">
                        <i class="fa-solid fa-clock" style="margin-right:4px;"></i>Onay Bekleyenler (${_pendingData.filter(x => x.enrichment_id && !x.is_approved).length})
                    </button>
                </div>
                <div style="display:flex; align-items:center; gap:10px;">
                    <button id="dsBulkDiscoverAllBtn" onclick="DSEnrichmentModule.discoverAll()"
                            ${_btnDiscoverAllDis ? 'disabled' : ''}
                            style="padding:8px 16px; border-radius:6px; border:none; background:#7c3aed; color:#fff; cursor:${_btnDiscoverAllDis ? 'not-allowed' : 'pointer'}; font-weight:600; opacity:${_btnDiscoverAllDis ? '0.45' : '1'}; transition: all 0.2s;"
                            title="${_ttDiscoverAll}">
                        <i class="fa-solid fa-magnifying-glass mr-2"></i> Tümünü Keşfet
                    </button>
                    <button id="dsBulkDiscoverBtn" onclick="DSEnrichmentModule.bulkDiscover()"
                            ${_btnDiscoverSelDis ? 'disabled' : ''}
                            style="padding:8px 16px; border-radius:6px; border:none; background:#a78bfa; color:#fff; cursor:${_btnDiscoverSelDis ? 'not-allowed' : 'pointer'}; font-weight:600; opacity:${_btnDiscoverSelDis ? '0.45' : '1'}; transition: all 0.2s;"
                            title="${_ttDiscoverSel}">
                        <i class="fa-solid fa-robot mr-2"></i> Seçilenleri Keşfet (<span id="dsBulkDiscoverCount">${_btnSelUndiscovered}</span>)
                    </button>
                    <button id="dsBulkApproveBtn" onclick="DSEnrichmentModule.bulkApprove()"
                            ${_btnApproveSelDis ? 'disabled' : ''}
                            style="padding:8px 16px; border-radius:6px; border:none; background:var(--primary-color, #4f46e5); color:#fff; cursor:${_btnApproveSelDis ? 'not-allowed' : 'pointer'}; font-weight:600; opacity:${_btnApproveSelDis ? '0.45' : '1'}; transition: all 0.2s;"
                            title="${_ttApproveSel}">
                        <i class="fa-solid fa-check-double mr-2"></i> Seçilenleri Onayla (<span id="dsBulkApproveCount">${_btnSelApprovable}</span>)
                    </button>
                    <button id="dsApproveAllBtn" onclick="DSEnrichmentModule.bulkApproveAll()"
                            ${_btnApproveAllDis ? 'disabled' : ''}
                            style="padding:8px 16px; border-radius:6px; border:none; background:#059669; color:#fff; cursor:${_btnApproveAllDis ? 'not-allowed' : 'pointer'}; font-weight:600; opacity:${_btnApproveAllDis ? '0.45' : '1'}; transition: all 0.2s;"
                            title="${_ttApproveAll}">
                        <i class="fa-solid fa-check-circle mr-2"></i> Tümünü Onayla
                    </button>
                </div>
            </div>
            
            <div class="ds-enrich-table-wrap" id="dsMainTableWrap" style="flex:1; overflow-y:auto; min-height:0; padding-right:4px;">
                <table class="ds-enrich-table" style="table-layout:fixed; width:100%;">
                    <colgroup>
                        <col style="width:40px;" />
                        <col style="width:22%;" />
                        <col style="width:14%;" />
                        <col style="width:80px;" />
                        <col style="width:72px;" />
                        <col style="width:auto;" />
                        <col style="width:210px;" />
                    </colgroup>
                    <thead style="position:sticky; top:0; z-index:10; background:var(--bg-card, #1a1e29); box-shadow:0 2px 5px rgba(0,0,0,0.2);">
                        <tr>
                            <th style="width:40px; text-align:center;">
                                <input type="checkbox" id="dsSelectAllChk" ${isAllSelected ? "checked" : ""} onchange="DSEnrichmentModule.toggleAllBulk(this.checked)" class="cursor-pointer" title="Bu sayfadaki tümünü seç" style="width:16px; height:16px; cursor:pointer; accent-color:var(--primary-color, #4f46e5); display:inline-block; visibility:visible; opacity:1;">
                            </th>
                            <th>Tablo</th>
                            <th>İş Adı (TR)</th>
                            <th>Kategori</th>
                            <th>Skor</th>
                            <th>Açıklama</th>
                            <th style="text-align:right; padding-right:12px;">İşlem</th>
                        </tr>
                    </thead>
                    <tbody id="dsEnrichTableBody">
                        ${rows}
                    </tbody>
                </table>
            </div>
            ${totalItems > 0 ? `
            <div class="ds-enrich-pagination" style="flex-shrink:0; padding:10px 0 4px 0; border-top:1px solid rgba(255,255,255,0.07); margin-top:6px;">
                <div class="ds-enrich-pagination-info">
                    Toplam <strong>${totalItems}</strong> kayıttan <strong>${startIndex + 1}-${Math.min(endIndex, totalItems)}</strong> arası gösteriliyor.
                </div>
                <div class="ds-enrich-pagination-controls">
                   <button class="ds-enrich-page-btn" ${ _currentPage === 1 ? 'disabled' : ''} onclick="DSEnrichmentModule.changePage(${_currentPage - 1})"><i class="fa-solid fa-chevron-left"></i></button>
                   ${pageBtns}
                   <button class="ds-enrich-page-btn" ${ _currentPage === totalPages ? 'disabled' : ''} onclick="DSEnrichmentModule.changePage(${_currentPage + 1})"><i class="fa-solid fa-chevron-right"></i></button>
                </div>
            </div>` : ''}
        `;

        if (wasSearchFocused) {
            const searchInput = document.getElementById('dsSearchInput');
            if (searchInput) {
                searchInput.focus();
                const len = searchInput.value.length;
                searchInput.setSelectionRange(len, len);
            }
        }
    }

    // ============================================
    // Quick Approve
    // ============================================

    async function quickApprove(objectId) {
        // _pendingData içinde id = object_id olarak map'lendi (satır 149)
        const item = _pendingData.find(p => p.id === objectId);
        if (!item || !item.enrichment_id) {
            _showToast('Bu tablonun keşif kaydı bulunamadı', 'error');
            return;
        }
        const enrichmentId = item.enrichment_id;

        // Çalışan iş kontrolü — keşif devam ediyorsa onay engelle
        try {
            const _jobCheckToken = localStorage.getItem('access_token');
            const _jobCheckRes = await fetch(`/api/data-sources/${_currentSourceId}/check-running-job`, {
                headers: { 'Authorization': `Bearer ${_jobCheckToken}` }
            });
            const _jobCheck = await _jobCheckRes.json();
            if (_jobCheck.has_running) {
                _showToast('Keşif işlemi devam ediyor. Tamamlanmasını bekleyin.', 'warning');
                return;
            }
        } catch (e) { /* kontrol başarısız, devam et */ }

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
                const existing = _pendingData.find(p => p.id === objectId);
                if (existing) existing.is_approved = true;
                const row = document.querySelector(`tr[data-id="${objectId}"]`);
                if (row) {
                    row.style.transition = 'opacity 0.3s, transform 0.3s';
                    row.style.opacity = '0';
                    row.style.transform = 'translateX(30px)';
                    setTimeout(() => {
                        _updateStatsAfterApprove();
                        applyFilterAndRender();
                    }, 300);
                } else {
                    _updateStatsAfterApprove();
                    applyFilterAndRender();
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
                const existing = _pendingData.find(p => p.id === enrichmentId);
                if(existing) existing.is_approved = true;
                _editingId = null;

                // Edit satırını ve veri satırını kaldır
                const editRow = document.querySelector('.ds-enrich-edit-row');
                const dataRow = document.querySelector(`tr[data-id="${enrichmentId}"]`);
                if (editRow) editRow.remove();
                if (dataRow) {
                    dataRow.style.transition = 'opacity 0.3s';
                    dataRow.style.opacity = '0';
                    setTimeout(() => {
                        const existing = _pendingData.find(p => p.id === enrichmentId);
                        if(existing) existing.is_approved = true;
                        _updateStatsAfterApprove();
                        applyFilterAndRender();
                    }, 300);
                } else {
                    _updateStatsAfterApprove();
                    applyFilterAndRender();
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

    function refreshData() {
        _searchQuery = '';
        _filterLowScore = false;
        _showApproved = false;
        _selectedIds.clear();
        const body = document.getElementById('dsEnrichBody');
        if(body) body.innerHTML = `<div class="ds-enrich-loading"><i class="fa-solid fa-spinner fa-spin"></i><p>Yükleniyor...</p></div>`;
        _loadData();
        _pollingTimer = setInterval(_loadDataSilently, 10000);
    }

    function filterTables(query) {
        _searchQuery = query;
        _currentPage = 1;
        if (_searchTimer) clearTimeout(_searchTimer);
        _searchTimer = setTimeout(() => {
            applyFilterAndRender();
        }, 300);
    }

    function toggleLowScoreFilter(checked) {
        _filterLowScore = checked;
        _currentPage = 1;
        applyFilterAndRender();
    }

    function changePage(page) {
        _currentPage = page;
        applyFilterAndRender();
    }

    function toggleShowApprovedFilter(checked) {
        _showApproved = checked;
        _currentPage = 1;
        applyFilterAndRender();
    }

    function togglePendingApprovalFilter() {
        _filterPendingApproval = !_filterPendingApproval;
        _currentPage = 1;
        applyFilterAndRender();
    }

    function toggleCheckbox(chk) {
        if (chk.checked) {
            _selectedIds.add(chk.value.toString());
        } else {
            _selectedIds.delete(chk.value.toString());
        }
        applyFilterAndRender();
    }

    function toggleAllBulk(checked) {
        const startIndex = (_currentPage - 1) * _pageSize;
        const endIndex = startIndex + _pageSize;
        const pageData = _filteredData.slice(startIndex, endIndex);

        pageData.forEach(item => {
            if (item.is_approved) return;
            if (checked) _selectedIds.add(item.id.toString());
            else _selectedIds.delete(item.id.toString());
        });
        applyFilterAndRender();
    }

    function updateBulkCount() {
        // Obsolete function, retained for compatibility if called externally.
        // Counting is rendered seamlessly inside applyFilterAndRender
    }

    async function bulkDiscover() {
        const toDiscover = Array.from(_selectedIds).filter(id => {
            const row = _pendingData.find(x => String(x.id) === String(id));
            return row && !row.enrichment_id;
        }).map(Number);

        if (toDiscover.length === 0) {
            _showToast('Keşfedilecek yeni tablo seçilmedi veya seçili olanlar zaten onaylanmış/keşfedilmiş.', 'warning');
            return;
        }

        const btn = document.getElementById('dsBulkDiscoverBtn');
        const oldContent = btn ? btn.innerHTML : '';
        if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin mr-2"></i> Keşif Başlatılıyor...';
            btn.disabled = true;
        }

        try {
            const token = localStorage.getItem('access_token');
            const res = await fetch(`/api/data-sources/${_currentSourceId}/enrich-selected`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({ object_ids: toDiscover })
            });
            const data = await res.json();
            if (data.success) {
                _showToast(data.message || `${toDiscover.length} tablo için arkada keşif başlatıldı. Birazdan liste yeşillenecek.`, 'success');
            } else {
                _showToast(data.message || 'Keşif başlatılamadı.', 'error');
            }
        } catch (err) {
            _showToast('Keşif isteği atılamadı.', 'error');
        } finally {
            if (btn) {
                btn.innerHTML = oldContent;
            }
        }
    }

    async function discoverAll() {
        // Keşfedilmemiş tüm tabloları keşfet (enrich-selected)
        const unprocessed = _pendingData.filter(x => !x.enrichment_id).map(x => Number(x.id));
        if (unprocessed.length === 0) {
            _showToast('Keşfedilmemiş tablo bulunamadı. Tüm tablolar zaten keşfedilmiş.', 'info');
            return;
        }

        const btn = document.getElementById('dsBulkDiscoverAllBtn');
        if (btn) {
            if (btn.disabled) return; // Çift tıklama koruması
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin mr-2"></i> Keşfediliyor...';
        }

        try {
            const token = localStorage.getItem('access_token');
            const res = await fetch(`/api/data-sources/${_currentSourceId}/enrich-selected`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({ object_ids: unprocessed })
            });
            const data = await res.json();
            if (data.success) {
                _showToast(data.message || `${unprocessed.length} tablo için keşif başlatıldı. Liste otomatik güncellenecek.`, 'success');
            } else {
                _showToast(data.message || 'Keşif başlatılamadı.', 'warning');
            }
        } catch (err) {
            _showToast('Keşif isteği atılamadı.', 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-magnifying-glass mr-2"></i> Tümünü Keşfet';
            }
        }
    }

    async function bulkApprove() {
        const checkedBoxes = Array.from(_selectedIds);
        if (checkedBoxes.length === 0) return;

        const btn = document.getElementById('dsBulkApproveBtn');
        if (btn) {
            if (btn.disabled) return; // Çift tıklama koruması
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin mr-2"></i> Onaylanıyor...';
        }

        // Çalışan iş kontrolü — keşif devam ediyorsa onay engelle
        try {
            const _jcToken = localStorage.getItem('access_token');
            const _jcRes = await fetch(`/api/data-sources/${_currentSourceId}/check-running-job`, {
                headers: { 'Authorization': `Bearer ${_jcToken}` }
            });
            const _jc = await _jcRes.json();
            if (_jc.has_running) {
                _showToast('Keşif işlemi devam ediyor. Tamamlanmasını bekleyin.', 'warning');
                if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-check-double mr-2"></i> Seçilenleri Onayla'; }
                return;
            }
        } catch (e) { /* kontrol başarısız, devam et */ }

        // object_id -> enrichment_id map: _selectedIds stores object_ids
        const objectToEnrichMap = {};
        for (const objectId of checkedBoxes) {
            const row = _pendingData.find(x => String(x.id) === String(objectId));
            if (row && row.enrichment_id) {
                objectToEnrichMap[objectId] = row.enrichment_id;
            }
        }
        const approvableIds = Object.keys(objectToEnrichMap);
        if (approvableIds.length === 0) {
            _showToast('Seçili tablolar henüz keşfedilmemiş, onaylanacak kayıt yok.', 'warning');
            if(btn) { btn.disabled=false; btn.innerHTML = '<i class="fa-solid fa-check-double mr-2"></i> Seçilenleri Onayla'; }
            return;
        }

        try {
            const token = localStorage.getItem('access_token');
            const results = [];
            
            // Send requests sequentially using enrichment_id (not object_id)
            for (const objectId of approvableIds) {
                const enrichmentId = objectToEnrichMap[objectId];
                try {
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
                    results.push({objectId, enrichmentId, success: data.success});
                } catch(err) {
                    console.error("[DSEnrich] Onay hatası id:", objectId, err);
                    results.push({objectId, enrichmentId, success: false});
                }
            }

            const successObjectIds = results.filter(r => r.success).map(r => String(r.objectId));
            
            if (successObjectIds.length > 0) {
                // Başarılı olanları is_approved = true yap
                _pendingData.forEach(p => {
                    if (successObjectIds.includes(String(p.id))) {
                        p.is_approved = true;
                    }
                });
                
                // Seçilenler listesinden kaldır
                successObjectIds.forEach(id => _selectedIds.delete(id));
                
                // UI Güncelle
                applyFilterAndRender();
                setTimeout(() => _updateStatsAfterApprove(), 350);
                
                _showToast(`${successObjectIds.length} tablo onaylandı`, 'success');
            } else {
                _showToast('Toplu onay başarısız', 'error');
            }
        } catch (err) {
            console.error('[DSEnrich] Toplu onay hatası:', err);
            _showToast('Onay sırasında hata oluştu', 'error');
        } finally {
            if(btn) btn.disabled=false; 
            applyFilterAndRender(); // update button state via render
        }
    }

    // ============================================
    // Tümünü Onayla
    // ============================================

    async function bulkApproveAll() {
        // Keşfedilmiş ama onaylanmamış tüm tabloları toplu onayla
        const toApprove = _pendingData.filter(x => x.enrichment_id && !x.is_approved);
        if (toApprove.length === 0) {
            _showToast('Onaylanacak tablo bulunamadı. Önce keşif yapın.', 'warning');
            return;
        }

        const btn = document.getElementById('dsApproveAllBtn');
        if (btn) {
            if (btn.disabled) return; // Çift tıklama koruması
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin mr-2"></i> Onaylanıyor...';
        }

        // Çalışan iş kontrolü — keşif devam ediyorsa onay engelle
        try {
            const _jcToken = localStorage.getItem('access_token');
            const _jcRes = await fetch(`/api/data-sources/${_currentSourceId}/check-running-job`, {
                headers: { 'Authorization': `Bearer ${_jcToken}` }
            });
            const _jc = await _jcRes.json();
            if (_jc.has_running) {
                _showToast('Keşif işlemi devam ediyor. Tamamlanmasını bekleyin.', 'warning');
                if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-check-circle mr-2"></i> Tümünü Onayla'; }
                return;
            }
        } catch (e) { /* kontrol başarısız, devam et */ }

        try {
            const token = localStorage.getItem('access_token');
            let successCount = 0;
            let failCount = 0;

            for (const item of toApprove) {
                try {
                    const res = await fetch(
                        `/api/data-sources/${_currentSourceId}/enrichment-approve/${item.enrichment_id}`,
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
                        item.is_approved = true;
                        successCount++;
                    } else {
                        failCount++;
                    }
                } catch (e) {
                    failCount++;
                }
            }

            if (successCount > 0) {
                const msg = failCount > 0
                    ? `${successCount} tablo onaylandı, ${failCount} başarısız`
                    : `${successCount} tablo onaylandı`;
                _showToast(msg, 'success');
                _updateStatsAfterApprove();
                applyFilterAndRender();
            } else {
                _showToast('Toplu onay başarısız', 'error');
            }
        } catch (err) {
            console.error('[DSEnrich] Tümünü onayla hatası:', err);
            _showToast('Onay sırasında hata oluştu', 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-check-circle mr-2"></i> Tümünü Onayla';
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
            const body = document.getElementById('dsEnrichBody');
            if (body) {
                body.innerHTML = `
                    <div class="ds-enrich-empty">
                        <i class="fa-solid fa-circle-check"></i>
                        <h4>Tüm Tablolar Onaylandı!</h4>
                        <p>Artık tüm tablolar etiketlenmiş ve kullanıma hazır.</p>
                    </div>
                `;
            }
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
        toggleLowScoreFilter,
        toggleShowApprovedFilter,
        togglePendingApprovalFilter,
        changePage,
        toggleCheckbox,
        toggleAllBulk,
        updateBulkCount,
        bulkApprove,
        bulkApproveAll,
        bulkDiscover,
        discoverAll,
        applyFilterAndRender,
        refreshData
    };
})();

// Global erişim
window.DSEnrichmentModule = DSEnrichmentModule;
