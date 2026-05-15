/**
 * NGSSAI Notification Center
 * Modern SaaS Notification System
 * 
 * Usage:
 * NgssNotification.success('Başlık', 'Mesaj');
 * NgssNotification.error('Hata', 'Bir şeyler yanlış gitti');
 * NgssNotification.warning('Uyarı', 'Dikkat edilmeli');
 * NgssNotification.info('Bilgi', 'Bilgilendirme');
 */

const NgssNotification = {
    container: null,
    dropdown: null,
    badge: null,
    list: null,
    notifications: [],
    isOpen: false,
    maxItems: 50,

    /**
     * Notification sistemini başlat
     */
    init() {
        if (this.container) return;
        this.loadFromStorage();
        this.render();
        this.bindEvents();
    },

    /**
     * LocalStorage'dan yükle
     */
    loadFromStorage() {
        try {
            const stored = localStorage.getItem('vyra_notifications');
            if (stored) {
                this.notifications = JSON.parse(stored);
            }
        } catch (e) {
            this.notifications = [];
        }
    },

    /**
     * LocalStorage'a kaydet
     */
    saveToStorage() {
        try {
            localStorage.setItem('vyra_notifications', JSON.stringify(this.notifications));
        } catch (e) {
            console.error('[Notification] Storage error:', e);
        }
    },

    /**
     * HTML render
     */
    render() {
        // Container oluştur
        this.container = document.createElement('div');
        this.container.className = 'notification-center';
        this.container.style.cssText = 'position: relative; display: inline-block;';
        this.container.innerHTML = `
            <div class="notification-bell" id="notificationBell" title="Bildirimler">
                <i class="fas fa-bell"></i>
                <span class="notification-badge hidden" id="notificationBadge">0</span>
            </div>
            <div class="notification-dropdown" id="notificationDropdown">
                <div class="notification-header">
                    <h3><i class="fas fa-bell"></i> Bildirimler</h3>
                    <button class="notification-clear-btn" id="notificationClearBtn">
                        <i class="fas fa-trash-alt"></i> Temizle
                    </button>
                </div>
                <div class="notification-list" id="notificationList"></div>
            </div>
        `;

        // Global notification alanını öncelikle kullan (her sayfada görünür)
        const globalContainer = document.getElementById('globalNotificationArea');
        const notificationContainer = document.getElementById('notificationArea') || document.getElementById('notificationContainer');
        const headerRight = document.querySelector('.header-right, .top-bar-right, .user-area');

        if (globalContainer) {
            globalContainer.appendChild(this.container);
        } else if (notificationContainer) {
            notificationContainer.appendChild(this.container);
        } else if (headerRight) {
            headerRight.insertBefore(this.container, headerRight.firstChild);
        } else {
            // Fallback: body'nin başına ekle (fixed position)
            document.body.insertBefore(this.container, document.body.firstChild);
            this.container.style.cssText = 'position: fixed; top: 16px; right: 24px; z-index: 9999;';
        }

        this.dropdown = document.getElementById('notificationDropdown');
        this.badge = document.getElementById('notificationBadge');
        this.list = document.getElementById('notificationList');

        this.renderList();
        this.updateBadge();
    },

    /**
     * Event listener'ları bağla
     */
    bindEvents() {
        const bell = document.getElementById('notificationBell');
        const clearBtn = document.getElementById('notificationClearBtn');

        bell.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggle();
        });

        clearBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.clearAll();
        });

        // Dışarı tıklamada kapat
        document.addEventListener('click', (e) => {
            if (this.isOpen && !this.container.contains(e.target)) {
                this.close();
            }
        });

        // ESC ile kapat
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isOpen) {
                this.close();
            }
        });
    },

    /**
     * Dropdown aç/kapa
     */
    toggle() {
        if (this.isOpen) {
            this.close();
        } else {
            this.open();
        }
    },

    open() {
        this.isOpen = true;
        this.dropdown.classList.add('active');
        this.markAllAsRead();
    },

    close() {
        this.isOpen = false;
        this.dropdown.classList.remove('active');
    },

    /**
     * Bildirim listesini render et
     */
    renderList() {
        if (!this.list) return;

        if (this.notifications.length === 0) {
            this.list.innerHTML = `
                <div class="notification-empty">
                    <i class="fas fa-bell-slash"></i>
                    <p>Henüz bildirim yok</p>
                </div>
            `;
            return;
        }

        this.list.innerHTML = this.notifications
            .slice()
            .reverse()
            .map((n, idx) => this.renderItem(n, this.notifications.length - 1 - idx))
            .join('');

        // İtem tıklama event'leri
        this.list.querySelectorAll('.notification-item').forEach(item => {
            item.addEventListener('click', () => {
                const id = item.dataset.id;
                const notification = this.notifications.find(n => n.id === id);

                this.markAsRead(id);
                this.close();

                if (!notification) return;

                // v2.39.0: targetSection varsa o sekmeye git
                if (notification.targetSection === 'rag') {
                    this.navigateToRag();
                }
                // v2.24.6: Dialog ID varsa o dialog'u yükle
                else if (notification.dialogId) {
                    this.navigateToDialog(notification.dialogId);
                }
                // "Çözüm Önerisi" bildirimiyse dialog sekmesine git (v2.24.0)
                else if (notification.title.includes('Çözüm')) {
                    this.navigateToDialog();
                }
                else if (notification.title.includes('NGSSAI') || notification.title.includes('VYRA')) {
                    this.navigateToDialog();
                }
            });
        });
    },

    /**
     * v2.24.0: NGSSAI'ye Sor sekmesine git
     */
    navigateToTicket() {
        this.navigateToDialog();
    },

    /**
     * NGSSAI'ye Sor sekmesine git
     * v2.24.6: dialogId verilirse o dialog'un mesajlarını yükle
     * v2.26.1: DOM hazır olması için setTimeout eklendi
     */
    navigateToDialog(dialogId = null) {
        // Sidebar active state güncelle
        const allMenuItems = document.querySelectorAll('.menu-item');
        allMenuItems.forEach(item => item.classList.remove('active'));

        const homeBtn = document.getElementById('menuNewTicket');
        if (homeBtn) {
            homeBtn.classList.add('active');
        }

        // v2.24.6: Dialog ID varsa, sıfırlamadan o dialog'u yükle
        if (dialogId && window.DialogChatModule && typeof DialogChatModule.loadDialogById === 'function') {
            // Önce section'ı göster
            if (typeof showSection === 'function') {
                showSection('dialog', true); // skipLoad=true parametresi
            }
            // v2.26.1: DOM'un hazır olması için kısa gecikme
            setTimeout(() => {
                DialogChatModule.loadDialogById(dialogId);
                console.log('[NgssNotification] Dialog #' + dialogId + ' yükleniyor');
            }, 50);
        } else {
            // Normal davranış
            if (typeof showSection === 'function') {
                showSection('dialog');
                console.log('[NgssNotification] Dialog sekmesine yönlendirildi');
            } else {
                window.location.href = 'home.html';
            }
        }
    },

    /**
     * v2.39.0: Bilgi Tabanı (RAG) sekmesine git
     * Notification tıklanınca bilgi tabanı ekranına yönlendirir.
     */
    navigateToRag() {
        // Sidebar active state güncelle
        const allMenuItems = document.querySelectorAll('.menu-item');
        allMenuItems.forEach(item => item.classList.remove('active'));

        const ragBtn = document.getElementById('menuRAG');
        if (ragBtn) {
            ragBtn.classList.add('active');
        }

        if (typeof showSection === 'function') {
            showSection('rag');
            console.log('[NgssNotification] Bilgi Tabanı sekmesine yönlendirildi');
        } else {
            window.location.href = 'home.html';
        }
    },

    renderItem(notification, index) {
        const iconClass = this.getIconClass(notification.type);
        const timeAgo = this.getTimeAgo(notification.timestamp);
        const unreadClass = notification.read ? '' : 'unread';

        return `
            <div class="notification-item ${unreadClass}" data-id="${notification.id}">
                <div class="notification-icon ${notification.type}">
                    <i class="${iconClass}"></i>
                </div>
                <div class="notification-content">
                    <div class="notification-title">${this.escapeHtml(notification.title)}</div>
                    <div class="notification-message">${this.escapeHtml(notification.message)}</div>
                    <div class="notification-time">${timeAgo}</div>
                </div>
            </div>
        `;
    },

    getIconClass(type) {
        const icons = {
            success: 'fas fa-check-circle',
            error: 'fas fa-times-circle',
            warning: 'fas fa-exclamation-triangle',
            info: 'fas fa-info-circle'
        };
        return icons[type] || icons.info;
    },

    getTimeAgo(timestamp) {
        const now = Date.now();
        const diff = now - timestamp;
        const minutes = Math.floor(diff / 60000);
        const hours = Math.floor(diff / 3600000);
        const days = Math.floor(diff / 86400000);

        // Tarih ve saat formatı
        const date = new Date(timestamp);
        const timeStr = date.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
        const dateStr = date.toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric' });

        // Bugün ise sadece saat
        const today = new Date();
        const isToday = date.toDateString() === today.toDateString();

        // Dün mü?
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);
        const isYesterday = date.toDateString() === yesterday.toDateString();

        if (minutes < 1) return `Şimdi • ${timeStr}`;
        if (minutes < 60) return `${minutes} dk önce • ${timeStr}`;
        if (isToday) return `Bugün ${timeStr}`;
        if (isYesterday) return `Dün ${timeStr}`;
        if (days < 7) return `${days} gün önce • ${dateStr} ${timeStr}`;
        return `${dateStr} ${timeStr}`;
    },

    /**
     * Badge güncelle
     */
    updateBadge() {
        const unreadCount = this.notifications.filter(n => !n.read).length;

        if (unreadCount > 0) {
            this.badge.textContent = unreadCount > 99 ? '99+' : unreadCount;
            this.badge.classList.remove('hidden');
        } else {
            this.badge.classList.add('hidden');
        }
    },

    /**
     * Bildirim ekle
     * v2.24.6: dialogId parametresi eklendi
     * v2.39.0: targetSection parametresi eklendi (rag, dialog vb.)
     * v3.15.5: options.suppressToast → toast popup'ı atla (zil badge'i yine güncellenir).
     *           Kullanıcı zaten ilgili ekranda ise toast gereksiz olur.
     */
    add(type, title, message, dialogId = null, targetSection = null, options = {}) {
        const notification = {
            id: Date.now().toString(),
            type,
            title,
            message,
            dialogId,  // v2.24.6: Dialog ID sakla
            targetSection,  // v2.39.0: Hedef sekme (örn: 'rag')
            timestamp: Date.now(),
            read: false
        };

        this.notifications.push(notification);

        // Max limit
        if (this.notifications.length > this.maxItems) {
            this.notifications = this.notifications.slice(-this.maxItems);
        }

        this.saveToStorage();
        this.renderList();
        this.updateBadge();

        // v3.15.2: Sağdan akan toast popup — kullanıcı zile bakmasa bile fark etsin.
        // v3.15.5: Çağıran "suppressToast" diyorsa atla (kullanıcı sonucu zaten ekranda görüyor).
        if (!options || !options.suppressToast) {
            try { this._showToastPopup(notification); } catch (_) { /* sessiz */ }
        }

        return notification;
    },

    /**
     * v3.15.2: Sağdan kayarak gelen toast bildirim. ~5 saniye sonra kaybolur.
     * Tıklanırsa bildirim panelini açar + ilgili bildirimi okundu işaretler.
     *
     * v3.15.3 (TYCHE-TQ2 fix): 10+ çağrı noktası ve WS event akışı toast spam'a yol açabilir.
     * - De-dup: son 2 saniyede aynı (type+title+message) toast varsa atla
     * - Max stack: aynı anda en fazla 3 toast; fazlası en eskini erken kapatır
     */
    _showToastPopup(notification) {
        // De-dup penceresi
        const DEDUP_WINDOW_MS = 2000;
        const MAX_VISIBLE = 3;
        if (!this._toastRecent) this._toastRecent = [];
        const now = Date.now();
        this._toastRecent = this._toastRecent.filter(e => (now - e.t) < DEDUP_WINDOW_MS);
        const key = `${notification.type}|${notification.title || ''}|${notification.message || ''}`;
        if (this._toastRecent.some(e => e.k === key)) {
            return; // yakın zamanda aynı bildirim toast olarak çıkmış — atla
        }
        this._toastRecent.push({ k: key, t: now });

        // Konteyner — toast.js'in oluşturduğuyla aynı; yoksa oluştur.
        let container = document.getElementById('toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            container.style.cssText = 'position:fixed;top:20px;right:20px;z-index:100002;display:flex;flex-direction:column;gap:10px;';
            document.body.appendChild(container);
        }

        // Max görünür stack — en eski toast'ı erken kapat
        const visibleToasts = container.querySelectorAll('.toast.toast-notif.show');
        if (visibleToasts.length >= MAX_VISIBLE) {
            const oldest = visibleToasts[0];
            oldest.classList.remove('show');
            setTimeout(() => { try { oldest.remove(); } catch (_) {} }, 300);
        }

        const iconMap = {
            success: 'check-circle',
            error:   'exclamation-circle',
            warning: 'exclamation-triangle',
            info:    'info-circle'
        };
        const icon = iconMap[notification.type] || iconMap.info;

        const toast = document.createElement('div');
        toast.className = `toast toast-${notification.type} toast-notif`;

        const iconEl = document.createElement('i');
        iconEl.className = `fas fa-${icon} toast-notif-icon`;

        const body = document.createElement('div');
        body.className = 'toast-notif-body';

        const titleEl = document.createElement('div');
        titleEl.className = 'toast-notif-title';
        titleEl.textContent = notification.title || '';

        const msgEl = document.createElement('div');
        msgEl.className = 'toast-notif-msg';
        msgEl.textContent = notification.message || '';

        body.appendChild(titleEl);
        body.appendChild(msgEl);

        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'toast-notif-close';
        closeBtn.setAttribute('aria-label', 'Kapat');
        closeBtn.textContent = '×';

        toast.appendChild(iconEl);
        toast.appendChild(body);
        toast.appendChild(closeBtn);
        container.appendChild(toast);

        // Slide-in
        requestAnimationFrame(() => toast.classList.add('show'));

        // Otomatik kaybolma — 5sn
        const AUTO_DISMISS_MS = 5000;
        let timer = setTimeout(dismiss, AUTO_DISMISS_MS);

        const self = this;
        function dismiss() {
            if (timer) { clearTimeout(timer); timer = null; }
            toast.classList.remove('show');
            setTimeout(() => { try { toast.remove(); } catch (_) {} }, 300);
        }

        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            dismiss();
        });

        // Tıklama → bildirim panelini aç, ilgili bildirimi okundu işaretle
        toast.addEventListener('click', () => {
            try {
                self.markAsRead(notification.id);
                if (self.dropdown && !self.dropdown.classList.contains('active')) {
                    self.dropdown.classList.add('active');
                }
            } catch (_) { /* sessiz */ }
            dismiss();
        });

        // Hover'da timer dursun, mouse ayrılınca yeniden başla
        toast.addEventListener('mouseenter', () => {
            if (timer) { clearTimeout(timer); timer = null; }
        });
        toast.addEventListener('mouseleave', () => {
            if (!timer) timer = setTimeout(dismiss, AUTO_DISMISS_MS);
        });
    },

    /**
     * Okundu olarak işaretle
     */
    markAsRead(id) {
        const notification = this.notifications.find(n => n.id === id);
        if (notification) {
            notification.read = true;
            this.saveToStorage();
            this.renderList();
            this.updateBadge();
        }
    },

    /**
     * Tümünü okundu işaretle
     */
    markAllAsRead() {
        this.notifications.forEach(n => n.read = true);
        this.saveToStorage();
        this.renderList();
        this.updateBadge();
    },

    /**
     * Tümünü temizle
     */
    clearAll() {
        this.notifications = [];
        this.saveToStorage();
        this.renderList();
        this.updateBadge();
    },

    /**
     * XSS koruması
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    // Kısa yollar
    success(title, message) {
        return this.add('success', title, message);
    },

    error(title, message) {
        return this.add('error', title, message);
    },

    warning(title, message) {
        return this.add('warning', title, message);
    },

    info(title, message) {
        return this.add('info', title, message);
    }
};

// Auto-init
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => NgssNotification.init());
} else {
    NgssNotification.init();
}

// Global export
window.NgssNotification = NgssNotification;
