# Agentic SQL Pipeline (LangGraph)

> **Faz 0 — İskelet.** Bu modül henüz runtime'da kullanılmıyor.
> Faz 3'te aktif olacak. Mevcut `DeepThinkService` (3371 satır) korunur; pipeline yan yana çalışıp kademeli geçiş yapacak.

## Mimari Karar

VYRA'nın doğal dil → SQL akışı `LangGraph` state machine olarak yeniden modellenir.

**Neden LangGraph?**
- **Conditional edges:** Ambiguity → clarification → resume akışı temiz ifade edilir.
- **Checkpointing:** PostgresSaver ile state persist olur — clarification beklerken bağlantı koparsa kalınan yerden devam.
- **Self-healing retry:** Validate fail → sql_generate node'una geri dön, error LLM'e geri besle, max 2 retry.
- **Tool-use ready:** Multi-step agent ihtiyacı oluşursa hazır altyapı (örn. user'a sample data göster → karar bekle → sub-query).

**Neden mevcut `DeepThinkService` korunuyor?**
- 3371 satır mevcut iş mantığı + iyi test edilmiş → big-bang refactor riski yüksek.
- Yeni pipeline opt-in feature flag ile kademeli devreye alınır (`USE_AGENTIC_PIPELINE` env / system_settings).

## Klasör Yapısı

```
app/services/pipeline/
├── __init__.py          # Public API (Faz 3'te dolar)
├── README.md            # Bu dosya
├── state.py             # QueryState TypedDict + alt tipler
├── graph.py             # build_query_graph() — state machine kurucu
├── checkpointer.py      # PostgresSaver factory (Faz 3'te eklenecek)
└── nodes/               # Node implementasyonları
    ├── __init__.py
    ├── intent_extract.py
    ├── retrieve.py
    ├── multi_signal_rank.py
    ├── ambiguity_gate.py
    ├── clarification.py
    ├── sql_generate.py
    ├── validate.py
    └── execute.py
```

## Faz Geçiş Planı

| Faz | Bu Modülde Ne Olur |
|-----|---------------------|
| **0** (şu an) | İskelet — `state.py`, `graph.py` stub, `nodes/` boş |
| **1** | Değişmez — Faz 1 sadece RLS+scoping |
| **2** | `nodes/retrieve.py` ön taslak (hybrid search — opsiyonel hazırlık) |
| **3** | **AKTİVASYON** — Tüm node'lar implement edilir, `graph.py` compile edilir, feature flag eklenir |
| **4** | `nodes/sql_generate.py` self-healing retry + few-shot store entegrasyonu |
| **5** | `nodes/sql_generate.py` AST builder entegrasyonu (drag-drop için |
| **6** | `nodes/execute.py` row-chunk SSE streaming |

## Dependencies (Faz 3'te `requirements.txt`'e eklenecek)

```
langgraph>=0.2,<0.3
langgraph-checkpoint-postgres>=2.0
```

## Akış Diyagramı

```
                    ┌─────────────┐
                    │   START     │
                    └──────┬──────┘
                           │
                  ┌────────▼─────────┐
                  │ intent_extract   │
                  └────────┬─────────┘
                           │
                  ┌────────▼─────────┐
                  │ retrieve (RLS)   │
                  └────────┬─────────┘
                           │
                  ┌────────▼─────────┐
                  │ multi_signal_rank│
                  └────────┬─────────┘
                           │
                  ┌────────▼─────────┐
                  │ ambiguity_gate   │
                  └────────┬─────────┘
                  needs_clarify? ──── YES ──┐
                           │                │
                           │ NO             ▼
                           │      ┌─────────────────┐
                           │      │  clarification  │
                           │      │  (interrupt)    │
                           │      └────────┬────────┘
                           │               │
                           │      [user picks via UI]
                           │               │
                           │      ┌────────▼────────┐
                           │      │ resume (state)  │
                           │      └────────┬────────┘
                           │               │
                           ◄───────────────┘
                           │
                  ┌────────▼─────────┐
                  │ sql_generate     │ ◄──┐
                  └────────┬─────────┘    │ self-heal (retry<2)
                           │              │
                  ┌────────▼─────────┐    │
                  │ validate (EXPLAIN)──fail───┘
                  └────────┬─────────┘
                           │ pass
                  ┌────────▼─────────┐
                  │ execute (stream) │
                  └────────┬─────────┘
                           │
                    ┌──────▼──────┐
                    │     END     │
                    └─────────────┘
```

## Test Stratejisi

- **Unit (Faz 3+):** Her node'a izole pytest — fake QueryState girişi, çıkış delta'sı assert.
- **Integration:** Tam graph compile + invoke, mock DB + mock LLM.
- **E2E:** `Test_Senaryolari.md`'deki 7 senaryo gerçek DB üzerinde.
