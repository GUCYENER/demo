/**
 * FILE GUIDELINES MODAL MODULE
 * Dosya hazırlama kuralları için modal yönetimi
 * 
 * @version 1.0.0
 * @author VYRA Team
 */

const FileGuidelinesModal = (function() {
    'use strict';

    // ========================================
    // PRIVATE VARIABLES
    // ========================================
    let isInitialized = false;
    let overlay = null;
    let currentTab = 'pdf';

    // ========================================
    // PRIVATE METHODS
    // ========================================

    /**
     * ESC tuşu ile modal kapatma
     */
    function handleKeyDown(e) {
        if (e.key === 'Escape' && overlay && overlay.classList.contains('active')) {
            close();
        }
    }

    /**
     * Tab switching
     */
    function switchTab(tabName) {
        if (!overlay) return;

        currentTab = tabName;

        // Tab butonlarını güncelle
        const tabs = overlay.querySelectorAll('.file-guidelines-tab');
        tabs.forEach(tab => {
            if (tab.dataset.tab === tabName) {
                tab.classList.add('active');
            } else {
                tab.classList.remove('active');
            }
        });

        // Tab içeriklerini güncelle
        const panes = overlay.querySelectorAll('.file-guidelines-pane');
        panes.forEach(pane => {
            if (pane.dataset.pane === tabName) {
                pane.classList.add('active');
            } else {
                pane.classList.remove('active');
            }
        });
    }

    /**
     * Modal HTML oluştur
     */
    function createModalHTML() {
        return `
            <div class="file-guidelines-modal">
                <!-- Header -->
                <div class="file-guidelines-header">
                    <div class="file-guidelines-title">
                        <i class="fa-solid fa-book-open"></i>
                        <span>Dosya Hazırlama Kuralları</span>
                    </div>
                    <button type="button" class="file-guidelines-close" title="Kapat">
                        <i class="fa-solid fa-times"></i>
                    </button>
                </div>

                <!-- Tabs -->
                <div class="file-guidelines-tabs">
                    <button type="button" class="file-guidelines-tab active" data-tab="pdf">
                        <i class="fa-solid fa-file-pdf"></i>
                        <span>PDF</span>
                    </button>
                    <button type="button" class="file-guidelines-tab" data-tab="docx">
                        <i class="fa-solid fa-file-word"></i>
                        <span>DOCX</span>
                    </button>
                    <button type="button" class="file-guidelines-tab" data-tab="xlsx">
                        <i class="fa-solid fa-file-excel"></i>
                        <span>XLSX</span>
                    </button>
                </div>

                <!-- Content -->
                <div class="file-guidelines-content">
                    <!-- PDF Panel -->
                    <div class="file-guidelines-pane active" data-pane="pdf">
                        <div class="guidelines-intro">
                            <i class="fa-solid fa-lightbulb"></i>
                            <p>PDF dosyalarınızı RAG sistemine yüklemeden önce aşağıdaki kurallara uygun hazırlayarak daha doğru sonuçlar alabilirsiniz.</p>
                        </div>
                        <ul class="guidelines-list pdf-rules">
                            <li>
                                <div class="rule-icon"><i class="fa-solid fa-heading"></i></div>
                                <div class="rule-content">
                                    <div class="rule-title">Başlık Hiyerarşisi Kullanın</div>
                                    <div class="rule-desc">Heading 1, Heading 2, Heading 3 gibi başlık seviyeleri kullanın. Sistem başlıkları otomatik tespit eder.</div>
                                </div>
                            </li>
                            <li>
                                <div class="rule-icon"><i class="fa-solid fa-table"></i></div>
                                <div class="rule-content">
                                    <div class="rule-title">Tabloları Düzgün Formatlayın</div>
                                    <div class="rule-desc">Tablolar düzenli satır ve sütunlarla oluşturulmalı. Merge edilmiş hücrelerden kaçının.</div>
                                </div>
                            </li>
                            <li>
                                <div class="rule-icon"><i class="fa-solid fa-search"></i></div>
                                <div class="rule-content">
                                    <div class="rule-title">Aranabilir Metin Olmalı</div>
                                    <div class="rule-desc">Taranmış (scanned) PDF'ler yerine, metin içeren veya OCR yapılmış PDF'ler tercih edin.</div>
                                </div>
                            </li>
                            <li>
                                <div class="rule-icon"><i class="fa-solid fa-font"></i></div>
                                <div class="rule-content">
                                    <div class="rule-title">Metin Tercih Edin</div>
                                    <div class="rule-desc">Resim olarak kaydedilmiş metin yerine, gerçek metin içeriği kullanın.</div>
                                </div>
                            </li>
                            <li>
                                <div class="rule-icon"><i class="fa-solid fa-broom"></i></div>
                                <div class="rule-content">
                                    <div class="rule-title">Gereksiz İçerikleri Temizleyin</div>
                                    <div class="rule-desc">Tekrarlayan header/footer, sayfa numaraları gibi gereksiz içerikler sonuçları etkileyebilir.</div>
                                </div>
                            </li>
                            <li>
                                <div class="rule-icon"><i class="fa-solid fa-language"></i></div>
                                <div class="rule-content">
                                    <div class="rule-title">Türkçe Karakter Kontrolü</div>
                                    <div class="rule-desc">ğ, ü, ş, ı, ö, ç karakterlerinin doğru encode edildiğinden emin olun.</div>
                                </div>
                            </li>
                        </ul>
                    </div>

                    <!-- DOCX Panel -->
                    <div class="file-guidelines-pane" data-pane="docx">
                        <div class="guidelines-intro">
                            <i class="fa-solid fa-lightbulb"></i>
                            <p>Word dosyalarınızı RAG sistemine yüklemeden önce aşağıdaki kurallara uygun hazırlayarak daha doğru sonuçlar alabilirsiniz.</p>
                        </div>
                        <ul class="guidelines-list docx-rules">
                            <li>
                                <div class="rule-icon"><i class="fa-solid fa-list-ol"></i></div>
                                <div class="rule-content">
                                    <div class="rule-title">Word Stilleri Kullanın</div>
                                    <div class="rule-desc">Manuel kalın/büyük yazı yerine Heading 1, 2, 3 stilleri kullanın. Sistem bölümleri otomatik ayırır.</div>
                                </div>
                            </li>
                            <li>
                                <div class="rule-icon"><i class="fa-solid fa-square"></i></div>
                                <div class="rule-content">
                                    <div class="rule-title">Metin Kutusu Kullanmayın</div>
                                    <div class="rule-desc">Text box içindeki metinler işlenemez. Normal paragraf olarak yazın.</div>
                                </div>
                            </li>
                            <li>
                                <div class="rule-icon"><i class="fa-solid fa-table-columns"></i></div>
                                <div class="rule-content">
                                    <div class="rule-title">Tablo Başlık Satırı</div>
                                    <div class="rule-desc">Tablolarınızın ilk satırı başlık satırı olmalı ve her sütunun ne içerdiğini belirtmeli.</div>
                                </div>
                            </li>
                            <li>
                                <div class="rule-icon"><i class="fa-solid fa-image"></i></div>
                                <div class="rule-content">
                                    <div class="rule-title">Görseller Yerine Metin</div>
                                    <div class="rule-desc">Önemli bilgiler görselde değil, metin olarak açıklanmalı. Görseller işlenemez.</div>
                                </div>
                            </li>
                            <li>
                                <div class="rule-icon"><i class="fa-solid fa-list-check"></i></div>
                                <div class="rule-content">
                                    <div class="rule-title">Liste Formatı</div>
                                    <div class="rule-desc">Madde işaretli ve numaralı listeler düzgün Word formatında olmalı.</div>
                                </div>
                            </li>
                            <li>
                                <div class="rule-icon"><i class="fa-solid fa-eraser"></i></div>
                                <div class="rule-content">
                                    <div class="rule-title">Gereksiz Boşlukları Temizleyin</div>
                                    <div class="rule-desc">Fazla boş satırlar, sayfa sonları (page break) sonuçları bozabilir.</div>
                                </div>
                            </li>
                        </ul>
                    </div>

                    <!-- XLSX Panel -->
                    <div class="file-guidelines-pane" data-pane="xlsx">
                        <div class="guidelines-intro">
                            <i class="fa-solid fa-lightbulb"></i>
                            <p>Excel dosyalarınızı RAG sistemine yüklemeden önce aşağıdaki kurallara uygun hazırlayarak daha doğru sonuçlar alabilirsiniz.</p>
                        </div>
                        <ul class="guidelines-list xlsx-rules">
                            <li>
                                <div class="rule-icon"><i class="fa-solid fa-arrow-up"></i></div>
                                <div class="rule-content">
                                    <div class="rule-title">İlk Satır Başlık Olmalı</div>
                                    <div class="rule-desc">Her sayfanın ilk satırı sütun başlıklarını içermeli. Ad, Tip, Açıklama gibi.</div>
                                </div>
                            </li>
                            <li>
                                <div class="rule-icon"><i class="fa-solid fa-table-cells"></i></div>
                                <div class="rule-content">
                                    <div class="rule-title">Merge Hücrelerden Kaçının</div>
                                    <div class="rule-desc">Birleştirilmiş hücreler veri kaybına neden olabilir. Her hücre bağımsız olmalı.</div>
                                </div>
                            </li>
                            <li>
                                <div class="rule-icon"><i class="fa-solid fa-border-none"></i></div>
                                <div class="rule-content">
                                    <div class="rule-title">Boş Satır/Sütun Bırakmayın</div>
                                    <div class="rule-desc">Veriler arasında boş satır veya sütun bırakmak bölümleme sorunlarına yol açar.</div>
                                </div>
                            </li>
                            <li>
                                <div class="rule-icon"><i class="fa-solid fa-filter"></i></div>
                                <div class="rule-content">
                                    <div class="rule-title">Tutarlı Veri Tipi</div>
                                    <div class="rule-desc">Her sütunda aynı veri tipi olmalı (metin, sayı, tarih). Karışık tiplerden kaçının.</div>
                                </div>
                            </li>
                            <li>
                                <div class="rule-icon"><i class="fa-solid fa-comment-slash"></i></div>
                                <div class="rule-content">
                                    <div class="rule-title">Açıklama Satırları Yerine Metadata</div>
                                    <div class="rule-desc">Veri üstüne açıklama satırları eklemeyin. Gerekirse ayrı bir sayfa kullanın.</div>
                                </div>
                            </li>
                            <li>
                                <div class="rule-icon"><i class="fa-solid fa-calculator"></i></div>
                                <div class="rule-content">
                                    <div class="rule-title">Formül Yerine Değer</div>
                                    <div class="rule-desc">Formüller işlenemez. Önemli hesaplamaları değer olarak yapıştırın (Paste as Values).</div>
                                </div>
                            </li>
                        </ul>
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Event listener'ları bağla
     */
    function bindEvents() {
        if (!overlay) return;

        // Close button
        const closeBtn = overlay.querySelector('.file-guidelines-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', close);
        }

        // Tab buttons
        const tabs = overlay.querySelectorAll('.file-guidelines-tab');
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                switchTab(tab.dataset.tab);
            });
        });

        // ESC key
        document.addEventListener('keydown', handleKeyDown);

        // Overlay click - KAPATMAZ (global kurallara uygun)
        // overlay.addEventListener('click', (e) => {
        //     if (e.target === overlay) close();
        // });
    }

    // ========================================
    // PUBLIC API
    // ========================================

    /**
     * Modülü başlat
     */
    function init() {
        if (isInitialized) return;

        // Overlay oluştur
        overlay = document.createElement('div');
        overlay.className = 'file-guidelines-overlay';
        overlay.innerHTML = createModalHTML();
        document.body.appendChild(overlay);

        // Event'leri bağla
        bindEvents();

        isInitialized = true;
        console.log('[FileGuidelinesModal] Initialized');
    }

    /**
     * Modal'ı aç
     */
    function open() {
        if (!isInitialized) init();
        if (!overlay) return;

        overlay.classList.add('active');
        document.body.style.overflow = 'hidden';
        
        // İlk tab'ı göster
        switchTab('pdf');
    }

    /**
     * Modal'ı kapat
     */
    function close() {
        if (!overlay) return;

        overlay.classList.remove('active');
        document.body.style.overflow = '';
    }

    /**
     * Modal açık mı?
     */
    function isOpen() {
        return overlay && overlay.classList.contains('active');
    }

    // Public API
    return {
        init: init,
        open: open,
        close: close,
        isOpen: isOpen
    };

})();

// Global erişim için
window.FileGuidelinesModal = FileGuidelinesModal;
