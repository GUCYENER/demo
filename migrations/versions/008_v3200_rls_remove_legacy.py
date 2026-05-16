"""v3.20.0: RLS hardening — legacy passthrough klozu kaldır (Faz 1d)

Revision ID: 008_v3200_rls_remove_legacy
Revises: 007_v3200_rls_discovery_tables
Create Date: 2026-05-17

Faz 1d (Hardening)
------------------
007 migration'da uygulanan PERMISSIVE policy:
    USING (
        current_setting('app.current_source_id', true) IS NULL
        OR current_setting('app.current_source_id', true) = ''   ← legacy passthrough
        OR current_setting('app.bypass_rls', true) = 'on'        ← admin bypass
        OR source_id::text = current_setting('app.current_source_id', true)
    )

Bu migration "legacy passthrough" (ilk iki kloz) şartını kaldırır:
    USING (
        current_setting('app.bypass_rls', true) = 'on'           ← admin bypass
        OR source_id::text = current_setting('app.current_source_id', true)
    )

ÖN KOŞUL:
    Faz 1c (callsite refactor) tamamlanmış olmalı. Tüm `get_db_conn()`/
    `get_db_context()` çağrıları korumalı 4 tabloya erişiyorsa ya
    `get_db_context_scoped(source_id)` ya da
    `get_db_context_scoped(bypass=True)` kullanmalı.

ETKİ:
    - Scoped erişim olmayan SELECT/INSERT/UPDATE/DELETE → 0 satır (sessizce)
    - INSERT WITH CHECK ihlali → permission denied
    - Eski legacy kod (henüz refactor edilmemişse) BURADA PATLAR

UYARI: RLS yalnızca app rolü non-superuser ise etkilidir. Production'da
`DB_USER=vyra_app` (BYPASSRLS attribute'u olmayan) önerilir.
Bkz: app/api/main.py:_warn_if_db_user_bypasses_rls
"""
from typing import Sequence, Union
from alembic import op

# revision identifiers
revision: str = "008_v3200_rls_remove_legacy"
down_revision: Union[str, None] = "007_v3200_rls_discovery_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES = (
    "ds_db_objects",
    "ds_db_relationships",
    "ds_db_samples",
    "ds_learning_results",
)

# Sıkı policy — legacy passthrough YOK
_POLICY_USING_STRICT = """(
    current_setting('app.bypass_rls', true) = 'on'
    OR source_id::text = current_setting('app.current_source_id', true)
)"""

# Permissive policy — 007'deki orijinal (downgrade için)
_POLICY_USING_PERMISSIVE = """(
    current_setting('app.current_source_id', true) IS NULL
    OR current_setting('app.current_source_id', true) = ''
    OR current_setting('app.bypass_rls', true) = 'on'
    OR source_id::text = current_setting('app.current_source_id', true)
)"""


def upgrade() -> None:
    """007 policy'sini DROP edip strict policy ile değiştir."""
    for tbl in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS rls_source_scoped ON {tbl};")
        op.execute(f"""
        CREATE POLICY rls_source_scoped ON {tbl}
            FOR ALL
            USING {_POLICY_USING_STRICT}
            WITH CHECK {_POLICY_USING_STRICT};
        """)


def downgrade() -> None:
    """Permissive policy'ye geri dön (007 davranışı)."""
    for tbl in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS rls_source_scoped ON {tbl};")
        op.execute(f"""
        CREATE POLICY rls_source_scoped ON {tbl}
            FOR ALL
            USING {_POLICY_USING_PERMISSIVE}
            WITH CHECK {_POLICY_USING_PERMISSIVE};
        """)
