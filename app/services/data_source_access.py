"""Data source access permission helpers (Faz 1, v3.20.0).

Kullanıcının bir `data_sources.id` üzerinde `can_view` (varsayılan) veya
`can_execute` yetkisine sahip olup olmadığını kontrol eder.

`data_source_permissions` tablosu polymorphic — `subject_type` 'user' veya
'org' olabilir. Org permission'ları `user_organizations` üzerinden çözümlenir.

Bu modül `data_sources_api.list_data_sources` SQL pattern'ini taşır
(yalnızca tek bir source_id için filtre).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Tuple

from app.core.db import get_db_context


def user_can_access_source(
    user_id: int,
    source_id: int,
    *,
    is_admin: bool = False,
    permission: str = "can_view",
) -> bool:
    """Kullanıcının `source_id` üzerinde belirtilen yetkisi var mı?

    Args:
        user_id: users.id
        source_id: data_sources.id
        is_admin: True ise yetki kontrolü atlanır (admin her şeye erişir)
        permission: 'can_view' (varsayılan) veya 'can_execute'

    Returns:
        bool: Erişim varsa True

    Raises:
        ValueError: permission geçersizse
    """
    if is_admin:
        return True

    if permission not in ("can_view", "can_execute"):
        raise ValueError(f"Geçersiz permission: {permission!r}")

    with get_db_context() as conn:
        cur = conn.cursor()
        # Hem user-direct hem org-membership üzerinden kontrol
        cur.execute(
            f"""
            SELECT 1
            FROM data_source_permissions p
            LEFT JOIN user_organizations uo
                   ON uo.user_id = %s
                  AND p.subject_type = 'org'
                  AND uo.org_id = p.subject_id
            WHERE p.source_id = %s
              AND p.{permission} = TRUE
              AND (
                  (p.subject_type = 'user' AND p.subject_id = %s)
                  OR
                  (p.subject_type = 'org'  AND uo.id IS NOT NULL)
              )
            LIMIT 1
            """,
            (user_id, source_id, user_id),
        )
        return cur.fetchone() is not None


@dataclass(frozen=True)
class AccessScope:
    """Bir kullanıcının bir kaynaktaki tablo erişim kapsamı.

    - ``all_tables=True``  → kaynaktaki TÜM tablolar erişilebilir (scope_mode='all'
      grant veya admin). ``tables`` anlamsızdır.
    - ``all_tables=False`` → yalnız ``tables`` kümesindeki (schema, tablo) çiftleri.
      Boş küme = hiçbir tablo erişilemez (restricted + seçim yok).

    Karşılaştırma case-insensitive olsun diye ``tables`` içindeki schema/tablo
    adları **lowercase** tutulur (Oracle UPPER vs PostgreSQL lower farkı).
    """

    all_tables: bool
    tables: FrozenSet[Tuple[str, str]] = frozenset()

    def allows(self, schema_name: str | None, table_name: str | None) -> bool:
        """Verilen (schema, tablo) bu kapsamda erişilebilir mi?"""
        if self.all_tables:
            return True
        if not table_name:
            return False
        key = ((schema_name or "").strip().lower(), table_name.strip().lower())
        return key in self.tables

    def allows_table_name(self, table_name: str | None) -> bool:
        """Şema bilgisi olmayan çıplak tablo adı için kapsam kontrolü.

        `SafeSQLExecutor.get_allowed_tables` yalnız `object_name` (şemasız) döner;
        bu durumda herhangi bir şemadaki eşleşen tablo adı kabul edilir. Şema-duyarlı
        sıkı kontrol arama/kolon/şema-bağlamı katmanlarında ayrıca yapılır.
        """
        if self.all_tables:
            return True
        if not table_name:
            return False
        tn = table_name.strip().lower()
        return any(t == tn for _s, t in self.tables)


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def user_accessible_tables(
    user_id: int,
    source_id: int,
    *,
    is_admin: bool = False,
    permission: str = "can_view",
) -> AccessScope:
    """Kullanıcının `source_id` üzerinde erişebildiği tablo kapsamını döner.

    Çözümleme (union semantiği):
      - Admin → her zaman ALL.
      - Uygulanabilir grant'lar = kullanıcının `permission` (can_view/can_execute)
        TRUE olan direkt VEYA org-üyeliği grant'ları.
      - Hiç uygulanabilir grant yok → erişim yok (boş kapsam, all_tables=False).
      - Herhangi biri scope_mode='all' → ALL (tüm tablolar).
      - Aksi halde restricted grant'ların allowlist tablolarının BİRLEŞİMİ.

    Args:
        permission: 'can_view' (görüntüleme kapsamı) veya 'can_execute' (çalıştırma).

    Returns:
        AccessScope
    """
    if is_admin:
        return AccessScope(all_tables=True)

    if permission not in ("can_view", "can_execute"):
        raise ValueError(f"Geçersiz permission: {permission!r}")

    with get_db_context() as conn:
        cur = conn.cursor()
        # 1) Uygulanabilir grant'lar (permission TRUE olanlar)
        cur.execute(
            f"""
            SELECT p.subject_type, p.subject_id, p.scope_mode
            FROM data_source_permissions p
            LEFT JOIN user_organizations uo
                   ON uo.user_id = %s
                  AND p.subject_type = 'org'
                  AND uo.org_id = p.subject_id
            WHERE p.source_id = %s
              AND p.{permission} = TRUE
              AND (
                  (p.subject_type = 'user' AND p.subject_id = %s)
                  OR
                  (p.subject_type = 'org'  AND uo.id IS NOT NULL)
              )
            """,
            (user_id, source_id, user_id),
        )
        grants = cur.fetchall()

        if not grants:
            # Kaynağa hiç erişim yok → hiçbir tablo yok
            return AccessScope(all_tables=False, tables=frozenset())

        restricted_subjects = set()
        for subject_type, subject_id, scope_mode in grants:
            if scope_mode == "all":
                # Tek bir 'all' grant tüm tabloları açar
                return AccessScope(all_tables=True)
            restricted_subjects.add((subject_type, subject_id))

        # 2) restricted grant'ların allowlist tablolarının birleşimi
        cur.execute(
            """
            SELECT subject_type, subject_id, schema_name, table_name
            FROM data_source_table_permissions
            WHERE source_id = %s
            """,
            (source_id,),
        )
        tables = {
            (_norm(schema_name), _norm(table_name))
            for subject_type, subject_id, schema_name, table_name in cur.fetchall()
            if (subject_type, subject_id) in restricted_subjects
        }
        return AccessScope(all_tables=False, tables=frozenset(tables))


def user_can_access_table(
    user_id: int,
    source_id: int,
    schema_name: str | None,
    table_name: str | None,
    *,
    is_admin: bool = False,
    permission: str = "can_view",
) -> bool:
    """Kullanıcı belirtilen tabloya (schema, tablo) erişebilir mi? (kapsam kontrolü).

    Not: Bu yalnız TABLO kapsamını kontrol eder. Kaynak seviyesi erişim için
    `user_can_access_source` ayrıca çağrılmalıdır (ya da bu fonksiyon onu da
    kapsayacak şekilde `user_accessible_tables` zaten 0 grant'ta boş döner).
    """
    scope = user_accessible_tables(
        user_id, source_id, is_admin=is_admin, permission=permission
    )
    return scope.allows(schema_name, table_name)
