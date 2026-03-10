/* ─────────────────────────────────────────────
   NGSSAI — VPN Handler & Tagline Animation Module
   v2.30.0 · home_page.js'den ayrıştırıldı
   ───────────────────────────────────────────── */

// --- VPN/NETWORK HATA TESPİTİ ---
// LLM bağlantı hatalarını tespit eder ve kullanıcı dostu popup gösterir
window.isVPNNetworkError = function (errorMessage) {
    if (!errorMessage || typeof errorMessage !== 'string') return false;

    const vpnIndicators = [
        'HTTPSConnectionPool',
        'port=443',
        'Max retries exceeded',
        'NameResolutionError',
        'Failed to resolve',
        'getaddrinfo failed',
        'connection refused',
        'ConnectionError',
        'SSLError',
        'Errno 11001',
        'corpix.global-bilgi',
        'Network is unreachable'
    ];

    const lowerError = errorMessage.toLowerCase();
    return vpnIndicators.some(indicator =>
        lowerError.includes(indicator.toLowerCase())
    );
};

// VPN hata popup'ını göster
window.showVPNErrorPopup = function () {
    if (typeof VyraModal !== 'undefined' && VyraModal.vpnError) {
        VyraModal.vpnError();
    } else {
        alert('Corpix desteği için, şirket VPN ya da Wi-Fi açık olmalıdır. Lütfen bağlantı sağlayarak tekrar deneyin.');
    }
};

// --- YARAMAZ ÇOCUK ANİMASYONU (5 saniyede bir) ---
(function naughtyTagline() {
    // Enerjik renkler paleti
    const energyColors = [
        '#facc15', // Sarı (varsayılan)
        '#f97316', // Turuncu
        '#ef4444', // Kırmızı
        '#22c55e', // Yeşil
        '#3b82f6', // Mavi
        '#a855f7', // Mor
        '#ec4899', // Pembe
        '#14b8a6', // Turkuaz
        '#f59e0b', // Amber
    ];

    function triggerNaughty() {
        const brand = document.querySelector('.tagline-brand');
        const emoji = document.querySelector('.tagline-emoji');
        const text = document.querySelector('.tagline-text');

        if (brand && emoji && text) {
            // Random renk seç
            const randomColor = energyColors[Math.floor(Math.random() * energyColors.length)];
            brand.style.color = randomColor;

            // Animasyonu başlat
            brand.classList.add('naughty');
            emoji.classList.add('naughty');
            text.classList.add('naughty');

            // 1.5 saniye sonra kaldır
            setTimeout(() => {
                brand.classList.remove('naughty');
                emoji.classList.remove('naughty');
                text.classList.remove('naughty');
            }, 1500);
        }
    }

    // Sayfa yüklenince 3 sn sonra ilk animasyon
    setTimeout(triggerNaughty, 3000);

    // Sonra 5 saniyede bir tekrarla
    setInterval(triggerNaughty, 5000);
})();
