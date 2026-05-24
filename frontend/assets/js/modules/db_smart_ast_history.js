/**
 * VYRA — DB Smart AST History (Faz 3 / P20-B / v3.30.0)
 * =====================================================
 * Undo/redo stack for the DB Smart wizard's AST editor. Pure JS, no DOM,
 * no network, no globals beyond `window.DbSmartAstHistory`.
 *
 * Semantik (spec'ten):
 *   - `push(astAfter, label)` — patch UYGULANDIKTAN SONRA snapshot al.
 *   - İlk seed: editor mount'ta `push(initialAst, "başlangıç")`.
 *   - `undo()` → cursor--, return entries[cursor]  (canUndo: cursor > 0)
 *   - `redo()` → cursor++, return entries[cursor]  (canRedo: cursor < length-1)
 *   - Partial undo'dan sonra push edilirse forward branch kesilir.
 *   - HISTORY_MAX=20; taşınca en eski entry shift edilir, cursor decrement.
 *   - Deep clone: JSON.stringify + JSON.parse (backend AST'i plain JSON).
 *
 * Public API:
 *   window.DbSmartAstHistory = {
 *     push(ast, label), undo(), redo(),
 *     canUndo(), canRedo(),
 *     clear(), length(), cursor()
 *   }
 *
 * Idempotent global: rerun'da overwrite + console.info uyarısı.
 */
(function () {
    'use strict';

    if (window.DbSmartAstHistory) {
        console.info('[DbSmartAstHistory] overwriting previous definition (rerun/hot-reload)');
    }

    const HISTORY_MAX = 20;

    // ---- State ----
    /** @type {Array<{ast: any, label: string, ts: number}>} */
    let entries = [];
    /** @type {number} */
    let cursor = -1;

    // ---- Helpers ----
    function deepClone(value) {
        // Backend AST plain JSON — Date/Map/Set/Function yok varsayımı.
        // Round-trip stringify/parse en hızlı ve test edilebilir yol.
        try {
            return JSON.parse(JSON.stringify(value));
        } catch (e) {
            // FIX5 P3 (TYCHE): silent fail yerine kullanıcıya görünür hata —
            // history corruption sessizce kaybolmasın.
            console.error('[DbSmartAstHistory] deepClone failed:', e);
            try {
                if (window.showToast) {
                    window.showToast('AST geçmiş anlık görüntüsü alınamadı: ' + (e && e.message || 'unknown'), 'error');
                }
            } catch (_) { /* toast missing — console.error zaten yapıldı */ }
            return null;
        }
    }

    function snapshot(index) {
        if (index < 0 || index >= entries.length) return null;
        const entry = entries[index];
        return {
            ast: deepClone(entry.ast),
            label: entry.label,
        };
    }

    // ---- Public methods ----
    function push(ast, label) {
        if (ast === null || ast === undefined) {
            console.warn('[DbSmartAstHistory] push: ast null/undefined, no-op');
            return;
        }
        const cloned = deepClone(ast);
        if (cloned === null && ast !== null) {
            // deepClone başarısız (circular vs); no-op.
            console.warn('[DbSmartAstHistory] push: clone failed, no-op');
            return;
        }
        const entry = {
            ast: cloned,
            label: typeof label === 'string' && label ? label : '(unlabeled)',
            ts: Date.now(),
        };

        // Partial undo sonrası push → forward branch kesilir.
        if (cursor < entries.length - 1) {
            entries = entries.slice(0, cursor + 1);
        }

        entries.push(entry);
        cursor = entries.length - 1;

        // Overflow: en eski entry shift, cursor decrement.
        while (entries.length > HISTORY_MAX) {
            entries.shift();
            cursor -= 1;
            if (cursor < 0) cursor = 0;
        }
    }

    function canUndo() {
        return cursor > 0;
    }

    function canRedo() {
        return cursor >= 0 && cursor < entries.length - 1;
    }

    function undo() {
        if (!canUndo()) return null;
        cursor -= 1;
        return snapshot(cursor);
    }

    function redo() {
        if (!canRedo()) return null;
        cursor += 1;
        return snapshot(cursor);
    }

    function clear() {
        entries = [];
        cursor = -1;
    }

    function length() {
        return entries.length;
    }

    function cursorPos() {
        return cursor;
    }

    // ---- Expose ----
    window.DbSmartAstHistory = {
        push: push,
        undo: undo,
        redo: redo,
        canUndo: canUndo,
        canRedo: canRedo,
        clear: clear,
        length: length,
        cursor: cursorPos,
    };
})();
