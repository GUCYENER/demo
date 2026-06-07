---
plan_id: tema2_slice1_join_path_weighting
created: 2026-06-07
branch: hira
status: implemented_pending_commit
review: plan-eng-review (grounding-first, 2 fork kullanıcı onayı ile kilitlendi)
note: TEMA-2 "cevap doğruluğu" Dilim-1. Grounding planın 112-128 dersini doğruladı — teşhis boşluğu abarttı. 2.1 skorlama ZATEN yazılı (cardinality_analyzer.path_weight + fk_graph_resolver weighted Yen's); tek gerçek boşluk ana SQL-gen yolunun hâlâ BFS join_planner kullanması. Cerrahi + additive + tüm guard'lar korunur.
---

# TEMA-2 Dilim-1 — Ana SQL-gen join-path'i cardinality ile ağırlıklandır

## Karar Özeti (plan-eng-review)
- **Kapsam (kullanıcı seçimi A):** 2.1 önce (cerrahi), 2.3 yorum-clarify ayrı dilim.
- **Mekanizma (kullanıcı seçimi A):** `join_planner`'ı cardinality-ağırlıklandır — resolver'ı bağlama (resolver guard'ları regrese ediyordu).
- **Mutlak kısıt:** çalışan kodu bozma + varsayım yapma. Değişiklik join_planner-içi; call-site'lar ve return shape AYNEN korunur.

## Problem (grounded)
Ana rapor üretimi (`llm_generate_report.generate_report`, frontend FK hint yoksa) join yolunu
`join_planner.find_join_path` ile türetiyor — ama `_shortest_path` **saf BFS (min-hop)**. Hop sayısı
join *doğruluğunu* yansıtmaz: 1-hop bir junction (N:M, fan-out riski) 2-hop iki 1:1 join'den "kısa"
görünür ama yanlış/şişirilmiş sonuç verir. Cardinality sinyali (`path_weight`) ZATEN hesaplı ama
ana yolda KULLANILMIYOR.

```
A → B iki yol:
  Yol-1 (1 hop, junction):  A ──[N:M, path_weight=200]── B            Σ=200
  Yol-2 (2 hop, 1:1+1:1):   A ──[1:1, 50]── X ──[1:1, 50]── B          Σ=100
ESKİ BFS:      Yol-1 (1 hop < 2 hop)   → junction üzerinden, fan-out / yanlış agregasyon
YENİ weighted: Yol-2 (Σ100 < Σ200)     → daha selektif, doğru join   ← 2.1 kazanım
```

## What already exists (yeniden kullan — sıfırdan YOK)
- `db_learning/cardinality_analyzer.analyze_relationships` → `ds_db_relationships.path_weight`
  (1:1=50 / 1:N=100 / N:M junction=200 / self-loop +20), `confidence_score`, `is_junction`. **HESAPLI.**
- `db_smart/join_planner` → scope-filtre + **rejected/düşük-güven FK dışlama** (load_fk_edges WHERE
  `rejected_at IS NULL AND (declared|verified|conf≥0.70)`) + multi-target + bridge-leak diagnostic. **VAR, genişletilecek.**
- `db_learning/fk_graph_resolver` → cardinality-weighted Yen's K-shortest (Query Builder/disambig/wizard-FK-graph). **VAR — DOKUNULMAZ** (paylaşılan; option C "birleştirme" reddedildi).

## Implementation (tek production dosyası: `app/services/db_smart/join_planner.py`)

```
generate_report()  [DEĞİŞMEZ call-site]
   └─ fk_lines boş → find_join_path(load_fk_edges(src), primary, joins, in_scope)
        ├─ load_fk_edges:  WHERE rejected_at IS NULL AND (declared|verified|conf≥0.70)  ← GUARD korunur
        │                  [+YENİ]  SELECT ... , COALESCE(path_weight,100) AS pw         ← cardinality
        │                  Edge: (ft,fc,tt,tc) → (ft,fc,tt,tc, pw)  [5-tuple]
        ├─ _adjacency:     komşuluk artık weight taşır
        ├─ _shortest_path: ESKİ BFS(min-hop) → YENİ Dijkstra(min-Σpw, tie→min-hop, stable)  ← 2.1
        └─ find_join_path: YAPI DEĞİŞMEZ → post-hoc scope check → missing_scope diagnostic  ← GUARD korunur
```

**Adımlar:**
1. `load_fk_edges` SELECT'ine `COALESCE(path_weight,100)` ekle (WHERE **dokunma** — guard aynen). Edge 5-tuple.
2. `_adjacency` weight taşı: `adj[ft].append((tt, fc, tc, w))`.
3. `_shortest_path`: BFS → Dijkstra (`heapq`, anahtar `(Σweight, hop, node)`); min-weight, eşitlikte az-hop, deterministik. Return shape (left,left_col,right,right_col adımları) **aynı**.
4. `Edge` type alias + tip ipuçlarını 5-tuple'a güncelle.

**KARARLAŞTIRILMIŞ tasarım detayı (post-hoc scope, owned):** `_shortest_path` scope-aware DEĞİL,
scope `find_join_path`'te post-hoc kontrol ediliyor (satır 171-174) — bu KASITLI korunuyor: out-of-scope
köprü `missing_scope` diagnostic'i üretir ("şu köprüyü seç"). Scope-aware arama bu değerli diagnostic'i
kaybederdi (sadece `unreachable` derdi). Nadir kenar durum: weighted-min yol out-of-scope köprüden geçer
ama hafif-olmayan in-scope yol vardı → gereksiz "köprü seç" uyarısı. Yanlış join ASLA üretmez (yalnız
kullanıcıdan köprü ister) → kabul edildi, test edilecek.

## Test Coverage Diagram (pure-fn, DB'siz — mevcut desen `tests/db_smart/test_join_planner.py`)
```
[~] app/services/db_smart/join_planner.py
  ├── load_fk_edges()    [→integration] path_weight SELECT — standalone/MagicMock (WSL pytest /mnt/d asılır)
  ├── _adjacency()       [GAP] weight taşıma (5-tuple)                                        ★★
  ├── _shortest_path()   DİJKSTRA yeni branch'ler:
  │     ├── [GAP] weighted: hafif-uzun yol(Σ100) < ağır-junction kısa yol(Σ200) seçilir       ★★★ 2.1 ÇEKİRDEK
  │     ├── [GAP] tie-break: eşit Σweight → az-hop kazanır (determinism, cache-stable)         ★★★
  │     ├── [GAP] COALESCE default: path_weight yok → uniform → BFS-eşdeğer (güvenli degrade)  ★★★
  │     └── [★★ var] unreachable: yol yok → None (korunur)
  └── find_join_path()   yapı değişmez:
        ├── [GAP] scope post-check: weighted yol out-of-scope köprü → missing_scope, ok=False  ★★★ bridge-leak guard
        ├── [★★ var] multi-target: start→[B,C] weighted, dedup joins
        └── [REGRESYON] mevcut 10 test BFS-beklentisi → weighted'e göre güncelle               CRITICAL

HEDEF: 10 güncellenen + 6 yeni = 16 pure-fn test. Koşum: standalone script (memory: reference_test_runner_wsl).
```

**REGRESYON kuralı:** mevcut 10 test min-hop beklentisi taşıyor; weight≡uniform olan senaryolarda
(tek yol / eşit-ağırlık) AYNEN geçmeli, farklı olanlarda beklenti weighted'e güncellenir. Her güncelleme
"neden değişti" yorumu ile.

## Failure Modes
| Codepath | Üretim hatası | Test | Hata yönetimi | Görünür? |
|---|---|---|---|---|
| path_weight NULL (cardinality_analyzer koşmadı) | uniform → BFS-benzeri | ✓ COALESCE | COALESCE(100) | sessiz-GÜVENLİ degrade (doğru) |
| weighted yol out-of-scope köprü | gereksiz "köprü seç" | ✓ scope | missing_scope diagnostic | kullanıcı net uyarı |
| Dijkstra eşit-ağırlık nondeterminism | rasgele yol → cache tutarsız | ✓ tie-break | (hop,node) stable key | yok |
| join_planner exception | join eklenmez | mevcut | try/except llm_gen:712 | LLM hint'siz devam (fail-soft) |
**Kritik açık YOK** — her mod test + handling + görünür/güvenli-degrade.

## Blast radius
`find_join_path` İKİ yerden çağrılır — `llm_generate_report:698` (ana) + `deep_think_service:2557`
(DB-only follow-up). İkisi de AYNI imza + return shape değişmez → **ikisi de iyileşir, ikisi de
API-değişiksiz**. İkisini de smoke-test et (return shape + ok davranışı korundu).

## NOT in scope
- 2.2 synonymy grafiği; 2.3 yorum-clarify (ayrı dilim); 2.4 identifier-case (bu oturum value-case değdi).
- `fk_graph_resolver` birleştirme (option C reddedildi) — iki weighted path-finder DRY-borcu KABUL edildi (path_weight kolonunu cost olarak kullanmak küçük tekrar).
- `fk_graph_resolver`/build_graph değişikliği (paylaşılan: Query Builder/disambig) — DOKUNULMAZ.
- Scope-aware arama (post-hoc check + missing_scope diagnostic kasıtlı korunur).
- Migration / yeni tablo YOK (path_weight zaten var).

## Implementation Tasks
- [x] **T1** — join_planner load_fk_edges: `COALESCE(path_weight,100)` SELECT + Edge opsiyonel-5-tuple. WHERE guard DEĞİŞMEDİ (code-review teyit). pw try/except → _DEFAULT_WEIGHT.
- [x] **T2** — `_shortest_path` BFS→lazy-Dijkstra (heapq key (Σweight,hop,counter), target-on-POP, seen-set). Deterministik tie-break. Uniform-ağırlıkta BFS-özdeş.
- [x] **T3** — `_adjacency` weight taşır (4-tuple adjacency); `Edge`=heterojen tuple, `_DEFAULT_WEIGHT=100`; deque→heapq import.
- [x] **T4** — test_join_planner.py: 10 mevcut DEĞİŞMEDEN geçti + 6 yeni weighted (lighter-over-hops/tie/default-degrade/scope-bridge/determinism/multi-target). **16/16 PASS** (standalone runner).
- [x] **T5** — call-site contract: find_join_path joins[] dict shape değişmedi → llm_generate_report:702 + deep_think:2588 etkilenmez (code-review cross-file teyit + load_fk_edges MagicMock smoke PASS).
- [x] **T6** — canlı DB: source=3 (VYRA_TEST) 12 FK hepsi path_weight=100 (1:N) → o şemada weighting NO-OP (junction/1:1 yok, doğru). Etki junction(200)/1:1(50) içeren kaynakta (ONEDESKPG-tipi) materyalize olur. Kod hazır+degrade-safe.

## İmplementasyon Kaydı
- **Değişen:** `app/services/db_smart/join_planner.py` (+heapq/-deque, _DEFAULT_WEIGHT, load_fk_edges, _adjacency, _shortest_path **scope-aware**, find_join_path scope-içi-önce arama) + `tests/db_smart/test_join_planner.py` (+7 test) + `app/core/config.py` (v3.78.3).
- **🛡️ gstack-adversarial F1 fix (REGRESYON YAKALANDI + DÜZELTİLDİ):** İlk implementasyonda scope yalnız post-filter'dı → Dijkstra global-en-hafif yolu seçince, in-scope direkt join (ağır) yerine daha-hafif out-of-scope köprü seçilip `ok=False` → call-site join enjekte etmez → LLM join'i tahmin eder (feature'ın önlediği halüsinasyon). gstack adversarial subagent yakaladı; /code-review (3 ajan) KAÇIRMIŞTI. **Fix:** `_shortest_path`'e `in_scope` param + `find_join_path` ÖNCE scope-içi en hafif yolu arar, yoksa filtresiz (diagnostic için). In-scope yol varken regresyon olmaz; gerçek köprü-eksikte missing_scope korunur. Eski BFS'teki latent aynı sorunu da kapatır (strictly better).
- **Doğrulama:** py_compile 2/2 · **17/17 test** (10 mevcut + 7 weighted, F1-regresyon + missing-bridge-diagnostic dahil) · load_fk_edges MagicMock · call-site contract korundu · **/code-review medium = 0 bulgu** + **/gstack-review = F1 yakalandı→fix→re-verify** · MOD2 council 6 üye ✅.
- **Bekleyen:** commit (kullanıcı onayı) + backend restart. Migration YOK, FE YOK.

## Sürüm / deploy
- v3.78.3 (TEMA-2 Dilim-1). Backend restart (join_planner). Migration YOK. FE değişiklik YOK.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | Step-0 scope reduction (teşhis abartmış → cerrahi); Arch #1 resolver-wiring regression landmine (bridge-leak + rejected-FK) → join_planner-weighting seçildi; 0 kritik açık |

- **GROUNDING:** 2.1 skorlama zaten mevcut (cardinality_analyzer + fk_graph_resolver); tek boşluk ana-yol BFS. 2.3 clarify altyapısı mevcut (tablo-seviye); yorum-seviye eksik (ayrı dilim).
- **DECISIONS:** (1) kapsam A = 2.1 önce / 2.3 ayrı; (2) mekanizma A = join_planner-weighting (resolver-wiring guard-regression nedeniyle reddedildi).
- **UNRESOLVED:** yok (her iki fork kullanıcı onaylı).
- **VERDICT:** ENG CLEARED → MOD2 council ✅ → **IMPLEMENTED v3.78.3** (16/16 test + code-review 0 bulgu). Kalan: commit (kullanıcı onayı) + backend restart.
