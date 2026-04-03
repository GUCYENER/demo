/* -----------------------------------------------
   VYRA - ML Training Module
   Model eğitim yönetimi ve UI kontrolü
   v2.13.1 - CatBoost Training Admin
------------------------------------------------ */

/**
 * MLTrainingModule - Model eğitim admin arayüzü
 * @module MLTrainingModule
 */
window.MLTrainingModule = (function () {
    'use strict';

    // API Base URL (Backend - Port 8002)
    const API_BASE = window.API_BASE_URL || 'http://localhost:8002';

    // State
    let isTraining = false;
    let trainingPollInterval = null;
    let savedScheduleState = null; // Kaydedilmiş schedule durumu
    let _errorCache = {}; // Hata mesajları cache'i (jobId -> errorMessage)
    let _jobCache = {};   // Job detay cache'i (jobId -> full job object)
    let _clCountdownInterval = null;  // Countdown timer interval ID

    // Toast helper (VyraToast veya showToast fallback)
    function toast(type, message) {
        if (window.VyraToast && typeof window.VyraToast[type] === 'function') {
            window.VyraToast[type](message);
        } else if (typeof showToast === 'function') {
            showToast(message, type);
        } else {
            console.log(`[Toast ${type}]`, message);
        }
    }

    // DOM References
    function getElements() {
        return {
            // Stats
            feedbackCount: document.getElementById('ml-feedback-count'),
            activeModel: document.getElementById('ml-active-model'),
            lastTraining: document.getElementById('ml-last-training'),
            pendingFeedback: document.getElementById('ml-pending-feedback'),

            // Training
            btnStartTraining: document.getElementById('btnStartTraining'),
            trainingProgress: document.getElementById('trainingProgress'),
            trainingStatusText: document.getElementById('trainingStatusText'),

            // Hybrid Schedule
            scheduleFeedbackActive: document.getElementById('scheduleFeedbackActive'),
            scheduleFeedbackValue: document.getElementById('scheduleFeedbackValue'),
            scheduleIntervalActive: document.getElementById('scheduleIntervalActive'),
            scheduleIntervalValue: document.getElementById('scheduleIntervalValue'),
            scheduleQualityActive: document.getElementById('scheduleQualityActive'),
            scheduleQualityValue: document.getElementById('scheduleQualityValue'),
            scheduleTimeoutActive: document.getElementById('scheduleTimeoutActive'),
            scheduleTimeoutValue: document.getElementById('scheduleTimeoutValue'),
            scheduleCLIntervalActive: document.getElementById('scheduleCLIntervalActive'),
            scheduleCLIntervalValue: document.getElementById('scheduleCLIntervalValue'),
            btnSaveSchedule: document.getElementById('btnSaveSchedule'),

            // History
            trainingHistoryBody: document.getElementById('trainingHistoryBody'),
            btnRefreshHistory: document.getElementById('btnRefreshMLHistory'),

            // Tab
            tabMLTraining: document.getElementById('tabMLTraining'),
            contentMLTraining: document.getElementById('contentMLTraining')
        };
    }

    // ============================================
    // API Calls
    // ============================================

    async function apiCall(endpoint, method = 'GET', body = null) {
        const token = localStorage.getItem('access_token');
        const options = {
            method,
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            }
        };

        if (body) {
            options.body = JSON.stringify(body);
        }

        const response = await fetch(`${API_BASE}/api/system${endpoint}`, options);
        return response.json();
    }

    // ============================================
    // Stats
    // ============================================

    async function loadStats(companyId) {
        const el = getElements();

        try {
            const qp = companyId ? `?company_id=${companyId}` : '';
            const data = await apiCall('/ml/training/stats' + qp);
            console.log('[MLTraining] Stats API response:', data);

            // Feedback count
            if (el.feedbackCount) {
                el.feedbackCount.textContent = formatNumber(data.total_feedback || 0);
            }

            // Active model
            if (el.activeModel) {
                if (data.active_model) {
                    el.activeModel.textContent = `v${data.active_model.version}`;
                    el.activeModel.classList.add('has-model');
                } else {
                    el.activeModel.textContent = 'Yok';
                    el.activeModel.classList.remove('has-model');
                }
            }

            // Last training
            if (el.lastTraining) {
                if (data.last_training && data.last_training.start_time) {
                    el.lastTraining.textContent = formatRelativeTime(data.last_training.start_time);
                } else {
                    el.lastTraining.textContent = 'Hiç';
                }
            }

            // Pending feedback
            if (el.pendingFeedback) {
                el.pendingFeedback.textContent = formatNumber(data.feedback_since_last_training || 0);
            }

            // Update training button state
            const totalFeedback = data.total_feedback || 0;
            updateTrainingButtonState(data.is_training, totalFeedback);
            isTraining = data.is_training;

            if (isTraining) {
                startTrainingPoll();
            }

        } catch (error) {
            console.error('[MLTraining] Stats yükleme hatası:', error);
        }
    }

    function updateTrainingButtonState(training, totalFeedback = 0) {
        const el = getElements();
        if (!el.btnStartTraining) return;

        // Hint mesajını bilgi amaçlı güncelle (kriter yok)
        const hintEl = document.querySelector('.ml-train-hint');
        if (hintEl) {
            if (totalFeedback > 0) {
                hintEl.innerHTML = `<i class="fa-solid fa-database" style="color:var(--accent)"></i> Sistemdeki feedback: <strong>${totalFeedback}</strong>`;
            } else {
                hintEl.innerHTML = `<i class="fa-solid fa-info-circle"></i> Henüz feedback verisi yok`;
            }
        }

        if (training) {
            el.btnStartTraining.disabled = true;
            el.btnStartTraining.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Eğitim Devam Ediyor...';
            el.btnStartTraining.classList.add('training');
            if (el.trainingProgress) el.trainingProgress.classList.remove('hidden');
        } else {
            el.btnStartTraining.disabled = false;
            el.btnStartTraining.innerHTML = '<i class="fa-solid fa-play"></i> Modeli Şimdi Eğit';
            el.btnStartTraining.classList.remove('training');
            if (el.trainingProgress) el.trainingProgress.classList.add('hidden');
        }
    }

    // ============================================
    // Training
    // ============================================

    async function startTraining() {
        const el = getElements();

        // 1. Zaten çalışan eğitim varsa uyarı ver
        if (isTraining) {
            toast('warning', 'Arka planda bir eğitim süreci zaten devam ediyor. Lütfen tamamlanmasını bekleyin.');
            return;
        }

        // 2. Sunucudaki durumu anlık kontrol et (otomatik/CL çalışıyor olabilir)
        try {
            const statusCheck = await apiCall('/ml/training/status');
            if (statusCheck.is_training) {
                toast('warning', 'Arka planda otomatik bir eğitim süreci çalışıyor. Manuel eğitim başlatılamaz.');
                isTraining = true;
                updateTrainingButtonState(true);
                startTrainingPoll();
                return;
            }
        } catch (checkErr) {
            console.warn('[MLTraining] Durum kontrol hatası:', checkErr);
        }

        try {
            // 3. Butonu hemen pasif yap
            if (el.btnStartTraining) {
                el.btnStartTraining.disabled = true;
                el.btnStartTraining.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Başlatılıyor...';
            }

            const result = await apiCall('/ml/training/start', 'POST');

            if (result.success) {
                isTraining = true;
                toast('success', 'Model eğitimi arka planda başlatıldı');
                updateTrainingButtonState(true);
                startTrainingPoll();
                // v3.3.1: Eğitim başladığında geçmişi hemen yenile — "Çalışıyor" statüsüyle görünsün
                loadHistory();
            } else {
                toast('error', result.error || 'Eğitim başlatılamadı');
                await loadStats();
            }

        } catch (error) {
            console.error('[MLTraining] Start training hatası:', error);
            toast('error', 'Eğitim başlatılırken hata oluştu');
            await loadStats();
        }
    }

    function startTrainingPoll() {
        if (trainingPollInterval) return;

        trainingPollInterval = setInterval(async () => {
            try {
                const status = await apiCall('/ml/training/status');

                if (!status.is_training) {
                    stopTrainingPoll();
                    isTraining = false;
                    loadStats();
                    loadHistory();

                    // Eğitim tamamlandı — bildirime yaz
                    toast('success', 'Model eğitimi tamamlandı!');
                    if (window.NgssNotification) {
                        NgssNotification.success(
                            'Model Eğitimi Tamamlandı',
                            'CatBoost modeli başarıyla eğitildi ve aktif edildi.'
                        );
                    }
                } else {
                    // Update status text
                    const el = getElements();
                    if (el.trainingStatusText && status.current_job) {
                        const elapsed = status.current_job.elapsed_seconds || 0;
                        el.trainingStatusText.textContent = `Eğitim devam ediyor... (${formatDuration(elapsed)})`;
                    }
                }
            } catch (error) {
                console.error('[MLTraining] Poll hatası:', error);
            }
        }, 5000); // 5 saniyede bir kontrol
    }

    function stopTrainingPoll() {
        if (trainingPollInterval) {
            clearInterval(trainingPollInterval);
            trainingPollInterval = null;
        }
    }

    // ============================================
    // Schedule
    // ============================================

    async function loadSchedule(companyId) {
        const el = getElements();

        try {
            const qp = companyId ? `?company_id=${companyId}` : '';
            const data = await apiCall('/ml/training/schedule' + qp);

            if (data.schedules) {
                // Hibrit schedule - her koşul için ayrı kontrol
                data.schedules.forEach(schedule => {
                    if (schedule.trigger_type === 'feedback_count') {
                        if (el.scheduleFeedbackActive) el.scheduleFeedbackActive.checked = schedule.is_active;
                        if (el.scheduleFeedbackValue) el.scheduleFeedbackValue.value = schedule.trigger_value;
                    } else if (schedule.trigger_type === 'interval_days') {
                        if (el.scheduleIntervalActive) el.scheduleIntervalActive.checked = schedule.is_active;
                        if (el.scheduleIntervalValue) el.scheduleIntervalValue.value = schedule.trigger_value;
                    } else if (schedule.trigger_type === 'quality_drop') {
                        if (el.scheduleQualityActive) el.scheduleQualityActive.checked = schedule.is_active;
                        if (el.scheduleQualityValue) el.scheduleQualityValue.value = schedule.trigger_value;
                    } else if (schedule.trigger_type === 'job_timeout') {
                        if (el.scheduleTimeoutActive) el.scheduleTimeoutActive.checked = schedule.is_active;
                        if (el.scheduleTimeoutValue) el.scheduleTimeoutValue.value = schedule.trigger_value;
                    } else if (schedule.trigger_type === 'cl_interval') {
                        if (el.scheduleCLIntervalActive) el.scheduleCLIntervalActive.checked = schedule.is_active;
                        if (el.scheduleCLIntervalValue) el.scheduleCLIntervalValue.value = schedule.trigger_value;
                    }
                });

                // Mevcut durumu kaydet
                saveCurrentScheduleState();
                updateSaveButtonState();
            }

        } catch (error) {
            console.error('[MLTraining] Schedule yükleme hatası:', error);
        }
    }

    function saveCurrentScheduleState() {
        const el = getElements();
        savedScheduleState = {
            feedbackActive: el.scheduleFeedbackActive?.checked || false,
            feedbackValue: el.scheduleFeedbackValue?.value || '500',
            intervalActive: el.scheduleIntervalActive?.checked || false,
            intervalValue: el.scheduleIntervalValue?.value || '7',
            qualityActive: el.scheduleQualityActive?.checked || false,
            qualityValue: el.scheduleQualityValue?.value || '0.7',
            timeoutActive: el.scheduleTimeoutActive?.checked ?? true,
            timeoutValue: el.scheduleTimeoutValue?.value || '60',
            clIntervalActive: el.scheduleCLIntervalActive?.checked ?? true,
            clIntervalValue: el.scheduleCLIntervalValue?.value || '30'
        };
    }

    function getCurrentScheduleState() {
        const el = getElements();
        return {
            feedbackActive: el.scheduleFeedbackActive?.checked || false,
            feedbackValue: el.scheduleFeedbackValue?.value || '500',
            intervalActive: el.scheduleIntervalActive?.checked || false,
            intervalValue: el.scheduleIntervalValue?.value || '7',
            qualityActive: el.scheduleQualityActive?.checked || false,
            qualityValue: el.scheduleQualityValue?.value || '0.7',
            timeoutActive: el.scheduleTimeoutActive?.checked ?? true,
            timeoutValue: el.scheduleTimeoutValue?.value || '60',
            clIntervalActive: el.scheduleCLIntervalActive?.checked ?? true,
            clIntervalValue: el.scheduleCLIntervalValue?.value || '30'
        };
    }

    function hasScheduleChanged() {
        if (!savedScheduleState) return true;
        const current = getCurrentScheduleState();
        return JSON.stringify(savedScheduleState) !== JSON.stringify(current);
    }

    function updateSaveButtonState() {
        const el = getElements();
        if (el.btnSaveSchedule) {
            const hasChanges = hasScheduleChanged();
            el.btnSaveSchedule.disabled = !hasChanges;
            el.btnSaveSchedule.classList.toggle('btn-disabled', !hasChanges);
        }
    }


    async function saveSchedule() {
        const el = getElements();

        // Hibrit schedule - 3 koşulu birden gönder
        const payload = {
            schedules: [
                {
                    trigger_type: 'feedback_count',
                    trigger_value: el.scheduleFeedbackValue?.value || '500',
                    is_active: el.scheduleFeedbackActive?.checked || false
                },
                {
                    trigger_type: 'interval_days',
                    trigger_value: el.scheduleIntervalValue?.value || '7',
                    is_active: el.scheduleIntervalActive?.checked || false
                },
                {
                    trigger_type: 'quality_drop',
                    trigger_value: el.scheduleQualityValue?.value || '0.7',
                    is_active: el.scheduleQualityActive?.checked || false
                },
                {
                    trigger_type: 'job_timeout',
                    trigger_value: el.scheduleTimeoutValue?.value || '60',
                    is_active: el.scheduleTimeoutActive?.checked ?? true
                },
                {
                    trigger_type: 'cl_interval',
                    trigger_value: el.scheduleCLIntervalValue?.value || '30',
                    is_active: el.scheduleCLIntervalActive?.checked ?? true
                }
            ]
        };

        try {
            const result = await apiCall('/ml/training/schedule', 'POST', payload);

            if (result.success) {
                toast('success', 'Otomatik eğitim ayarları kaydedildi');
                // Kayıt başarılı - yeni durumu sakla
                saveCurrentScheduleState();
                updateSaveButtonState();

                // CL interval değişti mi? Backend'e bildir
                const clInterval = parseInt(el.scheduleCLIntervalValue?.value || '30');
                const clActive = el.scheduleCLIntervalActive?.checked ?? true;
                try {
                    await apiCall('/ml/training/continuous-config', 'POST', {
                        interval_minutes: clInterval,
                        is_active: clActive
                    });
                    console.log(`[MLTraining] CL interval güncellendi: ${clInterval}dk, aktif: ${clActive}`);
                } catch (e) {
                    console.warn('[MLTraining] CL config güncellenemedi:', e);
                }

                // Stats'ı yeniden yükle
                console.log('[MLTraining] Schedule kaydedildi, stats yeniden yükleniyor...');
                loadStats().then(() => {
                    console.log('[MLTraining] Stats güncellendi');
                });
                loadContinuousStatus();
            } else {
                toast('error', result.error || 'Kayıt başarısız');
            }

        } catch (error) {
            console.error('[MLTraining] Schedule kayıt hatası:', error);
            toast('error', 'Kayıt sırasında hata oluştu');
        }
    }

    // ============================================
    // History
    // ============================================

    async function loadHistory(companyId) {
        const el = getElements();
        if (!el.trainingHistoryBody) return;

        try {
            const qp = companyId ? `?company_id=${companyId}` : '';
            const data = await apiCall('/ml/training/history' + qp);
            const history = data.history || [];

            if (history.length === 0) {
                el.trainingHistoryBody.innerHTML = `
                    <tr class="empty-row">
                        <td colspan="5">
                            <i class="fa-solid fa-inbox"></i>
                            Henüz eğitim yapılmamış
                        </td>
                    </tr>
                `;
                return;
            }

            el.trainingHistoryBody.innerHTML = history.map(job => {
                const date = job.start_time ? formatDateTime(job.start_time) : '-';
                let typeLabel = 'Manuel';
                let typeClass = 'manual';
                if (job.type === 'continuous') {
                    typeLabel = 'Sürekli Öğrenme';
                    typeClass = 'continuous';
                } else if (job.type === 'scheduled') {
                    typeLabel = 'Otomatik';
                    typeClass = 'scheduled';
                }
                const duration = job.duration ? formatDuration(job.duration) : '-';
                const samples = job.samples || '-';

                // Job detayını cache'e kaydet
                _jobCache[job.id] = job;

                let statusClass = '';
                let statusIcon = '';
                let statusLabel = '';
                let statusTooltip = '';
                let clickHandler = '';

                switch (job.status) {
                    case 'completed':
                        statusClass = 'success';
                        statusIcon = 'fa-check-circle';
                        statusLabel = job.model_version ? `v${job.model_version}` : 'Başarılı';
                        break;
                    case 'failed':
                        statusClass = 'error clickable';
                        statusIcon = 'fa-times-circle';
                        statusLabel = 'Başarısız';
                        // Hata mesajını data attribute olarak sakla ve tıklanabilir yap
                        if (job.error) {
                            // Kısa tooltip (özet) - 500 karakter
                            const shortError = job.error.substring(0, 500).replace(/"/g, '&quot;');
                            statusTooltip = shortError + (job.error.length > 500 ? '... (tıkla)' : '');
                            // Tıklandığında modal aç
                            clickHandler = `onclick="MLTrainingModule.showErrorDetail(${job.id})"`;
                            // Tam hatayı cache'e kaydet
                            _errorCache[job.id] = job.error;
                        }
                        break;
                    case 'running':
                        statusClass = 'running';
                        statusIcon = 'fa-spinner fa-spin';
                        statusLabel = 'Çalışıyor';
                        break;
                    default:
                        statusClass = 'pending';
                        statusIcon = 'fa-clock';
                        statusLabel = 'Bekliyor';
                }

                const tooltipAttr = statusTooltip ? `title="${statusTooltip}"` : '';

                return `
                    <tr>
                        <td>${date}</td>
                        <td><span class="type-badge ${typeClass}">${typeLabel}</span></td>
                        <td>${duration}</td>
                        <td>${samples !== '-' ? `<span class="samples-link" onclick="MLTrainingModule.showJobDetail(${job.id})" title="Detayları görmek için tıkla">${samples} <i class="fa-solid fa-up-right-from-square samples-link-icon"></i></span>` : '-'}</td>
                        <td><span class="status-badge ${statusClass}" ${tooltipAttr} ${clickHandler}><i class="fa-solid ${statusIcon}"></i> ${statusLabel}</span></td>
                    </tr>
                `;
            }).join('');

        } catch (error) {
            console.error('[MLTraining] History yükleme hatası:', error);
        }
    }

    // ============================================
    // Continuous Learning Status
    // ============================================

    async function loadContinuousStatus() {
        try {
            const data = await apiCall('/ml/training/continuous-status');

            // Status dot + text
            const dot = document.getElementById('clStatusDot');
            const text = document.getElementById('clStatusText');
            if (dot && text) {
                if (data.is_running) {
                    dot.className = 'cl-status-dot active';
                    text.textContent = 'Aktif — Arka planda çalışıyor';
                } else {
                    dot.className = 'cl-status-dot inactive';
                    text.textContent = 'Durdu';
                }
            }

            // Stats
            const totalEl = document.getElementById('clTotalTrainings');
            if (totalEl) totalEl.textContent = data.total_trainings || 0;

            const lastEl = document.getElementById('clLastTraining');
            if (lastEl) {
                lastEl.textContent = data.last_training_time
                    ? formatRelativeTime(data.last_training_time)
                    : 'Henüz yok';
            }

            // Sonraki Çalışma — Countdown Timer
            startNextRunCountdown(data.next_scheduled_run, data.is_running);

            const intervalEl = document.getElementById('clInterval');
            if (intervalEl) intervalEl.textContent = `${data.interval_minutes || 30} dk`;

        } catch (error) {
            console.error('[MLTraining] CL status hatası:', error);
        }
    }

    /**
     * Sonraki çalışma için geri sayım sayacı başlat
     * @param {string|null} nextRunISO - Sonraki çalışma ISO tarih string
     * @param {boolean} isRunning - Servis çalışıyor mu
     */
    function startNextRunCountdown(nextRunISO, isRunning) {
        // Önceki timer'ı temizle
        if (_clCountdownInterval) {
            clearInterval(_clCountdownInterval);
            _clCountdownInterval = null;
        }

        const nextEl = document.getElementById('clNextRun');
        if (!nextEl) return;

        // Servis çalışmıyorsa veya tarih yoksa
        if (!isRunning) {
            nextEl.textContent = '-';
            return;
        }

        if (!nextRunISO || nextRunISO === 'Yakında...') {
            nextEl.textContent = 'Yakında...';
            return;
        }

        const targetTime = new Date(nextRunISO).getTime();

        // Invalid date koruması
        if (isNaN(targetTime)) {
            nextEl.textContent = formatRelativeTime(nextRunISO);
            return;
        }

        function updateCountdown() {
            const now = Date.now();
            const diff = targetTime - now;

            if (diff <= 0) {
                nextEl.innerHTML = '<span class="cl-countdown running">⏳ Çalışıyor...</span>';
                clearInterval(_clCountdownInterval);
                _clCountdownInterval = null;
                // 15 saniye sonra status'u yeniden yükle
                setTimeout(() => loadContinuousStatus(), 15000);
                return;
            }

            const totalSeconds = Math.floor(diff / 1000);
            const minutes = Math.floor(totalSeconds / 60);
            const seconds = totalSeconds % 60;
            const mm = String(minutes).padStart(2, '0');
            const ss = String(seconds).padStart(2, '0');

            nextEl.innerHTML = `<span class="cl-countdown">${mm}:${ss}</span>`;
        }

        // İlk güncelleme hemen
        updateCountdown();
        // Her saniye güncelle
        _clCountdownInterval = setInterval(updateCountdown, 1000);
    }

    // ============================================
    // Helpers
    // ============================================

    function formatNumber(num) {
        return new Intl.NumberFormat('tr-TR').format(num);
    }

    function formatDuration(seconds) {
        if (!seconds) return '-';
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }

    function formatDateTime(isoString) {
        const date = new Date(isoString);
        return date.toLocaleDateString('tr-TR', {
            day: '2-digit',
            month: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    function formatRelativeTime(isoString) {
        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);

        if (diffMins < 60) return `${diffMins} dk önce`;
        if (diffHours < 24) return `${diffHours} saat önce`;
        if (diffDays < 7) return `${diffDays} gün önce`;
        return formatDateTime(isoString);
    }

    // ============================================
    // Event Listeners
    // ============================================

    function setupEventListeners() {
        const el = getElements();

        // Tab click
        if (el.tabMLTraining) {
            el.tabMLTraining.addEventListener('click', () => {
                loadStats();
                loadSchedule();
                loadHistory();
                loadContinuousStatus();
            });
        }

        // Start training & Save schedule - event delegation (partial dinamik yükleniyor)
        document.addEventListener('click', (e) => {
            const target = e.target.closest('#btnStartTraining');
            if (target) startTraining();
        });
        document.addEventListener('click', (e) => {
            const target = e.target.closest('#btnSaveSchedule');
            if (target && !target.disabled) saveSchedule();
        });

        // Schedule değişiklik dinleyicileri - event delegation (partial dinamik yükleniyor)
        const scheduleInputIds = [
            'scheduleFeedbackActive', 'scheduleFeedbackValue',
            'scheduleIntervalActive', 'scheduleIntervalValue',
            'scheduleQualityActive', 'scheduleQualityValue',
            'scheduleTimeoutActive', 'scheduleTimeoutValue',
            'scheduleCLIntervalActive', 'scheduleCLIntervalValue'
        ];
        document.addEventListener('change', (e) => {
            if (scheduleInputIds.includes(e.target.id)) {
                updateSaveButtonState();
            }
        });

        // Schedule type change - dinamik değer seçenekleri
        if (el.scheduleType) {
            el.scheduleType.addEventListener('change', (e) => {
                updateScheduleOptions(e.target.value);
            });
        }

        // Refresh ML history (v2.52.0: unique ID — duplicate çakışması giderildi)
        if (el.btnRefreshHistory) {
            el.btnRefreshHistory.addEventListener('click', () => {
                loadHistory();
                loadStats();
                loadContinuousStatus();
            });
        }
    }

    // ============================================
    // Init
    // ============================================

    function init() {
        // Önce butonu yükleniyor olarak başlat (stats gelince güncellenecek)
        const el = getElements();
        if (el.btnStartTraining) {
            el.btnStartTraining.disabled = true;
            el.btnStartTraining.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Durum kontrol ediliyor...';
        }

        setupEventListeners();
        console.log('[MLTraining] Modül yüklendi');
    }

    // Hata detayını modal ile göster
    function showErrorDetail(jobId) {
        const errorMsg = _errorCache[jobId] || 'Hata detayı bulunamadı.';

        if (window.VyraModal && typeof window.VyraModal.error === 'function') {
            VyraModal.error({
                title: 'Eğitim Hata Detayı',
                message: `<pre class="detail-error">${escapeHtml(errorMsg)}</pre>`,
                confirmText: 'Kapat'
            });
        } else {
            VyraModal.error({
                title: 'Eğitim Hata Detayı',
                message: `<pre class="detail-error">${escapeHtml(errorMsg)}</pre>`,
                confirmText: 'Kapat'
            });
        }
    }

    // Eğitim iş detayını modal ile göster
    function showJobDetail(jobId) {
        const job = _jobCache[jobId];
        if (!job) {
            toast('error', 'İş detayı bulunamadı');
            return;
        }

        // Tip badge'i
        let typeLabel = 'Manuel';
        if (job.type === 'continuous') typeLabel = 'Sürekli Öğrenme';
        else if (job.type === 'scheduled') typeLabel = 'Otomatik';

        // Durum
        let statusLabel = 'Bekliyor';
        let statusColor = '#94a3b8';
        if (job.status === 'completed') { statusLabel = '✅ Başarılı'; statusColor = '#22c55e'; }
        else if (job.status === 'failed') { statusLabel = '❌ Başarısız'; statusColor = '#ef4444'; }
        else if (job.status === 'running') { statusLabel = '🔄 Çalışıyor'; statusColor = '#f59e0b'; }

        // Süre
        const duration = job.duration ? formatDuration(job.duration) : '-';
        const startTime = job.start_time ? formatDateTime(job.start_time) : '-';
        const endTime = job.end_time ? formatDateTime(job.end_time) : '-';

        // Modal içeriği
        const content = `
            <div class="job-detail-modal">
                <table class="job-detail-table">
                    <tr><td class="detail-label">İş No</td><td class="detail-value">#${job.id}</td></tr>
                    <tr><td class="detail-label">İş Adı</td><td class="detail-value">${escapeHtml(job.name || '-')}</td></tr>
                    <tr><td class="detail-label">Kaynak</td><td class="detail-value">${typeLabel}</td></tr>
                    <tr><td class="detail-label">Tetikleyici</td><td class="detail-value">${escapeHtml(job.trigger || '-')}</td></tr>
                    <tr><td class="detail-label">Başlangıç</td><td class="detail-value">${startTime}</td></tr>
                    <tr><td class="detail-label">Bitiş</td><td class="detail-value">${endTime}</td></tr>
                    <tr><td class="detail-label">Süre</td><td class="detail-value">${duration}</td></tr>
                    <tr><td class="detail-label">Örnek Sayısı</td><td class="detail-value"><strong>${job.samples || '-'}</strong> ${job.samples ? `<span class="samples-link" onclick="VyraModal.close(); setTimeout(() => MLTrainingModule.showJobSamples(${job.id}), 300);" title="Eğitim örneklerini göster">Örnekleri Gör <i class="fa-solid fa-up-right-from-square samples-link-icon"></i></span>` : ''}</td></tr>
                    <tr><td class="detail-label">Durum</td><td class="detail-value" style="color: ${statusColor}">${statusLabel}</td></tr>
                    ${job.model_version ? `<tr><td class="detail-label">Model Versiyon</td><td class="detail-value">v${escapeHtml(job.model_version)}</td></tr>` : ''}
                    ${job.error ? `<tr><td class="detail-label">Hata</td><td class="detail-value"><pre class="detail-error">${escapeHtml(job.error)}</pre></td></tr>` : ''}
                </table>
            </div>
        `;

        if (window.VyraModal && typeof window.VyraModal.info === 'function') {
            VyraModal.info({
                title: `Eğitim Detayı #${job.id}`,
                message: content,
                confirmText: 'Kapat'
            });
        } else if (window.VyraModal && typeof window.VyraModal.error === 'function') {
            VyraModal.error({
                title: `Eğitim Detayı #${job.id}`,
                message: content,
                confirmText: 'Kapat'
            });
        } else {
            VyraModal.info({
                title: `Eğitim #${job.id}`,
                message: `Kaynak: ${typeLabel}<br>Örnek: ${job.samples}<br>Süre: ${duration}<br>Durum: ${statusLabel}`,
                confirmText: 'Kapat'
            });
        }
    }

    // Eğitim örneklerini API'den çekip modal ile göster (pagination + filtre + sıralama destekli)
    const SAMPLES_PER_PAGE = 50;

    // Filtre ve sıralama state'i (sayfa değişimlerinde korunur)
    let _samplesFilterState = {
        sourceFile: '',
        intent: '',
        relevance: '',
        scoreMin: '',
        scoreMax: '',
        sortField: null,
        sortDir: null  // 'asc' | 'desc' | null
    };

    // Örneklerin orijinal datasetini tut (client-side filtre+sıralama için)
    let _samplesPageData = [];

    /**
     * Sayfadaki örneklere filtre uygula
     */
    function _applyFilters(samples) {
        const f = _samplesFilterState;
        return samples.filter(s => {
            // Kaynak dosya filtresi (arama)
            if (f.sourceFile && !(s.source_file || '').toLowerCase().includes(f.sourceFile.toLowerCase())) {
                return false;
            }
            // Intent filtresi (dropdown)
            if (f.intent && s.intent !== f.intent) {
                return false;
            }
            // Eşleşme filtresi (dropdown)
            if (f.relevance !== '') {
                const rel = parseInt(f.relevance);
                if (s.relevance !== rel) return false;
            }
            // Skor aralığı
            if (f.scoreMin !== '' && s.score != null) {
                if (s.score < parseFloat(f.scoreMin)) return false;
            }
            if (f.scoreMax !== '' && s.score != null) {
                if (s.score > parseFloat(f.scoreMax)) return false;
            }
            return true;
        });
    }

    /**
     * Örneklere sıralama uygula
     */
    function _applySort(samples) {
        const { sortField, sortDir } = _samplesFilterState;
        if (!sortField || !sortDir) return samples;

        const sorted = [...samples];
        sorted.sort((a, b) => {
            let valA, valB;
            switch (sortField) {
                case 'source_file':
                    valA = (a.source_file || '').toLowerCase();
                    valB = (b.source_file || '').toLowerCase();
                    return sortDir === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
                case 'intent':
                    valA = (a.intent || '').toLowerCase();
                    valB = (b.intent || '').toLowerCase();
                    return sortDir === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
                case 'relevance':
                    valA = a.relevance || 0;
                    valB = b.relevance || 0;
                    return sortDir === 'asc' ? valA - valB : valB - valA;
                case 'score':
                    valA = a.score || 0;
                    valB = b.score || 0;
                    return sortDir === 'asc' ? valA - valB : valB - valA;
                default:
                    return 0;
            }
        });
        return sorted;
    }

    /**
     * Sıralama icon'unu döndür
     */
    function _sortIcon(field) {
        const { sortField, sortDir } = _samplesFilterState;
        if (sortField === field) {
            return sortDir === 'asc'
                ? '<i class="fa-solid fa-sort-up samples-sort-icon"></i>'
                : '<i class="fa-solid fa-sort-down samples-sort-icon"></i>';
        }
        return '<i class="fa-solid fa-sort samples-sort-icon"></i>';
    }

    /**
     * Tablo içeriğini filtre/sıralama ile yeniden render et (modal içinde DOM güncelleme)
     */
    function _renderSamplesTable(offset) {
        const filtered = _applyFilters(_samplesPageData);
        const sorted = _applySort(filtered);

        const tbody = document.querySelector('.samples-table tbody');
        const filteredCountEl = document.querySelector('.samples-filtered-count');
        if (!tbody) return;

        if (sorted.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="sample-num" style="text-align:center; padding: 24px; color: #64748b;">
                <i class="fa-solid fa-filter-circle-xmark" style="margin-right: 6px;"></i>Filtre kriterlerine uygun örnek bulunamadı
            </td></tr>`;
        } else {
            tbody.innerHTML = sorted.map((s, i) => {
                const relIcon = s.relevance === 1 ? '✅' : '❌';
                const rowNum = offset + i + 1;
                const showAnswerBtn = s.has_learned_answer
                    ? `<button class="sample-answer-btn sample-answer-ready" data-query="${escapeHtml(s.query)}" onclick="MLTrainingModule.showSampleAnswer(this)" title="Öğrenilmiş cevabı göster"><i class="fa-solid fa-comment-dots"></i></button>`
                    : (s.relevance === 1 && s.score >= 0.70)
                        ? `<span class="sample-answer-pending" title="Cevap henüz üretilmedi"><i class="fa-solid fa-hourglass-half"></i></span>`
                        : '<span class="sample-answer-na">—</span>';
                return `<tr>
                    <td class="sample-num">${rowNum}</td>
                    <td class="sample-query">${escapeHtml(s.query)}</td>
                    <td class="sample-source">${escapeHtml(s.source_file || '-')}</td>
                    <td><span class="sample-intent" data-intent="${s.intent}">${s.intent || '-'}</span></td>
                    <td class="sample-rel">${relIcon}</td>
                    <td class="sample-score">${s.score ? s.score.toFixed(2) : '-'}</td>
                    <td class="sample-answer-col">${showAnswerBtn}</td>
                </tr>`;
            }).join('');
        }

        // Filtrelenmiş sayıyı güncelle
        if (filteredCountEl) {
            if (sorted.length < _samplesPageData.length) {
                filteredCountEl.textContent = `${sorted.length} / ${_samplesPageData.length} gösteriliyor`;
                filteredCountEl.style.display = 'block';
            } else {
                filteredCountEl.style.display = 'none';
            }
        }

        // Sıralama header class güncelle
        document.querySelectorAll('.samples-table th.sortable').forEach(th => {
            th.classList.remove('sort-asc', 'sort-desc');
            const field = th.dataset.sortField;
            if (field === _samplesFilterState.sortField) {
                th.classList.add(_samplesFilterState.sortDir === 'asc' ? 'sort-asc' : 'sort-desc');
                const icon = th.querySelector('.samples-sort-icon');
                if (icon) {
                    icon.className = _samplesFilterState.sortDir === 'asc'
                        ? 'fa-solid fa-sort-up samples-sort-icon'
                        : 'fa-solid fa-sort-down samples-sort-icon';
                }
            }
        });
    }

    /**
     * Filtre event handler'larını bağla
     */
    function _bindFilterEvents(offset) {
        // Kaynak dosya input
        const srcInput = document.getElementById('samplesFilterSource');
        if (srcInput) {
            srcInput.addEventListener('input', (e) => {
                _samplesFilterState.sourceFile = e.target.value;
                _renderSamplesTable(offset);
            });
        }

        // Intent select
        const intentSelect = document.getElementById('samplesFilterIntent');
        if (intentSelect) {
            intentSelect.addEventListener('change', (e) => {
                _samplesFilterState.intent = e.target.value;
                _renderSamplesTable(offset);
            });
        }

        // Eşleşme select
        const relSelect = document.getElementById('samplesFilterRelevance');
        if (relSelect) {
            relSelect.addEventListener('change', (e) => {
                _samplesFilterState.relevance = e.target.value;
                _renderSamplesTable(offset);
            });
        }

        // Skor min/max
        const scoreMin = document.getElementById('samplesFilterScoreMin');
        const scoreMax = document.getElementById('samplesFilterScoreMax');
        if (scoreMin) {
            scoreMin.addEventListener('input', (e) => {
                _samplesFilterState.scoreMin = e.target.value;
                _renderSamplesTable(offset);
            });
        }
        if (scoreMax) {
            scoreMax.addEventListener('input', (e) => {
                _samplesFilterState.scoreMax = e.target.value;
                _renderSamplesTable(offset);
            });
        }

        // Filtreleri temizle butonu
        const clearBtn = document.getElementById('samplesFilterClear');
        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                _samplesFilterState.sourceFile = '';
                _samplesFilterState.intent = '';
                _samplesFilterState.relevance = '';
                _samplesFilterState.scoreMin = '';
                _samplesFilterState.scoreMax = '';
                // Input elemanlarını sıfırla
                if (srcInput) srcInput.value = '';
                if (intentSelect) intentSelect.value = '';
                if (relSelect) relSelect.value = '';
                if (scoreMin) scoreMin.value = '';
                if (scoreMax) scoreMax.value = '';
                _renderSamplesTable(offset);
            });
        }

        // Sıralanabilir header tıklama
        document.querySelectorAll('.samples-table th.sortable').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.dataset.sortField;
                if (_samplesFilterState.sortField === field) {
                    // Toggle: asc → desc → none
                    if (_samplesFilterState.sortDir === 'asc') {
                        _samplesFilterState.sortDir = 'desc';
                    } else if (_samplesFilterState.sortDir === 'desc') {
                        _samplesFilterState.sortField = null;
                        _samplesFilterState.sortDir = null;
                    }
                } else {
                    _samplesFilterState.sortField = field;
                    _samplesFilterState.sortDir = 'asc';
                }
                _renderSamplesTable(offset);
            });
        });
    }

    async function showJobSamples(jobId, page = 1) {
        try {
            if (page === 1) {
                toast('info', 'Örnekler yükleniyor...');
                // Yeni job yüklendiğinde filtreleri sıfırla
                _samplesFilterState = {
                    sourceFile: '', intent: '', relevance: '',
                    scoreMin: '', scoreMax: '',
                    sortField: null, sortDir: null
                };
            }

            const offset = (page - 1) * SAMPLES_PER_PAGE;
            const data = await apiCall(`/ml/training/samples/${jobId}?limit=${SAMPLES_PER_PAGE}&offset=${offset}`);
            const samples = data.samples || [];
            const total = data.total || 0;
            const totalPages = Math.ceil(total / SAMPLES_PER_PAGE);

            if (samples.length === 0 && page === 1) {
                if (window.VyraModal) {
                    VyraModal.info({
                        title: `Eğitim Örnekleri #${jobId}`,
                        message: '<div class="job-detail-modal"><p>Bu eğitim için henüz kayıtlı örnek bulunamadı.</p><p class="samples-note">Not: Örnek kayıtları v2.33.0 sonrası eğitimlerden itibaren saklanmaktadır.</p></div>',
                        confirmText: 'Kapat'
                    });
                } else {
                    VyraModal.info({
                        title: `Eğitim Örnekleri #${jobId}`,
                        message: '<div class="job-detail-modal"><p>Bu eğitim için örnek bulunamadı.</p><p class="samples-note">Not: Örnek kayıtları v2.33.0 sonrası eğitimlerden itibaren saklanmaktadır.</p></div>',
                        confirmText: 'Kapat'
                    });
                }
                return;
            }

            // Sayfadaki datayı sakla (client-side filtre/sıralama için)
            _samplesPageData = samples;

            // Intent benzersiz listesini çıkar (filtre dropdown için)
            const uniqueIntents = [...new Set(samples.map(s => s.intent).filter(Boolean))].sort();

            const rows = samples.map((s, i) => {
                const relIcon = s.relevance === 1 ? '✅' : '❌';
                const rowNum = offset + i + 1;
                const showAnswerBtn = s.has_learned_answer
                    ? `<button class="sample-answer-btn sample-answer-ready" data-query="${escapeHtml(s.query)}" onclick="MLTrainingModule.showSampleAnswer(this)" title="Öğrenilmiş cevabı göster"><i class="fa-solid fa-comment-dots"></i></button>`
                    : (s.relevance === 1 && s.score >= 0.70)
                        ? `<span class="sample-answer-pending" title="Cevap henüz üretilmedi"><i class="fa-solid fa-hourglass-half"></i></span>`
                        : '<span class="sample-answer-na">—</span>';
                return `<tr>
                    <td class="sample-num">${rowNum}</td>
                    <td class="sample-query">${escapeHtml(s.query)}</td>
                    <td class="sample-source">${escapeHtml(s.source_file || '-')}</td>
                    <td><span class="sample-intent" data-intent="${s.intent}">${s.intent || '-'}</span></td>
                    <td class="sample-rel">${relIcon}</td>
                    <td class="sample-score">${s.score ? s.score.toFixed(2) : '-'}</td>
                    <td class="sample-answer-col">${showAnswerBtn}</td>
                </tr>`;
            }).join('');

            // Pagination kontrolleri
            let paginationHtml = '';
            if (totalPages > 1) {
                paginationHtml = `
                    <div class="samples-pagination">
                        <div class="samples-pagination-total">
                            Toplam: <strong>${total}</strong> örnek
                        </div>
                        <div class="samples-pagination-controls">
                            <button class="samples-page-btn" ${page <= 1 ? 'disabled' : ''} 
                                onclick="VyraModal.close(); setTimeout(() => MLTrainingModule.showJobSamples(${jobId}, 1), 200);" title="İlk sayfa">
                                <i class="fa-solid fa-angles-left"></i>
                            </button>
                            <button class="samples-page-btn" ${page <= 1 ? 'disabled' : ''} 
                                onclick="VyraModal.close(); setTimeout(() => MLTrainingModule.showJobSamples(${jobId}, ${page - 1}), 200);" title="Önceki sayfa">
                                <i class="fa-solid fa-angle-left"></i>
                            </button>
                            <span class="samples-page-info">Sayfa <strong>${page}</strong> / ${totalPages}</span>
                            <button class="samples-page-btn" ${page >= totalPages ? 'disabled' : ''} 
                                onclick="VyraModal.close(); setTimeout(() => MLTrainingModule.showJobSamples(${jobId}, ${page + 1}), 200);" title="Sonraki sayfa">
                                <i class="fa-solid fa-angle-right"></i>
                            </button>
                            <button class="samples-page-btn" ${page >= totalPages ? 'disabled' : ''} 
                                onclick="VyraModal.close(); setTimeout(() => MLTrainingModule.showJobSamples(${jobId}, ${totalPages}), 200);" title="Son sayfa">
                                <i class="fa-solid fa-angles-right"></i>
                            </button>
                        </div>
                    </div>`;
            }

            // Filtre satırı HTML
            const filterHtml = `
                <div class="samples-filter-row">
                    <div class="samples-filter-group">
                        <span class="samples-filter-label"><i class="fa-solid fa-filter" style="margin-right: 4px;"></i>Filtre:</span>
                    </div>
                    <div class="samples-filter-group">
                        <span class="samples-filter-label">Kaynak</span>
                        <input type="text" id="samplesFilterSource" class="samples-filter-input" 
                               placeholder="Dosya ara..." value="${escapeHtml(_samplesFilterState.sourceFile)}">
                    </div>
                    <div class="samples-filter-group">
                        <span class="samples-filter-label">Intent</span>
                        <select id="samplesFilterIntent" class="samples-filter-select">
                            <option value="">Tümü</option>
                            ${uniqueIntents.map(i => `<option value="${i}" ${_samplesFilterState.intent === i ? 'selected' : ''}>${i}</option>`).join('')}
                        </select>
                    </div>
                    <div class="samples-filter-group">
                        <span class="samples-filter-label">Eşleşme</span>
                        <select id="samplesFilterRelevance" class="samples-filter-select" style="min-width: 80px;">
                            <option value="">Tümü</option>
                            <option value="1" ${_samplesFilterState.relevance === '1' ? 'selected' : ''}>✅ Pozitif</option>
                            <option value="0" ${_samplesFilterState.relevance === '0' ? 'selected' : ''}>❌ Negatif</option>
                        </select>
                    </div>
                    <div class="samples-filter-group">
                        <span class="samples-filter-label">Skor</span>
                        <input type="number" id="samplesFilterScoreMin" class="samples-filter-input" 
                               placeholder="Min" step="0.01" min="0" max="1" style="min-width: 65px; width: 65px;"
                               value="${_samplesFilterState.scoreMin}">
                        <span style="color: #64748b;">-</span>
                        <input type="number" id="samplesFilterScoreMax" class="samples-filter-input" 
                               placeholder="Max" step="0.01" min="0" max="1" style="min-width: 65px; width: 65px;"
                               value="${_samplesFilterState.scoreMax}">
                    </div>
                    <button id="samplesFilterClear" class="samples-filter-btn" title="Filtreleri temizle">
                        <i class="fa-solid fa-xmark"></i> Temizle
                    </button>
                    <span class="samples-filtered-count" style="display: none;"></span>
                </div>`;

            const content = `
                <div class="samples-viewer">
                    <div class="samples-summary">
                        <span>Toplam: <strong>${total}</strong> örnek</span>
                        <span>Gösterilen: <strong>${offset + 1}-${offset + samples.length}</strong></span>
                    </div>
                    ${filterHtml}
                    <div class="samples-table-wrapper">
                        <table class="samples-table">
                            <thead>
                                <tr>
                                    <th>#</th>
                                    <th>Sentetik Soru</th>
                                    <th class="sortable" data-sort-field="source_file">
                                        <span class="samples-th-content">Kaynak Dosya ${_sortIcon('source_file')}</span>
                                    </th>
                                    <th class="sortable" data-sort-field="intent">
                                        <span class="samples-th-content">Intent ${_sortIcon('intent')}</span>
                                    </th>
                                    <th class="sortable" data-sort-field="relevance">
                                        <span class="samples-th-content">Eşleşme ${_sortIcon('relevance')}</span>
                                    </th>
                                    <th class="sortable" data-sort-field="score">
                                        <span class="samples-th-content">Skor ${_sortIcon('score')}</span>
                                    </th>
                                    <th>Cevap</th>
                                </tr>
                            </thead>
                            <tbody>${rows}</tbody>
                        </table>
                    </div>
                    ${paginationHtml}
                    <div class="samples-note">Örnekler, bilgi tabanındaki chunk'lardan üretilen sentetik soru-cevap çiftleridir. ✅ = ilgili eşleşme, ❌ = negatif örnek</div>
                </div>
            `;

            if (window.VyraModal) {
                VyraModal.info({
                    title: `Eğitim Örnekleri #${jobId} (${total} adet)`,
                    message: content,
                    confirmText: 'Kapat'
                });

                // Modal render edildikten sonra event handler'ları bağla
                requestAnimationFrame(() => {
                    _bindFilterEvents(offset);
                });
            } else {
                VyraModal.info({
                    title: 'Eğitim Örnekleri',
                    message: `${total} eğitim örneği yüklendi.`,
                    confirmText: 'Tamam'
                });
            }

        } catch (error) {
            console.error('[MLTraining] Samples yükleme hatası:', error);
            toast('error', 'Örnekler yüklenemedi');
        }
    }

    // HTML escape helper
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // 🆕 v2.51.0: Öğrenilmiş cevabı API'den çekip modal ile göster
    async function showSampleAnswer(btnEl) {
        const query = btnEl.dataset.query;
        if (!query) return;

        // Loading state
        const origHtml = btnEl.innerHTML;
        btnEl.disabled = true;
        btnEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';

        try {
            const data = await window.VYRA_API.request(`/system/ml/learned-answer?question=${encodeURIComponent(query)}`);

            if (!data || !data.found) {
                btnEl.innerHTML = origHtml;
                btnEl.disabled = false;
                toast('info', 'Bu soru için henüz öğrenilmiş cevap üretilmedi');
                return;
            }

            const content = `
                <div class="learned-answer-preview">
                    <div class="learned-answer-question">
                        <i class="fa-solid fa-circle-question"></i>
                        <span>${escapeHtml(query)}</span>
                    </div>
                    <div class="learned-answer-body">
                        ${escapeHtml(data.answer).replace(/\n/g, '<br>')}
                    </div>
                    <div class="learned-answer-meta">
                        <span><i class="fa-solid fa-star"></i> Kalite: ${(data.quality_score || 0).toFixed(2)}</span>
                        <span><i class="fa-solid fa-eye"></i> Kullanım: ${data.hit_count || 0}</span>
                    </div>
                </div>
            `;

            VyraModal.info({
                title: '🧠 Öğrenilmiş Cevap',
                message: content,
                confirmText: 'Kapat'
            });

        } catch (err) {
            console.error('[MLTraining] Learned answer hatası:', err);
            toast('error', 'Cevap getirilemedi');
        } finally {
            btnEl.innerHTML = origHtml;
            btnEl.disabled = false;
        }
    }

    // Public API
    return {
        init,
        loadStats,
        loadHistory,
        loadSchedule,
        loadContinuousStatus,
        showErrorDetail,   // Hata detayı modal
        showJobDetail,     // İş detayı modal
        showJobSamples,     // Eğitim örnekleri modal
        showSampleAnswer    // 🆕 v2.51.0: Öğrenilmiş cevap göster
    };
})();

// Otomatik init
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', window.MLTrainingModule.init);
} else {
    window.MLTrainingModule.init();
}
