---
plan_id: tema2_slice2_metric_ambiguity_clarify
created: 2026-06-07
branch: hira
status: engine_implemented_flag_off_fe_pending
review: plan-eng-review (grounding-first, 2 fork kullanıcı onayı ile kilitlendi)
version_target: v3.79.0
council_mod: 3
hebe_gate_required: true
note: TEMA-2 "cevap doğruluğu" Dilim-2. Grounding planın 112-128 dersini 3. kez doğruladı — teşhis "N aday SQL" diye abartmış; gerçek = agentic serbest-metin yolunda METRİK belirsizliği tespiti (extract_intent_heuristic.agg_func=None sinyali zaten var) + MEVCUT clarify interrupt/resume plumbing'ini yeniden kullan. Wizard rehberli (metrik UI-seçimli) → kapsam dışı.
---

# TEMA-2 Dilim-2 — Agentic serbest-metin: metrik/yorum belirsizliği clarify

## Karar Özeti (plan-eng-review)
- **Kapsam (kullanıcı seçimi A):** Agentic serbest-metin yolu, minimal HEURİSTİK metrik-belirsizlik. Wizard'a DOKUNMA (orada metrik UI-seçimli), LLM-tabanlı enum YOK, N-aday-SQL YOK (tek SQL, metrik seçildikten sonra).
- **Mimari (kullanıcı seçimi A):** YENİ adanmış node'lar (metric_ambiguity_gate + metric_clarification); çalışan TABLO-clarify'a sıfır dokunuş. Interrupt/resume plumbing + /resume endpoint reuse (kind:"metric").
- **Mutlak kısıt:** çalışan kodu bozma + varsayım yapma + mevcut altyapıyı yeniden kullan.

## Problem (grounded)
Kullanıcı agentic serbest-metin sorduğunda ("top 10 müşteri") metrik BELİRSİZ olabilir (ciroya mı,
adede mi, son tarihe mi göre?) ama iki SQL-gen yolu da TEK SQL üretip LLM **sessizce bir yorum seçiyor**
→ kullanıcı yanlış metrikle cevap alabilir, fark etmez. Mevcut clarify yalnız TABLO-seviyesi.

## What already exists (yeniden kullan — sıfırdan YOK)
- `db_smart/custom_metric_parser.extract_intent_heuristic` → `agg_func` (SUM/COUNT/AVG/.../None) + time_window
  + group_hints. **`agg_func is None` = "explicit metrik yok" sinyali HAZIR.**
- `custom_metric_parser.build_metric_schema_context` → seçili tabloların kolon bağlamı (aday-metrik enum için).
- `pipeline/nodes/ambiguity_gate.py` → `top1_dominant` auto-seç deseni (metrik için aynalanacak).
- `pipeline/nodes/clarification.py` + `/api/agentic-query/resume` + SSE interrupt → **interrupt/resume PLUMBING** (generic payload+user_choice; node mapping tablo-spesifik → metrik için ayrı node).
- `pipeline/nodes/disambiguation_card.py` (FE kart) → metrik-kart varyantı için uyarlanır.

## Implementation (pipeline)
```
intent_extract → ... → ambiguity_gate ─(cond)─► clarification(TABLO) ─┐
                            │ (auto) ───────────────────────────────────┤
                                                                         ▼
            [YENİ] metric_ambiguity_gate ─(route_after_metric_amb)─► [YENİ] metric_clarification ─┐
                            │ (auto: metrik net/dominant) ────────────────────────────────────────┤
                                                                                                    ▼
                                                                          sql_generate (chosen_metric inject)
                                                                                → validate → self_heal → execute
```
**Tespit + enum (heuristik, `metric_ambiguity.py` yeni modül):**
```
"top 10 müşteri" → extract_intent_heuristic.agg_func == None  (explicit metrik YOK)
                 + ranking-keyword ("top N"/"en çok"/"en iyi"/"en fazla"/"en az"/"sırala")  ✓
                 + seçili tablolar → aday metrikler (build_metric_schema_context):
                     • SUM(siparis.tutar)  "ciroya göre"
                     • COUNT(siparis.*)     "sipariş adedine göre"
                     • MAX(siparis.tarih)   "son sipariş tarihine göre"
                 → ≥2 DİSTİNKT aday → BELİRSİZ → metric_clarification (interrupt + kind:"metric" kart)
                 → 1 aday / dominant → auto-pick → sql_generate

"toplam ciro en çok müşteri" → agg_func=SUM (explicit)     → NET → auto
"müşterileri listele"        → ranking-keyword YOK          → NET → auto
```
**Adımlar:**
1. `metric_ambiguity.py` (yeni): `detect_metric_ambiguity(nl, schema_ctx) → {ambiguous, candidates:[{label_tr,agg_func,expr,table}], reason}`. ranking-regex + agg_func=None + enum (numeric→SUM/AVG, child-fact-rowcount→COUNT, date→MAX-recency).
2. `metric_ambiguity_gate_node` (yeni): detect → `metric_needs_clarification` + `metric_candidates` state'e.
3. `metric_clarification_node` (yeni): pre-interrupt payload (kind:"metric", candidates) + post-resume `user_choice → chosen_metric`.
4. `graph.py`: 2 node + `route_after_metric_ambiguity` conditional, table-clarify SONRASI / sql_generate ÖNCESİ.
5. `sql_generate.py`: `chosen_metric` set'liyse LLM context'ine enjekte (ADDITIVE — yoksa mevcut davranış).
6. `agentic_query_api.py`: SSE payload'a `kind` passthrough (FE doğru kartı çizsin).
7. **FE:** metrik-kart varyantı (disambiguation_card uyarlaması: label_tr + agg expr + opsiyonel önizleme). **HEBE gate** (kart a11y/marka/toast).

**KARARLAŞTIRILMIŞ (false-positive mitigasyonu, owned):** clarify YALNIZ (a) ranking-intent + (b) agg_func=None
+ (c) ≥2 DİSTİNKT aday metrik iken. Tek aday / belirgin-dominant → auto (kullanıcıyı gereksiz soruyla yorma).

## Test Coverage Diagram
```
[+] metric_ambiguity.py  (pure-fn, DB'siz — join_planner deseni)
  └── detect_metric_ambiguity()
      ├── [GAP] ranking + agg_func=None + ≥2 aday → ambiguous=True + candidates    ★★★ ÇEKİRDEK
      ├── [GAP] explicit metrik ("toplam ciro") → agg_func=SUM → ambiguous=False    ★★★
      ├── [GAP] ranking-keyword YOK → ambiguous=False                               ★★★
      ├── [GAP] 1 aday → auto (ambiguous=False)                                      ★★
      ├── [GAP] enum: numeric→SUM, date→MAX-recency, child→COUNT                     ★★★
      └── [GAP] TR ranking keyword'leri (en çok/iyi/fazla/az/top N/sırala)           ★★
[+] metric_ambiguity_gate_node / metric_clarification_node  (state, MagicMock)
      ├── [GAP] gate: ambiguous → metric_needs_clarification + candidates            ★★
      ├── [GAP] clarification pre-interrupt payload kind="metric"                    ★★
      └── [GAP] post-resume user_choice → chosen_metric                              ★★★
[+] graph routing
      └── [GAP] route_after_metric_ambiguity: clarify vs auto                        ★★
[+] sql_generate.py
      └── [GAP] chosen_metric inject (varsa context'e; yoksa mevcut — REGRESYON yok) ★★★ [→regresyon]
[+] FE metrik-kart [→E2E]
      └── [GAP] kart render + seç → resume → SQL                                     ★★ (gstack qa)
[+] LLM context değişikliği [→EVAL]
      └── [GAP] chosen_metric prompt'a girince SQL doğru agregasyon kullanıyor mu

HEDEF: ~14 unit (detect/enum/node/route/sql-inject) + 1 E2E (gstack) + 1 eval (prompt).
Koşum: standalone runner (WSL pytest /mnt/d asılır — memory).
```

## Failure Modes
| Codepath | Üretim hatası | Test | Handling | Görünür? |
|---|---|---|---|---|
| detect_metric_ambiguity şema-hatası | clarify atlanır | ✓ | try/except fail-soft → ambiguous=False (mevcut tek-SQL akışı) | sessiz-güvenli |
| metric_clarification resume'da chosen_metric boş | yanlış metrik | ✓ | auto-pick top aday (ambiguity_gate top1 deseni) | net (seçili metrik kartta) |
| false-positive (gereksiz clarify) | kullanıcı yorulur | ✓ | ≥2-distinkt + dominant-auto guard | clarify kartı |
| sql_generate chosen_metric yok | — | ✓ | additive: yoksa mevcut davranış (regresyon yok) | — |
**Kritik açık:** FE metrik-kart render hatası → HEBE gate + fallback (auto top-aday) ile kapatılacak (impl'de).

## NOT in scope
- **Wizard yolu clarify** (rehberli; metrik UI-seçimli) — ayrı dilim olursa.
- LLM-tabanlı belirsizlik/aday üretimi (bu dilim heuristik).
- N-aday-SQL üretimi (aday METRİK sunulur; SQL metrik seçildikten sonra TEK üretilir).
- Yeni tablo/migration (dedektör stateless; adaylar mevcut şemadan). **ARES+METIS:** yeni tablo YOK.

## Blast radius
Yeni node'lar table-clarify'a DOKUNMAZ (concern ayrımı). Değişen mevcut: `graph.py` (routing — additive edge),
`sql_generate.py` (chosen_metric additive), `agentic_query_api.py` (kind passthrough). Agentic-only — wizard/
deep_think etkilenmez. Risk: graph routing + sql_generate regresyonu → test + E2E gate.

## Implementation Tasks
- [ ] **T1 (METIS+ORACLE)** — `metric_ambiguity.py`: detect + heuristik enum (ranking-regex + agg_func=None + build_metric_schema_context reuse). Unit ★★★.
- [ ] **T2 (METIS)** — `metric_ambiguity_gate_node` + `metric_clarification_node` (interrupt/resume, chosen_metric map).
- [ ] **T3 (HERMES+METIS)** — `graph.py` 2 node + route_after_metric_ambiguity (table-clarify sonrası).
- [ ] **T4 (ORACLE)** — `sql_generate.py` chosen_metric inject (additive) + [→EVAL] prompt.
- [ ] **T5 (HERMES)** — `agentic_query_api.py` SSE kind passthrough + /resume metrik-resume.
- [ ] **T6 (ATHENA+HEBE)** — FE metrik-kart varyantı + HEBE a11y/marka gate.
- [ ] **T7 (TYCHE)** — ~14 unit + standalone runner + gstack E2E (metrik-belirsiz soru → kart → seç → SQL).

## Sürüm / deploy
- v3.79.0 (TEMA-2 Dilim-2, agentic). Backend restart + FE bundle rebuild. Migration YOK.

## İmplementasyon Kaydı (2026-06-07)
**Backend ENGINE yapıldı + test + adversarial-review; feature FLAG ile DORMANT (FE pending).**
- **Yeni:** `metric_ambiguity.py` (detect + enum), `metric_ambiguity_gate.py` (+`METRIC_CLARIFY_ENABLED=False` flag), `metric_clarification.py`. **Değişen (additive):** `graph.py` (run_pipeline metrik gate + interrupt[flag-gated] + resume_pipeline kind-routing + make_graph wiring), `sql_generate.py` (chosen_metric inject), `sse_adapter.py` (kind:metric kartı), `agentic_query_api.py` (AgenticResumeIn chosen_metric/metric_index + user_choice builder).
- **Dedektör adversarial-fix:** #4 ASCII ranking ("en cok"), #5 recency ("en son" → soru sorma), #6 hep-COUNT → tablo sorusu (soru sorma).
- **Doğrulama:** py_compile 7/7 · **19/19 unit test** · graph import-smoke · sse metrik-branch · 2 adversarial ajan: **REGRESYON YOK** (table-clarify/auto/resume/force birebir korunmuş, empirik) + feature uçtan-uca eksik bulundu → FE wiring şart.
- **🚩 FLAG OFF (çalışanı sakın bozma):** `METRIC_CLARIFY_ENABLED=False` → run_pipeline metrik INTERRUPT ETMEZ → sql_generate'e düşer = MEVCUT davranış (LLM metrik seçer). Engine wired+test'li ama DORMANT, sıfır UX riski.
- **BEKLEYEN (T6, flag-on ön-şartı):** FE metrik-kart — FE table-clarify `_sendDbMessageWithHint` (re-send) kullanıyor, `/resume` değil; metrik için re-send + run-path chosen_metric threading + metrik-kart render (HEBE gate) gerekir. Çalışan FE clarification handler'ını riske atmamak için ayrı/dikkatli oturumda. Flag-on + FE doğrulanınca v3.79.0.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | Step-0: teşhis "N-aday-SQL" abartmış → gerçek=metrik-tespit (agg_func=None sinyali + clarify-infra mevcut); Arch #1: yeni-node vs gate-genişlet → yeni-node (table-clarify regresyonu önlenir); 0 kritik açık |

- **GROUNDING:** metrik-ayrıştırma (extract_intent_heuristic) + clarify-infra (interrupt/resume/card) mevcut; gerçek boşluk = agentic serbest-metin metrik-belirsizlik TESPİTİ. Wizard rehberli → kapsam dışı.
- **DECISIONS:** (1) kapsam A = agentic minimal-heuristik (wizard/LLM-enum/N-SQL dışı); (2) mimari A = yeni adanmış metric node'ları (plumbing reuse, table-clarify'a dokunma).
- **UNRESOLVED:** yok (iki fork kullanıcı onaylı).
- **VERDICT:** ENG CLEARED — MOD3 council (HEBE gate dahil) + HERA plan onayı sonrası implement. Sıra: T1→T2→T3→T4 (unit gate) → T5/T6 → T7 (E2E+eval) → gstack-review → v3.79.0.
