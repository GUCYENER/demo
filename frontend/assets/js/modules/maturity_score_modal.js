/**
 * Maturity Score Modal Module
 * ============================
 * Dosya yükleme öncesi RAG olgunluk skoru analiz modalı.
 * Kategorik skor gösterimi, ihlal raporu ve yükleme onayı.
 * 
 * @version 1.0.0
 */

const MaturityScoreModal = {
    API_BASE: (window.API_BASE_URL || 'http://localhost:8002') + '/api',
    overlay: null,
    results: [],
    activeFileIndex: 0,
    pendingFiles: null,
    onConfirmCallback: null,
    onCancelCallback: null,

    /**
     * Modal HTML'ini oluşturur ve DOM'a ekler
     */
    init() {
        if (document.getElementById('maturity-modal-overlay')) return;

        const html = `
            <div id="maturity-modal-overlay" class="maturity-modal-overlay">
                <div class="maturity-modal">
                    <div class="maturity-modal-header">
                        <h3><i class="fas fa-clipboard-check"></i> Dosya Olgunluk Analizi</h3>
                        <button class="maturity-close-btn" id="maturity-close-btn">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                    <div class="maturity-modal-body" id="maturity-modal-body">
                        <!-- İçerik dinamik olarak doldurulacak -->
                    </div>
                    <div class="maturity-modal-footer" id="maturity-modal-footer">
                        <div class="maturity-footer-left">
                            <button class="maturity-btn maturity-btn-violations" id="maturity-btn-violations">
                                <i class="fas fa-exclamation-triangle"></i> İhlal Raporu
                            </button>
                            <button class="maturity-btn maturity-btn-enhance hidden" id="maturity-btn-enhance">
                                <i class="fas fa-magic"></i> İyileştir
                            </button>
                        </div>
                        <div class="maturity-footer-right">
                            <button class="maturity-btn maturity-btn-secondary" id="maturity-btn-cancel">
                                <i class="fas fa-times"></i> İptal
                            </button>
                            <button class="maturity-btn maturity-btn-primary" id="maturity-btn-upload">
                                <i class="fas fa-cloud-upload-alt"></i> Yükle
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', html);
        this.overlay = document.getElementById('maturity-modal-overlay');
        this._bindEvents();
    },

    /**
     * Event listener'ları bağlar
     */
    _bindEvents() {
        // Kapat butonu
        document.getElementById('maturity-close-btn').addEventListener('click', () => this.close());

        // ESC tuşu
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.overlay && this.overlay.classList.contains('active')) {
                this.close();
            }
        });

        // v3.2.1: Overlay tıklama koruması — modalın dışına tıklayınca kapanMAZ
        // Global kural: "Overlay'e tıklayınca pencere KAPANMAMALIDIR"
        // EventListener sadece modalIn kendisinde stopPropagation ile engelleniyor
        // Overlay click yok — sadece X ve İptal butonu kapatır

        // İptal butonu
        document.getElementById('maturity-btn-cancel').addEventListener('click', () => this.close());

        // Yükle butonu
        document.getElementById('maturity-btn-upload').addEventListener('click', () => {
            // Skorları topla
            const scores = this.results.map(r => r.total_score);
            this.close();
            if (this.onConfirmCallback) {
                this.onConfirmCallback(this.pendingFiles, scores);
            }
        });

        // İhlal Raporu butonu
        document.getElementById('maturity-btn-violations').addEventListener('click', () => {
            this._toggleViolations();
        });

        // İyileştir butonu
        document.getElementById('maturity-btn-enhance').addEventListener('click', () => {
            this._onEnhanceClick();
        });
    },

    /**
     * Dosyaları analiz eder ve modalı açar
     * @param {File[]} files - Analiz edilecek dosyalar
     * @param {Function} onConfirm - Yükleme onay callback'i
     * @param {Function} onCancel - İptal callback'i
     */
    async analyze(files, onConfirm, onCancel) {
        this.init();
        this.pendingFiles = files;
        this.onConfirmCallback = onConfirm;
        this.onCancelCallback = onCancel;
        this.activeFileIndex = 0;

        // Modalı aç - loading göster
        this.overlay.classList.add('active');
        document.body.style.overflow = 'hidden';

        const body = document.getElementById('maturity-modal-body');
        const footer = document.getElementById('maturity-modal-footer');
        footer.classList.remove('visible');

        body.innerHTML = `
            <div class="maturity-analyzing">
                <div class="spinner"></div>
                <p>Dosyalar analiz ediliyor... (${files.length} dosya)</p>
            </div>
        `;

        try {
            const formData = new FormData();
            files.forEach(file => formData.append('files', file));

            // v3.2.1: Fetch timeout — büyük dosyalarda sonsuz spinner önlenir
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 120000); // 120 saniye

            const token = localStorage.getItem('access_token');
            const response = await fetch(`${this.API_BASE}/rag/analyze-maturity`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` },
                body: formData,
                signal: controller.signal
            });
            clearTimeout(timeoutId);

            if (!response.ok) {
                throw new Error('Analiz isteği başarısız oldu');
            }

            const data = await response.json();
            this.results = data.results || [];

            // Sonuçları göster
            footer.classList.add('visible');
            this._renderResults();

        } catch (error) {
            console.error('[MaturityScore] Analiz hatası:', error);
            body.innerHTML = `
                <div class="maturity-analyzing">
                    <i class="fas fa-exclamation-circle maturity-error-icon"></i>
                    <p>Analiz sırasında bir hata oluştu: ${error.message}</p>
                    <div class="maturity-error-actions">
                        <button class="maturity-btn maturity-btn-secondary" onclick="MaturityScoreModal.close()">İptal</button>
                        <button class="maturity-btn maturity-btn-primary" onclick="MaturityScoreModal._skipAndUpload()">Yine de Yükle</button>
                    </div>
                </div>
            `;
        }
    },

    /**
     * Analiz sonuçlarını render eder
     */
    _renderResults() {
        const body = document.getElementById('maturity-modal-body');
        if (!this.results || this.results.length === 0) {
            body.innerHTML = '<p class="maturity-empty-msg">Analiz sonucu bulunamadı.</p>';
            return;
        }

        let html = '';

        // Birden fazla dosya varsa tab'lar
        if (this.results.length > 1) {
            html += '<div class="maturity-file-tabs">';
            this.results.forEach((result, i) => {
                const shortName = result.file_name.length > 25
                    ? result.file_name.substring(0, 22) + '...'
                    : result.file_name;
                html += `<button class="maturity-file-tab ${i === this.activeFileIndex ? 'active' : ''}" 
                    onclick="MaturityScoreModal._switchFile(${i})">${shortName}</button>`;
            });
            html += '</div>';
        }

        // Aktif dosyanın sonuçlarını göster
        html += this._renderFileResult(this.results[this.activeFileIndex]);

        body.innerHTML = html;

        // İyileştir butonunu skor < eşik değeri ise göster
        const enhanceBtn = document.getElementById('maturity-btn-enhance');
        if (enhanceBtn) {
            const activeResult = this.results[this.activeFileIndex];
            const avgScore = activeResult ? Math.round(activeResult.total_score) : 100;
            const threshold = window._maturityEnhanceThreshold ?? 80;
            // v3.2.1: inline style yerine CSS class kullan
            if (avgScore < threshold) {
                enhanceBtn.classList.remove('hidden');
            } else {
                enhanceBtn.classList.add('hidden');
            }
        }
    },

    /**
     * Tek dosyanın sonucunu render eder
     */
    _renderFileResult(result) {
        const score = Math.round(result.total_score);
        const scoreClass = this._getScoreClass(score);
        const scoreLabel = this._getScoreLabel(score);
        const circumference = 2 * Math.PI * 38;
        const offset = circumference - (score / 100) * circumference;
        const strokeColor = this._getScoreColor(score);

        let html = '';

        // Toplam skor
        html += `
            <div class="maturity-total-score">
                <div class="maturity-score-circle">
                    <svg viewBox="0 0 84 84">
                        <circle class="score-bg" cx="42" cy="42" r="38"></circle>
                        <circle class="score-fill" cx="42" cy="42" r="38" 
                            stroke="${strokeColor}"
                            stroke-dasharray="${circumference}"
                            stroke-dashoffset="${offset}"></circle>
                    </svg>
                    <span class="maturity-score-value">${score}</span>
                </div>
                <div class="maturity-score-info">
                    <h4>${result.file_name}</h4>
                    <p>${result.file_type} • ${result.violations ? result.violations.length : 0} ihlal</p>
                    <span class="maturity-score-label ${scoreClass}">${scoreLabel}</span>
                </div>
            </div>
        `;

        // Kategoriler
        if (result.categories && result.categories.length > 0) {
            html += '<div class="maturity-categories">';
            for (const cat of result.categories) {
                const catScore = Math.round(cat.score);
                const catColor = this._getScoreColor(catScore);
                html += `
                    <div class="maturity-category">
                        <div class="maturity-category-header">
                            <span class="maturity-category-name">${cat.name}</span>
                            <span class="maturity-category-score" style="color:${catColor}">${catScore}%</span>
                        </div>
                        <div class="maturity-category-bar">
                            <div class="maturity-category-fill" style="width:${catScore}%;background:${catColor}"></div>
                        </div>
                        <div class="maturity-rules">
                `;
                for (const rule of cat.rules) {
                    const iconClass = rule.status === 'pass' ? 'fas fa-check' :
                        rule.status === 'warning' ? 'fas fa-exclamation' : 'fas fa-times';
                    html += `
                        <div class="maturity-rule">
                            <span class="maturity-rule-icon ${rule.status}"><i class="${iconClass}"></i></span>
                            <div class="maturity-rule-text">
                                <span class="maturity-rule-name">${rule.name}</span>
                                <span class="maturity-rule-detail">${rule.detail || ''}</span>
                            </div>
                        </div>
                    `;
                }
                html += '</div></div>';
            }
            html += '</div>';
        }

        // Violations panel (varsayılan gizli)
        html += this._renderViolationsPanel(result);

        return html;
    },

    /**
     * İhlal raporu panelini render eder
     */
    _renderViolationsPanel(result) {
        if (!result.violations || result.violations.length === 0) return '';

        const examples = {
            'Başlık Hiyerarşisi': 'Heading 1 → Ana Başlık, Heading 2 → Alt Başlık şeklinde kullanın.',
            'Tablo Formatı': 'Tabloları pipe (|) veya tab ile düzenli sütunlara ayırın.',
            'Aranabilir Metin': 'Taranmış PDF\'leri OCR ile metin tabanlı hale getirin.',
            'Metin Yoğunluğu': 'Önemli bilgileri görsel yerine metin olarak yazın.',
            'Gereksiz İçerik': 'Sayfa header/footer tekrarlarını temizleyin veya basitleştirin.',
            'Türkçe Karakter': 'PDF\'i UTF-8 encoding ile yeniden kaydedin.',
            'Word Stilleri': 'Manuel kalınlaştırma yerine Word Heading 1/2/3 stillerini kullanın.',
            'Metin Kutusu': 'Text box içindeki metni normal paragrafa taşıyın.',
            'Tablo Başlık Satırı': 'Tablonuzun ilk satırına sütun başlıklarını yazın.',
            'Görseller vs Metin': 'Görsel içindeki önemli bilgileri metin olarak da ekleyin.',
            'Liste Formatı': 'Manuel tire (-) yerine Word\'ün liste (bullet/numbered) stilini kullanın.',
            'Gereksiz Boşluklar': 'Fazla Enter ve boş satırları silin.',
            'İlk Satır Başlık': 'Her sayfanın 1. satırına sütun başlıklarını yazın.',
            'Merge Hücreler': 'Birleştirilmiş hücreleri ayırıp her birine değer girin.',
            'Boş Satır/Sütun': 'Veri blokları arasındaki boş satırları silin.',
            'Tutarlı Veri Tipi': 'Her sütunda aynı tip veri (metin/sayı) kullanın.',
            'Açıklama Satırları': 'Açıklamaları ayrı bir sayfaya taşıyın, veri sayfasının üstüne yazmayın.',
            'Formül vs Değer': 'Yapıştır > Değer Olarak Yapıştır kullanarak formülleri sabit değere çevirin.'
        };

        let html = `
            <div class="maturity-violations-panel" id="maturity-violations-panel">
                <table class="maturity-violations-table">
                    <thead>
                        <tr>
                            <th>Durum</th>
                            <th>Kural</th>
                            <th>Kategori</th>
                            <th>Detay</th>
                            <th>Örnek Çözüm</th>
                        </tr>
                    </thead>
                    <tbody>
        `;

        for (const v of result.violations) {
            const statusIcon = v.status === 'fail'
                ? '<i class="fas fa-times-circle v-status-fail"></i>'
                : '<i class="fas fa-exclamation-triangle v-status-warning"></i>';
            const example = examples[v.name] || 'Dosya hazırlama kurallarını inceleyin.';

            html += `
                <tr>
                    <td>${statusIcon}</td>
                    <td class="v-name">${v.name}</td>
                    <td>${v.category}</td>
                    <td class="v-detail">${v.detail || '-'}</td>
                    <td class="v-example">${example}</td>
                </tr>
            `;
        }

        html += '</tbody></table></div>';
        return html;
    },

    /**
     * Dosya tab'ı değiştirir
     */
    _switchFile(index) {
        this.activeFileIndex = index;
        this._renderResults();
    },

    /**
     * İhlal raporu panelini aç/kapa
     */
    _toggleViolations() {
        const panel = document.getElementById('maturity-violations-panel');
        if (!panel) {
            console.warn('[MaturityScore] Violations panel bulunamadı');
            return;
        }
        panel.classList.toggle('active');
        // Panel açıldıysa otomatik scroll ile görünür yap
        if (panel.classList.contains('active')) {
            setTimeout(() => panel.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100);
        }
    },

    /**
     * Analiz başarısız olsa bile yüklemeye devam et
     */
    _skipAndUpload() {
        this.close();
        if (this.onConfirmCallback && this.pendingFiles) {
            this.onConfirmCallback(this.pendingFiles);
        }
    },

    /**
     * Modalı kapatır
     */
    close() {
        if (this.overlay) {
            this.overlay.classList.remove('active');
            document.body.style.overflow = '';
        }
    },

    /**
     * Skor sınıfını döndürür
     */
    _getScoreClass(score) {
        if (score >= 85) return 'excellent';
        if (score >= 65) return 'good';
        if (score >= 45) return 'average';
        return 'poor';
    },

    /**
     * Skor etiketini döndürür
     */
    _getScoreLabel(score) {
        if (score >= 85) return 'Mükemmel';
        if (score >= 65) return 'İyi';
        if (score >= 45) return 'Orta';
        return 'Düşük';
    },

    /**
     * Skor rengini döndürür
     */
    _getScoreColor(score) {
        if (score >= 85) return '#22c55e';
        if (score >= 65) return '#3b82f6';
        if (score >= 45) return '#f59e0b';
        return '#ef4444';
    },

    /**
     * Dosya listesindeki skor badge'ini oluşturur (static helper)
     * @param {number|null} score - Olgunluk skoru
     * @returns {string} HTML badge
     */
    renderBadge(score) {
        // v3.2.1: Tip güvenliği — NaN, string veya beklenmedik değer kontrolü
        if (score === null || score === undefined || typeof score !== 'number' || isNaN(score)) {
            return '<span class="maturity-badge badge-empty"><i class="fas fa-minus"></i> -</span>';
        }
        const s = Math.round(score);
        const cls = this._getScoreClass(s);
        const icon = s >= 85 ? 'fa-check-circle' : s >= 65 ? 'fa-check' : s >= 45 ? 'fa-exclamation' : 'fa-times-circle';
        return `<span class="maturity-badge score-${cls}"><i class="fas ${icon}"></i> ${s}</span>`;
    },

    /**
     * İyileştir butonuna tıklanınca çalışır
     */
    _onEnhanceClick() {
        // Aktif dosyanın maturity sonucunu al
        const activeResult = this.results[this.activeFileIndex];
        const pendingFile = this.pendingFiles[this.activeFileIndex];

        if (!pendingFile) {
            console.error('[MaturityScore] İyileştir: pendingFile bulunamadı');
            return;
        }

        // Maturity modal'ı kapat
        this.close();

        // Enhancement modal'ı aç
        if (window.DocumentEnhancerModal) {
            window.DocumentEnhancerModal.analyze(pendingFile, activeResult);
        } else {
            console.error('[MaturityScore] DocumentEnhancerModal bulunamadı');
        }
    }
};

// Global erişim
window.MaturityScoreModal = MaturityScoreModal;
