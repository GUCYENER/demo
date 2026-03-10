/* ─────────────────────────────────────────────
   NGSSAI — Partial Loader (Senkron)
   v2.30.1 · Performans düzeltmesi
   
   Tüm HTML partials'ı SENKRON XHR ile yükler.
   Bu sayede sonraki <script> tag'ları çalıştığında
   DOM elementleri zaten hazır olur.
   ───────────────────────────────────────────── */

(function VyraPartialLoader() {
    'use strict';

    const PARTIALS = [
        { slot: 'sidebar-slot', src: 'partials/sidebar.html' },
        { slot: 'sections-slot', src: 'partials/section_dialog.html' },
        { slot: 'sections-slot', src: 'partials/section_history.html' },
        { slot: 'sections-slot', src: 'partials/section_parameters.html' },
        { slot: 'sections-slot', src: 'partials/section_knowledge.html' },
        { slot: 'sections-slot', src: 'partials/section_auth.html' },
        { slot: 'sections-slot', src: 'partials/section_org.html' },
        { slot: 'sections-slot', src: 'partials/section_profile.html' },
        { slot: 'modals-slot', src: 'partials/modals.html' },
    ];

    var loaded = 0;

    for (var i = 0; i < PARTIALS.length; i++) {
        var p = PARTIALS[i];
        try {
            var xhr = new XMLHttpRequest();
            xhr.open('GET', p.src, false); // ← SENKRON
            xhr.send(null);

            if (xhr.status === 200) {
                var slot = document.getElementById(p.slot);
                if (slot) {
                    slot.insertAdjacentHTML('beforeend', xhr.responseText);
                    loaded++;
                }
            } else {
                console.warn('[NGSSAI] Partial yüklenemedi: ' + p.src + ' (' + xhr.status + ')');
            }
        } catch (err) {
            console.error('[NGSSAI] Partial hata: ' + p.src, err);
        }
    }

    console.log('[NGSSAI] ' + loaded + '/' + PARTIALS.length + ' partial yüklendi (senkron).');
})();
