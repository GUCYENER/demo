# Graphify v1.3 Release Notes

**Sürüm**: graphify-v1.3 (F4 + F5 closure)
**Tarih**: 2026-05-26
**Önceki sürüm**: graphify-v1.2.2 (Wave D — BUG-G2 cross-instance writer serialization)
**Konsey**: HERMES (kod), TYCHE (test), HERA (doc), ZEUS (orchestrator)

**CHANGELOG**:
- v1.3 closes F4 (`GRAPHIFY_HOME` env var) and F5 (token cap `mine: 50 → 500`) — son iki açık spec drift'i kapatır.

---

## Özet

Graphify v1.3, v1.2.2 Wave D'den sonraki ilk feature release'idir ve **F4 + F5** spec drift'lerini birlikte kapatır. F4, `~/.graphify` home dizinini env var ile override edilebilir hâle getirir (CI / multi-user / per-job temp dir senaryoları). F5, `tool_mine` 50-token cap'ini 500'e çıkararak geniş projelerde mine sonuçlarının clip'lenmesini engeller. İkisi de disjoint, küçük ve geri uyumlu değişikliklerdir; toplam 6 yeni test ile 187 → 193 PASS hattına geçilir.

---

## F4 — `GRAPHIFY_HOME` env var

**Sorun**: `Path.home() / ".graphify"` üç farklı callsite'ta hardcoded — `core/cli.py:63`, `mcp/mcp_server.py:56`, `core/embedding.py:57`. CI ortamlarında temp dizine yönlendirme, multi-user makinelerde ayrı home, ya da Windows'ta alternatif disk (`D:\graphify`) kullanımı override mekanizması yokken mümkün değildi.

**Çözüm**: Yeni `core/paths.py` modülü içinde `graphify_home()` helper. Resolution order:

1. `GRAPHIFY_HOME` env var (set ve non-empty ise) — `os.path.expanduser` + `os.path.expandvars` üzerinden genişletilir, ardından `.resolve()` ile absolute hâle gelir.
2. Fallback: `Path.home() / ".graphify"` (önceki davranış aynen korunur).

Helper konfigürasyon dizinini **oluşturmaz** — yalnızca path'i döndürür; `mkdir` sorumluluğu çağıranındadır.

**Etkilenen dosyalar**:

| Dosya | Değişiklik |
|---|---|
| `core/paths.py` | NEW — `graphify_home()` helper (~25 satır) |
| `core/cli.py` | `DEFAULT_CONFIG_DIR = graphify_home()` |
| `mcp/mcp_server.py` | `DEFAULT_CONFIG_DIR = graphify_home()` |
| `core/embedding.py` | `Path("~/.graphify/models").expanduser()` → `graphify_home() / "models"` |

**Smoke test**:

```bash
GRAPHIFY_HOME=/tmp/gx python -m core.cli status
# → DB path /tmp/gx/instances/<slug>.db altına gider; logs ve models dizinleri /tmp/gx altında oluşur.
```

---

## F5 — Token cap `mine: 50 → 500`

**Sorun**: `tool_mine` 50-token cap'i geniş projelerde (633 File + 2102 Function gibi) AdapterReport summary'sini erkenden clip'liyor; sonuç payload'unda `_truncated: true` flag'i set oluyor ve mine sonrası dönen counter/predicate sayıları okunamaz hâle geliyordu.

**Çözüm**: `ontology/core.yml` `token_caps.mine` değeri **50 → 500**. Altyapı zaten yerinde: `mcp/tools.py:_cap_for()` ontology'den okuyor (statik dict değil), v1.2'de bu yol zaten devreye girmişti — sadece sayısal değer bump'lendi.

**Diğer cap'ler korunmuştur** (regresyon yok):

| Tool | Cap |
|---|---|
| `warmup` | 50 |
| `wakeup` | 250 |
| `search` | 250 |
| `mine` | **500** (was 50) |
| `add_decision` | 30 |
| `status` | 30 |
| `traverse` | 200 |

---

## Test outcome

- **6 yeni test** (3 F4 + 3 F5):
  - `tests/test_graphify_home_env.py`: default no-env, env override (tmp_path), env `~/custom` expanduser
  - `tests/test_token_caps_per_tool.py`: `mine` 500 from ontology, unknown tool default, `search` 250 unchanged
- **Suite**: 187 + 6 = **193/193 PASS**, coverage ≥ %74 hattı korunur.

---

## Backwards compatibility

- **F4**: `GRAPHIFY_HOME` boş veya unset ise `Path.home() / ".graphify"` fallback — sıfır migration, mevcut kullanıcılar değişiklik fark etmez.
- **F5**: `mine` cap artışı `_truncated: true` payload'larını "more data" yönünde değiştirir; eski clip'lenen sonuçlar artık tam dönecektir. Davranış değişikliği "more data" tarafında — fonksiyonel regresyon yok, downstream consumer'lar cap'i sınır olarak değil bütçe olarak okumalıdır.

---

## F4-F5 closure — F-series tamamlandı

v1.3 bu iki sürümle birlikte F1-F5 spec drift serisinin son iki açık öğesini kapatır:

- F1 — RESOLVED v1.2 (impl baseline `entities_created/triples_created`)
- F2 — RESOLVED v1.2 (CLI JSON keys `ratio_embedded/ok`)
- F3 — RESOLVED v1.2 (CLI empty project exit 1 vs 2 ayrımı)
- **F4 — RESOLVED v1.3 (`GRAPHIFY_HOME` env var)**
- **F5 — RESOLVED v1.3 (token cap `mine: 500`)**

---

## v1.3 backlog (gelecek sürümler)

Bu sürümde kapsam dışı bırakılan ancak takip edilen aday özellikler:

- **Cross-project search** — multi-project federation (`mcp__graphify__search --all-projects`).
- **Embedding model upgrade** — multilingual-MiniLM → larger model; latency vs recall trade-off.
- **Predicate index** — `imports`, `calls` SQLite index'leri (büyük projelerde query hızlanması).
- **CLI `--json` + `--table` output ayrımı** — CI vs human-readable çıktı.
- **File-lock multi-process serialization** — BUG-G2 Wave E (mevcut process-wide RLock'un üzerine `fcntl` / advisory lock).

---

## Sevkıyat onayı

| Wave | Tarih | Council | Test | Coverage | Status |
|---|---|---|---|---|---|
| v1.2 Wave A (G1-G8) | 2026-05-26 sabah | ZEUS+HERMES+ARIADNE | manual smoke | n/a | done/ |
| v1.2 Wave B (T1-T8) | 2026-05-26 öğle | TYCHE+ARES+HEBE | 181/186 PASS | %74 | done/ (drift F1-F5) |
| v1.2.1 Wave C | 2026-05-26 öğleden sonra | HERMES+TYCHE+HERA | 186/186 PASS | %74 | done/ |
| v1.2.2 Wave D | 2026-05-26 öğleden sonra | TYCHE+HERA+ZEUS (HERMES sub-agent refüze, ZEUS direct-apply) | 187/187 PASS | %74 | done/ |
| **v1.3 F4+F5** | **2026-05-26 akşam** | **HERMES→ZEUS direct+TYCHE+HERA** | **193/193 PASS** | **%74** | **APPLIED** |

**HERA imza**: KAPI-2 PASS (2026-05-26). HERMES sub-agent malware reminder refüze ettiği için ZEUS direct-apply (5 dosya); TYCHE 6 test PASS; suite 193/193 (43.89s); smoke (default + GRAPHIFY_HOME override) doğrulandı. v1.3.0 release-ready.
