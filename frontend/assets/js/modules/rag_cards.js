/* ─────────────────────────────────────────────
   VYRA – RAG Selection Cards Module
   v2.30.0 · home_page.js'den ayrıştırıldı
   RAG sonuç kartları gösterimi, gruplama ve seçim
   ───────────────────────────────────────────── */

// 🎴 RAG seçim kartlarını göster - v2.21.2: Aynı yetki adına sahip chunk'ları grupla
function showRAGSelectionCards(results, query) {
    const ragSelectionBox = document.getElementById('ragSelectionBox');
    const ragSelectionCards = document.getElementById('ragSelectionCards');

    if (!ragSelectionBox || !ragSelectionCards) {
        console.error('[VYRA] RAG seçim elementleri bulunamadı');
        return;
    }

    // 🔧 v2.21.2: Aynı "Yetki Hakkında Bilgi" içeren chunk'ları grupla
    const groupedResults = groupRAGResultsByYetki(results);

    // Kartları oluştur (gruplu veya tekil)
    ragSelectionCards.innerHTML = groupedResults.map((group, i) => {
        // Tek sonuç mu yoksa grup mu?
        if (group.isGroup) {
            // Grupta birden fazla ROL kodu var - hepsini listele
            return `
                <div class="rag-selection-card rag-grouped-card" onclick="handleRAGCardSelection(${i})" data-index="${i}">
                    <div class="rag-card-header">
                        <div class="rag-card-header-left">
                            <span class="rag-card-number">${i + 1}</span>
                            <span class="rag-card-title">${escapeHtml(group.file_name)}</span>
                            <span class="rag-card-badge">${group.items.length} Seçenek</span>
                        </div>
                        <span class="rag-card-score">%${group.avgScore}</span>
                    </div>
                    <div class="rag-card-body">
                        <div class="rag-card-kv-row">
                            <span class="rag-card-kv-label">Yetki Hakkında Bilgi:</span>
                            <span class="rag-card-kv-value">${escapeHtml(group.yetkiBilgisi)}</span>
                        </div>
                        <div class="rag-role-codes-section">
                            <span class="rag-role-codes-label">Rol/Yetki Kodları:</span>
                            <div class="rag-role-codes-list">
                                ${group.items.map(item => `
                                    <div class="rag-role-code-item">
                                        <i class="fa-solid fa-key"></i>
                                        <code>${escapeHtml(item.rolKodu)}</code>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    </div>
                    <div class="rag-card-footer">
                        <span class="rag-card-select-btn"><i class="fa-solid fa-check-circle"></i> Bu seçeneği seç</span>
                    </div>
                </div>
            `;
        } else {
            // Tekil sonuç - eski formatı kullan
            const r = group.original;
            const formattedContent = formatChunkTextForCard(r.chunk_text);
            return `
                <div class="rag-selection-card" onclick="handleRAGCardSelection(${i})" data-index="${i}">
                    <div class="rag-card-header">
                        <div class="rag-card-header-left">
                            <span class="rag-card-number">${i + 1}</span>
                            <span class="rag-card-title">${escapeHtml(r.file_name)}</span>
                        </div>
                        <span class="rag-card-score">%${r.score}</span>
                    </div>
                    <div class="rag-card-body">
                        ${formattedContent}
                    </div>
                    <div class="rag-card-footer">
                        <span class="rag-card-select-btn"><i class="fa-solid fa-check-circle"></i> Bu seçeneği seç</span>
                    </div>
                </div>
            `;
        }
    }).join('');

    // State'i kaydet (gruplu sonuçları da kaydet)
    window._currentRAGResults = results;  // Orijinal sonuçlar
    window._currentRAGGrouped = groupedResults;  // Gruplu sonuçlar
    window._currentRAGQuery = query;

    ragSelectionBox.classList.remove('hidden');
}

// 🔧 v2.21.2: RAG sonuçlarını "Yetki Hakkında Bilgi" alanına göre grupla
function groupRAGResultsByYetki(results) {
    const groups = {};
    const ungrouped = [];

    results.forEach((r, idx) => {
        // Yetki Hakkında Bilgi alanını bul
        const yetkiBilgisiMatch = r.chunk_text?.match(/Yetki\s*Hakkında\s*Bilgi[:：]?\s*([^\n]+)/i);
        const rolKoduMatch = r.chunk_text?.match(/Rol\s*Seçimi[\/\s]*Rol\s*Adı[\/\s]*Yetki\s*Adı[:：]?\s*([^\n]+)/i)
            || r.chunk_text?.match(/Rol[\/\s]+Yetki\s*Adı[:：]?\s*([^\n]+)/i);

        if (yetkiBilgisiMatch && rolKoduMatch) {
            const yetkiBilgisi = yetkiBilgisiMatch[1].trim();
            const rolKodu = rolKoduMatch[1].trim();

            // Aynı yetki bilgisine sahip chunk'ları grupla
            if (!groups[yetkiBilgisi]) {
                groups[yetkiBilgisi] = {
                    isGroup: true,
                    yetkiBilgisi: yetkiBilgisi,
                    file_name: r.file_name,
                    items: [],
                    scores: [],
                    originalIndices: []
                };
            }
            groups[yetkiBilgisi].items.push({ rolKodu, original: r, originalIndex: idx });
            groups[yetkiBilgisi].scores.push(r.score);
            groups[yetkiBilgisi].originalIndices.push(idx);
        } else {
            // Gruplanamayan sonuçlar
            ungrouped.push({ isGroup: false, original: r, originalIndex: idx });
        }
    });

    // Grupları sonuç dizisine dönüştür
    const finalResults = [];

    Object.values(groups).forEach(group => {
        if (group.items.length > 1) {
            // Birden fazla ROL kodu var - grup olarak ekle
            group.avgScore = Math.round(group.scores.reduce((a, b) => a + b, 0) / group.scores.length);
            finalResults.push(group);
        } else {
            // Tek ROL kodu - tekil olarak ekle
            ungrouped.push({ isGroup: false, original: group.items[0].original, originalIndex: group.items[0].originalIndex });
        }
    });

    // Grupları önce, sonra tekilleri ekle
    return [...finalResults, ...ungrouped];
}

// 🎨 Chunk text'i kart için formatla (Çözüm Bulundu! gibi key-value)
function formatChunkTextForCard(chunkText) {
    if (!chunkText) return '<p class="rag-card-empty">İçerik yok</p>';

    // Key-value satırlarını parse et
    const lines = chunkText.split('\n');
    let html = '';

    // Bilinen alanlar için mapping (dosyalardaki format)
    const labelPatterns = [
        { regex: /^\*?\*?Uygulama\s*Adı\s*[:：]?\*?\*?[:：]?\s*(.*)$/i, label: 'Uygulama Adı' },
        { regex: /^\*?\*?Keyflow\s*Search\s*[:：]?\*?\*?[:：]?\s*(.*)$/i, label: 'Keyflow Search' },
        { regex: /^\*?\*?Talep\s*Tipi\s*[:：]?\*?\*?[:：]?\s*(.*)$/i, label: 'Talep Tipi' },
        { regex: /^\*?\*?Rol\s*Seçimi[\s\/]*Rol\s*Adı[\s\/]*Yetki\s*Adı\s*[:：]?\*?\*?[:：]?\s*(.*)$/i, label: 'Rol Seçimi/Rol Adı/Yetki Adı' },
        { regex: /^\*?\*?Rol[\s\/]+Yetki\s*Adı\s*[:：]?\*?\*?[:：]?\s*(.*)$/i, label: 'Rol/Yetki Adı' },
        { regex: /^\*?\*?Rol\s*Seçimi\s*[:：]?\*?\*?[:：]?\s*(.*)$/i, label: 'Rol Seçimi' },
        { regex: /^\*?\*?Yetki\s*Hakkında\s*Bilgi\s*[:：]?\*?\*?[:：]?\s*(.*)$/i, label: 'Yetki Hakkında Bilgi' },
        { regex: /^\*?\*?Yetki\s*Bilgisi\s*[:：]?\*?\*?[:：]?\s*(.*)$/i, label: 'Yetki Bilgisi' },
    ];

    let currentLabel = null;
    let currentValue = '';
    let parsedPairs = [];

    lines.forEach(line => {
        const trimmed = line.trim();
        if (!trimmed) return;

        // Bu satır bir label satırı mı?
        let matched = false;
        for (const pattern of labelPatterns) {
            const match = trimmed.match(pattern.regex);
            if (match) {
                // Önceki pair'i kaydet
                if (currentLabel && currentValue) {
                    parsedPairs.push({ label: currentLabel, value: currentValue.trim() });
                }

                currentLabel = pattern.label;
                currentValue = match[1] || '';
                matched = true;
                break;
            }
        }

        // Markdown **Label:** Value formatı
        if (!matched) {
            const mdMatch = trimmed.match(/^\*\*([^*]+?)[:：]?\*\*[:：]?\s*(.*)$/);
            if (mdMatch) {
                // Önceki pair'i kaydet
                if (currentLabel && currentValue) {
                    parsedPairs.push({ label: currentLabel, value: currentValue.trim() });
                }
                currentLabel = mdMatch[1].trim();
                currentValue = mdMatch[2] || '';
                matched = true;
            }
        }

        // Basit "Label: Value" formatı
        if (!matched) {
            const simpleMatch = trimmed.match(/^([^:：]+)[:：]\s*(.+)$/);
            if (simpleMatch && simpleMatch[1].length < 40) {
                // Önceki pair'i kaydet
                if (currentLabel && currentValue) {
                    parsedPairs.push({ label: currentLabel, value: currentValue.trim() });
                }
                currentLabel = simpleMatch[1].trim();
                currentValue = simpleMatch[2] || '';
                matched = true;
            }
        }

        // Eşleşme yoksa mevcut değere ekle
        if (!matched && currentLabel) {
            currentValue += ' ' + trimmed;
        }
    });

    // Son pair'i kaydet
    if (currentLabel && currentValue) {
        parsedPairs.push({ label: currentLabel, value: currentValue.trim() });
    }

    // Eğer hiç pair bulunamadıysa ham metni göster
    if (parsedPairs.length === 0) {
        // İlk 300 karakteri göster
        const preview = chunkText.length > 300 ? chunkText.substring(0, 300) + '...' : chunkText;
        return `<p class="rag-card-preview">${escapeHtml(preview)}</p>`;
    }

    // Key-value formatında HTML oluştur
    parsedPairs.forEach(pair => {
        html += `
            <div class="rag-card-kv-row">
                <span class="rag-card-kv-label">${escapeHtml(pair.label)}:</span>
                <span class="rag-card-kv-value">${escapeHtml(pair.value)}</span>
            </div>
        `;
    });

    return html;
}


// 🎯 RAG kart seçimi işle - v2.21.2: Gruplu sonuçları da destekle
async function handleRAGCardSelection(index) {
    const results = window._currentRAGResults;
    const groupedResults = window._currentRAGGrouped;
    const query = window._currentRAGQuery;

    if (!groupedResults || index >= groupedResults.length) {
        console.error('[VYRA] Geçersiz RAG seçimi');
        return;
    }

    const selectedGroup = groupedResults[index];

    // 🔧 v2.21.2: Grup mu yoksa tekil sonuç mu?
    let combinedChunkText = '';
    let allItems = [];

    if (selectedGroup.isGroup) {
        // Gruplu sonuç - tüm chunk'ları birleştir
        allItems = selectedGroup.items.map(item => item.original);
        combinedChunkText = selectedGroup.items.map(item => item.original.chunk_text).join('\n\n---\n\n');
        console.log(`[VYRA] Gruplu seçim: ${selectedGroup.items.length} chunk birleştirildi`);
    } else {
        // Tekil sonuç
        allItems = [selectedGroup.original];
        combinedChunkText = selectedGroup.original.chunk_text;
    }

    // Kartı seçili olarak işaretle
    const cards = document.querySelectorAll('.rag-selection-card');
    cards.forEach((card, i) => {
        card.classList.remove('selected');
        if (i === index) card.classList.add('selected');
    });

    // RAG seçim kartlarını gizle
    const ragSelectionBox = document.getElementById('ragSelectionBox');
    if (ragSelectionBox) ragSelectionBox.classList.add('hidden');

    // Loading göstermeden direkt içeriği göster
    const finalSolutionBox = document.getElementById('finalSolutionBox');
    const solutionSteps = document.getElementById('solutionSteps');
    const loadingBox = document.getElementById('loadingBox');

    if (loadingBox) loadingBox.classList.add('hidden');
    if (finalSolutionBox) finalSolutionBox.classList.remove('hidden');

    // ⏱️ Yanıt süresini hesapla ve göster
    if (requestStartTime) {
        const responseTime = ((performance.now() - requestStartTime) / 1000).toFixed(1);
        const responseTimeEl = document.getElementById("responseTime");
        if (responseTimeEl) {
            responseTimeEl.textContent = `${responseTime}s`;
        }
    }

    // RAG içeriğini formatla ve göster (AI çağırmadan)
    if (solutionSteps && combinedChunkText) {
        // Kaynak bilgisi ile birlikte göster
        const formattedContent = window.SolutionDisplayModule?.format?.(combinedChunkText)
            || `<p class="solution-text">${combinedChunkText}</p>`;

        // Çoklu kaynak varsa diğer sonuçları da ekle
        const allSources = allItems.map(r => r.file_name).filter((v, i, a) => a.indexOf(v) === i);
        const sourceInfo = `<div class="source-info"><i class="fa-solid fa-file-lines"></i> Kaynak: <strong>${allSources.join(', ')}</strong></div>`;

        solutionSteps.innerHTML = formattedContent + sourceInfo;
    }

    // State kaydet - Corpix ile Değerlendir için kullanılacak
    // 🔧 v2.21.2: Tüm chunk'ları kaydet (LLM değerlendirmesi için)
    window._selectedRAGResult = {
        chunk_text: combinedChunkText,
        file_name: allItems[0]?.file_name || '',
        score: selectedGroup.isGroup ? selectedGroup.avgScore : selectedGroup.original?.score,
        all_items: allItems  // Tüm orijinal sonuçlar
    };
    window._selectedRAGQuery = query;
    window._currentRAGResults = results;  // Orijinal sonuçları koru

    // Çözüm sağlandı moduna geç (newRequestBtn animasyonu vb.)
    if (window.TicketChatModule?.setSolutionProvided) {
        window.TicketChatModule.setSolutionProvided();
    }

    // Ticket henüz oluşturulmadı - sadece kullanıcıya gösterildi
    console.log(`[VYRA] RAG içeriği gösterildi (${allItems.length} chunk). Kullanıcı "Corpix ile Değerlendir" için tıklayabilir.`);
}

// ⚡ RAG seçimini işle ve ticket oluştur
async function processRAGSelection(query, selectedResult) {
    const loadingBox = document.getElementById("loadingBox");
    const ragSelectionBox = document.getElementById('ragSelectionBox');
    const progressEl = loadingBox?.querySelector('.progress-text') || createProgressElement();

    // Kart seçim alanını gizle, loading göster
    if (ragSelectionBox) ragSelectionBox.classList.add('hidden');
    if (loadingBox) loadingBox.classList.remove("hidden");
    updateProgress(progressEl, "✅ Çözüm kaydediliyor...");

    // ⏱️ Zamanlayıcı başlat
    requestStartTime = performance.now();

    try {
        // Ticket oluştur (LLM kullanmadan, direkt RAG sonucu)
        const ticketResult = await VyraWebSocket.createTicketFromSelection(
            query,
            selectedResult.chunk_text,
            selectedResult.file_name
        );

        // Sonucu göster
        handleAsyncTicketResult(ticketResult);

        // Butonu resetle
        const suggestBtn = document.getElementById("suggestBtn");
        if (suggestBtn) {
            suggestBtn.classList.remove("loading");
        }

    } catch (err) {
        console.error('[VYRA] RAG seçim işleme hatası:', err);
        handleTicketError(err.message, document.getElementById("suggestBtn"), document.getElementById("problemText"));
    }
}

// 🧠 LLM ile değerlendirme talep et
async function requestLLMEvaluation() {
    const llmBtn = document.getElementById('llmEvaluateBtn');
    const llmResultBox = document.getElementById('llmEvaluationResult');
    const llmResultContent = document.getElementById('llmResultContent');
    const solutionSteps = document.getElementById('solutionSteps');

    if (!llmBtn || !llmResultBox || !llmResultContent) return;

    // Mevcut çözümü al
    const currentSolution = solutionSteps?.innerText || '';
    const query = document.getElementById('problemText')?.value || '';

    if (!currentSolution || !query) {
        if (typeof VyraToast !== 'undefined') {
            VyraToast.warning('Değerlendirilecek içerik bulunamadı.');
        }
        return;
    }

    // Loading state
    llmBtn.disabled = true;
    llmBtn.classList.add('loading');
    llmBtn.innerHTML = '<i class="fa-solid fa-spinner"></i> <span class="llm-btn-text">Değerlendiriliyor...</span>';

    try {
        // SolutionDisplayModule'dan mevcut ticket ID'yi al (varsa kaydedilir)
        const ticketId = window.SolutionDisplayModule?.getCurrentTicketId?.() || null;

        const result = await VyraWebSocket.evaluateWithLLM(query, currentSolution, ticketId);

        // Sonucu göster
        llmResultContent.innerHTML = result.formatted_html;
        llmResultBox.classList.remove('hidden');

        // Butonu başarı state'ine al
        llmBtn.innerHTML = '<i class="fa-solid fa-check"></i> <span class="llm-btn-text">Değerlendirildi</span>';
        llmBtn.disabled = true;
        llmBtn.classList.remove('loading');

        if (typeof VyraToast !== 'undefined') {
            VyraToast.success('Corpix AI değerlendirmesi tamamlandı!');
        }

    } catch (err) {
        console.error('[VYRA] LLM değerlendirme hatası:', err);

        llmBtn.innerHTML = '<i class="fa-solid fa-brain"></i> <span class="llm-btn-text">Corpix ile Değerlendir</span>';
        llmBtn.disabled = false;
        llmBtn.classList.remove('loading');

        // 🌐 VPN/Network hatası kontrolü
        if (window.isVPNNetworkError && window.isVPNNetworkError(err.message)) {
            window.showVPNErrorPopup();
        } else if (typeof VyraToast !== 'undefined') {
            VyraToast.error('Değerlendirme hatası: ' + err.message);
        }
    }
}

// HTML escape helper
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Global erişim için
window.handleRAGCardSelection = handleRAGCardSelection;
window.requestLLMEvaluation = requestLLMEvaluation;
