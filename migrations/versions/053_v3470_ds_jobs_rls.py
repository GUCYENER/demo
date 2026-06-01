"""v3.47.0 P3b — ds_discovery_jobs company-scoped RLS (FK Loop job state tenant izolasyonu)

Revision ID: 053_v3470_ds_jobs_rls
Revises: 052_v3460_synthetic_error_kind
Create Date: 2026-06-01

FK Loop job state'i in-memory dict'ten ds_discovery_jobs'a taşınıyor (multi-worker görünürlük).
Bu tablo BUGÜNE KADAR RLS'siz (mig 007 source-scoped + mig 017 company-scoped listelerinin
hiçbirinde değil) — job state'i DB'ye taşımak tek başına tenant izolasyonu SAĞLAMAZ. Bu migration
company-scoped RLS ekler — mig 017 ile BİREBİR aynı permissive policy (tutarlılık; FORCE YOK,
017 deseni). Asıl tenant gate'i endpoint'te (_ensure_source_visible + apply_company_scope, yabancı
source 404); bu RLS defense-in-depth.

Permissive: `app.current_company_id` GUC NULL/boş → passthrough (mevcut discovery callsite'ları
GUC set etmeden çalışmaya devam eder); set ise yalnız o company'nin satırları.

Downgrade: policy + ENABLE geri alınır.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "053_v3470_ds_jobs_rls"
down_revision: Union[str, None] = "052_v3460_synthetic_error_kind"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "ds_discovery_jobs"

# mig 017 ile birebir aynı permissive policy (current_company_id GUC + bypass_rls).
_POLICY_USING = """(
    current_setting('app.current_company_id', true) IS NULL
    OR current_setting('app.current_company_id', true) = ''
    OR current_setting('app.bypass_rls', true) = 'on'
    OR company_id::text = current_setting('app.current_company_id', true)
)"""

_POLICY_CHECK = """(
    current_setting('app.current_company_id', true) IS NULL
    OR current_setting('app.current_company_id', true) = ''
    OR current_setting('app.bypass_rls', true) = 'on'
    OR company_id::text = current_setting('app.current_company_id', true)
)"""


def upgrade() -> None:
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"DROP POLICY IF EXISTS rls_company_scoped ON {_TABLE};")
    op.execute(f"""
        CREATE POLICY rls_company_scoped ON {_TABLE}
            FOR ALL
            USING {_POLICY_USING}
            WITH CHECK {_POLICY_CHECK};
    """)
    print("[mig 053_v3470] ds_discovery_jobs company-scoped RLS ready")


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS rls_company_scoped ON {_TABLE};")
    op.execute(f"ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY;")
