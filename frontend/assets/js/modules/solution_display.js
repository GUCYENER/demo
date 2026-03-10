/* -------------------------------
   VYRA - Solution Display Module
   Çözüm gösterimi ve formatlama
   v2.18.3 - CatBoost ML Feedback + TTS
-------------------------------- */

/**
 * SolutionDisplay modülü - Çözüm önerisi gösterimi, formatlama
 * @module SolutionDisplayModule
 */
window.SolutionDisplayModule = (function () {
    'use strict';

    // Mevcut ticket ve chunk bilgileri (feedback için)
    let currentTicketId = null;
    let currentChunkIds = [];
    let currentQuery = '';
    let feedbackSent = false;
    let isSpeaking = false;  // TTS durumu

    // DOM elementleri
    function getElements() {
        return {
            loadingBox: document.getElementById("loadingBox"),
            finalSolutionBox: document.getElementById("finalSolutionBox"),
            solutionSteps: document.getElementById("solutionSteps"),
            cymContent: document.getElementById("cymContent"),
            cymText: document.getElementById("cymText"),
            showCYM: document.getElementById("showCYM"),
            copyBtn: document.getElementById("copyBtn"),
            newRequestBtn: document.getElementById("newRequestBtn"),
            responseTimeEl: document.getElementById("responseTime"),
            userRequestTextEl: document.getElementById("userRequestText"),
            sourceInfoBox: document.getElementById("sourceInfo"),
            sourceText: document.getElementById("sourceText"),
            feedbackContainer: document.getElementById("feedbackContainer"),
        };
    }

    // --- HTML Escape ---
    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // --- Inline numaralı adımları formatla ---
    function formatInlineNumberedSteps(text) {
        // Önce kaynak bilgisini al ve temizle
        let sourceInfo = '';
        const sourceMatch = text.match(/[��📄]?\s*Kaynak:\s*(.+?)(?:\s*$|\.?\s*$)/i);
        if (sourceMatch) {
            sourceInfo = sourceMatch[1].trim();
            text = text.replace(sourceMatch[0], '').trim();
        }

        // --- ayracını temizle
        if (text.includes('---')) {
            text = text.split('---')[0].trim();
        }

        // İlk paragrafı (adımlardan önceki metin) ayır
        let introText = '';
        const firstStepMatch = text.match(/^(.+?)(?=\d+[\)\.])/);
        if (firstStepMatch) {
            introText = firstStepMatch[1].trim();
            if (introText.endsWith(':')) {
                introText = introText.slice(0, -1).trim();
            }
        }

        // Adımları parse et - Geliştirilmiş regex
        // "1) ... 2) ... 3) ..." veya "1. ... 2. ... 3. ..." formatları
        const steps = [];
        const stepRegex = /(\d+)[\)\.]\s*([^0-9]+?)(?=\s*\d+[\)\.]|$)/g;
        let match;

        while ((match = stepRegex.exec(text)) !== null) {
            let stepContent = match[2].trim();

            // Kaynak bilgisini içeriyorsa temizle
            if (stepContent.toLowerCase().includes('kaynak:')) {
                stepContent = stepContent.split(/kaynak:/i)[0].trim();
            }

            // Çok kısa içerikleri atla
            if (stepContent.length > 3) {
                steps.push({
                    num: parseInt(match[1]),
                    content: stepContent
                });
            }
        }

        // Adım bulunamadıysa düz metin olarak döndür
        if (steps.length === 0) {
            return `<p class="solution-text">${escapeHtml(text)}</p>`;
        }

        // HTML oluştur - Container ile sarmalı
        let html = '<div class="solution-steps-container">';

        // Giriş metni varsa ekle
        if (introText && introText.length > 10) {
            html += `<p class="solution-intro-text">${escapeHtml(introText)}</p>`;
        }

        // Adımları ekle
        steps.forEach((step, index) => {
            let content = step.content;
            // Son karakteri kontrol et
            if (!content.endsWith('.') && !content.endsWith('!') && !content.endsWith('?')) {
                content += '.';
            }
            // İlk harfi büyüt
            content = content.charAt(0).toUpperCase() + content.slice(1);

            html += `
                <div class="solution-step-item">
                    <div class="step-number">${index + 1}</div>
                    <div class="step-content">${escapeHtml(content)}</div>
                </div>
            `;
        });

        html += '</div>';

        // Kaynak bilgisi varsa ekle
        if (sourceInfo) {
            html += `
                <div class="source-info-box">
                    <i class="fa-solid fa-lightbulb"></i>
                    <span>Kaynak: ${escapeHtml(sourceInfo)}</span>
                </div>
            `;
        }

        return html;
    }

    // --- Tek paragraf formatla ---
    function formatSingleParagraph(text) {
        let sentences;

        if (/,\s*ardından\s+/i.test(text)) {
            sentences = text.split(/,\s*ardından\s+/i).filter(s => s.trim().length > 5);
        } else if (/,\s*sonra\s+/i.test(text)) {
            sentences = text.split(/,\s*sonra\s+/i).filter(s => s.trim().length > 5);
        } else if (text.includes(';')) {
            sentences = text.split(/;\s*/).filter(s => s.trim().length > 5);
        } else {
            sentences = text.split(/\.\s+(?=[A-ZÇĞİÖŞÜ])/).filter(s => s.trim());
            if (sentences.length < 2) {
                sentences = [text];
            }
        }

        let html = '<div class="solution-steps-container">';
        let stepCounter = 0;

        sentences.forEach(sentence => {
            let cleanSentence = sentence.trim();

            if (cleanSentence.toLowerCase().includes('kaynak:') || cleanSentence.startsWith('📄')) {
                return;
            }

            if (cleanSentence.length < 10) return;

            if (!cleanSentence.endsWith('.') && !cleanSentence.endsWith('!') && !cleanSentence.endsWith('?')) {
                cleanSentence += '.';
            }

            cleanSentence = cleanSentence.charAt(0).toUpperCase() + cleanSentence.slice(1);
            stepCounter++;

            html += `
                <div class="solution-step-item">
                    <div class="step-number">${stepCounter}</div>
                    <div class="step-content">${escapeHtml(cleanSentence)}</div>
                </div>
            `;
        });

        html += '</div>';
        return html;
    }

    // --- Numaralı adımlar formatla ---
    function formatSolutionWithSteps(solution) {
        const lines = solution.split('\n');
        let html = '';
        let inList = false;
        let inAlternative = false;
        let stepCounter = 0;
        let alternativeStepCounter = 0;

        lines.forEach(line => {
            const trimmedLine = line.trim();
            if (!trimmedLine) return;

            const alternativeMatch = trimmedLine.match(/^alternatif(?:\s+olarak)?[:]/i);
            if (alternativeMatch) {
                if (inList) {
                    html += '</div>';
                    inList = false;
                }

                html += `
                    <div class="solution-alternative-header">
                        <i class="fa-solid fa-shuffle"></i>
                        <span>Alternatif Olarak</span>
                    </div>
                `;
                inAlternative = true;
                alternativeStepCounter = 0;
                return;
            }

            const numberedMatch = trimmedLine.match(/^(\d+)[.\)]\s*(.+)/);

            if (numberedMatch) {
                if (!inList) {
                    html += '<div class="solution-steps-container">';
                    inList = true;
                }

                const counter = inAlternative ? ++alternativeStepCounter : ++stepCounter;
                const stepClass = inAlternative ? 'solution-step-item alternative' : 'solution-step-item';

                html += `
                    <div class="${stepClass}">
                        <div class="step-number">${counter}</div>
                        <div class="step-content">${escapeHtml(numberedMatch[2])}</div>
                    </div>
                `;
            } else {
                if (inList) {
                    html += '</div>';
                    inList = false;
                }

                if (trimmedLine.startsWith('📄') || trimmedLine.toLowerCase().startsWith('kaynak:')) {
                    html += `
                        <div class="solution-source">
                            <i class="fa-solid fa-file-lines"></i>
                            <span>Kaynak: ${escapeHtml(trimmedLine.replace('📄', '').replace(/^kaynak:/i, '').trim())}</span>
                        </div>
                    `;
                } else if (trimmedLine === '---') {
                    html += '<hr class="solution-divider">';
                } else {
                    html += `<p class="solution-text">${escapeHtml(trimmedLine)}</p>`;
                }
            }
        });

        if (inList) html += '</div>';

        return html || `<p class="solution-text">${escapeHtml(solution)}</p>`;
    }

    // --- Markdown key-value formatını tespit et ve profesyonel render et ---
    function formatKeyValuePairs(solution) {
        // **Label:** Value veya **Label** Value formatlarını yakala
        const keyValuePattern = /\*\*([^*]+?)[:：]?\*\*[:：]?\s*(.+)/g;
        const lines = solution.split('\n');
        let hasKeyValue = false;
        let pairs = [];

        lines.forEach(line => {
            const trimmed = line.trim();
            if (!trimmed) return;

            // **Label:** Value formatı
            const match = trimmed.match(/^\*\*([^*]+?)[:：]?\*\*[:：]?\s*(.*)$/);
            if (match) {
                hasKeyValue = true;
                pairs.push({
                    label: match[1].trim(),
                    value: match[2].trim()
                });
            } else if (hasKeyValue && pairs.length > 0 && !trimmed.startsWith('**')) {
                // Önceki pair'in devamı
                pairs[pairs.length - 1].value += ' ' + trimmed;
            } else if (!trimmed.startsWith('**')) {
                // Normal metin
                pairs.push({
                    label: null,
                    value: trimmed
                });
            }
        });

        if (!hasKeyValue || pairs.length === 0) {
            return null; // Key-value formatı değil
        }

        // Profesyonel key-value HTML render
        let html = '<div class="solution-key-value-container">';

        pairs.forEach(pair => {
            if (pair.label) {
                html += `
                    <div class="solution-kv-row">
                        <span class="solution-kv-label">${escapeHtml(pair.label)}:</span>
                        <span class="solution-kv-value">${escapeHtml(pair.value)}</span>
                    </div>
                `;
            } else if (pair.value) {
                // Normal paragraf
                html += `<p class="solution-text">${escapeHtml(pair.value)}</p>`;
            }
        });

        html += '</div>';
        return html;
    }

    // --- Ana format fonksiyonu ---
    function formatSolution(solution) {
        if (!solution) return '<p class="text-gray-500">Çözüm bilgisi yok</p>';

        // v2.21.12: FEEDBACK_SECTION satırlarını ve --- ayracını temizle
        solution = solution
            .split('\n')
            .filter(line => {
                const trimmed = line.trim();
                return trimmed !== '---' &&
                    trimmed !== '[FEEDBACK_SECTION]' &&
                    trimmed !== '[/FEEDBACK_SECTION]' &&
                    !trimmed.startsWith('**Bu değerlendirme');
            })
            .join('\n')
            .trim();

        // 1. Önce key-value formatını kontrol et (ilk görsel formatı)
        const keyValueHtml = formatKeyValuePairs(solution);
        if (keyValueHtml) {
            return keyValueHtml;
        }

        // 2. Inline numaralı adımları kontrol et
        const inlineNumberedPattern = /(\d+)[.\)]\s/g;
        const matches = solution.match(inlineNumberedPattern);

        if (matches && matches.length >= 2) {
            return formatInlineNumberedSteps(solution);
        }

        // 3. Satır bazlı numaralı adımları kontrol et
        const hasNewlineNumberedSteps = /^\d+[.\)]\s/m.test(solution);
        if (hasNewlineNumberedSteps || solution.includes('\n')) {
            return formatSolutionWithSteps(solution);
        }

        // 4. Tek paragraf
        return formatSingleParagraph(solution);
    }

    // --- Kaynak bilgisini güncelle ---
    function updateSourceInfo(solution) {
        const el = getElements();
        if (!el.sourceInfoBox || !el.sourceText) return;

        const sourceMatch = solution?.match(/📄\s*Kaynak:\s*(.+?)(?:\s*$|\.)/i) ||
            solution?.match(/Kaynak:\s*(.+?)(?:\s*$|\.)/i);

        if (sourceMatch && sourceMatch[1]) {
            el.sourceText.textContent = "Kaynak: " + sourceMatch[1].trim();
            el.sourceInfoBox.classList.remove("hidden");
        } else {
            el.sourceInfoBox.classList.add("hidden");
        }
    }

    // ============================================
    // 🚀 FEEDBACK UI (v2.13.0 - CatBoost)
    // ============================================

    /**
     * Feedback butonlarını render et
     */
    function renderFeedbackButtons() {
        const el = getElements();

        // Feedback container yoksa oluştur
        let container = el.feedbackContainer;
        if (!container) {
            container = document.createElement('div');
            container.id = 'feedbackContainer';
            container.className = 'feedback-container';

            // finalSolutionBox içine ekle
            if (el.finalSolutionBox) {
                el.finalSolutionBox.appendChild(container);
            }
        }

        // Feedback zaten gönderildiyse farklı görünüm
        if (feedbackSent) {
            container.innerHTML = `
                <div class="feedback-thanks">
                    <i class="fa-solid fa-check-circle"></i>
                    <span>Geri bildiriminiz için teşekkürler!</span>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="feedback-question">
                <span class="feedback-label">Bu cevap işinize yaradı mı?</span>
                <div class="feedback-buttons">
                    <button class="feedback-btn feedback-btn-helpful" data-type="helpful" title="Evet, işe yaradı">
                        <i class="fa-solid fa-thumbs-up"></i>
                        <span>Evet</span>
                    </button>
                    <button class="feedback-btn feedback-btn-not-helpful" data-type="not_helpful" title="Hayır, işe yaramadı">
                        <i class="fa-solid fa-thumbs-down"></i>
                        <span>Hayır</span>
                    </button>
                    <button class="feedback-btn feedback-btn-speak" data-type="speak" title="Çözümü sesli oku">
                        <i class="fa-solid fa-volume-up"></i>
                    </button>
                </div>
            </div>
        `;

        // Event listeners ekle
        container.querySelectorAll('.feedback-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const feedbackType = btn.dataset.type;
                if (feedbackType === 'speak') {
                    toggleSpeech();
                } else {
                    sendFeedback(feedbackType);
                }
            });
        });
    }

    /**
     * Feedback API'ye gönder
     */
    async function sendFeedback(feedbackType) {
        if (feedbackSent) return;

        const token = localStorage.getItem('access_token');
        if (!token) {
            console.warn('Feedback gönderilemedi: token yok');
            return;
        }

        try {
            const response = await fetch('/api/feedback', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({
                    feedback_type: feedbackType,
                    ticket_id: currentTicketId,
                    chunk_ids: currentChunkIds,
                    query_text: currentQuery
                })
            });

            if (response.ok) {
                feedbackSent = true;
                renderFeedbackButtons(); // Teşekkür mesajı göster

                // Toast bildirim
                if (typeof VyraToast !== 'undefined') {
                    VyraToast.success('Geri bildiriminiz kaydedildi. Teşekkürler!');
                }
            } else {
                console.error('Feedback gönderme hatası:', response.status);
                if (typeof VyraToast !== 'undefined') {
                    VyraToast.error('Geri bildirim kaydedilemedi.');
                }
            }
        } catch (error) {
            console.error('Feedback gönderme hatası:', error);
        }
    }

    // ============================================
    // 🔊 TTS (Text-to-Speech) - v2.18.3
    // ============================================

    /**
     * Çözümü sesli oku veya durdur
     */
    function toggleSpeech() {
        if (isSpeaking) {
            stopSpeaking();
        } else {
            speakSolution();
        }
    }

    /**
     * Çözümü Web Speech API ile seslendir
     */
    function speakSolution() {
        // Web Speech API desteğini kontrol et
        if (!('speechSynthesis' in window)) {
            if (typeof VyraToast !== 'undefined') {
                VyraToast.warning('Tarayıcınız sesli okumayı desteklemiyor.');
            }
            return;
        }

        // Çözüm metnini al
        const el = getElements();
        const solutionText = el.solutionSteps?.innerText || '';

        if (!solutionText.trim()) {
            if (typeof VyraToast !== 'undefined') {
                VyraToast.warning('Okunacak çözüm metni bulunamadı.');
            }
            return;
        }

        // Önceki seslendirmeyi durdur
        window.speechSynthesis.cancel();

        // Yeni seslendirme oluştur
        const utterance = new SpeechSynthesisUtterance(solutionText);
        utterance.lang = 'tr-TR';
        utterance.rate = 0.9;
        utterance.pitch = 1;

        // Türkçe ses tercih et
        const voices = window.speechSynthesis.getVoices();
        const turkishVoice = voices.find(v => v.lang.startsWith('tr'));
        if (turkishVoice) {
            utterance.voice = turkishVoice;
        }

        // Olayları dinle
        utterance.onstart = () => {
            isSpeaking = true;
            updateSpeakButtonState(true);
        };

        utterance.onend = () => {
            isSpeaking = false;
            updateSpeakButtonState(false);
        };

        utterance.onerror = () => {
            isSpeaking = false;
            updateSpeakButtonState(false);
            if (typeof VyraToast !== 'undefined') {
                VyraToast.error('Sesli okuma başarısız oldu.');
            }
        };

        // Seslendirmeyi başlat
        window.speechSynthesis.speak(utterance);

        if (typeof VyraToast !== 'undefined') {
            VyraToast.info('Çözüm sesli okunuyor...');
        }
    }

    /**
     * Seslendirmeyi durdur
     */
    function stopSpeaking() {
        if ('speechSynthesis' in window) {
            window.speechSynthesis.cancel();
        }
        isSpeaking = false;
        updateSpeakButtonState(false);
    }

    /**
     * Hoparlör butonunun görsel durumunu güncelle
     */
    function updateSpeakButtonState(speaking) {
        const speakBtn = document.querySelector('.feedback-btn-speak');
        if (speakBtn) {
            const icon = speakBtn.querySelector('i');
            if (speaking) {
                speakBtn.classList.add('speaking');
                if (icon) icon.className = 'fa-solid fa-volume-xmark';
                speakBtn.title = 'Sesli okumayı durdur';
            } else {
                speakBtn.classList.remove('speaking');
                if (icon) icon.className = 'fa-solid fa-volume-up';
                speakBtn.title = 'Çözümü sesli oku';
            }
        }
    }

    /**
     * Feedback state'ini sıfırla (yeni soru için)
     */
    function resetFeedback() {
        currentTicketId = null;
        currentChunkIds = [];
        currentQuery = '';
        feedbackSent = false;
        stopSpeaking();  // TTS'i de durdur
    }

    /**
     * Ticket ve chunk bilgilerini set et
     */
    function setTicketInfo(ticketId, chunkIds, query) {
        currentTicketId = ticketId;
        currentChunkIds = chunkIds || [];
        currentQuery = query || '';
        feedbackSent = false;
    }

    // --- Çözümü göster ---
    function showSolution(data, userQuery, responseTime) {
        const el = getElements();

        if (el.loadingBox) el.loadingBox.classList.add("hidden");
        if (el.finalSolutionBox) el.finalSolutionBox.classList.remove("hidden");

        if (el.userRequestTextEl) {
            el.userRequestTextEl.textContent = userQuery || "-";
        }

        if (el.responseTimeEl && responseTime) {
            el.responseTimeEl.textContent = `${responseTime}s`;
        }

        if (el.solutionSteps) {
            el.solutionSteps.innerHTML = formatSolution(data.final_solution);
            updateSourceInfo(data.final_solution);
        }

        if (el.cymText) {
            el.cymText.textContent = data.cym_text || "ÇYM metni oluşturulamadı.";
        }

        // Ticket bilgilerini kaydet ve feedback butonlarını göster
        setTicketInfo(data.ticket_id, data.chunk_ids, userQuery);
        renderFeedbackButtons();

        // "Yeni Soru" butonuna pulse animasyonu ekle (v2.24.0)
        const newRequestBtn = document.getElementById('newRequestBtn');
        if (newRequestBtn) {
            newRequestBtn.classList.add('new-request-pulse');
        }
    }

    // --- Loading göster ---
    function showLoading() {
        const el = getElements();
        if (el.loadingBox) el.loadingBox.classList.remove("hidden");
        if (el.finalSolutionBox) el.finalSolutionBox.classList.add("hidden");
        resetFeedback();

        // Attach butonu pasif - çözüm süreci başladı
        const attachImageBtn = document.getElementById("attachImageBtn");
        if (attachImageBtn) attachImageBtn.disabled = true;
    }

    // --- Gizle ---
    function hide() {
        const el = getElements();
        if (el.loadingBox) el.loadingBox.classList.add("hidden");
        if (el.finalSolutionBox) el.finalSolutionBox.classList.add("hidden");
        resetFeedback();

        // Pulse animasyonunu kaldır
        const newRequestBtn = document.getElementById('newRequestBtn');
        if (newRequestBtn) {
            newRequestBtn.classList.remove('new-request-pulse');
        }
    }

    // --- Event listeners ---
    function setupEventListeners() {
        const el = getElements();

        if (el.showCYM) {
            el.showCYM.addEventListener("change", () => {
                el.cymContent.classList.toggle("hidden", !el.showCYM.checked);
            });
        }

        if (el.copyBtn) {
            el.copyBtn.addEventListener("click", () => {
                if (el.cymText) navigator.clipboard.writeText(el.cymText.textContent);

                // Kopyalama feedback'i gönder
                if (!feedbackSent && currentTicketId) {
                    sendFeedback('copied');
                }

                if (typeof VyraToast !== 'undefined') {
                    VyraToast.success("Çağrı metni kopyalandı.");
                } else {
                    alert("Çağrı metni kopyalandı.");
                }
            });
        }

        if (el.newRequestBtn) {
            el.newRequestBtn.addEventListener("click", () => {
                const problemText = document.getElementById("problemText");
                if (problemText) {
                    problemText.value = "";
                    problemText.disabled = false; // ⚡ KRİTİK: disabled'ı kaldır
                    problemText.focus();
                }
                hide();
                if (el.showCYM) el.showCYM.checked = false;
                if (el.cymContent) el.cymContent.classList.add("hidden");
            });
        }
    }

    // --- Init ---
    function init() {
        setupEventListeners();
    }

    // ============================================
    // 🆕 v2.23.0: RAG Sonuçları Gösterimi
    // ============================================

    /**
     * RAG sonuçlarını göster (AI değerlendirmesi isteğe bağlı)
     */
    function showRagResults(result) {
        const el = getElements();

        // Loading'i gizle
        if (el.loadingBox) el.loadingBox.classList.add("hidden");
        if (el.finalSolutionBox) el.finalSolutionBox.classList.remove("hidden");

        // Ticket bilgilerini sakla
        currentTicketId = result.ticket_id;
        currentQuery = result.description || '';

        const ragResults = result.rag_results || [];
        const hasResults = ragResults.length > 0;

        if (el.solutionSteps) {
            let html = '';

            if (hasResults) {
                // RAG sonuçları var
                html = `
                    <div class="rag-results-container">
                        <div class="rag-results-header">
                            <i class="fa-solid fa-search text-yellow-400"></i>
                            <span>Bilgi Tabanında ${ragResults.length} Sonuç Bulundu</span>
                        </div>
                        <div class="rag-results-list">
                `;

                ragResults.forEach((r, index) => {
                    const score = r.score || 0;
                    const scoreClass = score >= 75 ? 'high' : score >= 50 ? 'medium' : 'low';

                    html += `
                        <div class="rag-result-card" data-index="${index}">
                            <div class="rag-result-header">
                                <span class="rag-result-file">
                                    <i class="fa-solid fa-file-alt"></i>
                                    ${escapeHtml(r.file_name || 'Bilgi Tabanı')}
                                </span>
                                <span class="rag-result-score ${scoreClass}">${score}%</span>
                            </div>
                            <div class="rag-result-content">
                                ${escapeHtml((r.chunk_text || '').substring(0, 300))}${(r.chunk_text || '').length > 300 ? '...' : ''}
                            </div>
                            <button class="btn-select-result" data-index="${index}" title="Bu çözümü seç">
                                <i class="fa-solid fa-check"></i> Bunu Seç
                            </button>
                        </div>
                    `;
                });

                html += `
                        </div>
                    </div>
                `;
            } else {
                // RAG sonucu yok
                html = `
                    <div class="rag-no-results">
                        <i class="fa-solid fa-search-minus text-gray-400"></i>
                        <p>Bilgi tabanında eşleşen sonuç bulunamadı.</p>
                        <p class="text-sm text-gray-500">Corpix AI ile değerlendirme yapabilirsiniz.</p>
                    </div>
                `;
            }

            // AI Değerlendir butonu ekle
            html += `
                <div class="ai-evaluate-section">
                    <button class="btn-ai-evaluate" id="btnAIEvaluate" title="Corpix AI ile değerlendirme yap">
                        <i class="fa-solid fa-robot"></i>
                        <span>Corpix ile Değerlendir</span>
                    </button>
                    <p class="ai-evaluate-hint">AI, ${hasResults ? 'bulunan sonuçları analiz edip' : ''} detaylı bir çözüm önerisi hazırlayacak.</p>
                </div>
            `;

            el.solutionSteps.innerHTML = html;

            // Event listeners ekle
            setupRagResultsEventListeners();
        }
    }

    /**
     * RAG sonuçları için event listener'ları kur
     */
    function setupRagResultsEventListeners() {
        // AI Değerlendir butonu
        const aiEvaluateBtn = document.getElementById('btnAIEvaluate');
        if (aiEvaluateBtn) {
            aiEvaluateBtn.addEventListener('click', requestAIEvaluation);
        }

        // Seç butonları
        document.querySelectorAll('.btn-select-result').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const index = parseInt(btn.dataset.index);
                selectRagResult(index);
            });
        });
    }

    /**
     * AI Değerlendirmesi iste (isteğe bağlı)
     */
    async function requestAIEvaluation() {
        if (!currentTicketId) {
            console.error('Ticket ID bulunamadı');
            return;
        }

        const btn = document.getElementById('btnAIEvaluate');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Değerlendiriliyor...';
        }

        const token = localStorage.getItem('access_token');
        if (!token) {
            if (typeof VyraToast !== 'undefined') {
                VyraToast.error('Oturum bulunamadı');
            }
            return;
        }

        try {
            const response = await fetch(`/api/tickets/${currentTicketId}/ai-evaluate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                }
            });

            const data = await response.json();

            if (data.success) {
                // Çözümü göster
                const el = getElements();
                if (el.solutionSteps && data.final_solution) {
                    el.solutionSteps.innerHTML = formatSolution(data.final_solution);
                    updateSourceInfo(data.final_solution);
                }

                // CYM metnini güncelle
                if (el.cymText && data.cym_text) {
                    el.cymText.textContent = data.cym_text;
                }

                // Feedback butonlarını göster
                renderFeedbackButtons();

                if (typeof VyraToast !== 'undefined') {
                    VyraToast.success('AI değerlendirmesi tamamlandı!');
                }

                // History'yi yenile
                if (typeof loadTicketHistory === 'function') {
                    loadTicketHistory(true);
                }
            } else {
                throw new Error(data.error || 'AI değerlendirme hatası');
            }
        } catch (error) {
            console.error('AI değerlendirme hatası:', error);
            if (typeof VyraToast !== 'undefined') {
                VyraToast.error('AI değerlendirme hatası: ' + error.message);
            }

            // Butonu geri aç
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-robot"></i> <span>Corpix ile Değerlendir</span>';
            }
        }
    }

    /**
     * RAG sonucunu seç
     */
    async function selectRagResult(index) {
        const ragResults = window.currentRagResults || [];
        const selected = ragResults[index];

        if (!selected || !currentTicketId) {
            console.error('Seçim yapılamadı');
            return;
        }

        const token = localStorage.getItem('access_token');
        if (!token) return;

        // Butonu devre dışı bırak
        const btn = document.querySelector(`.btn-select-result[data-index="${index}"]`);
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
        }

        try {
            const response = await fetch(`/api/tickets/${currentTicketId}/select`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({
                    selected_chunk_text: selected.chunk_text,
                    selected_file_name: selected.file_name
                })
            });

            const data = await response.json();

            if (data.success) {
                // Çözümü göster
                const el = getElements();
                if (el.solutionSteps) {
                    el.solutionSteps.innerHTML = formatSolution(selected.chunk_text);
                }

                // CYM metnini güncelle
                if (el.cymText && data.cym_text) {
                    el.cymText.textContent = data.cym_text;
                }

                // Feedback butonlarını göster
                renderFeedbackButtons();

                if (typeof VyraToast !== 'undefined') {
                    VyraToast.success('Çözüm seçildi!');
                }

                // History'yi yenile
                if (typeof loadTicketHistory === 'function') {
                    loadTicketHistory(true);
                }
            } else {
                throw new Error(data.error || 'Seçim kaydedilemedi');
            }
        } catch (error) {
            console.error('Seçim hatası:', error);
            if (typeof VyraToast !== 'undefined') {
                VyraToast.error('Seçim hatası: ' + error.message);
            }

            // Butonu geri aç
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-check"></i> Bunu Seç';
            }
        }
    }

    // Public API
    return {
        init: init,
        format: formatSolution,
        show: showSolution,
        showLoading: showLoading,
        hide: hide,
        updateSourceInfo: updateSourceInfo,
        escapeHtml: escapeHtml,
        // v2.13.0 - Feedback
        setTicketInfo: setTicketInfo,
        resetFeedback: resetFeedback,
        renderFeedbackButtons: renderFeedbackButtons,
        // v2.17.1 - LLM Evaluation için ticket ID getter
        getCurrentTicketId: () => currentTicketId,
        // 🆕 v2.23.0 - RAG sonuçları gösterimi
        showRagResults: showRagResults,
        requestAIEvaluation: requestAIEvaluation,
        selectRagResult: selectRagResult
    };

})();

// Otomatik init
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', window.SolutionDisplayModule.init);
} else {
    window.SolutionDisplayModule.init();
}

