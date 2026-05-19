"""v3.20.0: Row-Level Security (RLS) on discovery + learning tables (PERMISSIVE phase)

Revision ID: 007_v3200_rls_discovery_tables
Revises: 006_v3140_async_golden_sql
Create Date: 2026-05-17

Faz 1a (Permissive Rollout)
---------------------------
4 hedef tabloda RLS aktif edilir (+FORCE ile tablo sahibi bypass'ı engellenir):
    - ds_db_objects
    - ds_db_relationships
    - ds_db_samples
    - ds_learning_results

Policy 3 koşuldan biri sağlanırsa erişim verir:
    1) `app.current_source_id` GUC set edilmemiş → legacy passthrough (eski davranış)
    2) `app.bypass_rls = 'on'` → admin bypass
    3) `source_id::text = current_setting('app.current_source_id', true)` → normal scoped erişim

Bu PERMISSIVE faz — eski kod kırılmaz. Hardening Faz 1d'de
(`008_v3200_rls_remove_legacy.py`) "1) legacy passthrough" şartı kaldırılır.

UYARI: RLS yalnızca app rolü superuser değilse VEYA BYPASSRLS attribute'u yoksa
etkilidir. Production'da `DB_USER=vyra_app` (non-superuser) önerilir.
Bkz: app/core/config.py:111
"""
from typing import Sequence, Union
from alembic import op

# revision identifiers
revision: str = "007_v3200_rls_discovery_tables"
down_revision: Union[str, None] = "006_v3140_async_golden_sql"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES = (
    "ds_db_objects",
    "ds_db_relationships",
    "ds_db_samples",
    "ds_learning_results",
)

_POLICY_USING = """(
    current_setting('app.current_source_id', true) IS NULL
    OR current_setting('app.current_source_id', true) = ''
    OR current_setting('app.bypass_rls', true) = 'on'
    OR source_id::text = current_setting('app.current_source_id', true)
)"""


def upgrade() -> None:
    for tbl in _TABLES:
        # 1) RLS aç + FORCE (table owner'ı da kapsa)
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY;")

        # 2) Tek policy — tüm DML operasyonları (SELECT/INSERT/UPDATE/DELETE)
        #    Idempotency: önce DROP (varsa)
        op.execute(f"DROP POLICY IF EXISTS rls_source_scoped ON {tbl};")
        op.execute(f"""
        CREATE POLICY rls_source_scoped ON {tbl}
            FOR ALL
            USING {_POLICY_USING}
            WITH CHECK {_POLICY_USING};
        """)


def downgrade() -> None:
    for tbl in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS rls_source_scoped ON {tbl};")
        op.execute(f"ALTER TABLE {tbl} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY;")
