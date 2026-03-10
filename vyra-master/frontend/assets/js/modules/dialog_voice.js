/* ─────────────────────────────────────────────
   VYRA – Dialog Voice & TTS Module
   v2.30.1 · dialog_chat.js'den ayrıştırıldı
   Speech Recognition + Text-to-Speech
   ───────────────────────────────────────────── */

window.DialogVoiceModule = (function () {
    'use strict';

    // State
    let recognition = null;
    let finalTranscript = '';
    let isSpeaking = false;
    let activeSpeakBtn = null;


    // =============================================================================
    // VOICE RECORDING (Web Speech API)
    // =============================================================================

    function initSpeechRecognition() {
        if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
            console.warn('[DialogChat] Tarayıcı ses tanımayı desteklemiyor');
            return;
        }

        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SpeechRecognition();
        recognition.lang = 'tr-TR';
        recognition.continuous = true;   // Kullanıcı durduruncaya kadar dinle
        recognition.interimResults = true;  // Anlık sonuçları göster
        recognition.maxAlternatives = 1;

        // Sessizlik timeout'u için
        let silenceTimeout = null;
        const SILENCE_DELAY = 2000; // 2 saniye sessizlik sonrası dur

        recognition.onresult = (event) => {
            let interimTranscript = '';

            // Önceki timeout'u iptal et (yeni ses geldi)
            if (silenceTimeout) {
                clearTimeout(silenceTimeout);
                silenceTimeout = null;
            }

            for (let i = event.resultIndex; i < event.results.length; i++) {
                const transcript = event.results[i][0].transcript;
                if (event.results[i].isFinal) {
                    finalTranscript += transcript + ' ';

                    // Final sonuç alındı, 2 sn sessizlik sonrası dur
                    silenceTimeout = setTimeout(() => {
                        console.log('[DialogChat] Sessizlik - otomatik durdurma');
                        stopRecording();
                    }, SILENCE_DELAY);
                } else {
                    interimTranscript += transcript;
                }
            }

            const input = document.getElementById('dialogInput');
            if (input) {
                // Anlık + final sonuçları birleştir
                input.value = (finalTranscript + interimTranscript).trim();
                updateSendButtonState();
                console.log('[DialogChat] STT:', finalTranscript + interimTranscript);
            }
        };

        recognition.onerror = (event) => {
            console.error('[DialogChat] Ses tanıma hatası:', event.error);
            stopRecording();
            if (event.error === 'not-allowed') {
                showToast('error', 'Mikrofon izni gerekli. Lütfen tarayıcı ayarlarından izin verin.');
            } else if (event.error === 'no-speech') {
                showToast('warning', 'Ses algılanamadı. Tekrar deneyin.');
            } else if (event.error === 'network') {
                showToast('error', 'Ağ hatası. İnternet bağlantınızı kontrol edin.');
            }
        };

        recognition.onend = () => {
            // Konuşma bitince otomatik stop
            console.log('[DialogChat] Ses tanıma tamamlandı');
            stopRecording();
        };

        console.log('[DialogChat] Ses tanıma başlatıldı');
    }

    function toggleVoiceRecording() {
        if (isRecording) {
            stopRecording();
        } else {
            startRecording();
        }
    }

    function startRecording() {
        if (!recognition) {
            showToast('error', 'Ses tanıma desteklenmiyor');
            return;
        }

        // Önceki transcript'i temizle
        finalTranscript = '';
        isRecording = true;

        const voiceBtn = document.getElementById('dialogVoiceBtn');
        if (voiceBtn) {
            voiceBtn.classList.add('recording');
            voiceBtn.innerHTML = '<i class="fa-solid fa-stop"></i>';
        }

        try {
            recognition.start();
            console.log('[DialogChat] Kayıt başlatıldı');
        } catch (e) {
            console.error('[DialogChat] Kayıt başlatılamadı:', e);
            stopRecording();
        }
    }

    function stopRecording() {
        isRecording = false;

        const voiceBtn = document.getElementById('dialogVoiceBtn');
        if (voiceBtn) {
            voiceBtn.classList.remove('recording');
            voiceBtn.innerHTML = '<i class="fa-solid fa-microphone"></i>';
        }

        if (recognition) {
            try {
                recognition.stop();
            } catch (e) {
                // Zaten durmuş olabilir
            }
        }
    }

    // =============================================================================
    // TEXT-TO-SPEECH (TTS)
    // =============================================================================

    /**
     * v2.26.0: Message ID ile sesli okuma - DOM'dan içeriği alır
     * Bu yöntem, uzun içeriklerin HTML attribute'a gömülmesini önler
     */
    function speakMessage(messageId, btn = null) {
        const messageEl = document.querySelector(`[data-message-id="${messageId}"] .message-content`);
        if (!messageEl) {
            showToast('warning', 'Mesaj bulunamadı');
            return;
        }
        // DOM'dan text içeriğini al (HTML tag'leri olmadan)
        const text = messageEl.textContent || messageEl.innerText || '';
        speakText(text, btn);
    }

    function speakText(text, btn = null) {
        // Zaten konuşuyorsa durdur
        if (isSpeaking) {
            window.speechSynthesis.cancel();
            isSpeaking = false;
            updateSpeakButtons(false);
            return;
        }

        // Aktif butonu kaydet
        activeSpeakBtn = btn;

        if (!('speechSynthesis' in window)) {
            showToast('error', 'Tarayıcı sesli okumayı desteklemiyor');
            return;
        }

        // Markdown ve HTML temizle
        const cleanText = text
            .replace(/\*\*(.*?)\*\*/g, '$1')
            .replace(/<[^>]*>/g, '')
            .replace(/---/g, '')
            .replace(/👍 👎/g, '')
            .replace(/[\u{1F300}-\u{1F9FF}]/gu, '') // Emoji temizle (Unicode)
            .trim();

        if (!cleanText) {
            showToast('warning', 'Okunacak metin yok');
            return;
        }

        // Sesler async yüklenir, önce bekle
        const doSpeak = () => {
            const utterance = new SpeechSynthesisUtterance(cleanText);
            utterance.lang = 'tr-TR';
            utterance.rate = 0.95;  // Biraz yavaş, daha anlaşılır
            utterance.pitch = 1.0;

            // Türkçe ses bul - Microsoft veya Google Türkçe öncelikli
            const voices = window.speechSynthesis.getVoices();
            const turkishVoices = voices.filter(v => v.lang.startsWith('tr'));

            // Öncelik: Microsoft > Google > Diğer
            const preferredVoice = turkishVoices.find(v =>
                v.name.includes('Microsoft') || v.name.includes('Tolga') || v.name.includes('Emel')
            ) || turkishVoices.find(v =>
                v.name.includes('Google')
            ) || turkishVoices[0];

            if (preferredVoice) {
                utterance.voice = preferredVoice;
                console.log('[TTS] Türkçe ses:', preferredVoice.name);
            } else {
                console.warn('[TTS] Türkçe ses bulunamadı, varsayılan kullanılacak');
            }

            utterance.onstart = () => {
                isSpeaking = true;
                updateSpeakButtons(true);
            };

            utterance.onend = () => {
                isSpeaking = false;
                updateSpeakButtons(false);
            };

            utterance.onerror = () => {
                isSpeaking = false;
                updateSpeakButtons(false);
            };

            window.speechSynthesis.speak(utterance);
        };

        // Sesler yüklü mü kontrol et
        if (window.speechSynthesis.getVoices().length === 0) {
            // Sesler henüz yüklenmemiş, bekle
            window.speechSynthesis.onvoiceschanged = () => {
                doSpeak();
            };
        } else {
            doSpeak();
        }
    }

    function updateSpeakButtons(speaking) {
        // Sadece aktif butonu güncelle, diğerlerini değil
        if (activeSpeakBtn) {
            if (speaking) {
                activeSpeakBtn.classList.add('speaking');
                activeSpeakBtn.innerHTML = '<i class="fa-solid fa-volume-xmark"></i>';
            } else {
                activeSpeakBtn.classList.remove('speaking');
                activeSpeakBtn.innerHTML = '<i class="fa-solid fa-volume-high"></i>';
                activeSpeakBtn = null; // Reset
            }
        }
    }


    return {
        initSpeechRecognition,
        toggleVoiceRecording,
        startRecording,
        stopRecording,
        speakMessage,
        speakText,
        updateSpeakButtons,
        getIsSpeaking: function () { return isSpeaking; },
        setIsSpeaking: function (v) { isSpeaking = v; }
    };
})();
