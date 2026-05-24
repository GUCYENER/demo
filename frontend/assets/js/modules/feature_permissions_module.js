/**
 * VYRA Sistem Özellikleri Yetkilendirmesi (v3.18.0)
 * ====================================================
 * Ana sayfadaki 3 mod (kb/db/llm) için kullanıcı/org bazlı görünürlük.
 *
 * Sorumluluklar:
 *  1) Bootstrap: sayfa açılır açılmaz `/api/feature-permissions/my` çağrılır,
 *     izinli olmayan mode-card'lar gizlenir.
 *  2) chatMode fallback: ilk izinli moda otomatik geçer (rag → db → llm).
 *  3) Admin paneli: Yetkilendirme → Sistem Özellikleri sekmesi.
 */

(function () {
    'use strict';

    // v3.34.0: vyraFetch /api prefix'i kendi ekliyor — burada sadece path tutuyoruz.
    const API_BASE = '/feature-permissions';
    const SUBJECTS_API = '/data-sources/permissions/subjects';
    // v3.30.0: aki_kesif (Akıllı Veri Keşfi / DB Smart Wizard) eklendi
    const FEATURE_KEYS = ['kb', 'db', 'llm', 'aki_kesif'];
    const FEATURE_LABELS = {
        kb:        { title: 'Bilgi Tabanında Ara',  icon: 'fa-book-open' },
        db:        { title: 'Veritabanında Ara',    icon: 'fa-database' },
        llm:       { title: 'VYRA ile Sohbet Et',   icon: 'fa-comments' },
        aki_kesif: { title: 'Akıllı Veri Keşfi',    icon: 'fa-magic' },
    };

    // Mode-card → chatMode mapping (UI 'kb' → backend chatMode 'rag')
    const MODE_TO_CHAT = { kb: 'rag', db: 'db', llm: 'llm', aki_kesif: 'aki_kesif' };

    let _myFeatures = null;          // { kb:true, db:false, llm:true }
    let _isAdmin = false;
    let _adminCache = null;          // GET /admin cache
    let _adminSubjects = null;       // users + orgs
    let _adminState = null;          // editing state per feature

    // v3.34.0: vyraFetch delegate — Auth + JSON + friendly error helper'da.
    async function _fetchJson(path, opts = {}) {
        return window.vyraFetch(path, opts);
    }

    // ============================================
    // 1) Bootstrap — sayfa açılırken çağrılır
    // ============================================

    async function applyMyFeaturePermissions() {
        const panel = document.getElementById('modeSelectorPanel');
        try {
            const data = await _fetchJson(`${API_BASE}/my`);
            _myFeatures = data.features || {};
            _isAdmin = !!data.is_admin;

            const visibleKeys = [];
            for (const key of FEATURE_KEYS) {
                const card = document.querySelector(`[data-feature-key="${key}"]`);
                if (!card) continue;
                if (_myFeatures[key]) {
                    card.classList.remove('hidden');
                    card.style.display = '';
                    visibleKeys.push(key);
                } else {
                    card.classList.add('hidden');
                    card.style.display = 'none';
                }
            }

            // Hiç görünür yoksa empty state
            const notice = document.getElementById('modeAllDeniedNotice');
            if (notice) {
                if (visibleKeys.length === 0 && !_isAdmin) {
                    notice.classList.remove('hidden');
                } else {
                    notice.classList.add('hidden');
                }
            }

            // chatMode fallback: default 'rag' (kb) izinli değilse ilk izinli moda geç
            _applyChatModeFallback(visibleKeys);

            // Global erişim (diğer modüller için)
            window.VYRA_FEATURE_PERMS = {
                features: Object.assign({}, _myFeatures),
                isAdmin: _isAdmin,
                visibleKeys: visibleKeys.slice(),
            };
            // v3.19.0: Diğer modüller (history, sidebar vb.) buna abone olabilir
            try { window.dispatchEvent(new CustomEvent('vyra:feature-perms-ready', { detail: window.VYRA_FEATURE_PERMS })); } catch (_) {}
        } catch (err) {
            // Hata olursa hepsi görünür kalır (default açık)
            console.warn('[FeaturePerm] /my çağrısı başarısız, default açık:', err);
        } finally {
            if (panel) panel.classList.remove('feature-perm-pending');
        }
    }

    function _applyChatModeFallback(visibleKeys) {
        if (!visibleKeys || visibleKeys.length === 0) return;
        // 'kb' (rag) izinli ise default zaten doğru — yine de sub-tab label'i temin et
        if (visibleKeys.includes('kb')) {
            const tabLabel = document.getElementById('tabDialogLabel');
            if (tabLabel) tabLabel.textContent = 'Bilgi Tabanında Ara';
            return;
        }

        const firstKey = visibleKeys[0];
        try {
            // v3.19.2: window.selectChatMode üzerinden geç → sub-tab label otomatik güncellenir
            if (typeof window.selectChatMode === 'function') {
                window.selectChatMode(firstKey);
                return;
            }

            // Fallback (selectChatMode tanımlı değilse)
            document.querySelectorAll('.mode-card.selected').forEach(el => el.classList.remove('selected'));
            const targetCard = document.querySelector(`[data-feature-key="${firstKey}"]`);
            if (targetCard) targetCard.classList.add('selected');

            const dcm = window.DialogChatModule;
            if (firstKey === 'db' && dcm && typeof dcm.switchToDbMode === 'function') {
                dcm.switchToDbMode();
            } else if (firstKey === 'llm' && dcm && typeof dcm.switchToLlmMode === 'function') {
                dcm.switchToLlmMode();
            }
            const tabLabel = document.getElementById('tabDialogLabel');
            if (tabLabel) {
                tabLabel.textContent = firstKey === 'db' ? 'Veritabanında Ara'
                    : firstKey === 'llm' ? 'VYRA ile Sohbet'
                    : 'Bilgi Tabanında Ara';
            }
        } catch (e) {
            console.warn('[FeaturePerm] chatMode fallback hatası:', e);
        }
    }

    /**
     * selectChatMode çağrıldığında izin kontrolü.
     * dialog_chat.js'in mevcut fonksiyonunu wrap eder.
     */
    function guardChatMode(mode) {
        if (!_myFeatures) return true; // henüz yüklenmedi, izin ver
        if (_isAdmin) return true;
        if (_myFeatures[mode]) return true;
        if (typeof window.showToast === 'function') {
            window.showToast('Bu özellik için yetkiniz yok.', 'warning');
        }
        return false;
    }

    // ============================================
    // 2) Admin paneli
    // ============================================

    async function openAdminPanel() {
        const body = document.getElementById('featurePermPanelBody');
        if (!body) return;
        body.innerHTML = `
            <div class="fp-loading">
                <i class="fa-solid fa-spinner fa-spin"></i>
                <span>Yükleniyor...</span>
            </div>
        `;

        try {
            const [adminData, subjectsData] = await Promise.all([
                _fetchJson(`${API_BASE}/admin`),
                _fetchJson(SUBJECTS_API),
            ]);
            _adminCache = adminData;
            _adminSubjects = {
                users: subjectsData.users || [],
                orgs:  subjectsData.orgs  || [],
            };

            // Editing state
            _adminState = {};
            for (const fk of FEATURE_KEYS) {
                const item = adminData[fk] || {};
                _adminState[fk] = {
                    user_allow_ids: new Set(item.user_allow_ids || []),
                    user_deny_ids:  new Set(item.user_deny_ids  || []),
                    org_allow_ids:  new Set(item.org_allow_ids  || []),
                };
            }

            _renderAdminPanel();
        } catch (err) {
            body.innerHTML = `
                <div class="fp-error">
                    <i class="fa-solid fa-circle-exclamation"></i>
                    Yetki verisi yüklenemedi: ${err.message || err}
                </div>
            `;
        }
    }

    function _renderAdminPanel() {
        const body = document.getElementById('featurePermPanelBody');
        if (!body) return;

        const featureCards = FEATURE_KEYS.map(fk => {
            const meta = FEATURE_LABELS[fk];
            const st = _adminState[fk];
            return `
                <div class="fp-feature-card" data-feature="${fk}" role="group" aria-label="${meta.title} yetkilendirmesi">
                    <div class="fp-feature-head">
                        <i class="fa-solid ${meta.icon}" aria-hidden="true"></i>
                        <span class="fp-feature-title">${meta.title}</span>
                        <span class="fp-feature-key" data-tooltip="Feature anahtarı: ${fk}">${fk}</span>
                    </div>
                    <div class="fp-feature-tabs" role="tablist" aria-label="${meta.title} yetkilendirme tabları">
                        <button class="fp-ftab active" data-fk="${fk}" data-tab="org" role="tab" aria-selected="true" data-tooltip="Bu org grubu üyeleri özelliği görür">Org Bazlı (İzin Ver)</button>
                        <button class="fp-ftab" data-fk="${fk}" data-tab="user-allow" role="tab" aria-selected="false" data-tooltip="Bireysel kullanıcıya özelliği aç">Kullanıcı (İzin Ver)</button>
                        <button class="fp-ftab" data-fk="${fk}" data-tab="user-deny" role="tab" aria-selected="false" data-tooltip="Kullanıcı org üyesi olsa bile özelliği gizle">Kullanıcı (Hariç Tut)</button>
                    </div>
                    <div class="fp-feature-list" id="fpList_${fk}" role="tabpanel">
                        <!-- list rendered dynamically -->
                    </div>
                    <div class="fp-feature-counts">
                        <span class="fp-count org" data-tooltip="İzin verilen org sayısı">Org: <strong>${st.org_allow_ids.size}</strong></span>
                        <span class="fp-count allow" data-tooltip="Bireysel izinli kullanıcı sayısı">İzinli: <strong>${st.user_allow_ids.size}</strong></span>
                        <span class="fp-count deny" data-tooltip="Hariç tutulan kullanıcı sayısı">Hariç: <strong>${st.user_deny_ids.size}</strong></span>
                    </div>
                </div>
            `;
        }).join('');

        body.innerHTML = `
            <div class="fp-info-banner">
                <i class="fa-solid fa-info-circle"></i>
                <div>
                    <strong>Öncelik kuralları (v3.19.0):</strong>
                    Tabloda <strong>en az bir kayıt</strong> varsa <em>strict mode</em> aktiftir &mdash; yalnızca açıkça yetkilendirilen kullanıcılar/org grupları ilgili özelliği görür.
                    Kullanıcı için <em>Hariç Tut</em> daima kazanır. Admin tüm özellikleri görür.
                </div>
            </div>
            <div class="fp-features">${featureCards}</div>
            <div class="fp-actions">
                <button class="btn" id="btnFpRevert">
                    <i class="fa-solid fa-rotate-left"></i> Geri Al
                </button>
                <button class="btn primary" id="btnFpSave">
                    <i class="fa-solid fa-save"></i> Kaydet
                </button>
            </div>
        `;

        // Per-card: ilk tab + liste render
        for (const fk of FEATURE_KEYS) {
            _adminState[fk]._activeTab = 'org';
            _renderFeatureList(fk);
        }

        // Tab event delegation — önceki listener'ı temizle ki mükerrer ekleme olmasın
        body.removeEventListener('click', _onPanelClick);
        body.addEventListener('click', _onPanelClick);
    }

    function _onPanelClick(ev) {
        const tabBtn = ev.target.closest('.fp-ftab');
        if (tabBtn) {
            const fk = tabBtn.getAttribute('data-fk');
            const tab = tabBtn.getAttribute('data-tab');
            _adminState[fk]._activeTab = tab;
            // Active class + aria-selected toggle
            document.querySelectorAll(`.fp-ftab[data-fk="${fk}"]`).forEach(b => {
                b.classList.remove('active');
                b.setAttribute('aria-selected', 'false');
            });
            tabBtn.classList.add('active');
            tabBtn.setAttribute('aria-selected', 'true');
            _renderFeatureList(fk);
            return;
        }

        const revertBtn = ev.target.closest('#btnFpRevert');
        if (revertBtn) {
            openAdminPanel();
            return;
        }

        const saveBtn = ev.target.closest('#btnFpSave');
        if (saveBtn) {
            _saveAll();
        }
    }

    function _renderFeatureList(fk) {
        const container = document.getElementById(`fpList_${fk}`);
        if (!container) return;
        const tab = _adminState[fk]._activeTab || 'org';
        const st = _adminState[fk];

        let items = [];
        let selectedSet;
        if (tab === 'org') {
            items = (_adminSubjects.orgs || []).map(o => ({
                id: o.id, label: o.org_name || o.name, sub: o.org_code || ''
            }));
            selectedSet = st.org_allow_ids;
        } else if (tab === 'user-allow') {
            items = (_adminSubjects.users || []).map(u => ({
                id: u.id, label: u.full_name || u.username, sub: u.email || u.username || ''
            }));
            selectedSet = st.user_allow_ids;
        } else { // user-deny
            items = (_adminSubjects.users || []).map(u => ({
                id: u.id, label: u.full_name || u.username, sub: u.email || u.username || ''
            }));
            selectedSet = st.user_deny_ids;
        }

        if (!items.length) {
            container.innerHTML = `<div class="fp-empty">Liste boş.</div>`;
            return;
        }

        const rows = items.map(it => {
            const checked = selectedSet.has(it.id) ? 'checked' : '';
            return `
                <label class="fp-row">
                    <input type="checkbox" class="fp-chk" data-fk="${fk}" data-tab="${tab}" data-id="${it.id}" ${checked}>
                    <span class="fp-row-label">${_escape(it.label)}</span>
                    <span class="fp-row-sub">${_escape(it.sub)}</span>
                </label>
            `;
        }).join('');
        container.innerHTML = rows;

        container.querySelectorAll('.fp-chk').forEach(cb => {
            cb.addEventListener('change', _onCheckboxChange);
        });
    }

    function _onCheckboxChange(ev) {
        const cb = ev.target;
        const fk = cb.getAttribute('data-fk');
        const tab = cb.getAttribute('data-tab');
        const id = parseInt(cb.getAttribute('data-id'), 10);
        const st = _adminState[fk];
        const set = tab === 'org' ? st.org_allow_ids :
                    tab === 'user-allow' ? st.user_allow_ids :
                    st.user_deny_ids;

        if (cb.checked) {
            set.add(id);
            // Conflict: user-allow & user-deny aynı id'ye sahip olamaz
            if (tab === 'user-allow') st.user_deny_ids.delete(id);
            else if (tab === 'user-deny') st.user_allow_ids.delete(id);
        } else {
            set.delete(id);
        }

        // Count update
        const card = document.querySelector(`.fp-feature-card[data-feature="${fk}"]`);
        if (card) {
            const counts = card.querySelectorAll('.fp-count strong');
            if (counts.length >= 3) {
                counts[0].textContent = st.org_allow_ids.size;
                counts[1].textContent = st.user_allow_ids.size;
                counts[2].textContent = st.user_deny_ids.size;
            }
        }
    }

    async function _saveAll() {
        const saveBtn = document.getElementById('btnFpSave');
        const originalHtml = saveBtn ? saveBtn.innerHTML : '';
        if (saveBtn) {
            saveBtn.disabled = true;
            saveBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Kaydediliyor...';
        }
        try {
            for (const fk of FEATURE_KEYS) {
                const st = _adminState[fk];
                await _fetchJson(`${API_BASE}/${fk}`, {
                    method: 'PUT',
                    body: {
                        user_allow_ids: Array.from(st.user_allow_ids),
                        user_deny_ids:  Array.from(st.user_deny_ids),
                        org_allow_ids:  Array.from(st.org_allow_ids),
                    },
                });
            }
            if (typeof window.showToast === 'function') {
                window.showToast('Sistem özelliği yetkileri güncellendi.', 'success');
            }
        } catch (err) {
            if (typeof window.showToast === 'function') {
                window.showToast('Kaydetme hatası: ' + (err.message || err), 'error');
            }
        } finally {
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.innerHTML = originalHtml;
            }
        }
    }

    function _escape(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // ============================================
    // 3) Init + sub-tab bağla
    // ============================================

    function _initSubTabHook() {
        const tabFeature = document.getElementById('tabFeaturePermissions');
        if (!tabFeature) return;

        // Sistem Özellikleri sekmesi: göster + diğerlerini gizle
        tabFeature.addEventListener('click', () => {
            document.querySelectorAll('.sub-tab').forEach(b => b.classList.remove('active'));
            tabFeature.classList.add('active');
            document.querySelectorAll('.auth-tab-content').forEach(c => c.classList.add('hidden'));
            const content = document.getElementById('contentFeaturePermissions');
            if (content) content.classList.remove('hidden');
            openAdminPanel();
        });

        // Diğer sub-tab'lar tıklandığında Sistem Özellikleri içeriğini gizle
        // (mevcut authorization.js Kullanıcı Listesi / Rol Yetkileri'ni biliyor ama
        //  yeni eklenen contentFeaturePermissions'ı bilmiyor → çakışmayı burada çöz)
        ['tabUsersList', 'tabRolePermissions'].forEach(id => {
            const t = document.getElementById(id);
            if (!t) return;
            t.addEventListener('click', () => {
                const content = document.getElementById('contentFeaturePermissions');
                if (content) content.classList.add('hidden');
                tabFeature.classList.remove('active');
            });
        });
    }

    // Sayfa hazır olduğunda bootstrap
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            applyMyFeaturePermissions();
            _initSubTabHook();
        });
    } else {
        applyMyFeaturePermissions();
        _initSubTabHook();
    }

    // Public API
    window.VYRA_FeaturePermissions = {
        apply: applyMyFeaturePermissions,
        guard: guardChatMode,
        openAdminPanel: openAdminPanel,
    };
})();
