/* -----------------------------------------------
   VYRA - DS Learning Module (DB Keşif & Öğrenme)
   Veritabanı keşif pipeline UI kontrolü
   v2.56.0
------------------------------------------------ */

/**
 * DSLearningModule - DB Keşif Wizard ve Öğrenme Geçmişi
 * @module DSLearningModule
 */
window.DSLearningModule = (function () {
    'use strict';

    const API_BASE = window.API_BASE_URL || 'http://localhost:8002';

    // State
    let _currentSourceId = null;
    let _currentSourceName = '';
    let _wizardStep = 0;  // 0: idle, 1: technology, 2: objects, 3: samples, 4: qa_generation
    let _stepResults = {};

    // Toast helper
    function toast(type, message) {
        if (window.VyraToast && typeof window.VyraToast[type] === 'function') {
            window.VyraToast[type](message);
        } else if (typeof showToast === 'function') {
            showToast(message, type);
        } else {
            console.log(`[Toast ${type}]`, message);
        }
    }

    // API helper
    async function apiCall(endpoint, method = 'GET', body = null) {
        const token = localStorage.getItem('access_token');
        const options = {
            method,
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            }
        };
        if (body) options.body = JSON.stringify(body);

        const response = await fetch(`${API_BASE}/api/data-sources${endpoint}`, options);

        // Response body'yi text olarak oku, sonra JSON parse dene
        const text = await response.text();
        let data;
        try {
            data = JSON.parse(text);
        } catch (_parseErr) {
            // Backend düzgün JSON dönmedi — anlamlı hata objesi üret
            console.error('[DSLearning] JSON parse hatası:', text.substring(0, 200));
            return { success: false, message: `Sunucu hatası (HTTP ${response.status})` };
        }

        // HTTP hata durumunda success: false dön
        if (!response.ok && data.success === undefined) {
            return { success: false, message: data.detail || data.message || `HTTP ${response.status}` };
        }

        return data;
    }

    // ============================================
    // Wizard Modal
    // ============================================

    function openWizard(sourceId, sourceName) {
        _currentSourceId = sourceId;
        _currentSourceName = sourceName;
        _wizardStep = 0;
        _stepResults = {};

        // Modal varsa kaldır
        const existing = document.getElementById('dsLearningWizardModal');
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.id = 'dsLearningWizardModal';
        modal.className = 'ds-wizard-overlay';
        modal.innerHTML = `
            <div class="ds-wizard-modal">
                <div class="ds-wizard-header">
                    <div class="ds-wizard-title">
                        <i class="fa-solid fa-magnifying-glass-chart"></i>
                        <span>DB Keşif — ${_escapeHtml(sourceName)}</span>
                    </div>
                    <button class="ds-wizard-close" id="dsWizardClose" title="Kapat">
                        <i class="fa-solid fa-times"></i>
                    </button>
                </div>

                <div class="ds-wizard-steps">
                    <div class="ds-step" id="dsStep1" data-step="1">
                        <div class="ds-step-circle">1</div>
                        <span class="ds-step-label">Teknoloji Keşfi</span>
                    </div>
                    <div class="ds-step-line" id="dsStepLine1"></div>
                    <div class="ds-step" id="dsStep2" data-step="2">
                        <div class="ds-step-circle">2</div>
                        <span class="ds-step-label">Obje Tespiti</span>
                    </div>
                    <div class="ds-step-line" id="dsStepLine2"></div>
                    <div class="ds-step" id="dsStep3" data-step="3">
                        <div class="ds-step-circle">3</div>
                        <span class="ds-step-label">Veri Toplama</span>
                    </div>
                </div>

                <div class="ds-wizard-body" id="dsWizardBody">
                    <div class="ds-wizard-intro">
                        <div class="ds-wizard-intro-icon">
                            <i class="fa-solid fa-database"></i>
                        </div>
                        <h3>Veritabanı Keşfi Başlat</h3>
                        <p>3 aşamalı keşif pipeline'ı çalıştırılacak:</p>
                        <ul class="ds-wizard-intro-list">
                            <li><i class="fa-solid fa-microchip"></i> <strong>Adım 1:</strong> DB teknoloji ve şema keşfi</li>
                            <li><i class="fa-solid fa-table-cells"></i> <strong>Adım 2:</strong> Tablo, sütun ve ilişki tespiti</li>
                            <li><i class="fa-solid fa-download"></i> <strong>Adım 3:</strong> Örnek veri toplama</li>
                        </ul>
                        <button class="ds-wizard-start-btn" id="dsWizardStartBtn">
                            <i class="fa-solid fa-rocket"></i> Keşfi Başlat
                        </button>
                    </div>
                </div>

                <div class="ds-wizard-footer" id="dsWizardFooter" style="display:none;">
                    <button class="ds-wizard-btn secondary" id="dsWizardPrevBtn" style="display:none;">
                        <i class="fa-solid fa-arrow-left"></i> Önceki
                    </button>
                    <button class="ds-wizard-btn primary" id="dsWizardNextBtn" style="display:none;">
                        Sonraki <i class="fa-solid fa-arrow-right"></i>
                    </button>
                    <button class="ds-wizard-btn success" id="dsWizardViewResultsBtn" style="display:none;">
                        <i class="fa-solid fa-chart-bar"></i> Sonuçları Görüntüle
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        const startBtn = document.getElementById('dsWizardStartBtn');
        const closeBtn = document.getElementById('dsWizardClose');

        // Mevcut durumu kontrol et
        const checkStatus = async () => {
            startBtn.disabled = true;
            startBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Durum Kontrol Ediliyor...';
            try {
                const statusRes = await apiCall(`/${sourceId}/discovery-status`);
                let isRunning = false;
                if (statusRes && !statusRes.error) {
                    if (statusRes.technology?.status === 'running' || 
                        statusRes.objects?.status === 'running' || 
                        statusRes.samples?.status === 'running') {
                        isRunning = true;
                    }
                }
                
                if (isRunning) {
                    startBtn.innerHTML = '<i class="fa-solid fa-ban"></i> Mevcut Keşif Sürüyor...';
                    startBtn.disabled = true;
                    startBtn.style.background = '#475569';
                    startBtn.style.cursor = 'not-allowed';
                    toast('warning', 'Şu anda arka planda devam eden bir keşif veya öğrenme işlemi var.');
                } else {
                    startBtn.innerHTML = '<i class="fa-solid fa-rocket"></i> Keşfi Başlat';
                    startBtn.disabled = false;
                }
            } catch (err) {
                startBtn.innerHTML = '<i class="fa-solid fa-rocket"></i> Keşfi Başlat';
                startBtn.disabled = false;
            }
        };

        // Events
        closeBtn.addEventListener('click', closeWizard);
        startBtn.addEventListener('click', () => {
            if (!startBtn.disabled) runStep(1);
        });

        // Hızlıca durumu check et
        checkStatus();

        // ESC desteği
        modal._escHandler = (e) => { if (e.key === 'Escape') closeWizard(); };
        document.addEventListener('keydown', modal._escHandler);

        // Animasyon
        requestAnimationFrame(() => modal.classList.add('active'));
    }

    function closeWizard() {
        const modal = document.getElementById('dsLearningWizardModal');
        if (modal) {
            if (modal._escHandler) document.removeEventListener('keydown', modal._escHandler);
            modal.classList.remove('active');
            setTimeout(() => modal.remove(), 300);
        }
    }

    // ============================================
    // Wizard Steps
    // ============================================

    async function runStep(step) {
        _wizardStep = step;
        _updateStepIndicator(step, 'running');
        _showStepLoading(step);

        const endpoints = {
            1: `/${_currentSourceId}/discover`,
            2: `/${_currentSourceId}/detect-objects`,
            3: `/${_currentSourceId}/collect-samples`
        };
        const stepNames = {
            1: 'Teknoloji Keşfi',
            2: 'Obje Tespiti',
            3: 'Veri Toplama'
        };

        try {
            const result = await apiCall(endpoints[step], 'POST');
            _stepResults[step] = result;

            if (result.success) {
                _updateStepIndicator(step, 'completed');
                _showStepResult(step, result);
                toast('success', `${stepNames[step]} tamamlandı`);

                // Otomatik sonraki adıma geç
                if (step < 3) {
                    _showAutoNextButton(step);
                } else {
                    _showFinalResults();
                }
            } else {
                _updateStepIndicator(step, 'failed');
                _showStepError(step, result.message || 'Bilinmeyen hata');
                toast('error', `${stepNames[step]} başarısız`);
            }
        } catch (err) {
            _updateStepIndicator(step, 'failed');
            _showStepError(step, err.message || 'Bağlantı hatası');
            toast('error', `${stepNames[step]} sırasında hata oluştu`);
        }
    }

    function _updateStepIndicator(step, status) {
        const stepEl = document.getElementById(`dsStep${step}`);
        if (!stepEl) return;
        stepEl.className = `ds-step ${status}`;

        const circle = stepEl.querySelector('.ds-step-circle');
        if (status === 'running') {
            circle.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
        } else if (status === 'completed') {
            circle.innerHTML = '<i class="fa-solid fa-check"></i>';
        } else if (status === 'failed') {
            circle.innerHTML = '<i class="fa-solid fa-times"></i>';
        }

        // Step line
        if (step < 3) {
            const line = document.getElementById(`dsStepLine${step}`);
            if (line) {
                line.classList.toggle('active', status === 'completed');
            }
        }
    }

    function _showStepLoading(step) {
        const body = document.getElementById('dsWizardBody');
        const stepNames = { 1: 'Teknoloji keşfi', 2: 'Obje tespiti', 3: 'Veri toplama' };
        const stepIcons = { 1: 'fa-microchip', 2: 'fa-table-cells', 3: 'fa-download' };
        body.innerHTML = `
            <div class="ds-step-loading">
                <div class="ds-step-loading-icon">
                    <i class="fa-solid ${stepIcons[step]} fa-pulse"></i>
                </div>
                <h3>Adım ${step}: ${stepNames[step]}</h3>
                <p>İşlem devam ediyor, lütfen bekleyin...</p>
                <div class="ds-step-loading-bar">
                    <div class="ds-step-loading-bar-inner"></div>
                </div>
            </div>
        `;
    }

    function _showStepResult(step, result) {
        const body = document.getElementById('dsWizardBody');

        if (step === 1) {
            // Teknoloji sonuçları
            const schemas = (result.schemas || []).join(', ') || '-';
            body.innerHTML = `
                <div class="ds-step-result">
                    <div class="ds-step-result-header success">
                        <i class="fa-solid fa-check-circle"></i> Teknoloji Keşfi Tamamlandı
                    </div>
                    <div class="ds-step-result-grid">
                        <div class="ds-result-card">
                            <div class="ds-result-card-label">Veritabanı Motoru</div>
                            <div class="ds-result-card-value">${_escapeHtml(result.db_dialect || '-')}</div>
                        </div>
                        <div class="ds-result-card">
                            <div class="ds-result-card-label">Versiyon</div>
                            <div class="ds-result-card-value small">${_escapeHtml((result.db_version || '-').substring(0, 80))}</div>
                        </div>
                        <div class="ds-result-card">
                            <div class="ds-result-card-label">Şemalar</div>
                            <div class="ds-result-card-value">${result.schemas ? result.schemas.length : 0}</div>
                        </div>
                        <div class="ds-result-card">
                            <div class="ds-result-card-label">Karakter Seti</div>
                            <div class="ds-result-card-value">${_escapeHtml(result.character_set || '-')}</div>
                        </div>
                    </div>
                    <div class="ds-result-detail">
                        <strong>Bulunan Şemalar:</strong> ${_escapeHtml(schemas)}
                    </div>
                    <div class="ds-result-elapsed">
                        <i class="fa-solid fa-clock"></i> ${result.elapsed_ms || 0}ms
                    </div>
                </div>
            `;
        } else if (step === 2) {
            body.innerHTML = `
                <div class="ds-step-result">
                    <div class="ds-step-result-header success">
                        <i class="fa-solid fa-check-circle"></i> Obje Tespiti Tamamlandı
                    </div>
                    <div class="ds-step-result-grid">
                        <div class="ds-result-card">
                            <div class="ds-result-card-label">Tablolar</div>
                            <div class="ds-result-card-value">${result.table_count || 0}</div>
                        </div>
                        <div class="ds-result-card">
                            <div class="ds-result-card-label">View'lar</div>
                            <div class="ds-result-card-value">${result.view_count || 0}</div>
                        </div>
                        <div class="ds-result-card">
                            <div class="ds-result-card-label">FK İlişkileri</div>
                            <div class="ds-result-card-value">${result.relationship_count || 0}</div>
                        </div>
                        <div class="ds-result-card">
                            <div class="ds-result-card-label">Toplam Sütun</div>
                            <div class="ds-result-card-value">${result.total_columns || 0}</div>
                        </div>
                    </div>
                    <div class="ds-result-elapsed">
                        <i class="fa-solid fa-clock"></i> ${result.elapsed_ms || 0}ms
                    </div>
                </div>
            `;
        } else if (step === 3) {
            const failedHtml = (result.failed_details && result.failed_details.length > 0)
                ? `<div class="ds-result-warning"><i class="fa-solid fa-triangle-exclamation"></i> ${result.tables_failed} tablo okunamadı</div>` : '';
            body.innerHTML = `
                <div class="ds-step-result">
                    <div class="ds-step-result-header success">
                        <i class="fa-solid fa-check-circle"></i> Veri Toplama Tamamlandı
                    </div>
                    <div class="ds-step-result-grid">
                        <div class="ds-result-card">
                            <div class="ds-result-card-label">Örneklenen Tablolar</div>
                            <div class="ds-result-card-value">${result.tables_sampled || 0}</div>
                        </div>
                        <div class="ds-result-card">
                            <div class="ds-result-card-label">Başarısız</div>
                            <div class="ds-result-card-value">${result.tables_failed || 0}</div>
                        </div>
                    </div>
                    ${failedHtml}
                    <div class="ds-result-elapsed">
                        <i class="fa-solid fa-clock"></i> ${result.elapsed_ms || 0}ms
                    </div>
                </div>
            `;
        }
    }

    function _showStepError(step, message) {
        const body = document.getElementById('dsWizardBody');
        body.innerHTML = `
            <div class="ds-step-result">
                <div class="ds-step-result-header error">
                    <i class="fa-solid fa-times-circle"></i> Adım ${step} Başarısız
                </div>
                <div class="ds-step-error-msg">
                    <pre>${_escapeHtml(message)}</pre>
                </div>
                <button class="ds-wizard-btn primary" onclick="DSLearningModule.retryStep(${step})">
                    <i class="fa-solid fa-redo"></i> Tekrar Dene
                </button>
            </div>
        `;
    }

    function _showAutoNextButton(step) {
        const body = document.getElementById('dsWizardBody');
        const currentHtml = body.innerHTML;
        const nextStep = step + 1;
        const nextNames = { 2: 'Obje Tespiti', 3: 'Veri Toplama' };

        body.innerHTML = currentHtml + `
            <div class="ds-wizard-auto-next">
                <button class="ds-wizard-btn primary ds-auto-next-btn" id="dsAutoNextBtn">
                    <i class="fa-solid fa-arrow-right"></i> ${nextNames[nextStep]} Başlat (Adım ${nextStep})
                </button>
                <button class="ds-wizard-btn secondary" onclick="DSLearningModule.closeWizard()">
                    <i class="fa-solid fa-stop"></i> Durdur
                </button>
            </div>
        `;

        document.getElementById('dsAutoNextBtn').addEventListener('click', () => runStep(nextStep));

        // 2 saniye sonra otomatik başlat
        setTimeout(() => {
            const btn = document.getElementById('dsAutoNextBtn');
            if (btn && _wizardStep === step) {
                runStep(nextStep);
            }
        }, 2000);
    }

    function _showFinalResults() {
        const body = document.getElementById('dsWizardBody');
        const currentHtml = body.innerHTML;
        body.innerHTML = currentHtml + `
            <div class="ds-wizard-final">
                <div class="ds-wizard-final-badge">
                    <i class="fa-solid fa-trophy"></i>
                </div>
                <h3>Keşif Tamamlandı!</h3>
                <p>Tüm adımlar başarıyla tamamlandı. Detayları görüntüleyebilir veya yapay zeka ile <b>Tam Öğrenme (Enrichment)</b> sürecini başlatarak tabloları RAG sistemine hazırlayabilirsiniz.</p>
                <div class="ds-wizard-final-actions" style="flex-wrap: wrap; justify-content: center; gap: 8px;">
                    <button class="ds-wizard-btn primary" id="dsRunFullLearningBtn" style="background: var(--accent); color: white;">
                        <i class="fa-solid fa-brain"></i> Tam Öğrenme Başlat
                    </button>
                    <button class="ds-wizard-btn secondary" id="dsEnrichBtn">
                        <i class="fa-solid fa-tags"></i> Tablo Onay Paneli
                    </button>
                    <button class="ds-wizard-btn secondary" id="dsViewDetailsBtn">
                        <i class="fa-solid fa-table-list"></i> Detayları Görüntüle
                    </button>
                    <button class="ds-wizard-btn secondary" id="dsScheduleBtn">
                        <i class="fa-solid fa-clock"></i> Zamanlama
                    </button>
                    <button class="ds-wizard-btn secondary" onclick="DSLearningModule.closeWizard()">
                        <i class="fa-solid fa-check"></i> Kapat
                    </button>
                </div>
            </div>
        `;

        document.getElementById('dsRunFullLearningBtn').addEventListener('click', async (e) => {
            const btn = e.currentTarget;
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Başlatılıyor...';
            try {
                await runFullLearning(_currentSourceId, _currentSourceName || 'Veri Kaynağı');
            } catch (err) { }
            
            // Arka planda çalışmaya devam edeceği için butonu kapalı tutup kullanıcıya bilgi veriyoruz
            setTimeout(() => {
                btn.innerHTML = '<i class="fa-solid fa-clock"></i> Arka Planda Çalışıyor...';
                btn.style.background = '#475569'; // Gri renk yapalım ki aktif olmadığı belli olsun
                btn.style.cursor = 'not-allowed';
                // btn.disabled = false; -> İptal edildi, tekrar tıklanması engellendi.
            }, 2000);
        });

        document.getElementById('dsEnrichBtn').addEventListener('click', () => {
            if (window.DSEnrichmentModule) {
                DSEnrichmentModule.openPanel(_currentSourceId);
            }
        });
        document.getElementById('dsViewDetailsBtn').addEventListener('click', () => showDiscoveryDetails(_currentSourceId));
        document.getElementById('dsScheduleBtn').addEventListener('click', () => showScheduleModal(_currentSourceId));
    }

    function retryStep(step) {
        runStep(step);
    }

    // ============================================
    // Keşif Detayları Modal
    // ============================================

    async function showDiscoveryDetails(sourceId) {
        try {
            const data = await apiCall(`/${sourceId}/discovery-details`);
            const status = await apiCall(`/${sourceId}/discovery-status`);

            const existing = document.getElementById('dsDetailsModal');
            if (existing) existing.remove();

            const modal = document.createElement('div');
            modal.id = 'dsDetailsModal';
            modal.className = 'ds-wizard-overlay';

            // Objects tablosu
            let objectsHtml = '';
            if (data.objects && data.objects.length > 0) {
                objectsHtml = `
                    <div class="ds-details-section">
                        <h4><i class="fa-solid fa-table"></i> Bulunan Objeler (${data.objects.length})</h4>
                        <div class="ds-details-table-wrap">
                            <table class="ds-details-table">
                                <thead>
                                    <tr><th>Şema</th><th>Obje Adı</th><th>Tip</th><th>Sütun</th><th>Satır (Tahmini)</th></tr>
                                </thead>
                                <tbody>
                                    ${data.objects.map(o => `
                                        <tr class="ds-detail-row" onclick="DSLearningModule.showObjectColumns(${o.id}, '${_escapeHtml(o.object_name)}')">
                                            <td>${_escapeHtml(o.schema_name || '-')}</td>
                                            <td><strong>${_escapeHtml(o.object_name)}</strong></td>
                                            <td><span class="ds-obj-type-badge ${o.object_type}">${o.object_type}</span></td>
                                            <td>${o.column_count}</td>
                                            <td>${_formatNumber(o.row_count_estimate)}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                    </div>
                `;
            }

            // İlişkiler tablosu
            let relsHtml = '';
            if (data.relationships && data.relationships.length > 0) {
                relsHtml = `
                    <div class="ds-details-section">
                        <h4><i class="fa-solid fa-link"></i> İlişkiler (${data.relationships.length})</h4>
                        <div class="ds-details-table-wrap">
                            <table class="ds-details-table">
                                <thead>
                                    <tr><th>Kaynak Tablo</th><th>Kaynak Sütun</th><th></th><th>Hedef Tablo</th><th>Hedef Sütun</th></tr>
                                </thead>
                                <tbody>
                                    ${data.relationships.map(r => `
                                        <tr>
                                            <td>${_escapeHtml(r.from_table)}</td>
                                            <td>${_escapeHtml(r.from_column)}</td>
                                            <td><i class="fa-solid fa-arrow-right" style="color: var(--accent-primary);"></i></td>
                                            <td>${_escapeHtml(r.to_table)}</td>
                                            <td>${_escapeHtml(r.to_column)}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                    </div>
                `;
            }

            // Özet kartları
            const summaryHtml = `
                <div class="ds-step-result-grid">
                    <div class="ds-result-card">
                        <div class="ds-result-card-label">Toplam Obje</div>
                        <div class="ds-result-card-value">${status.total_objects || 0}</div>
                    </div>
                    <div class="ds-result-card">
                        <div class="ds-result-card-label">İlişkiler</div>
                        <div class="ds-result-card-value">${status.total_relationships || 0}</div>
                    </div>
                    <div class="ds-result-card">
                        <div class="ds-result-card-label">Örnek Veriler</div>
                        <div class="ds-result-card-value">${status.total_samples || 0}</div>
                    </div>
                </div>
            `;

            modal.innerHTML = `
                <div class="ds-wizard-modal ds-details-modal">
                    <div class="ds-wizard-header">
                        <div class="ds-wizard-title">
                            <i class="fa-solid fa-chart-bar"></i>
                            <span>Keşif Sonuçları — ${_escapeHtml(_currentSourceName)}</span>
                        </div>
                        <button class="ds-wizard-close" id="dsDetailsClose">
                            <i class="fa-solid fa-times"></i>
                        </button>
                    </div>
                    <div class="ds-wizard-body ds-details-body">
                        ${summaryHtml}
                        ${objectsHtml}
                        ${relsHtml}
                    </div>
                </div>
            `;

            document.body.appendChild(modal);
            document.getElementById('dsDetailsClose').addEventListener('click', () => {
                modal.classList.remove('active');
                setTimeout(() => modal.remove(), 300);
            });
            document.addEventListener('keydown', function escHandler(e) {
                if (e.key === 'Escape') {
                    modal.classList.remove('active');
                    setTimeout(() => modal.remove(), 300);
                    document.removeEventListener('keydown', escHandler);
                }
            });
            requestAnimationFrame(() => modal.classList.add('active'));

        } catch (err) {
            toast('error', 'Keşif detayları yüklenemedi: ' + err.message);
        }
    }

    // Obje sütunlarını gösteren küçük popup
    function showObjectColumns(objectId, objectName) {
        // Mevcut detay modal'dan objeyi bul
        apiCall(`/${_currentSourceId}/discovery-details`).then(data => {
            const obj = (data.objects || []).find(o => o.id === objectId);
            if (!obj || !obj.columns) {
                toast('info', 'Sütun bilgisi bulunamadı');
                return;
            }

            const columns = Array.isArray(obj.columns) ? obj.columns : [];
            const colHtml = columns.map(c => `
                <tr>
                    <td>${c.is_pk ? '<i class="fa-solid fa-key" style="color: gold;"></i>' : ''} ${_escapeHtml(c.name)}</td>
                    <td><code>${_escapeHtml(c.data_type)}</code></td>
                    <td>${c.is_nullable ? '<span class="ds-nullable">NULL</span>' : '<span class="ds-notnull">NOT NULL</span>'}</td>
                </tr>
            `).join('');

            if (window.VyraModal && typeof window.VyraModal.info === 'function') {
                VyraModal.info({
                    title: `📋 ${objectName} — Sütunlar (${columns.length})`,
                    message: `
                        <div class="ds-columns-popup">
                            <table class="ds-details-table compact">
                                <thead><tr><th>Sütun</th><th>Tip</th><th>Nullable</th></tr></thead>
                                <tbody>${colHtml}</tbody>
                            </table>
                        </div>
                    `,
                    confirmText: 'Kapat'
                });
            }
        });
    }

    // ============================================
    // Keşif Geçmişi
    // ============================================

    async function loadHistory(sourceId) {
        try {
            const data = await apiCall(`/${sourceId}/learning-history`);
            const history = data.history || [];
            const container = document.getElementById('dsLearningHistoryBody');
            if (!container) return;

            if (history.length === 0) {
                container.innerHTML = `
                    <tr class="empty-row">
                        <td colspan="5"><i class="fa-solid fa-inbox"></i> Henüz keşif yapılmamış</td>
                    </tr>
                `;
                return;
            }

            // Running job var mı kontrol et — butonları disable/enable
            const hasRunningJob = history.some(j => j.status === 'running');
            const fullBtn = document.getElementById('dsHistoryRunFull');
            if (fullBtn) {
                fullBtn.disabled = hasRunningJob;
                if (hasRunningJob) {
                    fullBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Çalışıyor...';
                    fullBtn.classList.add('ds-btn-disabled');
                } else {
                    fullBtn.innerHTML = '<i class="fa-solid fa-rocket"></i> Tam Pipeline Başlat';
                    fullBtn.classList.remove('ds-btn-disabled');
                }
            }

            // Auto-refresh eğer running job varsa
            if (hasRunningJob) {
                setTimeout(() => loadHistory(sourceId), 3000);
            }

            container.innerHTML = history.map(job => {
                const date = job.started_at ? _formatDateTime(job.started_at) : '-';
                const typeLabels = {
                    'technology': 'Teknoloji',
                    'objects': 'Obje Tespiti',
                    'samples': 'Veri Toplama',
                    'learning': 'Öğrenme',
                    'qa_generation': 'QA Üretimi',
                    'full_learning': 'Tam Pipeline'
                };
                const typeLabel = typeLabels[job.job_type] || job.job_type;
                const duration = job.duration_ms ? `${(job.duration_ms / 1000).toFixed(1)}s` : '-';

                let statusClass = '', statusIcon = '', statusLabel = '';
                switch (job.status) {
                    case 'completed':
                        statusClass = 'success'; statusIcon = 'fa-check-circle'; statusLabel = 'Başarılı'; break;
                    case 'failed':
                        statusClass = 'error'; statusIcon = 'fa-times-circle'; statusLabel = 'Başarısız'; break;
                    case 'running':
                        statusClass = 'running'; statusIcon = 'fa-spinner fa-spin'; statusLabel = 'Çalışıyor'; break;
                    default:
                        statusClass = 'pending'; statusIcon = 'fa-clock'; statusLabel = 'Bekliyor';
                }

                // Detay sütunu: başarılı işlerde tıklanabilir detay ikonu
                let detailHtml = '-';
                if (job.status === 'completed' && job.result_summary) {
                    detailHtml = `<button class="ds-detail-view-btn" data-job-id="${job.id}" data-job-type="${job.job_type}" data-result='${_escapeHtml(JSON.stringify(job.result_summary))}' title="Detayları Görüntüle">
                        <i class="fa-solid fa-eye"></i>
                    </button>`;
                } else if (job.error_message) {
                    detailHtml = `<span class="ds-error-hint" title="${_escapeHtml(job.error_message.substring(0, 200))}"><i class="fa-solid fa-info-circle"></i></span>`;
                }

                return `
                    <tr>
                        <td>${date}</td>
                        <td><span class="ds-job-type-badge ${job.job_type}">${typeLabel}</span></td>
                        <td>${duration}</td>
                        <td><span class="status-badge ${statusClass}"><i class="fa-solid ${statusIcon}"></i> ${statusLabel}</span></td>
                        <td>${detailHtml}</td>
                    </tr>
                `;
            }).join('');

            // Detay butonlarına event listener ekle
            container.querySelectorAll('.ds-detail-view-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    try {
                        const result = JSON.parse(btn.dataset.result);
                        showJobDetail(btn.dataset.jobType, result);
                    } catch (e) {
                        console.error('Job detail parse error:', e);
                    }
                });
            });

        } catch (err) {
            console.error('[DSLearning] History load error:', err);
        }
    }

    // ============================================
    // Job Detay Popup Modal
    // ============================================

    function showJobDetail(jobType, resultData) {
        const existing = document.getElementById('dsJobDetailModal');
        if (existing) existing.remove();

        let bodyContent = '';
        const typeNames = {
            'technology': 'Teknoloji Keşfi',
            'objects': 'Obje Tespiti',
            'samples': 'Veri Toplama',
            'qa_generation': 'QA Üretimi',
            'full_learning': 'Tam Pipeline'
        };
        const typeName = typeNames[jobType] || jobType;

        if (jobType === 'qa_generation') {
            const qaPairs = resultData.qa_pairs_generated || 0;
            const schemas = resultData.schema_descriptions || 0;
            const rels = resultData.relationship_maps || 0;
            const samples = resultData.sample_insights || 0;
            const aggs = resultData.aggregate_queries || 0;
            const elapsed = resultData.elapsed_ms ? `${(resultData.elapsed_ms / 1000).toFixed(1)}s` : '-';

            bodyContent = `
                <div class="ds-job-detail-summary">
                    <div class="ds-job-detail-total">
                        <div class="ds-job-detail-total-num">${qaPairs}</div>
                        <div class="ds-job-detail-total-label">Toplam QA Çifti Üretildi</div>
                    </div>
                </div>
                <div class="ds-step-result-grid" style="margin-top: 16px;">
                    <div class="ds-result-card">
                        <div class="ds-result-card-label">Şema Açıklaması</div>
                        <div class="ds-result-card-value">${schemas}</div>
                    </div>
                    <div class="ds-result-card">
                        <div class="ds-result-card-label">İlişki Haritası</div>
                        <div class="ds-result-card-value">${rels}</div>
                    </div>
                    <div class="ds-result-card">
                        <div class="ds-result-card-label">Örnek Veri</div>
                        <div class="ds-result-card-value">${samples}</div>
                    </div>
                    <div class="ds-result-card">
                        <div class="ds-result-card-label">SQL Sorguları</div>
                        <div class="ds-result-card-value">${aggs}</div>
                    </div>
                </div>
                <div class="ds-result-elapsed" style="margin-top: 12px;">
                    <i class="fa-solid fa-clock"></i> İşlem Süresi: ${elapsed}
                </div>
            `;
        } else if (jobType === 'technology') {
            bodyContent = `
                <div class="ds-step-result-grid">
                    <div class="ds-result-card">
                        <div class="ds-result-card-label">DB Motoru</div>
                        <div class="ds-result-card-value">${_escapeHtml(resultData.db_dialect || '-')}</div>
                    </div>
                    <div class="ds-result-card">
                        <div class="ds-result-card-label">Şema Sayısı</div>
                        <div class="ds-result-card-value">${resultData.schema_count || 0}</div>
                    </div>
                    <div class="ds-result-card">
                        <div class="ds-result-card-label">Karakter Seti</div>
                        <div class="ds-result-card-value">${_escapeHtml(resultData.character_set || '-')}</div>
                    </div>
                </div>
                <div class="ds-result-elapsed" style="margin-top: 12px;">
                    <i class="fa-solid fa-clock"></i> ${resultData.elapsed_ms || 0}ms
                </div>
            `;
        } else if (jobType === 'objects') {
            bodyContent = `
                <div class="ds-step-result-grid">
                    <div class="ds-result-card">
                        <div class="ds-result-card-label">Tablolar</div>
                        <div class="ds-result-card-value">${resultData.table_count || 0}</div>
                    </div>
                    <div class="ds-result-card">
                        <div class="ds-result-card-label">View'lar</div>
                        <div class="ds-result-card-value">${resultData.view_count || 0}</div>
                    </div>
                    <div class="ds-result-card">
                        <div class="ds-result-card-label">FK İlişkileri</div>
                        <div class="ds-result-card-value">${resultData.relationship_count || 0}</div>
                    </div>
                    <div class="ds-result-card">
                        <div class="ds-result-card-label">Toplam Sütun</div>
                        <div class="ds-result-card-value">${resultData.total_columns || 0}</div>
                    </div>
                </div>
                <div class="ds-result-elapsed" style="margin-top: 12px;">
                    <i class="fa-solid fa-clock"></i> ${resultData.elapsed_ms || 0}ms
                </div>
            `;
        } else if (jobType === 'samples') {
            bodyContent = `
                <div class="ds-step-result-grid">
                    <div class="ds-result-card">
                        <div class="ds-result-card-label">Örneklenen</div>
                        <div class="ds-result-card-value">${resultData.tables_sampled || 0}</div>
                    </div>
                    <div class="ds-result-card">
                        <div class="ds-result-card-label">Başarısız</div>
                        <div class="ds-result-card-value">${resultData.tables_failed || 0}</div>
                    </div>
                </div>
                <div class="ds-result-elapsed" style="margin-top: 12px;">
                    <i class="fa-solid fa-clock"></i> ${resultData.elapsed_ms || 0}ms
                </div>
            `;
        } else {
            // Genel fallback: JSON gösterimi
            bodyContent = `
                <div class="ds-job-detail-json">
                    <pre>${_escapeHtml(JSON.stringify(resultData, null, 2))}</pre>
                </div>
            `;
        }

        const modal = document.createElement('div');
        modal.id = 'dsJobDetailModal';
        modal.className = 'ds-wizard-overlay';
        modal.innerHTML = `
            <div class="ds-wizard-modal" style="max-width: 520px;">
                <div class="ds-wizard-header">
                    <div class="ds-wizard-title">
                        <i class="fa-solid fa-chart-pie"></i>
                        <span>İş Detayı — ${typeName}</span>
                    </div>
                    <button class="ds-wizard-close" id="dsJobDetailClose">
                        <i class="fa-solid fa-times"></i>
                    </button>
                </div>
                <div class="ds-wizard-body" style="padding: 1.5rem;">
                    ${bodyContent}
                </div>
                <div class="ds-wizard-footer" style="display: flex; justify-content: flex-end; padding: 1rem 1.5rem;">
                    <button class="ds-wizard-btn secondary" id="dsJobDetailOk">Kapat</button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
        requestAnimationFrame(() => modal.classList.add('active'));

        const closeDetail = () => { modal.classList.remove('active'); setTimeout(() => modal.remove(), 300); };
        document.getElementById('dsJobDetailClose').addEventListener('click', closeDetail);
        document.getElementById('dsJobDetailOk').addEventListener('click', closeDetail);
        document.addEventListener('keydown', function escJd(e) {
            if (e.key === 'Escape') { closeDetail(); document.removeEventListener('keydown', escJd); }
        });
    }

    // ============================================
    // Öğrenme Sonuçları Popup (ML QA Çiftleri)
    // ============================================

    async function showLearningResults(sourceId) {
        const existing = document.getElementById('dsLearningResultsModal');
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.id = 'dsLearningResultsModal';
        modal.className = 'ds-wizard-overlay';
        modal.innerHTML = `
            <div class="ds-wizard-modal ds-details-modal ds-lr-modal">
                <div class="ds-wizard-header">
                    <div class="ds-wizard-title">
                        <i class="fa-solid fa-graduation-cap"></i>
                        <span>ML Öğrenme Sonuçları — ${_escapeHtml(_currentSourceName || '')}</span>
                    </div>
                    <button class="ds-wizard-close" id="dsLrClose">
                        <i class="fa-solid fa-times"></i>
                    </button>
                </div>
                <div class="ds-lr-job-filter" id="dsLrJobFilter">
                    <label><i class="fa-solid fa-clock-rotate-left"></i> İş Geçmişi:</label>
                    <select id="dsLrJobSelect" class="ds-form-select ds-lr-job-select">
                        <option value="">Tüm İşler</option>
                    </select>
                </div>
                <div class="ds-lr-tabs" id="dsLrTabs">
                    <button class="ds-lr-tab active" data-type="">Tümü</button>
                    <button class="ds-lr-tab" data-type="schema_description">Şema Bilgileri</button>
                    <button class="ds-lr-tab" data-type="sample_insight">Örnek Veriler</button>
                    <button class="ds-lr-tab" data-type="aggregate_query">SQL Sorguları</button>
                    <button class="ds-lr-tab" data-type="relationship_map">İlişki Haritaları</button>
                </div>
                <div class="ds-lr-summary" id="dsLrSummary"></div>
                <div class="ds-wizard-body ds-details-body ds-lr-body" id="dsLrBody">
                    <div class="ds-lr-loading"><i class="fa-solid fa-spinner fa-spin"></i> Yükleniyor...</div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
        requestAnimationFrame(() => modal.classList.add('active'));

        const closeLr = () => { modal.classList.remove('active'); setTimeout(() => modal.remove(), 300); };
        document.getElementById('dsLrClose').addEventListener('click', closeLr);
        document.addEventListener('keydown', function escLr(e) {
            if (e.key === 'Escape') { closeLr(); document.removeEventListener('keydown', escLr); }
        });

        // İş geçmişi dropdown'ını doldur
        try {
            const statsData = await apiCall(`/${sourceId}/job-result-stats`);
            const select = document.getElementById('dsLrJobSelect');
            if (statsData.stats && statsData.stats.length > 0) {
                statsData.stats.forEach(s => {
                    const date = s.started_at ? _formatDateTime(s.started_at) : '?';
                    const opt = document.createElement('option');
                    opt.value = s.job_id;
                    opt.textContent = `${date} — ${s.result_count} QA (${s.type_count} tip)`;
                    select.appendChild(opt);
                });
            }
        } catch (e) { /* dropdown opsiyonel */ }

        // Dropdown seçimi
        document.getElementById('dsLrJobSelect').addEventListener('change', () => {
            const activeTab = document.querySelector('.ds-lr-tab.active');
            const contentType = activeTab ? activeTab.dataset.type || null : null;
            const jobId = document.getElementById('dsLrJobSelect').value || null;
            _loadLearningResults(sourceId, contentType, jobId);
        });

        // Tab tıklama
        document.getElementById('dsLrTabs').addEventListener('click', (e) => {
            const tab = e.target.closest('.ds-lr-tab');
            if (!tab) return;
            document.querySelectorAll('.ds-lr-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            const jobId = document.getElementById('dsLrJobSelect').value || null;
            _loadLearningResults(sourceId, tab.dataset.type || null, jobId);
        });

        // İlk yükleme
        await _loadLearningResults(sourceId, null, null);
    }

    async function _loadLearningResults(sourceId, contentType, jobId) {
        const body = document.getElementById('dsLrBody');
        const summary = document.getElementById('dsLrSummary');
        if (!body) return;

        body.innerHTML = '<div class="ds-lr-loading"><i class="fa-solid fa-spinner fa-spin"></i> Yükleniyor...</div>';

        try {
            let url = `/${sourceId}/learning-results?limit=100`;
            if (contentType) url += `&content_type=${contentType}`;
            if (jobId) url += `&job_id=${jobId}`;
            const data = await apiCall(url);
            const results = data.results || [];
            const typeCounts = data.type_counts || {};
            const total = data.total || 0;

            // Özet bilgi
            const typeLabels = {
                'schema_description': 'Şema',
                'relationship_map': 'İlişki',
                'sample_insight': 'Örnek Veri',
                'aggregate_query': 'SQL Sorgu'
            };
            summary.innerHTML = `
                <div class="ds-lr-summary-inner">
                    <div class="ds-lr-stat"><span class="ds-lr-stat-num">${total}</span><span class="ds-lr-stat-label">Toplam QA</span></div>
                    ${Object.entries(typeCounts).map(([t, c]) =>
                        `<div class="ds-lr-stat"><span class="ds-lr-stat-num">${c}</span><span class="ds-lr-stat-label">${typeLabels[t] || t}</span></div>`
                    ).join('')}
                </div>
            `;

            if (results.length === 0) {
                body.innerHTML = '<div class="ds-lr-loading">Henüz öğrenme sonucu bulunmuyor. Önce QA Üretimi yapın.</div>';
                return;
            }

            body.innerHTML = results.map((r, idx) => {
                const typeLabel = typeLabels[r.content_type] || r.content_type;
                const typeClass = r.content_type;
                const tableName = r.table_name || '';
                const question = r.question || '';
                const answer = r.content_text || '';

                // SQL sorguları için özel formatlama
                let answerHtml = _escapeHtml(answer);
                if (r.content_type === 'aggregate_query') {
                    // SQL'leri code bloğu olarak göster
                    const sqlMatch = answer.match(/(SELECT\s+.+?;)/is);
                    if (sqlMatch) {
                        answerHtml = _escapeHtml(answer.replace(sqlMatch[1], ''))
                            + '<pre class="ds-lr-sql">' + _escapeHtml(sqlMatch[1]) + '</pre>';
                    }
                }

                return `
                    <div class="ds-lr-card" data-idx="${idx}">
                        <div class="ds-lr-card-header" onclick="this.parentElement.classList.toggle('expanded')">
                            <div class="ds-lr-card-meta">
                                <span class="ds-lr-type-badge ${typeClass}">${typeLabel}</span>
                                ${tableName ? `<span class="ds-lr-table-name"><i class="fa-solid fa-table"></i> ${_escapeHtml(tableName)}</span>` : ''}
                            </div>
                            <div class="ds-lr-card-question">
                                <i class="fa-solid fa-circle-question"></i>
                                <span>${_escapeHtml(question) || 'Soru bilgisi yok'}</span>
                            </div>
                            <i class="fa-solid fa-chevron-down ds-lr-chevron"></i>
                        </div>
                        <div class="ds-lr-card-body">
                            <div class="ds-lr-answer">
                                <div class="ds-lr-answer-label"><i class="fa-solid fa-robot"></i> ML Cevabı</div>
                                <div class="ds-lr-answer-text">${answerHtml}</div>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');

        } catch (err) {
            body.innerHTML = `<div class="ds-lr-error">Yükleme hatası: ${_escapeHtml(err.message)}</div>`;
        }
    }

    // ============================================
    // Helpers
    // ============================================

    function _escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function _formatNumber(num) {
        if (!num || num <= 0) return '0';
        return new Intl.NumberFormat('tr-TR').format(num);
    }

    function _formatDateTime(isoString) {
        if (!isoString) return '-';
        const date = new Date(isoString);
        if (isNaN(date.getTime())) return '-';
        const dd = String(date.getDate()).padStart(2, '0');
        const mm = String(date.getMonth() + 1).padStart(2, '0');
        const yyyy = date.getFullYear();
        const hh = String(date.getHours()).padStart(2, '0');
        const mi = String(date.getMinutes()).padStart(2, '0');
        return `${dd}/${mm}/${yyyy} ${hh}:${mi}`;
    }

    // ============================================
    // Init
    // ============================================

    // QA Üretimi kaldırıldı — Tam Pipeline (run-full-learning) tüm adımları içerir

    // ============================================
    // Tam Pipeline çalıştırma
    // ============================================

    async function runFullLearning(sourceId, sourceName) {
        _currentSourceId = sourceId;
        _currentSourceName = sourceName;
        try {
            const result = await apiCall(`/${sourceId}/run-full-learning`, 'POST');
            if (result.success) {
                toast('success', result.message || 'Tam öğrenme pipeline başlatıldı');
            } else {
                toast('error', 'Pipeline başlatılamadı: ' + (result.message || ''));
            }
        } catch (err) {
            toast('error', 'Pipeline hatası: ' + err.message);
        }
    }

    // ============================================
    // Schedule Modal
    // ============================================

    async function showScheduleModal(sourceId) {
        _currentSourceId = sourceId;

        // Mevcut schedule bilgisini al
        let scheduleData = { exists: false };
        try {
            scheduleData = await apiCall(`/${sourceId}/schedule`);
        } catch (e) { /* ignore */ }

        const existing = document.getElementById('dsScheduleModal');
        if (existing) existing.remove();

        const schedType = scheduleData.schedule_type || 'manual_only';
        const interval = scheduleData.interval_hours || 24;
        const isActive = scheduleData.is_active !== false;
        const lastRun = scheduleData.last_run_at ? _formatDateTime(scheduleData.last_run_at) : 'Henüz çalışmadı';
        const nextRun = scheduleData.next_run_at ? _formatDateTime(scheduleData.next_run_at) : '-';

        const modal = document.createElement('div');
        modal.id = 'dsScheduleModal';
        modal.className = 'ds-wizard-overlay';
        modal.innerHTML = `
            <div class="ds-wizard-modal" style="max-width: 500px;">
                <div class="ds-wizard-header">
                    <div class="ds-wizard-title">
                        <i class="fa-solid fa-clock"></i>
                        <span>Öğrenme Zamanlaması</span>
                    </div>
                    <button class="ds-wizard-close" id="dsScheduleClose">
                        <i class="fa-solid fa-times"></i>
                    </button>
                </div>
                <div class="ds-wizard-body" style="padding: 1.5rem;">
                    <div class="ds-schedule-form">
                        <div class="ds-form-group">
                            <label>Zamanlama Tipi</label>
                            <select id="dsScheduleType" class="ds-form-select">
                                <option value="manual_only" ${schedType === 'manual_only' ? 'selected' : ''}>Manuel (Sadece elle çalıştır)</option>
                                <option value="hourly" ${schedType === 'hourly' ? 'selected' : ''}>Saatlik</option>
                                <option value="daily" ${schedType === 'daily' ? 'selected' : ''}>Günlük</option>
                                <option value="weekly" ${schedType === 'weekly' ? 'selected' : ''}>Haftalık</option>
                            </select>
                        </div>
                        <div class="ds-form-group" id="dsIntervalGroup">
                            <label>Interval (Saat)</label>
                            <input type="number" id="dsIntervalValue" class="ds-form-input" min="1" max="720" value="${interval}">
                        </div>
                        <div class="ds-form-group">
                            <label class="ds-form-checkbox">
                                <input type="checkbox" id="dsScheduleActive" ${isActive ? 'checked' : ''}>
                                <span>Zamanlama Aktif</span>
                            </label>
                        </div>
                        <div class="ds-schedule-info">
                            <div><i class="fa-solid fa-history"></i> Son çalışma: <strong>${lastRun}</strong></div>
                            <div><i class="fa-solid fa-forward"></i> Sonraki: <strong>${nextRun}</strong></div>
                        </div>
                    </div>
                </div>
                <div class="ds-wizard-footer" style="display: flex; justify-content: flex-end; padding: 1rem 1.5rem; gap: 0.75rem;">
                    <button class="ds-wizard-btn secondary" id="dsScheduleCancel">İptal</button>
                    <button class="ds-wizard-btn primary" id="dsScheduleSave">
                        <i class="fa-solid fa-save"></i> Kaydet
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
        requestAnimationFrame(() => modal.classList.add('active'));

        // Events
        const closeSchedule = () => { modal.classList.remove('active'); setTimeout(() => modal.remove(), 300); };
        document.getElementById('dsScheduleClose').addEventListener('click', closeSchedule);
        document.getElementById('dsScheduleCancel').addEventListener('click', closeSchedule);
        document.addEventListener('keydown', function escH(e) {
            if (e.key === 'Escape') { closeSchedule(); document.removeEventListener('keydown', escH); }
        });

        // Interval alanı visibility
        document.getElementById('dsScheduleType').addEventListener('change', (e) => {
            document.getElementById('dsIntervalGroup').style.display =
                e.target.value === 'manual_only' ? 'none' : 'block';
        });
        document.getElementById('dsIntervalGroup').style.display =
            schedType === 'manual_only' ? 'none' : 'block';

        // Save
        document.getElementById('dsScheduleSave').addEventListener('click', async () => {
            const sType = document.getElementById('dsScheduleType').value;
            const sInterval = parseInt(document.getElementById('dsIntervalValue').value) || 24;
            const sActive = document.getElementById('dsScheduleActive').checked;

            try {
                const r = await apiCall(`/${sourceId}/learning-schedule`, 'POST', {
                    schedule_type: sType,
                    interval_value: sInterval,
                    is_active: sActive
                });
                if (r.success) {
                    toast('success', 'Zamanlama kaydedildi');
                    closeSchedule();
                } else {
                    toast('error', 'Zamanlama kaydedilemedi');
                }
            } catch (err) {
                toast('error', 'Zamanlama hatası: ' + err.message);
            }
        });
    }

    // ============================================
    // Standalone Öğrenme Geçmişi Modal
    // ============================================

    async function showLearningHistory(sourceId, sourceName) {
        _currentSourceId = sourceId;
        _currentSourceName = sourceName || '';

        const existing = document.getElementById('dsHistoryModal');
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.id = 'dsHistoryModal';
        modal.className = 'ds-wizard-overlay';
        modal.innerHTML = `
            <div class="ds-wizard-modal ds-details-modal">
                <div class="ds-wizard-header">
                    <div class="ds-wizard-title">
                        <i class="fa-solid fa-history"></i>
                        <span>Öğrenme Geçmişi — ${_escapeHtml(sourceName || '')}</span>
                    </div>
                    <button class="ds-wizard-close" id="dsHistoryClose">
                        <i class="fa-solid fa-times"></i>
                    </button>
                </div>
                <div class="ds-wizard-body ds-details-body">
                    <div class="ds-wizard-final-actions" style="margin-bottom: 1rem;">
                        <button class="ds-wizard-btn success" id="dsHistoryRunFull">
                            <i class="fa-solid fa-rocket"></i> Tam Pipeline Başlat
                        </button>
                        <button class="ds-wizard-btn secondary" id="dsHistorySchedule">
                            <i class="fa-solid fa-clock"></i> Zamanlama
                        </button>
                        <button class="ds-wizard-btn secondary" id="dsHistoryViewResults">
                            <i class="fa-solid fa-database"></i> Öğrenme Sonuçları
                        </button>
                    </div>
                    <div class="ds-details-section">
                        <h4><i class="fa-solid fa-list"></i> İş Geçmişi</h4>
                        <div class="ds-details-table-wrap">
                            <table class="ds-details-table">
                                <thead>
                                    <tr><th>Tarih</th><th>Tip</th><th>Süre</th><th>Durum</th><th>Detay</th></tr>
                                </thead>
                                <tbody id="dsLearningHistoryBody">
                                    <tr><td colspan="5"><i class="fa-solid fa-spinner fa-spin"></i> Yükleniyor...</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
        requestAnimationFrame(() => modal.classList.add('active'));

        const closeHistory = () => { modal.classList.remove('active'); setTimeout(() => modal.remove(), 300); };
        document.getElementById('dsHistoryClose').addEventListener('click', closeHistory);
        document.addEventListener('keydown', function escH2(e) {
            if (e.key === 'Escape') { closeHistory(); document.removeEventListener('keydown', escH2); }
        });

        // Aksiyon butonları
        const fullBtn = document.getElementById('dsHistoryRunFull');

        fullBtn.addEventListener('click', async () => {
            fullBtn.disabled = true;
            fullBtn.classList.add('ds-btn-disabled');
            fullBtn.style.background = '#475569';
            fullBtn.style.cursor = 'not-allowed';
            fullBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Başlatılıyor...';
            try {
                await runFullLearning(sourceId, sourceName);
            } catch (e) { toast('error', e.message); }
            setTimeout(() => {
                fullBtn.innerHTML = '<i class="fa-solid fa-clock"></i> Arka Planda Çalışıyor...';
                loadHistory(sourceId);
            }, 2000);
        });

        document.getElementById('dsHistorySchedule').addEventListener('click', () => showScheduleModal(sourceId));
        document.getElementById('dsHistoryViewResults').addEventListener('click', () => showLearningResults(sourceId));

        // Geçmişi yükle
        await loadHistory(sourceId);
    }

    function init() {
        console.log('[DSLearning] Modül yüklendi (Faz 2)');
    }

    return {
        init,
        openWizard,
        closeWizard,
        retryStep,
        showDiscoveryDetails,
        showObjectColumns,
        showScheduleModal,
        showLearningHistory,
        showJobDetail,
        showLearningResults,
        runFullLearning,
        loadHistory
    };
})();

// Auto-init
document.addEventListener('DOMContentLoaded', () => DSLearningModule.init());
