"""v3.26.0: company-level RLS — agentic/few_shot/catboost/pipeline_events tabloları

Revision ID: 017_v3260_rls_tenant_tables
Revises: 016_v3250_pipeline_events
Create Date: 2026-05-17

Faz 1 — P0-a: Defense-in-depth tenant izolasyonu (DB-level)
-----------------------------------------------------------
Mevcut RLS (007/008) ``ds_*`` tablolarında `app.current_source_id` üzerinden
SOURCE-scoped izolasyon sağlar. Bu migration TENANT-scoped (company_id) RLS'i
şu tablolara ekler:

    - agentic_query_feedback   (CatBoost training verisi)
    - few_shot_examples         (validated NL→SQL örnek havuzu)
    - catboost_models           (model versiyonlama)
    - pipeline_events           (observability log)

Policy: PERMISSIVE (geriye uyumluluk)
--------------------------------------
``app.current_company_id`` setting NULL/boşsa passthrough — mevcut callsite
refactor edilmeden migration uygulanabilir. Tüm callsite'lar
``get_db_context_scoped_company(company_id)`` veya ``bypass=True`` kullanmaya
geçince ileride bir migration (018) **strict** policy'ye dönecek.

    USING (
        current_setting('app.current_company_id', true) IS NULL
        OR current_setting('app.current_company_id', true) = ''
        OR current_setting('app.bypass_rls', true) = 'on'
        OR company_id::text = current_setting('app.current_company_id', true)
    )

UYARI: RLS yalnızca app rolü non-superuser ise etkilidir. Bkz: 008 migration
uyarısı + `app/api/main.py:_warn_if_db_user_bypasses_rls`.

pipeline_events.company_id NULLABLE — NULL company_id satırlar yalnız
bypass=on iken görülür (analytics ihtiyacı). INSERT WITH CHECK NULL'a izin
verir (system-level event'ler için).
"""
from typing import Sequence, Union
from alembic import op

revision: str = "017_v3260_rls_tenant_tables"
down_revision: Union[str, None] = "016_v3250_pipeline_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES = (
    "agentic_query_feedback",
    "few_shot_examples",
    "catboost_models",
    "pipeline_events",
)

_POLICY_USING_PERMISSIVE = """(
    current_setting('app.current_company_id', true) IS NULL
    OR current_setting('app.current_company_id', true) = ''
    OR current_setting('app.bypass_rls', true) = 'on'
    OR company_id::text = current_setting('app.current_company_id', true)
)"""

# WITH CHECK: NULL company_id'ye izin ver (pipeline_events için sistem event'leri)
_POLICY_CHECK_PERMISSIVE = """(
    current_setting('app.current_company_id', true) IS NULL
    OR current_setting('app.current_company_id', true) = ''
    OR current_setting('app.bypass_rls', true) = 'on'
    OR company_id IS NULL
    OR company_id::text = current_setting('app.current_company_id', true)
)"""


def upgrade() -> None:
    for tbl in _TABLES:
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS rls_company_scoped ON {tbl};")
        op.execute(f"""
        CREATE POLICY rls_company_scoped ON {tbl}
            FOR ALL
            USING {_POLICY_USING_PERMISSIVE}
            WITH CHECK {_POLICY_CHECK_PERMISSIVE};
        """)


def downgrade() -> None:
    for tbl in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS rls_company_scoped ON {tbl};")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY;")
