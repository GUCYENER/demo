/**
 * VYRA Frontend Build Script (esbuild)
 * =====================================
 * CSS ve JS dosyalarını birleştirip minify eder.
 * 
 * Kullanım:
 *   node build.mjs          → Production build
 *   node build.mjs --watch  → Watch mode (dev)
 */

import * as esbuild from 'esbuild';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const isWatch = process.argv.includes('--watch');

// ===================================================
// CSS Bundle
// ===================================================

const CSS_FILES = [
    'assets/css/global.css',
    'assets/css/home.css',
    'assets/css/toast.css',
    'assets/css/rag_upload.css',
    'assets/css/authorization.css',
    'assets/css/modal.css',
    'assets/css/notification.css',
    'assets/css/ticket-history.css',
    'assets/css/ticket-history-markdown.css',
    'assets/css/dialog-chat.css',
    'assets/css/permissions.css',
    'assets/css/file_guidelines_modal.css',
    'assets/css/modules/maturity_score_modal.css',
    'assets/css/modules/document_enhancer_modal.css',
    'assets/css/modules/rag_image_lightbox.css',
    'assets/css/modules/ldap_settings.css',
    'assets/css/modules/org_permissions.css',
    'assets/css/modules/data_sources.css',
    'assets/css/modules/ds_learning.css',
    'assets/css/modules/ds_enrichment.css',
    'assets/css/modules/theme_catalog.css',
    'assets/css/theme_picker.css',
    'assets/css/modules/feature_permissions.css',  // v3.18.0
    'assets/css/modules/_tooltip.css',              // v3.19.0 — CSS-only tooltip helper
    'assets/css/modules/session_timeout.css',       // v3.28.1 — 30dk session timeout modal
    'assets/css/modules/sample_data_preview.css',   // v3.28.2 G3 — execute öncesi aday tablo sample data kartı
    'assets/css/modules/query_builder.css',         // v3.28.3 G4 — Pre-execute drag-drop query builder
    'assets/css/modules/db_source_selector.css',    // v3.20.0 Faz 1f — DB kaynak chip selector
    'assets/css/modules/agentic_observability.css', // v3.25.0 Faz 6g — pipeline gözlem dashboard
    'assets/css/modules/disambiguation_card.css',   // v3.29.7 G2 — clarification_v2 zengin kart
    'assets/css/modules/query_builder_v2.css',      // v3.29.7 G4 — Multi-table query builder
    'assets/css/modules/agentic_observability_faz6.css', // v3.29.7 G5 — Faz 6 observability sekmeleri
    'assets/css/modules/signal_weight_tuner.css',   // v3.29.8 L3 — multi_signal_rank weight tuner UI
    'assets/css/modules/fk_inference.css',          // v3.29.9 — FK inference observability + deploy banner
    'assets/css/modules/_db_smart_wizard.css',      // v3.30.0 P20 — AST editor chips/list/DnD/modal
    'assets/css/modules/_saved_reports_grid.css',   // v3.33.0 — Akıllı Veri Keşfi saved reports grid + report detail modal
    'assets/css/modules/ui_tooltip.css',            // v3.32.0 — Global modern tooltip utility (data-tt)
    'assets/css/modules/_db_loop.css',              // v3.32.0 G2 — FK Loop progress bar + failure UX
    'assets/css/modules/_learning_cache.css',       // v3.32.0 Ajan-G — Cache hit dashboard widget
];

const JS_FILES = [
    // 0. Config (API URL detection — must be first)
    'assets/js/config.js',

    // 1. Partial Loader (senkron — ayrı kalmalı, bundle'a dahil edilmez)
    // partial_loader.js bundle'dan HARIC tutulur, HTML'de ayrı yüklenir

    // 2. Temel Kütüphaneler
    'assets/js/toast.js',
    'assets/js/modal.js',
    'assets/js/notification.js',
    'assets/js/api_client.js',
    'assets/js/websocket_client.js',

    // 3. Modular Components
    'assets/js/modules/llm_module.js',
    'assets/js/modules/prompt_module.js',
    'assets/js/modules/image_handler.js',
    'assets/js/modules/sidebar_module.js',
    'assets/js/modules/param_tabs.js',
    'assets/js/modules/solution_display.js',
    'assets/js/modules/ml_training.js',
    'assets/js/modules/ticket_chat.js',
    'assets/js/modules/virtual_scroll_table.js', // v3.30.0 Faz 6 — dialog_chat_utils'ten ÖNCE (window.VirtualScrollTable)
    'assets/js/modules/dialog_chat_utils.js',
    'assets/js/modules/dialog_voice.js',
    'assets/js/modules/dialog_images.js',
    'assets/js/modules/dialog_ticket.js',
    'assets/js/modules/db_source_selector.js',  // v3.20.0 Faz 1f — dialog_chat'ten ÖNCE
    'assets/js/modules/sample_data_preview.js', // v3.28.2 G3 — dialog_chat'ten ÖNCE (window.renderSampleDataPreview)
    'assets/js/modules/query_builder.js',       // v3.28.3 G4 — Pre-execute drag-drop builder (window.QueryBuilder)
    'assets/js/modules/disambiguation_card.js', // v3.29.7 G2 — Disambiguation v2 (window.DisambiguationCardV2) — dialog_chat'ten ÖNCE
    'assets/js/modules/query_builder_v2.js',    // v3.29.7 G4 — Multi-table query builder (window.QueryBuilderV2)
    'assets/js/modules/dialog_chat.js',
    'assets/js/modules/permissions_manager.js',
    'assets/js/modules/file_guidelines_modal.js',
    'assets/js/modules/maturity_score_modal.js',
    'assets/js/modules/document_enhancer_modal.js',

    // 4. home_page.js'den ayrıştırılan modüller
    'assets/js/modules/vpn_handler.js',
    'assets/js/modules/rag_cards.js',
    'assets/js/modules/ticket_handler.js',
    'assets/js/modules/solution_formatter.js',

    // 5. Main Scripts — koordinatörler
    'assets/js/system_manager.js',
    'assets/js/home_page.js',
    // ticket_history.js ÖNCE: alt modüller (date_range, formatter vb.)
    // burada tanımlanan değişkenleri kullanır (dateRangeBtn, _historyDebounceTimer vb.)
    'assets/js/ticket_history.js',
    'assets/js/modules/ticket_formatter.js',
    'assets/js/modules/ticket_date_range.js',
    'assets/js/modules/ticket_dialog_render.js',
    'assets/js/modules/ticket_llm_eval.js',
    'assets/js/modules/rag_org_modal.js',
    'assets/js/modules/rag_file_list.js',
    'assets/js/modules/rag_file_org_edit.js',
    'assets/js/rag_upload.js',
    'assets/js/authorization.js',
    'assets/js/org_module.js',
    'assets/js/modules/rag_image_lightbox.js',
    'assets/js/modules/rag_ocr_popup.js',
    'assets/js/modules/ldap_settings.js',
    'assets/js/modules/org_permissions.js',
    'assets/js/modules/widget_module.js',
    'assets/js/modules/company_module.js',
    'assets/js/modules/data_sources_module.js',
    'assets/js/modules/ds_learning_module.js',
    'assets/js/modules/ds_enrichment_module.js',
    'assets/js/modules/theme_catalog_module.js',
    'assets/js/modules/theme_preview_modal.js',
    'assets/js/modules/theme_picker_popup.js',
    'assets/js/modules/feature_permissions_module.js',  // v3.18.0
    'assets/js/modules/agentic_query_consumer.js',      // v3.25.0 Faz 6f — SSE stream consumer
    'assets/js/modules/agentic_observability.js',       // v3.25.0 Faz 6g — admin dashboard
    'assets/js/modules/agentic_observability_faz6.js',  // v3.29.7 G5 — Faz 6 sekmeleri (heatmap/failures/glossary)
    'assets/js/modules/signal_weight_tuner.js',         // v3.29.8 L3 — multi_signal_rank weight tuner
    'assets/js/modules/fk_inference_observability.js',  // v3.29.9 — FK Inference observability sekmesi
    'assets/js/i18n/loader.js',                          // v3.30.0 P34 — i18n loader (VyraI18n) — wizard'dan ÖNCE
    'assets/js/modules/db_smart_ast_history.js',         // v3.30.0 P20 — AST undo/redo stack
    'assets/js/modules/db_smart_filter_modal.js',        // v3.30.0 P20 — Filter spec modal (DbSmartFilterModal.open)
    'assets/js/modules/db_smart_ast_editor.js',          // v3.30.0 P20 — AST editor core (DnD + a11y), Agent A
    'assets/js/modules/db_smart_wizard.js',              // v3.30.0 — Akıllı Veri Keşfi Wizard
    'assets/js/modules/report_detail_modal.js',          // v3.33.0 — Saved report detail modal (ReportDetailModal.open)
    'assets/js/modules/saved_reports_grid.js',           // v3.33.0 — Saved reports kart grid (SavedReportsGrid.mount)
    'assets/js/modules/learning_cache_dashboard.js',     // v3.32.0 Ajan-G — Cache hit dashboard widget
    'assets/js/modules/admin_error_review.js',           // v3.32.0 Ajan-I — Error pattern approval UI
    'assets/js/branding_engine.js',
];

// ===================================================
// Build Functions
// ===================================================

function concatFiles(files, ext) {
    let content = '';
    let missing = [];
    for (const f of files) {
        const fullPath = path.join(__dirname, f);
        if (fs.existsSync(fullPath)) {
            content += `/* === ${f} === */\n`;
            content += fs.readFileSync(fullPath, 'utf-8');
            content += '\n\n';
        } else {
            missing.push(f);
        }
    }
    if (missing.length > 0) {
        console.warn(`⚠️  Eksik ${ext} dosyaları:`, missing);
    }
    return content;
}

async function build() {
    const distDir = path.join(__dirname, 'dist');
    if (!fs.existsSync(distDir)) {
        fs.mkdirSync(distDir, { recursive: true });
    }

    // --- CSS Bundle ---
    const cssContent = concatFiles(CSS_FILES, 'CSS');
    const cssTempPath = path.join(distDir, '_temp_entry.css');
    fs.writeFileSync(cssTempPath, cssContent);

    const cssResult = await esbuild.build({
        entryPoints: [cssTempPath],
        outfile: path.join(distDir, 'bundle.min.css'),
        bundle: false,
        minify: true,
        sourcemap: true,
        logLevel: 'info',
    });

    // Temp dosyayı sil
    fs.unlinkSync(cssTempPath);

    const cssBundleSize = fs.statSync(path.join(distDir, 'bundle.min.css')).size;

    // --- JS Bundle ---
    const jsContent = concatFiles(JS_FILES, 'JS');
    const jsTempPath = path.join(distDir, '_temp_entry.js');
    fs.writeFileSync(jsTempPath, jsContent);

    const jsResult = await esbuild.build({
        entryPoints: [jsTempPath],
        outfile: path.join(distDir, 'bundle.min.js'),
        bundle: false,
        minify: true,
        sourcemap: true,
        target: ['es2020'],
        logLevel: 'info',
    });

    // Temp dosyayı sil
    // fs.unlinkSync(jsTempPath);

    const jsBundleSize = fs.statSync(path.join(distDir, 'bundle.min.js')).size;

    // --- Rapor ---
    const totalSourceCSS = CSS_FILES.reduce((sum, f) => {
        const p = path.join(__dirname, f);
        return sum + (fs.existsSync(p) ? fs.statSync(p).size : 0);
    }, 0);
    const totalSourceJS = JS_FILES.reduce((sum, f) => {
        const p = path.join(__dirname, f);
        return sum + (fs.existsSync(p) ? fs.statSync(p).size : 0);
    }, 0);

    console.log('\n╔══════════════════════════════════════════╗');
    console.log('║       VYRA Frontend Build Report         ║');
    console.log('╠══════════════════════════════════════════╣');
    console.log(`║  CSS: ${(totalSourceCSS / 1024).toFixed(0)}KB → ${(cssBundleSize / 1024).toFixed(0)}KB  (${Math.round((1 - cssBundleSize / totalSourceCSS) * 100)}% küçüldü)  `);
    console.log(`║  JS:  ${(totalSourceJS / 1024).toFixed(0)}KB → ${(jsBundleSize / 1024).toFixed(0)}KB  (${Math.round((1 - jsBundleSize / totalSourceJS) * 100)}% küçüldü)  `);
    console.log(`║  HTTP istekleri: 58 → 3                  ║`);
    console.log('╚══════════════════════════════════════════╝');
}

// ===================================================
// Watch Mode
// ===================================================

if (isWatch) {
    console.log('👀 Watch mode aktif — dosya değişikliklerini izliyorum...');

    const watchDirs = ['assets/css', 'assets/js'];

    // İlk build
    await build();

    // Dosya değişikliklerini izle
    for (const dir of watchDirs) {
        const fullDir = path.join(__dirname, dir);
        fs.watch(fullDir, { recursive: true }, async (eventType, filename) => {
            if (filename && (filename.endsWith('.css') || filename.endsWith('.js'))) {
                console.log(`\n🔄 Değişiklik: ${dir}/${filename}`);
                try {
                    await build();
                } catch (err) {
                    console.error('❌ Build hatası:', err.message);
                }
            }
        });
    }
} else {
    await build();
}
