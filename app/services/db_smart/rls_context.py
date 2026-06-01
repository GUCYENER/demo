"""Wizard RLS context injection (v3.30.0 FAZ 1 G1.1a — ARES carry-over).

Migration 032'de dbsmart_* tabloları aşağıdaki session setting'lerine bağlı
RLS policy ile kuruldu:

    current_setting('vyra.user_id',    true)::int  → kullanıcı izolasyonu
    current_setting('vyra.company_id', true)::int  → tenant izolasyonu
    current_setting('vyra.is_admin',   true)        → admin bypass ('true' literal)

Bu modül FastAPI endpoint'leri içinde — middleware'de DEĞİL — aktif transaction'a
SET LOCAL uygular. ARES (FAZ 0 code-review notu): middleware-tabanlı set yerine
endpoint-içi enjeksiyon mevcut `apply_company_scope` pattern'iyle uyumludur ve
pipeline cursor'ı havuza dönerken kendiliğinden temizlenir.

Kullanım:
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        cur.execute("SELECT ... FROM dbsmart_sessions ...")

Fail-closed semantik (ARES KRİTİK — v3.30.0 FAZ 3 P15+ fix):
    set_config / SET LOCAL hataları artık SESSİZ DEĞİL. RLSContextError fırlatılır.
    Sebep: SET başarısızsa sonraki sorgular RLS koruması olmadan çalışıp
    cross-tenant veri sızdırır. Default-deny varsayımı policy şemasına özgüdür ve
    her policy bunu garanti etmez — guard'ı uygulama katmanında zorluyoruz.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class RLSContextError(RuntimeError):
    """RLS context (vyra.* GUC) uygulanamadı — fail-closed sinyali.

    Endpoint katmanı bu hatayı 500/503'e çevirmeli; sorguya İLERLEMEMELİ.
    """


def _coerce_tenant_int(value: Any, field: str) -> int:
    """user_id / company_id için katı int doğrulama.

    NULL / bool / float / non-numeric str reddedilir. RLS GUC'leri
    `::int` cast'i ile okunduğundan tipi burada netleştiriyoruz.
    """
    if value is None:
        raise RLSContextError(f"{field} is required (got None)")
    # bool int alt-sınıfıdır; user_id=True gibi kazaları engelle.
    if isinstance(value, bool):
        raise RLSContextError(f"{field} must be int, got bool ({value!r})")
    if isinstance(value, int):
        ivalue = value
    elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
        ivalue = int(value)
    else:
        raise RLSContextError(f"{field} must be int-coercible, got {type(value).__name__} ({value!r})")
    if ivalue <= 0:
        raise RLSContextError(f"{field} must be a positive int, got {ivalue}")
    return ivalue


def _coerce_is_admin(user_ctx: Dict[str, Any]) -> bool:
    """is_admin yalnızca bool — string/int kabul edilmez.

    `role == 'admin'` legacy alias'ı korunur (mevcut auth payload'ı bunu
    gönderiyor); aksi halde explicit bool beklenir.
    """
    raw = user_ctx.get("is_admin")
    if raw is None:
        # role alias path — `role` string olmalı.
        role = user_ctx.get("role")
        if role is not None and not isinstance(role, str):
            raise RLSContextError(f"role must be str, got {type(role).__name__}")
        return role == "admin"
    if not isinstance(raw, bool):
        raise RLSContextError(f"is_admin must be bool, got {type(raw).__name__} ({raw!r})")
    # bool=True → admin; aksi durumda role alias'ını da OR'la.
    if raw:
        return True
    role = user_ctx.get("role")
    if role is not None and not isinstance(role, str):
        raise RLSContextError(f"role must be str, got {type(role).__name__}")
    return role == "admin"


def apply_vyra_user_context(cur: Any, user_ctx: Dict[str, Any]) -> None:
    """Aktif transaction'a `vyra.*` RLS setting'lerini SET LOCAL uygular.

    Args:
        cur: Aktif psycopg2 cursor (transaction-scoped).
        user_ctx: get_current_user dict'i — {id, company_id, is_admin/role, ...}

    Raises:
        RLSContextError:
            - user_ctx malformed (eksik/yanlış-tipli id/company_id/is_admin).
            - cur.execute("SELECT set_config(...)") DB tarafında patlarsa.
        TypeError:
            - user_ctx dict değilse (programlama hatası).

    Notlar:
        - SET LOCAL transaction-scoped: commit/rollback sonrası bağlantı pool'a
          dönünce setting temizlenir (mevcut `apply_company_scope` ile aynı garanti).
        - `is_admin` literal string `'true'` / `'false'` olarak gönderilir; RLS
          policy `current_setting('vyra.is_admin', true) = 'true'` karşılaştırır.
        - **Eski davranış (silent swallow) KALDIRILDI.** Tüm hatalar
          RLSContextError olarak yükselir → endpoint guard'ı sorguya geçmemeli.
    """
    if not isinstance(user_ctx, dict):
        raise TypeError(f"user_ctx must be dict, got {type(user_ctx).__name__}")

    # 1) Input validation — fail BEFORE touching DB.
    user_id = _coerce_tenant_int(user_ctx.get("id"), "user_id")
    # is_admin'i company_id'den ÖNCE hesapla: admin kullanıcılar çok-şirketlidir,
    # users.company_id NULL olabilir (örn. tüm firmaları yöneten Yönetici hesabı).
    is_admin = _coerce_is_admin(user_ctx)
    # v3.43.1 fix (ARES + APOLLO): admin + NULL company_id artık 500 vermez.
    # RLS policy admin'i `vyra.is_admin='true'` ile ZATEN bypass ettiğinden admin için
    # company_id zorunlu değil → sentinel 0 (geçerli int, ::int cast güvenli; OR is_admin
    # clause erişimi açar). NON-admin + NULL company_id GERÇEK fail-closed durumudur
    # (tenant scope yok → cross-tenant sızıntı) → hata KORUNUR, güvenlik bozulmaz.
    raw_company = user_ctx.get("company_id")
    if is_admin and raw_company is None:
        company_id = 0
    else:
        company_id = _coerce_tenant_int(raw_company, "company_id")

    # 2) DB calls — herhangi biri patlarsa RLSContextError fırlat.
    try:
        cur.execute(
            "SELECT set_config('vyra.user_id', %s, true)",
            (str(user_id),),
        )
        cur.execute(
            "SELECT set_config('vyra.company_id', %s, true)",
            (str(company_id),),
        )
        cur.execute(
            "SELECT set_config('vyra.is_admin', %s, true)",
            ("true" if is_admin else "false",),
        )
    except RLSContextError:
        raise
    except Exception as e:
        # Fail-closed: SET başarısızsa caller sorguya devam etmemeli.
        logger.error(
            "[db_smart.rls] apply_vyra_user_context FAILED (fail-closed): %s", e
        )
        raise RLSContextError(f"set_config failed: {e}") from e


def clear_vyra_user_context(cur: Any) -> None:
    """Explicit clear — testlerde veya idempotency için.

    SET LOCAL transaction sonunda zaten temizlenir; bu helper sadece test
    ortamında veya tek bağlantıyı arka arkaya farklı user'larla kullanan
    fixture'lar için sağlanır.

    Clear path *defensive* hatalar için sessiz kalır (caller user-context
    iptali peşinde — yeni bir context apply edilmeden sonraki sorgu zaten
    bağımsız transaction'da çalışır). Yine de log'lanır.
    """
    try:
        cur.execute("SELECT set_config('vyra.user_id', '', true)")
        cur.execute("SELECT set_config('vyra.company_id', '', true)")
        cur.execute("SELECT set_config('vyra.is_admin', '', true)")
    except Exception as e:
        logger.warning("[db_smart.rls] clear_vyra_user_context failed: %s", e)


def resolve_effective_company_id(cur, user_ctx: Dict[str, Any], source_id=None):
    """Kullanıcının efektif company_id'sini çözer (v3.43.4 — admin→kaynağın firması).

    - Normal kullanıcı: user_ctx['company_id'] (zaten dolu) → onu döndür.
    - Admin (company_id NULL, tasarımca — schema.py:764 backfill yalnız non-admin'e firma atar):
      db-smart oturum/rapor tabloları `company_id NOT NULL FK` ister; admin'in firması yok.
      Çözüm: KAYNAĞIN firması (`data_sources.company_id`, NOT NULL — mig 002). Böylece oturum/rapor
      kaynağın GERÇEK firmasına atanır → tenant izolasyonu korunur (admin cross-tenant kaçmaz;
      yalnız seçtiği kaynağın firması bağlamında çalışır).
    - Çözülemezse None döner → caller fail-closed davranmalı (non-admin asla NULL'la geçmez).

    Güvenlik: NON-admin + NULL company_id'de None döner (kaynaktan ÇÖZMEZ) — sadece admin için
    kaynak firması kullanılır. cur, apply_vyra_user_context set edilmiş scoped cursor olmalı.
    """
    raw = user_ctx.get("company_id") if user_ctx else None
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    is_admin = bool(user_ctx.get("is_admin")) or user_ctx.get("role") == "admin"
    if not is_admin or source_id is None:
        return None
    try:
        cur.execute("SELECT company_id FROM data_sources WHERE id = %s", (int(source_id),))
        row = cur.fetchone()
        if row:
            cid = row["company_id"] if isinstance(row, dict) else row[0]
            return int(cid) if cid is not None else None
    except Exception as e:
        logger.warning("[db_smart.rls] resolve_effective_company_id source=%s failed: %s",
                       source_id, e)
    return None
