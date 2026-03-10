/* ─────────────────────────────────────────────
   NGSSAI — Ticket Date Range Module
   v2.30.1 · ticket_history.js'den ayrıştırıldı
   Tarih aralığı seçim, dropdown, hazır aralıklar
   ───────────────────────────────────────────── */

// Başlangıç değerlerini ayarla
function initializeDateInputs() {
    if (startDateInput && endDateInput) {
        startDateInput.value = _startDate;
        endDateInput.value = _endDate;
        updateDateRangeText();
    }
}

// Tarih aralığı metnini güncelle
function updateDateRangeText() {
    if (!dateRangeText) return;

    if (_startDate && _endDate) {
        const startFormatted = formatDateTR(_startDate);
        const endFormatted = formatDateTR(_endDate);
        dateRangeText.textContent = `${startFormatted} - ${endFormatted}`;
    } else if (_startDate) {
        dateRangeText.textContent = `${formatDateTR(_startDate)} - ...`;
    } else if (_endDate) {
        dateRangeText.textContent = `... - ${formatDateTR(_endDate)}`;
    } else {
        dateRangeText.textContent = "Tarih Seçin";
    }
}

// Date range butonuna tıklayınca dropdown göster
if (dateRangeBtn) {
    dateRangeBtn.addEventListener("click", () => {
        const dropdown = document.getElementById("dateRangeDropdown");
        if (dropdown) {
            dropdown.classList.toggle("show");
        } else {
            showDateRangeDropdown();
        }
    });
}

// Tarih aralığı dropdown'unu oluştur
function showDateRangeDropdown() {
    // Mevcut dropdown varsa kaldır
    const existing = document.getElementById("dateRangeDropdown");
    if (existing) existing.remove();

    const dropdown = document.createElement("div");
    dropdown.id = "dateRangeDropdown";
    dropdown.className = "date-range-dropdown show";

    dropdown.innerHTML = `
        <div class="date-range-options">
            <button type="button" class="date-option" data-range="thisMonth">Bu Ay</button>
            <button type="button" class="date-option" data-range="lastMonth">Geçen Ay</button>
            <button type="button" class="date-option" data-range="last7">Son 7 Gün</button>
            <button type="button" class="date-option" data-range="last30">Son 30 Gün</button>
            <button type="button" class="date-option" data-range="all">Tümü</button>
        </div>
        <div class="date-range-custom">
            <label>Özel Aralık:</label>
            <div class="custom-date-row">
                <input type="date" id="customStartDate" value="${_startDate}" />
                <span>-</span>
                <input type="date" id="customEndDate" value="${_endDate}" />
            </div>
            <button type="button" class="btn-apply-date">Uygula</button>
        </div>
    `;

    dateRangeBtn.parentElement.appendChild(dropdown);

    // Option click handlers
    dropdown.querySelectorAll(".date-option").forEach(btn => {
        btn.addEventListener("click", () => {
            const range = btn.dataset.range;
            setDateRange(range);
            dropdown.classList.remove("show");
        });
    });

    // Custom apply button
    dropdown.querySelector(".btn-apply-date").addEventListener("click", () => {
        const customStart = document.getElementById("customStartDate").value;
        const customEnd = document.getElementById("customEndDate").value;
        if (customStart) _startDate = customStart;
        if (customEnd) _endDate = customEnd;
        if (startDateInput) startDateInput.value = _startDate;
        if (endDateInput) endDateInput.value = _endDate;
        updateDateRangeText();
        dropdown.classList.remove("show");
    });

    // Dışarı tıklayınca kapat
    document.addEventListener("click", function closeDropdown(e) {
        if (!dropdown.contains(e.target) && e.target !== dateRangeBtn && !dateRangeBtn.contains(e.target)) {
            dropdown.classList.remove("show");
            document.removeEventListener("click", closeDropdown);
        }
    });
}

// Hazır tarih aralıklarını ayarla
function setDateRange(range) {
    const today = new Date();
    let start, end;

    switch (range) {
        case 'thisMonth':
            start = new Date(today.getFullYear(), today.getMonth(), 1);
            end = new Date(today.getFullYear(), today.getMonth() + 1, 0);
            break;
        case 'lastMonth':
            start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
            end = new Date(today.getFullYear(), today.getMonth(), 0);
            break;
        case 'last7':
            start = new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000);
            end = today;
            break;
        case 'last30':
            start = new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000);
            end = today;
            break;
        case 'all':
            _startDate = '';
            _endDate = '';
            if (startDateInput) startDateInput.value = '';
            if (endDateInput) endDateInput.value = '';
            if (dateRangeText) dateRangeText.textContent = 'Tümü';
            return;
        default:
            return;
    }

    _startDate = formatDateForAPI(start);
    _endDate = formatDateForAPI(end);
    if (startDateInput) startDateInput.value = _startDate;
    if (endDateInput) endDateInput.value = _endDate;
    updateDateRangeText();
}
