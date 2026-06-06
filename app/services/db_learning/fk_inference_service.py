"""v3.29.9 — FK Inference Service (dialect-agnostic core).

Inference layer for databases that do NOT declare FK constraints at the DB
level (common with ORM/app-layer enforcement, e.g. OnedeskTest with 2138
tables and only 29 declared FKs).

Pipeline:
    1. Load discovered tables/columns from ds_db_objects.
    2. For each non-PK column matching naming pattern (`*_id`, `*Id`, `id_*`,
       `f_*_id`), parse a "root" → candidate target table name(s).
    3. Validate type compatibility (INT↔INT/BIGINT, UUID↔UUID, ...).
    4. (Optional) Sample-validate: query LEFT JOIN coverage on a bounded
       sample to confirm referential plausibility.
    5. Score: 0.6 naming + 0.2 type + up to 0.2 sample coverage.
    6. UPSERT into ds_db_relationships with is_inferred=TRUE,
       admin_verified=FALSE.

Public API:
    - infer_fks_for_source(cur, source_id, *, sample_validate, sample_rows,
        min_confidence, dialect) -> Dict[str, Any]

RLS: caller must apply company scope BEFORE invoking.
SECURITY: Identifiers used in sample validation SQL are guarded by
`is_safe_identifier` from `fk_inference_dialects`; non-conforming names
cause that candidate to be skipped (logged at INFO).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from app.services.db_learning.fk_inference_dialects import (
    FKInferenceDialect,
    get_dialect,
    is_safe_identifier,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Scoring weights
# ─────────────────────────────────────────────────────────────
SCORE_NAMING = 0.60       # full-root tablo eşleşmesi (user_id → users)
SCORE_NAMING_HEAD = 0.45  # v3.60.0: head-noun (rol-önekli) eşleşme (CreateUserId → user) — daha spekülatif,
                          # tek başına min_confidence(0.60) altında kalır → ancak tip uyumuyla (0.45+0.20=0.65) persist
SCORE_TYPE = 0.20
SCORE_SAMPLE_MAX = 0.20  # multiplied by coverage_ratio

DEFAULT_MIN_CONFIDENCE = 0.60   # below this we skip persisting
DEFAULT_SAMPLE_ROWS = 200
DEFAULT_PK_COL_NAMES = ("id", "pk", "uuid")
# v3.73.0: kolon-kökü prefix-soyma eşleşmesinde (NCUSTOMER→customer) bir hedef-token'ın
# kabul edilmesi için min uzunluk — kısa parça false-positive'lerini keser (node↛ode).
MIN_SUFFIX_TOKEN_LEN = 4

# v3.75.0: Framework/audit "satır-kimliği" kolonları — kurumsal şemalarda (ör. MS Dynamics
# RecId sınıfı) HER tabloda bulunur, gerçek FK DEĞİLdir (merkezi bir hedef tabloya işaret
# etmez). FK adayı sayılmaz + tanılama-uyarısı üretmez (ONEDESKPG: GCRecId tek başına 93
# sahte uyarı). Lowercased exact-match; gerekirse genişletilebilir.
# v3.77.x: guid/parentguid — MSSQL→PG kaynaklarda (ONEDESKPG) yaygın surrogate UID kolonları.
# "guid" → ID-soneki soyulunca kök="gu" üretiyor → "gu"/"gus" tablosu yok → her tabloda
# no_target_table. Kanıt (canlı log): GUID 588 + PARENTGUID 166 = 754 sahte uyarı (%27), 0
# çözülen FK. Kimlik kolonu, FK değil → adaylıktan muaf. (Hiyerarşik PARENTGUID→GUID self-ref
# gerekirse admin Tanılama ekranından elle kurar.)
NON_FK_COLUMN_NAMES = frozenset({"gcrecid", "recid", "guid", "parentguid"})

# v3.75.0: Self-reference kökleri — kolon kökü bunlardan biriyse ve adlı bir hedef tablo
# bulunamazsa hedef = kolonun KENDİ tablosu (org-chart/hiyerarşi: parent_id → own PK).
_SELF_REF_ROOTS = frozenset({"parent"})

# v3.76.0 (G4a): Sample-validation'lı FUZZY hedef eşleşme. İsim-tier'ları (exact/plural/
# entity-token/prefix/head/self) BOŞ dönünce, root/head ile HERHANGİ bir token'ı paylaşan
# tablolar aday yapılır ve YALNIZ sample coverage ile doğrulanırsa persist edilir → genel
# (her müşteri/dialect), hardcoded-abbreviation YOK, false-positive YOK (sample gate).
SCORE_NAMING_FUZZY = 0.30   # spekülatif → tek başına min_confidence altında; type+sample ile geçer
FUZZY_MIN_COVERAGE = 0.50   # fuzzy persist için min sample kapsama (FK değerleri hedef PK'da var mı)
MIN_FUZZY_TOKEN_LEN = 4     # kısa token (id/no) fuzzy gürültüsünü keser
_MAX_FUZZY_TARGETS_PER_COL = 8  # kolon başına sample-validate edilecek aday tavanı (perf-güvenli)


# ─────────────────────────────────────────────────────────────
# Naming pattern parser
# ─────────────────────────────────────────────────────────────
# Patterns (case-insensitive, applied to normalized ident):
#   suffix _id        → user_id     → root='user'
#   suffix _ref       → owner_ref   → root='owner' (cardinality hint)
#   suffix Id         → userId      → root='user' (CamelCase)
#   prefix id_        → id_user     → root='user'
#   f_<root>_id       → f_user_id   → root='user'  (Hungarian)
# v3.60.0: Unicode (re.UNICODE) → Türkçe kolon adları (müşteri_id, sipariş_ref) yakalanır.
# [^\W\d_] = bir Unicode HARF (ç/ğ/ı/ö/ş/ü dahil); \w = harf/rakam/_ (Unicode). Eski [a-z] Türkçe'yi atıyordu.
_NAMING_RES = [
    re.compile(r"^f_(?P<root>[^\W\d_][\w]*?)_id$", re.UNICODE),
    re.compile(r"^id_(?P<root>[^\W\d_][\w]*)$", re.UNICODE),
    re.compile(r"^(?P<root>[^\W\d_][\w]*?)_id$", re.UNICODE),
    re.compile(r"^(?P<root>[^\W\d_][\w]*?)_ref$", re.UNICODE),
]
# CamelCase / ayraçsız ID — ORIJİNAL ad üzerinde (normalize ÖNCESİ). v3.60.0: [Ii][Dd] → Id/ID/iD/id
# (eski yalnız 'Id'; ALL-CAPS PARTYID + ayraçsız userid kaçıyordu). Unicode → MüşteriId yakalanır.
# [^\W\d_] = Unicode harf, [\w] underscore içerir ama '_id' zaten _NAMING_RES'te (bu AYRAÇSIZ son-ek içindir).
_CAMEL_ID_RE = re.compile(r"^(?P<root>[^\W\d_][^\W_]*?)[Ii][Dd]$", re.UNICODE)

# v3.60.0: CamelCase/PascalCase sınırı (büyük harf öncesi) — Türkçe büyükler dahil.
# Head-noun (son anlamlı entity token) çıkarımı için: 'CreateUser'→['Create','User'], son='User'.
_CAMEL_SPLIT_RE = re.compile(r"(?<=.)(?=[A-ZÇĞİÖŞÜ])", re.UNICODE)
# FK son-ekini ORİJİNAL adtan at (camel 'Id' / snake '_id' / caps 'ID' / 'ref'/'fk'); Unicode.
_FK_SUFFIX_STRIP_RE = re.compile(r"(?:[_\s]?(?:[Ii][Dd]|[Rr][Ee][Ff]|[Ff][Kk]))$", re.UNICODE)


def _head_noun_from_name(col_name: str) -> Optional[str]:
    """v3.60.0: rol-önekli/bileşik FK kolonundan HEAD-NOUN (gerçek hedef entity) çıkar.

    'CreateUserId'→'user', 'PADCompanyId'→'company', 'create_user_id'→'user',
    'ParentPartyId'→'party', 'MüşteriId'→'müşteri'. Hedef tablo genelde son anlamlı token'dır
    (önek = rol/sıfat: Create/Modify/Parent/PAD...). Döndürülen lower; PK adıysa None.
    """
    raw = (col_name or "").strip()
    if not raw:
        return None
    stem = _FK_SUFFIX_STRIP_RE.sub("", raw).strip(" _-./")
    if not stem:
        return None
    pieces = [p for p in re.split(r"[\s_\-./]+", stem) if p]
    if not pieces:
        return None
    last_piece = pieces[-1]
    # All-caps (PARTYID) veya all-lower (party): camelCase sınırı yok → bütün parça.
    # Yalnız KARIŞIK kasa (PADCompany, CreateUser) camelCase-bölünür → son entity ('Company','User').
    # Aksi halde 'PARTY' → P|A|R|T|Y → 'y' gibi yanlış token üretirdi.
    if last_piece.upper() == last_piece or last_piece.lower() == last_piece:
        tok = last_piece.lower()
    else:
        camel = [w for w in _CAMEL_SPLIT_RE.split(last_piece) if w]
        tok = (camel[-1] if camel else last_piece).lower()
    if not tok or tok in DEFAULT_PK_COL_NAMES:
        return None
    return tok

# v3.60.0: tanılama amaçlı — kolon adı bir referans/FK'ya benziyor mu (kalıba uymasa bile)?
# 'PARTYID'/'OWNERREF' gibi adları Hata İzleme'de yüzeye çıkarmak için (kök neden).
# v3.75.0: 'code'/'key'/'no' çıkarıldı — Code/ApiKey/ConsumerKey/MethodNo gibi DEĞER kolonları
# "FK-benzeri" sayılıp 154 sahte 'no_pattern_match' uyarısı üretiyordu. Gerçek by-code FK tespiti
# ayrı bir tier (faz-2) işidir; tanılama yalnız gerçek FK son-eklerinde (_id/Id/_ref/fk).
_REF_ISH_SUFFIXES = ("id", "ref", "fk")


def _looks_reference_ish(col_name: str) -> bool:
    low = (col_name or "").strip().lower()
    if not low or low in DEFAULT_PK_COL_NAMES:
        return False
    return low.endswith(_REF_ISH_SUFFIXES)


def _extract_root(col_name: str) -> Optional[str]:
    """Extract candidate target-table root from FK column name.

    Returns the root (lowercase) on success; None if no pattern matches or
    the column is a PK column itself (e.g. just `id` or `pk`).
    """
    if not col_name:
        return None
    raw = col_name.strip()
    if not raw:
        return None

    # PK column itself — skip.
    low = raw.lower()
    if low in DEFAULT_PK_COL_NAMES:
        return None

    # Try CamelCase first on original casing.
    cm = _CAMEL_ID_RE.match(raw)
    if cm:
        root = cm.group("root")
        if root and root.lower() not in DEFAULT_PK_COL_NAMES:
            return root.lower()

    # Then snake_case / prefix patterns on lowercased.
    for rx in _NAMING_RES:
        m = rx.match(low)
        if m:
            root = m.group("root")
            if root and root not in DEFAULT_PK_COL_NAMES:
                return root
    return None


# ─────────────────────────────────────────────────────────────
# Singular/plural normalization
# ─────────────────────────────────────────────────────────────
def _candidates_from_root(root: str) -> List[str]:
    """Produce plausible target table names from a root.

    e.g. root='user' → ['user', 'users']
         root='party' → ['party', 'parties']
         root='category' → ['category', 'categories']
    """
    if not root:
        return []
    out = [root]
    # naive plural rules
    if root.endswith("y") and len(root) > 1 and root[-2] not in "aeiou":
        out.append(root[:-1] + "ies")
    elif root.endswith(("s", "x", "z", "ch", "sh")):
        out.append(root + "es")
    else:
        out.append(root + "s")
    # also single-trim if root already plural (best-effort)
    if root.endswith("s") and len(root) > 1:
        out.append(root[:-1])
    # dedupe preserving order
    seen: Set[str] = set()
    uniq: List[str] = []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


# ─────────────────────────────────────────────────────────────
# Type compatibility
# ─────────────────────────────────────────────────────────────
def _type_compatible(t_from: str, t_to: str, dialect: FKInferenceDialect) -> bool:
    """Compare normalized type categories."""
    nf = dialect.normalize_type(t_from or "")
    nt = dialect.normalize_type(t_to or "")
    if nf == "other" or nt == "other":
        return False
    return nf == nt


# ─────────────────────────────────────────────────────────────
# Schema loader
# ─────────────────────────────────────────────────────────────
@dataclass
class _TableInfo:
    schema: str
    name: str
    norm_name: str        # dialect-normalized for matching
    columns: List[Dict[str, Any]] = field(default_factory=list)
    pk_columns: List[str] = field(default_factory=list)


def _load_schema(
    cur,
    source_id: int,
    dialect: FKInferenceDialect,
) -> Dict[Tuple[str, str], _TableInfo]:
    """Read ds_db_objects → dict keyed by (norm_schema, norm_name)."""
    cur.execute(
        """
        SELECT schema_name, object_name, object_type, columns_json
          FROM ds_db_objects
         WHERE source_id = %s
           AND object_type IN ('table','TABLE','view','VIEW')
        """,
        (source_id,),
    )
    rows = cur.fetchall()
    out: Dict[Tuple[str, str], _TableInfo] = {}
    for r in rows:
        # support both tuple and dict row factories
        if isinstance(r, dict):
            schema = r["schema_name"]
            name = r["object_name"]
            cols_raw = r["columns_json"]
        else:
            schema, name, _otype, cols_raw = r[0], r[1], r[2], r[3]
        try:
            cols = cols_raw if isinstance(cols_raw, list) else json.loads(cols_raw or "[]")
        except Exception:
            cols = []
        pk_cols: List[str] = []
        for c in cols:
            # v3.56.0 KÖK fix: detect_objects columns_json'a `is_pk` yazıyor (ds_learning_service);
            # burada `is_primary_key` okunuyordu → pk_cols HEP BOŞ → inference hedef PK'yı 'id'ye
            # düşürüp XxxId PK'lı şemalarda candidate üretemiyordu. is_pk öncelik + eski key fallback.
            if isinstance(c, dict) and (c.get("is_pk") or c.get("is_primary_key")):
                pk_cols.append(c.get("name", ""))
        ns = dialect.normalize_ident(schema)
        nn = dialect.normalize_ident(name)
        out[(ns, nn)] = _TableInfo(
            schema=schema,
            name=name,
            norm_name=nn,
            columns=cols,
            pk_columns=pk_cols,
        )
    return out


def _load_existing_relationships(
    cur,
    source_id: int,
    dialect: FKInferenceDialect,
) -> Set[Tuple[str, str, str, str, str, str]]:
    """Active (not rejected) rels — used to skip duplicates."""
    cur.execute(
        """
        SELECT from_schema, from_table, from_column,
               to_schema, to_table, to_column
          FROM ds_db_relationships
         WHERE source_id = %s
           AND (rejected_at IS NULL)
        """,
        (source_id,),
    )
    out: Set[Tuple[str, str, str, str, str, str]] = set()
    for r in cur.fetchall():
        if isinstance(r, dict):
            key = (
                dialect.normalize_ident(r["from_schema"] or ""),
                dialect.normalize_ident(r["from_table"] or ""),
                dialect.normalize_ident(r["from_column"] or ""),
                dialect.normalize_ident(r["to_schema"] or ""),
                dialect.normalize_ident(r["to_table"] or ""),
                dialect.normalize_ident(r["to_column"] or ""),
            )
        else:
            key = (
                dialect.normalize_ident(r[0] or ""),
                dialect.normalize_ident(r[1] or ""),
                dialect.normalize_ident(r[2] or ""),
                dialect.normalize_ident(r[3] or ""),
                dialect.normalize_ident(r[4] or ""),
                dialect.normalize_ident(r[5] or ""),
            )
        out.add(key)
    return out


# ─────────────────────────────────────────────────────────────
# Sample validation
# ─────────────────────────────────────────────────────────────
def _validate_sample(
    cur,
    from_schema: str,
    from_table: str,
    from_column: str,
    to_schema: str,
    to_table: str,
    to_column: str,
    sample_rows: int,
    dialect: FKInferenceDialect,
) -> Optional[Dict[str, Any]]:
    """Run dialect-built coverage probe. Returns dict or None on error/skip.

    Caller must wrap this with try/except — sample validation MUST NOT
    block FK inference; failures are logged and the candidate falls back
    to naming+type only.
    """
    for ident in (from_schema, from_table, from_column, to_schema, to_table, to_column):
        if not is_safe_identifier(ident):
            logger.info(
                "[fk_inference] unsafe ident, skipping sample validation: %r",
                ident,
            )
            return None
    sql, params = dialect.build_sample_validate_sql(
        from_schema, from_table, from_column,
        to_schema, to_table, to_column,
        sample_rows,
    )
    try:
        cur.execute(sql, params)
        row = cur.fetchone()
    except Exception as e:
        logger.info(
            "[fk_inference] sample validate failed %s.%s.%s→%s.%s.%s: %s",
            from_schema, from_table, from_column, to_schema, to_table, to_column,
            str(e)[:200],
        )
        return None
    if not row:
        return None
    if isinstance(row, dict):
        distinct_from = int(row.get("distinct_from", 0) or 0)
        covered = int(row.get("covered", 0) or 0)
    else:
        distinct_from = int(row[0] or 0)
        covered = int(row[1] or 0)
    # v3.76.1 (code-review P2): coverage = DISTINCT eşleşen kaynak-değer / DISTINCT kaynak-değer
    # (dialect SQL'i COUNT(DISTINCT)'e geçti → hedef anahtar non-unique olsa da fan-out şişirmez).
    # min(...,1.0) ek defansif tavan: ratio matematiksel olarak ∈[0,1] ama gelecekteki SQL
    # regresyonu skoru spekülatif şişirmesin (fuzzy'nin TEK false-positive kapısı coverage).
    ratio = min(covered / distinct_from, 1.0) if distinct_from > 0 else 0.0
    return {
        "distinct_from": distinct_from,
        "covered": covered,
        "coverage_ratio": round(ratio, 4),
        "sample_size": sample_rows,
    }


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────
@dataclass
class _Candidate:
    from_schema: str
    from_table: str
    from_column: str
    from_type: str
    to_schema: str
    to_table: str
    to_column: str
    to_type: str
    naming_pattern: str   # the regex pattern that matched
    root: str
    confidence: float
    evidence: Dict[str, Any]
    method: str           # 'naming' | 'naming+type' | 'naming+type+sample'


def _column_dict(t: _TableInfo, name_lower: str, dialect: FKInferenceDialect) -> Optional[Dict[str, Any]]:
    for c in t.columns:
        if isinstance(c, dict) and dialect.normalize_ident(c.get("name", "")) == name_lower:
            return c
    return None


def _resolve_target_pk(
    target_tbl: _TableInfo,
    from_col_name: str,
    root: str,
    match_kind: str,
    dialect: FKInferenceDialect,
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """v3.76.0: hedef tablonun PK kolonunu ESNEK çöz (naming + fuzzy ortak — kod tekrarı yok).
    Sıra: declared PK > FK-col-adı (self hariç) > entity-token > root > id/pk/uuid. İlk VAR OLAN
    kolon (target.columns'ta). Tip-uyumu downstream. Döner: (target_col_dict | None, denenen_pk_listesi).
    """
    _ttoks = [x for x in str(target_tbl.norm_name).split("_") if x]
    ent_tok = _ttoks[-1] if _ttoks else str(target_tbl.norm_name)
    pk_name_cands: List[str] = [pc for pc in target_tbl.pk_columns if pc]
    # self-ref'te FK kolonunu (ParentId) hedef PK adayı YAPMA → kolonun kendine işaret ettiği
    # geçersiz döngüyü önle (child→parent aynı-ad deseni yalnız FARKLI tabloda geçerli).
    if match_kind != "self":
        pk_name_cands.append(from_col_name)
    if ent_tok:
        pk_name_cands += [f"{ent_tok}_id", f"{ent_tok}id", ent_tok]
    if root:
        pk_name_cands += [f"{root}_id", f"{root}id"]
    pk_name_cands += ["id", "pk", "uuid"]
    # v3.76.1 (code-review P2 + altitude): self-ref'te hedef PK = FK kolonunun KENDİSİ olamaz
    # (parent_id→parent_id geçersiz döngü, sample bile gerekmeden ~0.80 persist). from_col yukarıda
    # match_kind!="self"'te eklenmiyor AMA root-türevli f"{root}_id" onu geri getirebilir (root='parent'
    # → 'parent_id'). İnvaryant'ı TEK yerde ifade et: aday listesi tamamlandıktan sonra from_col'u
    # çıkar (loop'ta dağılmış ikinci-guard yok) → geçerli self-PK yoksa None döner (target_pk_not_found
    # tanılaması), uydurma kendine-işaret-eden FK üretilmez.
    if match_kind == "self":
        _fn = dialect.normalize_ident(from_col_name)
        pk_name_cands = [c for c in pk_name_cands if dialect.normalize_ident(c) != _fn]
    tried_pks: List[str] = []
    _seen_pk: Set[str] = set()
    for pkc in pk_name_cands:
        pkn = dialect.normalize_ident(pkc)
        if not pkn or pkn in _seen_pk:
            continue
        _seen_pk.add(pkn)
        tried_pks.append(pkc)
        _tc = _column_dict(target_tbl, pkn, dialect)
        if _tc is not None:
            return _tc, tried_pks
    return None, tried_pks


def _fuzzy_target_tables(
    t_from: _TableInfo,
    root: str,
    head: Optional[str],
    by_any_token: Dict[str, List[_TableInfo]],
    dialect: FKInferenceDialect,
    cap: int = _MAX_FUZZY_TARGETS_PER_COL,
) -> List[_TableInfo]:
    """v3.76.0 (G4a): isim-tier'ları başarısız olunca root/head ile HERHANGİ bir token'ı paylaşan
    aday hedef tablolar (entity-token yalnız SON token'a bakar; bu TÜM token'lara). Self hariç,
    same-schema tercihli, deterministik sıralı, cap'li. Çağıran SAMPLE-VALIDATION ile süzer →
    false-positive yok. O(1) token-index lookup (full-scan YOK) → 2000+ tabloda perf-güvenli.
    """
    out: List[_TableInfo] = []
    seen: Set[Tuple[str, str]] = set()
    self_norm = dialect.normalize_ident(t_from.name)
    self_schema = dialect.normalize_ident(t_from.schema)
    for r in [x for x in (root, head) if x and len(x) >= MIN_FUZZY_TOKEN_LEN]:
        raw_keys = {r, r + "s"}
        if r.endswith("s") and len(r) > MIN_FUZZY_TOKEN_LEN:
            raw_keys.add(r[:-1])
        for key in raw_keys:
            for tbl in by_any_token.get(dialect.normalize_ident(key), []):
                # v3.76.0 code-review: self yalnız ADA değil ŞEMA+AD ile karşılaştırılır —
                # cross-schema aynı-ad GEÇERLİ hedef (SALES.ORDER → REF.ORDER) yanlışça elenmesin.
                if (dialect.normalize_ident(tbl.name) == self_norm
                        and dialect.normalize_ident(tbl.schema) == self_schema):
                    continue  # gerçek self (aynı şema+ad) — fuzzy self-FK yapma
                k = (dialect.normalize_ident(tbl.schema), tbl.norm_name)
                if k in seen:
                    continue
                seen.add(k)
                out.append(tbl)
    same = [h for h in out if dialect.normalize_ident(h.schema) == self_schema]
    return sorted(same or out, key=lambda h: h.norm_name)[:cap]


def _iter_fk_candidates(
    tables: Dict[Tuple[str, str], _TableInfo],
    dialect: FKInferenceDialect,
    diag: Optional[List[Dict[str, Any]]] = None,
    enable_fuzzy: bool = False,
) -> Iterable[Tuple[_TableInfo, Dict[str, Any], str, str, _TableInfo, Dict[str, Any]]]:
    """Yield (from_table, from_col, root, pattern_name, to_table, to_col).

    Iterates every non-PK column across all tables, parses naming pattern,
    and emits potential targets via singular/plural matching against
    other tables in the source.

    v3.60.0: `diag` verilirse, FK üretilemeyen "yakın-ıska" kolonlar (root çıkmadı ama
    referans-benzeri / hedef tablo bulunamadı / hedef PK yok) tablo+şema+kolon+sebep ile
    kaydedilir → çağıran bunları Hata İzleme'ye tablo-aranabilir şekilde yazar (kök neden).
    """
    # Build name → list[_TableInfo] indexes for matching.
    by_norm_name: Dict[str, List[_TableInfo]] = {}
    # v3.56.0 PREFIX-TOLERANT + v3.73.0 unified entity-token. Kurumsal şemalar tabloları modül
    # prefix'iyle adlandırır (T_WF_INSTANCE, T_ORG_USER, MNP_NETWORK). entity-token = norm_name'in
    # son "_"-token'ı; TEK-token tabloda kendisi. Hem T_ORG_USER→"user" hem tek-token CUSTOMER→
    # "customer" indekslenir (eski by_last_token tek-token tabloyu atlıyordu → NCUSTOMER_ID gibi
    # Hungarian-önekli kolonlar prefix-soyma tier'ında hedef bulamıyordu). Exact match ÖNCE,
    # entity-token + prefix-soyma SONRA (düşük confidence + admin_verified ile sınırlı).
    by_entity_token: Dict[str, List[_TableInfo]] = {}
    # v3.76.0 (G4a): TÜM token'lar (yalnız son-token değil) — fuzzy fallback için. enable_fuzzy
    # kapalıysa kurulmaz (mevcut davranış + perf korunur).
    by_any_token: Dict[str, List[_TableInfo]] = {}
    for t in tables.values():
        by_norm_name.setdefault(t.norm_name, []).append(t)
        _toks = [x for x in str(t.norm_name).split("_") if x]
        _ent = _toks[-1] if _toks else str(t.norm_name)
        if _ent:
            by_entity_token.setdefault(_ent, []).append(t)
        if enable_fuzzy:
            for _tok in (_toks or [str(t.norm_name)]):
                by_any_token.setdefault(_tok, []).append(t)

    for t in tables.values():
        for col in t.columns:
            if not isinstance(col, dict):
                continue
            col_name = col.get("name") or ""
            if not col_name:
                continue
            # v3.75.0: framework satır-kimliği kolonları (GCRecId/RecId) — gerçek FK değil,
            # adaylıktan VE tanılama-uyarısından muaf (her tabloda var → 93 sahte uyarı kaynağı).
            if col_name.strip().lower() in NON_FK_COLUMN_NAMES:
                continue
            # Skip PKs (auto-generated id columns aren't FKs to themselves).
            # v3.56.0: is_pk öncelik (columns_json key'i), is_primary_key eski-fallback.
            if col.get("is_pk") or col.get("is_primary_key"):
                continue
            root = _extract_root(col_name)
            if not root:
                # Tanılama: kalıba uymadı ama referans-benzeri (PARTYID/STATUS_CODE) → kaydet.
                if diag is not None and _looks_reference_ish(col_name):
                    diag.append({
                        "schema": t.schema, "table": t.name, "column": col_name,
                        "reason": "no_pattern_match",
                        "hint": "kolon adı FK kalıbına uymadı (_id/Id/_ref vb. çıkarılamadı)",
                    })
                continue
            # Aday hedef tablo adları — ÖNCE full root (yüksek güven), SONRA head-noun (rol-önekli, düşük güven).
            # v3.60.0: 'CreateUserId' root='createuser' (hiçbir tabloya uymaz) ama head='user' → T_ORG_USER.
            head = _head_noun_from_name(col_name)
            name_cands: List[Tuple[str, str]] = [(c, "full") for c in _candidates_from_root(root)]
            if head and head != root:
                for c in _candidates_from_root(head):
                    name_cands.append((c, "head"))

            target_tbl: Optional[_TableInfo] = None
            match_kind = "full"
            for cand, kind in name_cands:
                cand_norm = dialect.normalize_ident(cand)
                # Tier 1: exact tam-ad. Tier 2: entity-token exact (prefix-tolerant, T_ORG_USER→user).
                hits = by_norm_name.get(cand_norm) or by_entity_token.get(cand_norm)
                tier_kind = kind
                if not hits:
                    # Tier 3 (v3.73.0): kolon kökü tip/modül önekli → öneki DETERMİNİSTİK soy.
                    # A) baştan 1-2 karakter (Hungarian N/V/C tip-öneki: NCUSTOMER→customer).
                    # B) baştan "_"-token at (modül öneki: vb_number_mnp_network→mnp_network→network).
                    # Tam-tarama YOK → O(küçük), 2000+ tablolu kaynakta perf-güvenli.
                    stripped: List[str] = []
                    for _k in (1, 2):
                        _v = cand_norm[_k:]
                        if len(_v) >= MIN_SUFFIX_TOKEN_LEN:
                            stripped.append(_v)
                    _ctoks = [x for x in cand_norm.split("_") if x]
                    for _i in range(1, len(_ctoks)):
                        _v = "_".join(_ctoks[_i:])
                        if len(_v) >= MIN_SUFFIX_TOKEN_LEN:
                            stripped.append(_v)
                    for _v in stripped:
                        _h = by_norm_name.get(_v) or by_entity_token.get(_v)
                        if _h:
                            hits = _h
                            tier_kind = "prefix"  # daha spekülatif → düşük confidence tier
                            break
                if not hits:
                    continue
                # Prefer same schema if multiple.
                same_schema = [h for h in hits if dialect.normalize_ident(h.schema) == dialect.normalize_ident(t.schema)]
                # v3.56.0 code-review: birden çok aday (son-token/önek çakışması) →
                # norm_name'e göre DETERMİNİSTİK seç (dict-iterasyon sırasına bağlı kalma →
                # re-keşif idempotent, aynı inferred FK üretilir).
                cand_tbl = sorted(same_schema or hits, key=lambda h: h.norm_name)[0]
                # Self-FK head/prefix eşleşme gürültüsünü ele: head 'user'/prefix-soyma + tablo kendisi
                # ise gerçek FK değil; full/token-exact root self-FK'ya izin verir (org chart parent_id).
                if tier_kind in ("head", "prefix") and dialect.normalize_ident(cand_tbl.name) == dialect.normalize_ident(t.name):
                    continue
                target_tbl = cand_tbl
                match_kind = tier_kind
                break
            # v3.75.0: parent_id/ParentId → self-reference (hiyerarşi/org-chart). Adlı 'parent'
            # tablosu yoktur; hedef = KENDİ tablosu (PK çözümü aşağıda declared/konvansiyon PK'dan).
            # Tip-uyumu (ParentId == own PK tipi) downstream _type_compatible'da doğrulanır.
            if target_tbl is None and root in _SELF_REF_ROOTS:
                target_tbl = t
                match_kind = "self"
            if target_tbl is None:
                # v3.76.0 (G4a): isim-tier'ları + self başarısız → FUZZY adaylar (root/head ile
                # token-paylaşan tablolar). Sample-validation ZORUNLU (infer_fks_for_source coverage
                # ile süzer + kolon başına EN İYİ'yi seçer) → false-positive yok.
                if enable_fuzzy:
                    for fz_tbl in _fuzzy_target_tables(t, root, head, by_any_token, dialect):
                        fz_col, _ = _resolve_target_pk(fz_tbl, col_name, root, "fuzzy", dialect)
                        if fz_col is not None:
                            yield t, col, root, "fuzzy", fz_tbl, fz_col
                # Tanılama (her durumda — fuzzy de sample-validation'da elenebilir → kök-neden görünür).
                if diag is not None:
                    diag.append({
                        "schema": t.schema, "table": t.name, "column": col_name,
                        "root": root, "head": head, "reason": "no_target_table",
                        "tried": [c for c, _ in name_cands],
                        "hint": "root/head'den üretilen aday tablo adları hiçbir tabloya (tam/son-token) eşleşmedi",
                    })
                continue
            # Self-FK is allowed (org chart parent_id → org.id). v3.76.0: ESNEK PK çözümü ortak
            # helper'da (_resolve_target_pk — naming + fuzzy aynı mantığı paylaşır, kod tekrarı yok).
            # Sıra: declared PK > FK-col-adı (self hariç) > entity-token > root > id/pk/uuid.
            target_col, tried_pks = _resolve_target_pk(target_tbl, col_name, root, match_kind, dialect)
            if target_col is None:
                # Tanılama: hedef tablo bulundu ama hiçbir PK adayı kolon olarak yok.
                if diag is not None:
                    diag.append({
                        "schema": t.schema, "table": t.name, "column": col_name,
                        "root": root, "reason": "target_pk_not_found",
                        "target": f"{target_tbl.schema}.{target_tbl.name}",
                        "target_pk_tried": tried_pks,
                        "hint": "hedef tablonun PK kolonu metadata'da yok (declared/FK-col-adı/konvansiyon hiçbiri eşleşmedi)",
                    })
                continue
            yield t, col, root, match_kind, target_tbl, target_col


def _score(
    match_kind: str,
    type_ok: bool,
    sample_info: Optional[Dict[str, Any]],
) -> Tuple[float, str]:
    # v3.60.0: head-noun eşleşmesi (rol-önekli) full root'tan daha spekülatif → daha düşük taban.
    # v3.76.0: fuzzy (token-paylaşan) en spekülatif → en düşük taban; tek başına min_confidence
    # altında, YALNIZ type+sample coverage ile geçer (false-positive sample gate'te elenir).
    if match_kind == "fuzzy":
        base = SCORE_NAMING_FUZZY
    elif match_kind == "head":
        base = SCORE_NAMING_HEAD
    else:
        base = SCORE_NAMING
    score = base
    # v3.65.0 KÖK fix: inference_method DB kolonu CHECK constraint'li (ck_dsdrel_inference_method:
    # 'naming'|'naming+type'|'naming+type+sample'|'manual'|'llm'). v3.60.0'da 'naming:full+type' yazınca
    # HER insert CheckViolation → 0 FK + flood. method constraint-VALID kalır; match_kind (full/head)
    # ayrıca evidence_json['match_kind']'de saklanır (bilgi kaybı yok).
    method = "naming"
    if type_ok:
        score += SCORE_TYPE
        method = "naming+type"
    if sample_info is not None:
        score += SCORE_SAMPLE_MAX * float(sample_info.get("coverage_ratio", 0.0))
        method = "naming+type+sample"
    if score > 1.0:
        score = 1.0
    return round(score, 4), method


def infer_fks_for_source(
    cur,
    source_id: int,
    *,
    sample_validate: bool = False,
    sample_rows: int = DEFAULT_SAMPLE_ROWS,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    dialect: str | None = None,
    target_cur=None,
    enable_fuzzy: Optional[bool] = None,
) -> Dict[str, Any]:
    """Infer FKs and UPSERT inferred rows.

    Args:
        cur: VYRA DB cursor (reads ds_db_objects, writes ds_db_relationships).
            RLS scope already applied.
        source_id: data source row id.
        sample_validate: if True, run coverage probe via `target_cur`.
        sample_rows: cap on distinct FK values probed.
        min_confidence: candidates below this score are dropped (not persisted).
        dialect: 'postgresql' | 'oracle' | 'mssql' | 'mysql' (None → PG default).
        target_cur: cursor against the TARGET database (where the user's
            data lives). Required when sample_validate=True. Must be a
            short-lived cursor with statement_timeout already applied by
            the caller.
        enable_fuzzy: v3.76.0 (G4a) — None (default) → otomatik (sample_validate AND target_cur).
            Fuzzy = isim-tier'ları boş dönen FK kolonları için token-paylaşan aday tablolar;
            YALNIZ sample coverage>=FUZZY_MIN_COVERAGE ile persist edilir (false-positive yok).
            sample/target yoksa fuzzy adaylar üretilse de coverage gate'te elenir.

    Returns:
        dict with counts and a list of inferred rows (capped at 200 for
        observability).
    """
    d = get_dialect(dialect or "postgresql")
    # v3.76.0 code-review: fuzzy OPT-IN (default OFF). Eski auto-coupling (sample_validate açıkken
    # otomatik) mevcut sample_validate kullanıcılarını yeni spekülatif FK'larla şaşırtıyordu →
    # çağıran AÇIKÇA enable_fuzzy=True vermeli (+ sample_validate; yoksa coverage gate'te elenir).
    if enable_fuzzy is None:
        enable_fuzzy = False
    tables = _load_schema(cur, source_id, d)
    if not tables:
        return {
            "source_id": source_id,
            "dialect": d.name,
            "tables_scanned": 0,
            "candidates": 0,
            "persisted": 0,
            "skipped_existing": 0,
            "skipped_low_confidence": 0,
            "unresolved_count": 0,
            "unresolved": [],
            "sample": [],
        }

    existing = _load_existing_relationships(cur, source_id, d)
    candidates: List[_Candidate] = []
    # v3.76.0 (G4a): fuzzy adaylar FROM-kolonu başına havuzlanır → döngü sonrası EN İYİ tek hedef.
    fuzzy_pool: Dict[Tuple[str, str, str], List[Tuple[_Candidate, float]]] = {}
    fuzzy_attempted_cols: Set[Tuple[str, str, str]] = set()  # v3.76.0 code-review: gözlemlenebilirlik
    unresolved: List[Dict[str, Any]] = []  # v3.60.0: FK üretilemeyen yakın-ıska kolonlar (tanılama)
    skipped_existing = 0
    for t_from, col_from, root, pattern, t_to, col_to in _iter_fk_candidates(tables, d, diag=unresolved, enable_fuzzy=enable_fuzzy):
        from_schema = t_from.schema
        from_table = t_from.name
        from_col = col_from.get("name") or ""
        to_schema = t_to.schema
        to_table = t_to.name
        to_col = col_to.get("name") or ""
        key = (
            d.normalize_ident(from_schema),
            d.normalize_ident(from_table),
            d.normalize_ident(from_col),
            d.normalize_ident(to_schema),
            d.normalize_ident(to_table),
            d.normalize_ident(to_col),
        )
        if key in existing:
            skipped_existing += 1
            continue
        from_type = col_from.get("type") or col_from.get("data_type") or ""
        to_type = col_to.get("type") or col_to.get("data_type") or ""
        type_ok = _type_compatible(from_type, to_type, d)

        sample_info: Optional[Dict[str, Any]] = None
        if sample_validate and target_cur is not None and type_ok:
            sample_info = _validate_sample(
                target_cur,
                from_schema, from_table, from_col,
                to_schema, to_table, to_col,
                sample_rows, d,
            )

        score, method = _score(pattern, type_ok, sample_info)
        evidence = {
            "naming_pattern": pattern,
            "match_kind": pattern,
            "root": root,
            "from_type": from_type,
            "to_type": to_type,
            "type_match": type_ok,
            # v3.74.0 provenance: hedef kimlik nereden? unique-index proxy / declared PK / isim-konvansiyonu.
            # (UI rozeti: 🟢 unique_index / 🔒 declared / 🟡 inferred). col_to ds_db_objects'tan gelir;
            # pk_source unique-index ise o; değilse is_pk gerçekten varsa declared, yoksa konvansiyonla
            # çözülmüş (inferred) → yanlış "declared" rozeti vermemek için ayır.
            "to_pk_source": (
                col_to.get("pk_source")
                or ("declared" if (col_to.get("is_pk") or col_to.get("is_primary_key")) else "inferred")
            ),
        }
        if sample_info is not None:
            evidence["sample"] = sample_info
        cand = _Candidate(
            from_schema=from_schema, from_table=from_table, from_column=from_col,
            from_type=from_type,
            to_schema=to_schema, to_table=to_table, to_column=to_col,
            to_type=to_type,
            naming_pattern=pattern, root=root,
            confidence=score, evidence=evidence, method=method,
        )
        if pattern == "fuzzy":
            # v3.76.0 (G4a): fuzzy YALNIZ sample coverage ile geçer. Aynı FROM kolonu için birden çok
            # fuzzy hedef olabilir → havuzla; döngü sonrası EN İYİ coverage'lı TEK hedef (1 kolon=1 FK).
            _fkey = (d.normalize_ident(from_schema), d.normalize_ident(from_table), d.normalize_ident(from_col))
            fuzzy_attempted_cols.add(_fkey)  # code-review: denenen fuzzy kolonları say (sessiz düşme yok)
            cov = float(sample_info.get("coverage_ratio", 0.0)) if sample_info else 0.0
            if type_ok and sample_info is not None and cov >= FUZZY_MIN_COVERAGE:
                fuzzy_pool.setdefault(_fkey, []).append((cand, cov))
            continue
        candidates.append(cand)

    # v3.76.0 (G4a): fuzzy havuzu → FROM kolonu başına EN İYİ (coverage, sonra confidence) tek aday.
    for _grp, _lst in fuzzy_pool.items():
        candidates.append(max(_lst, key=lambda x: (x[1], x[0].confidence))[0])

    # Persist
    persisted = 0
    fuzzy_persisted = 0  # v3.76.0 code-review: GERÇEK persist edilen fuzzy sayısı (havuz boyutu değil)
    skipped_low = 0
    sample_out: List[Dict[str, Any]] = []
    # v3.64.0: SAVEPOINT yalnız transaction'da geçerli (autocommit'te "can only be used in
    # transaction blocks" atar). VYRA conn transactional (autocommit=False) → savepoint kullanılır;
    # autocommit ise zaten cascade-abort olmaz → savepoint atlanır (bulletproof, riskli BEGIN yok).
    _use_sp = not bool(getattr(getattr(cur, "connection", None), "autocommit", False))
    for c in candidates:
        if c.confidence < min_confidence:
            skipped_low += 1
            continue
        try:
            # v3.64.0 KÖK fix: her INSERT'i SAVEPOINT ile izole et. Eskiden tek-insert hatası
            # (ör. duplicate/constraint) transaction'ı abort ediyor → KALAN tüm insert'ler
            # InFailedSqlTransaction ile cascade-fail edip her biri loglanıyordu (756 ERROR floodu).
            # Savepoint → hata yalnız o adayı düşürür, batch devam eder + GERÇEK kök hata izole görünür.
            if _use_sp:
                cur.execute("SAVEPOINT fk_persist_sp")
            cur.execute(
                """
                INSERT INTO ds_db_relationships
                    (source_id, from_schema, from_table, from_column,
                     to_schema, to_table, to_column, constraint_name,
                     is_inferred, inference_method, evidence_json,
                     admin_verified, confidence_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                        TRUE, %s, %s::jsonb, FALSE, %s)
                """,
                (
                    source_id, c.from_schema, c.from_table, c.from_column,
                    c.to_schema, c.to_table, c.to_column,
                    f"inferred_{c.from_table}_{c.from_column}",
                    c.method, json.dumps(c.evidence), c.confidence,
                ),
            )
            if _use_sp:
                cur.execute("RELEASE SAVEPOINT fk_persist_sp")
            persisted += 1
            if c.naming_pattern == "fuzzy":
                fuzzy_persisted += 1
            if len(sample_out) < 200:
                sample_out.append({
                    "from": f"{c.from_schema}.{c.from_table}.{c.from_column}",
                    "to": f"{c.to_schema}.{c.to_table}.{c.to_column}",
                    "method": c.method,
                    "confidence": c.confidence,
                })
        except Exception as e:
            # Savepoint'e geri dön → transaction kullanılabilir kalır (sonraki adaylar koşar).
            if _use_sp:
                try:
                    cur.execute("ROLLBACK TO SAVEPOINT fk_persist_sp")
                except Exception:
                    pass
            # v3.60.0: persist hatası system_logs'a (Hata İzleme) tablo-aranabilir. Artık yalnız
            # GERÇEK hatalar loglanır (cascade savepoint ile bitti). Şifre/hassas veri yok.
            try:
                from app.services.logging_service import log_exception
                log_exception(
                    e, module="fk_inference.persist",
                    context={
                        "source_id": source_id, "dialect": d.name,
                        "schema": c.from_schema, "table": c.from_table,
                        "column": c.from_column,
                        "to_table": f"{c.to_schema}.{c.to_table}",
                    },
                )
            except Exception:
                logger.warning(
                    "[fk_inference] persist failed for %s.%s.%s: %s",
                    c.from_schema, c.from_table, c.from_column, str(e)[:200],
                )

    # v3.76.0 code-review: fuzzy denendi ama (sample yok / düşük coverage / min_confidence) düşenler
    # SESSİZ kaybolmasın → özet log (yutulan hata yok prensibi). Denenen vs persist edilen.
    if enable_fuzzy and fuzzy_attempted_cols:
        logger.info(
            "[fk_inference] fuzzy: %d kolon denendi (sample probe), %d persist edildi (source=%s, %s)",
            len(fuzzy_attempted_cols), fuzzy_persisted, source_id, d.name,
        )

    return {
        "source_id": source_id,
        "dialect": d.name,
        "tables_scanned": len(tables),
        "candidates": len(candidates),
        "persisted": persisted,
        "fuzzy_resolved": fuzzy_persisted,  # v3.76.0 code-review: GERÇEK persist edilen fuzzy (havuz değil)
        "fuzzy_attempted": len(fuzzy_attempted_cols),  # sample probe açılan fuzzy kolon sayısı
        "skipped_existing": skipped_existing,
        "skipped_low_confidence": skipped_low,
        "unresolved_count": len(unresolved),
        "unresolved": unresolved,  # v3.77.0: TAM liste — endpoint ds_fk_diagnostics'e persist + client'a cap'ler
        "sample": sample_out,
    }


def persist_fk_diagnostics(cur, source_id: int, unresolved: List[Dict[str, Any]]) -> int:
    """v3.77.0 (Tema-1 kapalı-döngü): çözülemeyen FK kolonlarını ds_fk_diagnostics'e KALICI yaz —
    kök-neden görünürlüğü + trend + admin 'elle FK kur'. AYRI cursor/işlemde çağrılmalı (FK persist
    commit'ini riske atmamak için). Strateji: önce kaynağın AÇIK kayıtlarını PROVİZYON fixed işaretle,
    sonra bu koşunun unresolved'ını UPSERT ile yeniden-aç → bu koşuda görünmeyen = çözülmüş kabul (is_fixed).
    Döner: hâlâ-çözülemeyen (yeniden-açılan) kayıt sayısı. Tablo yoksa 0 + WARNING (eski şema güvenli)."""
    try:
        cur.execute(
            "UPDATE ds_fk_diagnostics SET is_fixed = TRUE, fixed_at = NOW() "
            "WHERE source_id = %s AND is_fixed = FALSE",
            (source_id,),
        )
    except Exception as e:
        logger.warning("[fk_inference] ds_fk_diagnostics yok/erişilemedi → diagnostics atlandı: %s", str(e)[:160])
        return 0
    n = 0
    for u in unresolved or []:
        ft = str(u.get("table") or "").strip()
        fc = str(u.get("column") or "").strip()
        if not ft or not fc:
            continue
        ev = {k: u.get(k) for k in ("hint", "root", "head") if u.get(k) is not None}
        cur.execute(
            """INSERT INTO ds_fk_diagnostics
                 (source_id, from_schema, from_table, from_column, reason, root, head,
                  evidence_json, is_fixed, first_seen_at, last_seen_at, fixed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s, FALSE, NOW(), NOW(), NULL)
               ON CONFLICT (source_id, COALESCE(from_schema,''), from_table, from_column)
               DO UPDATE SET reason = EXCLUDED.reason, root = EXCLUDED.root, head = EXCLUDED.head,
                             evidence_json = EXCLUDED.evidence_json,
                             is_fixed = FALSE, fixed_at = NULL, last_seen_at = NOW()""",
            (source_id, (u.get("schema") or None), ft, fc,
             str(u.get("reason") or "unknown")[:40], u.get("root"), u.get("head"),
             json.dumps(ev) if ev else None),
        )
        n += 1
    return n
