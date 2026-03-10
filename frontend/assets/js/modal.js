/**
 * NGSSAI Global Modal System
 * Modern SaaS Modal Dialogs
 * 
 * Usage:
 * VyraModal.confirm({ title: 'Silme', message: 'Emin misiniz?', onConfirm: () => {} });
 * VyraModal.alert({ type: 'success', title: 'Başarılı', message: 'İşlem tamamlandı' });
 * VyraModal.danger({ title: 'Dikkat', message: 'Bu işlem geri alınamaz', onConfirm: () => {} });
 */

const VyraModal = {
    overlay: null,
    modal: null,
    isOpen: false,

    /**
     * Modal sistemi başlat
     */
    init() {
        if (this.overlay) return;

        // Overlay oluştur
        this.overlay = document.createElement('div');
        this.overlay.className = 'vyra-modal-overlay';
        this.overlay.innerHTML = `
            <div class="vyra-modal">
                <div class="vyra-modal-header">
                    <div class="vyra-modal-icon warning">
                        <i class="fas fa-exclamation-triangle"></i>
                    </div>
                    <h3 class="vyra-modal-title">Başlık</h3>
                </div>
                <div class="vyra-modal-body">
                    <p class="vyra-modal-message">Mesaj içeriği</p>
                </div>
                <div class="vyra-modal-footer">
                    <button class="vyra-modal-btn cancel" id="vyraModalCancel">İptal</button>
                    <button class="vyra-modal-btn confirm" id="vyraModalConfirm">Onayla</button>
                </div>
            </div>
        `;

        document.body.appendChild(this.overlay);
        this.modal = this.overlay.querySelector('.vyra-modal');

        // Event listeners
        this.overlay.addEventListener('click', (e) => {
            if (e.target === this.overlay) {
                // Overlay'e tıklamada kapatma (opsiyonel)
            }
        });

        // ESC tuşu ile kapatma
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isOpen) {
                this.close();
            }
        });
    },

    /**
     * Icon sınıflarını güncelle
     */
    getIconClass(type) {
        const icons = {
            warning: 'fas fa-exclamation-triangle',
            danger: 'fas fa-trash-alt',
            success: 'fas fa-check-circle',
            info: 'fas fa-info-circle',
            question: 'fas fa-question-circle',
            error: 'fas fa-times-circle',
            network: 'fas fa-wifi'
        };
        return icons[type] || icons.warning;
    },

    /**
     * Modal aç
     */
    open(options) {
        this.init();

        const {
            type = 'warning',
            title = 'Uyarı',
            message = '',
            htmlMessage = null,
            confirmText = 'Onayla',
            cancelText = 'İptal',
            confirmClass = 'confirm',
            showCancel = true,
            onConfirm = null,
            onCancel = null
        } = options;

        // Icon
        const iconEl = this.overlay.querySelector('.vyra-modal-icon');
        iconEl.className = `vyra-modal-icon ${type}`;
        iconEl.innerHTML = `<i class="${this.getIconClass(type)}"></i>`;

        // Title & Message
        this.overlay.querySelector('.vyra-modal-title').textContent = title;
        const msgEl = this.overlay.querySelector('.vyra-modal-message');
        if (htmlMessage) {
            msgEl.innerHTML = htmlMessage;
        } else if (/<[a-z][\s\S]*>/i.test(message)) {
            msgEl.innerHTML = message;
        } else {
            msgEl.textContent = message;
        }

        // Buttons
        const cancelBtn = this.overlay.querySelector('#vyraModalCancel');
        const confirmBtn = this.overlay.querySelector('#vyraModalConfirm');

        cancelBtn.textContent = cancelText;
        cancelBtn.style.display = showCancel ? 'block' : 'none';

        confirmBtn.textContent = confirmText;
        confirmBtn.className = `vyra-modal-btn ${confirmClass}`;

        // Event handlers
        const newCancelBtn = cancelBtn.cloneNode(true);
        cancelBtn.parentNode.replaceChild(newCancelBtn, cancelBtn);
        newCancelBtn.addEventListener('click', () => {
            if (onCancel) onCancel();
            this.close();
        });

        const newConfirmBtn = confirmBtn.cloneNode(true);
        confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
        newConfirmBtn.addEventListener('click', () => {
            if (onConfirm) onConfirm();
            this.close();
        });

        // Show
        this.isOpen = true;
        this.overlay.classList.add('active');
        newConfirmBtn.focus();
    },

    /**
     * Modal kapat
     */
    close() {
        if (!this.overlay) return;

        this.isOpen = false;
        this.overlay.classList.remove('active');
    },

    /**
     * Onay diyaloğu (Soru)
     */
    confirm(options) {
        this.open({
            type: 'question',
            confirmClass: 'confirm',
            ...options
        });
    },

    /**
     * Tehlikeli işlem onayı
     */
    danger(options) {
        this.open({
            type: 'danger',
            confirmClass: 'danger',
            confirmText: 'Sil',
            ...options
        });
    },

    /**
     * Uyarı diyaloğu
     */
    warning(options) {
        this.open({
            type: 'warning',
            confirmClass: 'warning',
            confirmText: 'Tamam',
            showCancel: false,
            ...options
        });
    },

    /**
     * Başarı diyaloğu
     */
    success(options) {
        this.open({
            type: 'success',
            confirmClass: 'confirm',
            confirmText: 'Tamam',
            showCancel: false,
            ...options
        });
    },

    /**
     * Bilgi diyaloğu
     */
    info(options) {
        this.open({
            type: 'info',
            confirmClass: 'confirm',
            confirmText: 'Tamam',
            showCancel: false,
            ...options
        });
    },

    /**
     * Hata diyaloğu
     */
    error(options) {
        this.open({
            type: 'error',
            confirmClass: 'danger',
            confirmText: 'Tamam',
            showCancel: false,
            ...options
        });
    },

    /**
     * VPN/Network bağlantı hatası diyaloğu
     * Teknik detayları gizleyerek kullanıcı dostu mesaj gösterir
     */
    vpnError(options = {}) {
        this.open({
            type: 'network',
            title: options.title || 'Bağlantı Hatası',
            message: options.message || 'Corpix desteği için, şirket VPN ya da Wi-Fi açık olmalıdır. Lütfen bağlantı sağlayarak tekrar deneyin.',
            confirmClass: 'warning',
            confirmText: 'Tamam',
            showCancel: false,
            ...options
        });
    }
};

// Auto-init
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => VyraModal.init());
} else {
    VyraModal.init();
}

// Global export
window.VyraModal = VyraModal;
