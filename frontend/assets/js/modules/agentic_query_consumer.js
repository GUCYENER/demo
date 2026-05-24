/**
 * agentic_query_consumer.js — Faz 6+ (Frontend SSE consumer)
 * ----------------------------------------------------------
 * `POST /api/agentic-query/stream` endpoint'ini tüketir.
 *
 * Backend SSE event'leri:
 *   - clarification        { candidates, query, message, reason, confidence }
 *   - cache_hit            { id, similarity, source, intent, sql }
 *   - sample_data_preview  { source_id, schema, table, business_name_tr, columns:[{name,type}], rows:[{}...], row_count, fetched_at, cached } (v3.28.2 G3)
 *   - size_prediction      { bucket, estimated_rows, reason, streaming_recommended, ... }
 *   - columns              { columns: [...] }
 *   - rows                 { rows: [[...]], batch_index }
 *   - end                  { row_count, elapsed_ms, truncated }
 *   - run_summary          { run_id, nodes: [{node,duration_ms,status}], total_ms }
 *   - error                { message }
 *
 * Kullanım:
 *   const aq = window.AgenticQueryConsumer.run({
 *     question: 'kaç müşteri var',
 *     source_id: 12,
 *     mode: 'auto',
 *     on: {
 *       clarification: (data) => {...},
 *       columns: (cols) => {...},
 *       rows: (rows, batchIdx) => {...},
 *       end: (meta) => {...},
 *       run_summary: (s) => {...},
 *       error: (e) => {...},
 *     }
 *   });
 *   aq.abort();  // istek iptal
 */
(function () {
    'use strict';

    const ENDPOINT = '/api/agentic-query/stream';

    /**
     * SSE wire'dan event chunk'larını parse eder.
     * Format: "event: <type>\ndata: <json>\n\n" veya "data: <json>\n\n"
     */
    function parseSseChunk(buffer) {
        const events = [];
        const blocks = buffer.split('\n\n');
        // Son blok eksik olabilir — caller buffer'da bırakacak
        const tail = blocks.pop();
        for (const block of blocks) {
            const lines = block.split('\n');
            let eventType = null;
            const dataLines = [];
            for (const line of lines) {
                if (line.startsWith('event:')) {
                    eventType = line.slice(6).trim();
                } else if (line.startsWith('data:')) {
                    dataLines.push(line.slice(5).trim());
                }
            }
            const dataStr = dataLines.join('\n');
            if (!dataStr) continue;
            try {
                const data = JSON.parse(dataStr);
                // type alanı data içinde de olabilir (clarification)
                const finalType = eventType || data.type || 'message';
                events.push({ type: finalType, data: data.data !== undefined ? data.data : data });
            } catch (_e) {
                // parse hatası — sessizce atla
            }
        }
        return { events, tail };
    }

    /**
     * Tek bir agentic-query/stream çağrısı başlatır.
     * @returns {{ abort: () => void, promise: Promise<void> }}
     */
    function run(opts) {
        const { question, source_id, mode = 'auto', forced_tables, db_dialect, history, on = {} } = opts;
        if (!question || !source_id) {
            const err = new Error('question ve source_id zorunlu');
            on.error && on.error({ message: err.message });
            return { abort: () => {}, promise: Promise.reject(err) };
        }

        const controller = new AbortController();
        const headers = { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' };
        // Auth token (mevcut auth sistemiyle uyumlu)
        const token = (typeof window !== 'undefined' && window.localStorage)
            ? window.localStorage.getItem('access_token')
            : null;
        if (token) headers['Authorization'] = `Bearer ${token}`;

        const body = JSON.stringify({
            question, source_id, mode,
            forced_tables: forced_tables || null,
            db_dialect: db_dialect || 'postgresql',
            history: history || [],
        });

        // raw fetch: SSE streaming (text/event-stream) + AbortController — vyraFetch not applicable.
        const promise = fetch(ENDPOINT, {
            method: 'POST', headers, body, signal: controller.signal,
        }).then(async (res) => {
            if (!res.ok) {
                const txt = await res.text().catch(() => '');
                throw new Error(`HTTP ${res.status}: ${txt.slice(0, 200)}`);
            }
            const ctype = res.headers.get('content-type') || '';
            if (!ctype.includes('text/event-stream')) {
                throw new Error(`Beklenmedik content-type: ${ctype}`);
            }
            const reader = res.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';
            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const { events, tail } = parseSseChunk(buffer);
                buffer = tail;
                for (const evt of events) {
                    _dispatch(evt, on);
                }
            }
            // Buffer'da kalan son fragment
            if (buffer.trim()) {
                const { events } = parseSseChunk(buffer + '\n\n');
                for (const evt of events) _dispatch(evt, on);
            }
        }).catch((err) => {
            if (err.name === 'AbortError') return;
            on.error && on.error({ message: err.message || String(err) });
            throw err;
        });

        return { abort: () => controller.abort(), promise };
    }

    function _dispatch(evt, handlers) {
        const { type, data } = evt;
        switch (type) {
            case 'clarification':
                handlers.clarification && handlers.clarification(data);
                break;
            case 'cache_hit':
                handlers.cache_hit && handlers.cache_hit(data);
                break;
            case 'sample_data_preview':
                // v3.28.2 G3 — execute öncesi cached örnek satırlar
                handlers.sample_data_preview && handlers.sample_data_preview(data);
                break;
            case 'size_prediction':
                handlers.size_prediction && handlers.size_prediction(data);
                break;
            case 'start':
                handlers.start && handlers.start(data);
                break;
            case 'columns':
                handlers.columns && handlers.columns(data.columns || []);
                break;
            case 'rows':
                handlers.rows && handlers.rows(data.rows || [], data.batch_index || 0);
                break;
            case 'end':
                handlers.end && handlers.end(data);
                break;
            case 'run_summary':
                handlers.run_summary && handlers.run_summary(data);
                break;
            case 'error':
                handlers.error && handlers.error(data);
                break;
            default:
                handlers.unknown && handlers.unknown(type, data);
        }
    }

    /**
     * Basit yardımcı: bir <table> elementine satırları progresif yazar.
     * Kullanım:
     *   const writer = AgenticQueryConsumer.tableWriter(document.getElementById('myTbl'));
     *   run({..., on: { columns: writer.setColumns, rows: writer.appendRows, end: writer.done }});
     */
    function tableWriter(tableEl) {
        let cols = [];
        let totalAppended = 0;
        const thead = document.createElement('thead');
        const tbody = document.createElement('tbody');
        tableEl.replaceChildren(thead, tbody);

        return {
            setColumns(columns) {
                cols = columns.slice();
                const tr = document.createElement('tr');
                for (const c of cols) {
                    const th = document.createElement('th');
                    th.textContent = c;
                    tr.appendChild(th);
                }
                thead.replaceChildren(tr);
            },
            appendRows(rows, _batchIdx) {
                const frag = document.createDocumentFragment();
                for (const r of rows) {
                    const tr = document.createElement('tr');
                    // r dict de olabilir, array de
                    const values = Array.isArray(r) ? r : cols.map((c) => r[c]);
                    for (const v of values) {
                        const td = document.createElement('td');
                        td.textContent = v == null ? '' : String(v);
                        tr.appendChild(td);
                    }
                    frag.appendChild(tr);
                }
                tbody.appendChild(frag);
                totalAppended += rows.length;
            },
            done(meta) {
                const tfoot = document.createElement('tfoot');
                const tr = document.createElement('tr');
                const td = document.createElement('td');
                td.colSpan = cols.length || 1;
                td.className = 'agentic-table-foot';
                const truncatedTxt = meta && meta.truncated ? ' (kırpıldı)' : '';
                td.textContent = `Toplam ${meta?.row_count ?? totalAppended} satır, ${meta?.elapsed_ms ?? 0} ms${truncatedTxt}`;
                tr.appendChild(td);
                tfoot.appendChild(tr);
                if (tableEl.tFoot) tableEl.tFoot.remove();
                tableEl.appendChild(tfoot);
            },
        };
    }

    window.AgenticQueryConsumer = { run, tableWriter, parseSseChunk };
})();
