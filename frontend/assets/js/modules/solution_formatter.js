/* ─────────────────────────────────────────────
   VYRA – Solution Formatter Module
   v2.30.0 · home_page.js'den ayrıştırıldı
   Çözüm formatlama fallback fonksiyonları
   ───────────────────────────────────────────── */


// =============================================
// ÇÖZÜM FORMATLAMA - SolutionDisplayModule Kullanılır
// (Kod tekrarı önlendi - tek kaynak: solution_display.js)
// =============================================

// SolutionDisplayModule wrapper - Modül yüklüyse onu kullan, değilse fallback
function formatSolutionForDisplay(solution) {
    if (!solution) return '<p class="text-gray-500">Çözüm bilgisi yok</p>';

    // SolutionDisplayModule modülünü kullan
    if (typeof window.SolutionDisplayModule !== 'undefined' && window.SolutionDisplayModule.format) {
        return window.SolutionDisplayModule.format(solution);
    }

    // Fallback - modül yüklü değilse basit format
    console.warn('[VYRA] SolutionDisplayModule yüklü değil, basit format kullanılıyor');
    return `<p class="solution-text">${escapeHtmlForSolution(solution)}</p>`;
}

// Inline numaralı adımları ayır: "1) step1 2) step2 3) step3" -> ayrı adımlar
function formatInlineNumberedSteps(text) {
    // Önce kaynak bilgisini al ve temizle
    let sourceInfo = '';
    const sourceMatch = text.match(/[💡📄]?\s*Kaynak:\s*(.+?)(?:\s*$|\.?\s*$)/i);
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
    const firstStepMatch = text.match(/^(.+?)(?=\d+[\)\.]\s)/);
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
        return `<p class="solution-text">${escapeHtmlForSolution(text)}</p>`;
    }

    // HTML oluştur - Container ile sarmalı
    let html = '<div class="solution-steps-container">';

    // Giriş metni varsa ekle
    if (introText && introText.length > 10) {
        html += `<p class="solution-intro-text">${escapeHtmlForSolution(introText)}</p>`;
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
                <div class="step-content">${escapeHtmlForSolution(content)}</div>
            </div>
        `;
    });

    html += '</div>';

    // Kaynak bilgisi varsa ekle
    if (sourceInfo) {
        html += `
            <div class="source-info-box">
                <i class="fa-solid fa-lightbulb"></i>
                <span>Kaynak: ${escapeHtmlForSolution(sourceInfo)}</span>
            </div>
        `;
    }

    return html;
}

// Tek paragraf metni adımlara ayırır
function formatSingleParagraph(text) {
    // Adım ayırıcı kalıplar
    const stepPatterns = [
        /\.\s+(?=[A-ZÇĞİÖŞÜ])/g,  // Büyük harfle başlayan cümle
        /\.\s+(?=\d)/g,            // Sayı ile başlayan cümle
        /;\s+/g,                    // Noktalı virgül
    ];

    // Önce "ardından" veya "sonra" ile böl (en yaygın geçiş kelimeleri)
    if (/,\s*ardından\s+/i.test(text)) {
        sentences = text.split(/,\s*ardından\s+/i).filter(s => s.trim().length > 5);
    } else if (/,\s*sonra\s+/i.test(text)) {
        sentences = text.split(/,\s*sonra\s+/i).filter(s => s.trim().length > 5);
    } else if (text.includes(';')) {
        // Noktalı virgül ile ayrılmış adımlar
        sentences = text.split(/;\s*/).filter(s => s.trim().length > 5);
    } else {
        // Hiçbiri çalışmadıysa, nokta + büyük harf ile böl
        sentences = text.split(/\.\s+(?=[A-ZÇĞİÖŞÜ])/).filter(s => s.trim());
        // Yine de 1 cümle ise tek olarak bırak
        if (sentences.length < 2) {
            sentences = [text];
        }
    }

    // Kaynak bilgisini ayır
    let sourceInfo = '';
    const sourceMatch = text.match(/📄\s*Kaynak:\s*(.+?)(?:\s*$|\.\s)/i);
    if (sourceMatch) {
        sourceInfo = sourceMatch[1].trim();
    }

    // Cümleleri temizle ve adımlara dönüştür
    let html = '<div class="solution-steps-container">';
    let stepCounter = 0;

    sentences.forEach(sentence => {
        let cleanSentence = sentence.trim();

        // Kaynak satırını atla
        if (cleanSentence.toLowerCase().includes('kaynak:') || cleanSentence.startsWith('📄')) {
            return;
        }

        // Çok kısa cümleleri atla
        if (cleanSentence.length < 10) return;

        // Nokta ekle (yoksa)
        if (!cleanSentence.endsWith('.') && !cleanSentence.endsWith('!') && !cleanSentence.endsWith('?')) {
            cleanSentence += '.';
        }

        // İlk harfi büyük yap
        cleanSentence = cleanSentence.charAt(0).toUpperCase() + cleanSentence.slice(1);

        stepCounter++;

        html += `
            <div class="solution-step-item">
                <div class="step-number">${stepCounter}</div>
                <div class="step-content">${escapeHtmlForSolution(cleanSentence)}</div>
            </div>
        `;
    });

    html += '</div>';

    // Kaynak bilgisi ekle
    if (sourceInfo) {
        html += `
            <div class="solution-source">
                <i class="fa-solid fa-file-lines"></i>
                <span>Kaynak: ${escapeHtmlForSolution(sourceInfo)}</span>
            </div>
        `;
    }

    return html;
}

// Mevcut numaralı adım formatı
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

        // "Alternatif olarak:" kontrolü
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

        // Numaralı satır kontrolü
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
                    <div class="step-content">${escapeHtmlForSolution(numberedMatch[2])}</div>
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
                        <span>Kaynak: ${escapeHtmlForSolution(trimmedLine.replace('📄', '').replace(/^kaynak:/i, '').trim())}</span>
                    </div>
                `;
            } else if (trimmedLine === '---') {
                html += '<hr class="solution-divider">';
            } else {
                html += `<p class="solution-text">${escapeHtmlForSolution(trimmedLine)}</p>`;
            }
        }
    });

    if (inList) html += '</div>';

    return html || `<p class="solution-text">${escapeHtmlForSolution(solution)}</p>`;
}

// HTML escape (Yeni Soru için)
function escapeHtmlForSolution(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Kaynak bilgisini HTML elementine ekle
function updateSourceInfo(solution) {
    const sourceInfoBox = document.getElementById("sourceInfo");
    const sourceText = document.getElementById("sourceText");

    if (!sourceInfoBox || !sourceText) return;

    // Kaynak bilgisini çıkar
    const sourceMatch = solution?.match(/📄\s*Kaynak:\s*(.+?)(?:\s*$|\.)/i) ||
        solution?.match(/Kaynak:\s*(.+?)(?:\s*$|\.)/i);

    if (sourceMatch && sourceMatch[1]) {
        sourceText.textContent = "Kaynak: " + sourceMatch[1].trim();
        sourceInfoBox.classList.remove("hidden");
    } else {
        sourceInfoBox.classList.add("hidden");
    }
}
