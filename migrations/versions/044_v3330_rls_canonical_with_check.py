"""v3.33.0 RLS-strict — canonical USING + explicit WITH CHECK on ds_schema_record_warnings

Revision ID: 044_v3330_rls_canonical_with_check
Revises: 043_v3320_bulk_phase2
Create Date: 2026-05-23

Refactor scope: R005 + R006 (mini refactor sprint, v3.33.0)
-----------------------------------------------------------
Bkz: .agents/refactor/REFACTOR_BACKLOG.md
- R005: USING clause order mig 017 canonical pattern'a hizalanır + `IS NULL` branch
  geri eklenir. Davranış pratikte aynıdır (PG `current_setting(..., true)` unset
  durumda `''` döner, NULL değil) ama audit/grep `_POLICY_USING_PERMISSIVE`
  pattern'ını arayan araçlar `ds_schema_record_warnings` policy'sini bulamıyordu.
- R006: `FOR ALL` policy'sinde implicit `WITH CHECK = USING` davranışı, BG worker
  `apply_company_scope` çağırmadan INSERT yapabildiği durumda (boş setting →
  `= ''` permissive branch sayesinde) sessiz şirket-izolasyon kaybına yol açıyordu.
  WITH CHECK ayrı tanımlanır ve YAZMA için strict yapılır: setting boş olamaz,
  yalnız bypass VEYA `company_id::text = current_setting(...)` izinli. Okuma
  (USING) yan etkisiz olduğu için permissive kalır (geriye uyumluluk — eski
  okuma callsite'ları sessiz kırılmasın).

Tamamlayıcı app değişiklikleri (aynı commit'te):
- `app/core/db.py:apply_company_scope` — company_id verildi ama `set_config`
  fail olursa artık `RuntimeError` raise eder (önceki `except: pass` silent
  fail → strict WITH CHECK ile birlikte veri kaybı riski yaratıyordu).
- `app/api/routes/data_sources_api.py:_generate_schema_records_background`
  warning INSERT bloğu artık `apply_company_scope(cur, company_id=...)` ile
  çevriliyor (önceki `get_db_context()` cursor'unda scope set edilmiyordu;
  yeni WITH CHECK strict olduğu için INSERT reddedilirdi).

Notlar:
- Aynı policy adı (`ds_schema_warn_company_isolation`) korunur — drop+create.
- Mig 017 stilinde `_POLICY_USING_PERMISSIVE` ve `_POLICY_CHECK_STRICT` module
  konstantları kullanılır (audit/grep dostu).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "044_v3330_rls_canonical_with_check"
# NOT: Tuple down_revision — repository'de paralel iki head vardı
# (`042_v3320_merge_error_review_fernet` ve `043_v3320_bulk_phase2` arasında
# eksik merge migration). Bu dosya hem merge migration hem RLS canonical
# patch görevini birlikte üstleniyor (tek dosya — refactor sprintinde ayrı
# bir boş merge dosyası açmamak için).
down_revision: Union[str, Sequence[str], None] = (
    "042_v3320_merge_error_review_fernet",
    "043_v3320_bulk_phase2",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mig 017 canonical (read path — permissive; geriye uyumlu)
_POLICY_USING_PERMISSIVE = """(
    current_setting('app.current_company_id', true) IS NULL
    OR current_setting('app.current_company_id', true) = ''
    OR current_setting('app.bypass_rls', true) = 'on'
    OR company_id::text = current_setting('app.current_company_id', true)
)"""

# R006 — yazma yolu STRICT: setting boş olamaz; ya bypass ya da eşleşme şart.
# `IS NULL` ve `= ''` BRANCH'LERİ KASITLI OLARAK YOK — silent isolation
# loss önlenir (apply_company_scope çağrılmadan INSERT yapılamaz).
_POLICY_CHECK_STRICT = """(
    current_setting('app.bypass_rls', true) = 'on'
    OR company_id::text = current_setting('app.current_company_id', true)
)"""


def upgrade() -> None:
    # Drop existing PERMISSIVE-only policy and re-create with canonical USING
    # + explicit strict WITH CHECK.
    op.execute(
        "DROP POLICY IF EXISTS ds_schema_warn_company_isolation "
        "ON ds_schema_record_warnings;"
    )
    op.execute(f"""
    CREATE POLICY ds_schema_warn_company_isolation ON ds_schema_record_warnings
        AS PERMISSIVE FOR ALL TO PUBLIC
        USING {_POLICY_USING_PERMISSIVE}
        WITH CHECK {_POLICY_CHECK_STRICT};
    """)


def downgrade() -> None:
    # Revert to mig 043 original form (no explicit WITH CHECK; non-canonical USING).
    op.execute(
        "DROP POLICY IF EXISTS ds_schema_warn_company_isolation "
        "ON ds_schema_record_warnings;"
    )
    op.execute("""
    CREATE POLICY ds_schema_warn_company_isolation ON ds_schema_record_warnings
        AS PERMISSIVE FOR ALL TO PUBLIC
        USING (
            current_setting('app.bypass_rls', true) = 'on'
            OR company_id::text = current_setting('app.current_company_id', true)
            OR current_setting('app.current_company_id', true) = ''
        );
    """)
