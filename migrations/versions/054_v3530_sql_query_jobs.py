"""v3.53.0 — sql_query_jobs: async SQL sorgu job'ları cross-worker iptal tablosu

Revision ID: 054_v3530_sql_query_jobs
Revises: 053_v3470_ds_jobs_rls
Create Date: 2026-06-02

Sorun: deep_think async SQL execute job'ı `_SQL_JOB_REGISTRY` (safe_sql_executor.py) in-memory
worker-local dict'te tutuluyordu. Canlıda 3 worker (8002-8004) → "İptal Et" isteği işi ÇALIŞTIRAN
worker'a düşmezse registry boş → "Job bulunamadı" 404 (aktif sorguda bile).

Çözüm: bu tablo cross-worker cancel sinyalini taşır. register_sql_job INSERT eder (status='running');
cancel_sql_job (herhangi bir worker) status='cancel_requested' yazar; çalışan job (başka worker)
TICK döngüsünde bu satırı poll edip local cancel_event'i set eder → kendini iptal eder.

Idempotent (CREATE TABLE/INDEX IF NOT EXISTS). schema.py SCHEMA_SQL'de de mevcut (startup fallback).
Downgrade: tabloyu düşürür.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "054_v3530_sql_query_jobs"
down_revision: Union[str, None] = "053_v3470_ds_jobs_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS sql_query_jobs (
            job_id VARCHAR(64) PRIMARY KEY,
            owner_user_id INTEGER NOT NULL,
            dialog_id INTEGER,
            status VARCHAR(20) NOT NULL DEFAULT 'running',
            started_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_sql_query_jobs_status ON sql_query_jobs(status);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sql_query_jobs_started ON sql_query_jobs(started_at);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sql_query_jobs;")
