"""Baseline: Mevcut VYRA schema (tüm tablolar ve indexler)

Revision ID: 001_baseline
Revises: None
Create Date: 2026-02-15
"""
from typing import Sequence, Union
from alembic import op

# revision identifiers
revision: str = "001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Mevcut VYRA schema'sını baseline olarak oluşturur."""

    # =========================================================
    # 1. Tablolar (bağımlılık sırasıyla)
    # =========================================================

    op.execute("""
    -- Roller
    CREATE TABLE IF NOT EXISTS roles (
        id SERIAL PRIMARY KEY,
        name VARCHAR(50) NOT NULL UNIQUE,
        description VARCHAR(255),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    INSERT INTO roles (name, description) VALUES
        ('admin', 'Sistem yöneticisi - Tüm yetkiler'),
        ('user', 'Standart kullanıcı')
    ON CONFLICT (name) DO NOTHING;

    -- Kullanıcılar (organization_groups'tan ÖNCE — FK bağımlılığı)
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        full_name VARCHAR(255) NOT NULL,
        username VARCHAR(100) NOT NULL UNIQUE,
        email VARCHAR(255) NOT NULL UNIQUE,
        phone VARCHAR(20) NOT NULL,
        password TEXT NOT NULL,
        avatar TEXT,
        role_id INTEGER REFERENCES roles(id) DEFAULT 2,
        is_admin BOOLEAN DEFAULT FALSE,
        is_approved BOOLEAN DEFAULT FALSE,
        approved_by INTEGER REFERENCES users(id),
        approved_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Organizasyon Grupları (users'tan SONRA — created_by FK)
    CREATE TABLE IF NOT EXISTS organization_groups (
        id SERIAL PRIMARY KEY,
        org_code VARCHAR(50) UNIQUE NOT NULL,
        org_name VARCHAR(255) NOT NULL,
        description TEXT,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_by INTEGER REFERENCES users(id),
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Kullanıcı-Organizasyon İlişkisi
    CREATE TABLE IF NOT EXISTS user_organizations (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        org_id INTEGER NOT NULL REFERENCES organization_groups(id) ON DELETE CASCADE,
        assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        assigned_by INTEGER REFERENCES users(id),
        UNIQUE(user_id, org_id)
    );

    -- Ticket'lar
    CREATE TABLE IF NOT EXISTS tickets (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        title VARCHAR(500) NOT NULL,
        description TEXT NOT NULL,
        source_type VARCHAR(100),
        source_name VARCHAR(255),
        final_solution TEXT,
        cym_text TEXT,
        cym_portal_url VARCHAR(500),
        llm_evaluation TEXT,
        rag_results JSONB DEFAULT '[]',
        interaction_type VARCHAR(50) DEFAULT 'rag_only',
        source_org_ids INTEGER[] DEFAULT '{}',
        status VARCHAR(50) NOT NULL DEFAULT 'open',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Ticket adımları
    CREATE TABLE IF NOT EXISTS ticket_steps (
        id SERIAL PRIMARY KEY,
        ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
        step_order INTEGER NOT NULL,
        step_title VARCHAR(500) NOT NULL,
        step_body TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Ticket mesajları
    CREATE TABLE IF NOT EXISTS ticket_messages (
        id SERIAL PRIMARY KEY,
        ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
        sender VARCHAR(50) NOT NULL,
        message TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Çözüm logları
    CREATE TABLE IF NOT EXISTS solution_logs (
        id SERIAL PRIMARY KEY,
        ticket_id INTEGER NOT NULL REFERENCES tickets(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        topic VARCHAR(500) NOT NULL,
        description TEXT NOT NULL,
        source_type VARCHAR(100) NOT NULL,
        final_solution TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- LLM konfigürasyonları
    CREATE TABLE IF NOT EXISTS llm_config (
        id SERIAL PRIMARY KEY,
        vendor_code VARCHAR(100),
        provider VARCHAR(100) NOT NULL,
        model_name VARCHAR(255) NOT NULL,
        api_url VARCHAR(500) NOT NULL,
        api_token TEXT,
        temperature REAL DEFAULT 0.7,
        top_p REAL DEFAULT 1.0,
        timeout_seconds INTEGER DEFAULT 60,
        is_active BOOLEAN DEFAULT FALSE,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Sistem logları
    CREATE TABLE IF NOT EXISTS system_logs (
        id SERIAL PRIMARY KEY,
        level VARCHAR(20) NOT NULL,
        message TEXT NOT NULL,
        module VARCHAR(100),
        user_id INTEGER REFERENCES users(id),
        request_path VARCHAR(500),
        request_method VARCHAR(10),
        response_status INTEGER,
        error_detail TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Prompt şablonları
    CREATE TABLE IF NOT EXISTS prompt_templates (
        id SERIAL PRIMARY KEY,
        category VARCHAR(100) NOT NULL,
        title VARCHAR(255) NOT NULL,
        content TEXT NOT NULL,
        is_active BOOLEAN DEFAULT FALSE,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Yüklenen dosyalar
    CREATE TABLE IF NOT EXISTS uploaded_files (
        id SERIAL PRIMARY KEY,
        file_name VARCHAR(500) NOT NULL,
        file_type VARCHAR(50) NOT NULL,
        file_size_bytes BIGINT,
        file_content BYTEA NOT NULL,
        mime_type VARCHAR(100),
        chunk_count INTEGER DEFAULT 0,
        maturity_score REAL DEFAULT NULL,
        status VARCHAR(20) DEFAULT 'completed',
        uploaded_by INTEGER REFERENCES users(id),
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- RAG Chunk'ları
    CREATE TABLE IF NOT EXISTS rag_chunks (
        id SERIAL PRIMARY KEY,
        file_id INTEGER NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
        chunk_index INTEGER NOT NULL,
        chunk_text TEXT NOT NULL,
        embedding FLOAT[] DEFAULT NULL,
        metadata JSONB,
        quality_score FLOAT DEFAULT 0.5,
        topic_label VARCHAR(100),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Doküman-Organizasyon
    CREATE TABLE IF NOT EXISTS document_organizations (
        id SERIAL PRIMARY KEY,
        file_id INTEGER NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
        org_id INTEGER NOT NULL REFERENCES organization_groups(id) ON DELETE CASCADE,
        assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        assigned_by INTEGER REFERENCES users(id),
        UNIQUE(file_id, org_id)
    );

    -- Doküman görselleri
    CREATE TABLE IF NOT EXISTS document_images (
        id SERIAL PRIMARY KEY,
        file_id INTEGER NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
        image_index INTEGER NOT NULL,
        image_data BYTEA NOT NULL,
        image_format VARCHAR(10) NOT NULL,
        width_px INTEGER,
        height_px INTEGER,
        file_size_bytes INTEGER,
        context_heading VARCHAR(500),
        context_chunk_index INTEGER,
        alt_text TEXT DEFAULT '',
        ocr_text TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- User Feedback (CatBoost)
    CREATE TABLE IF NOT EXISTS user_feedback (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
        chunk_id INTEGER REFERENCES rag_chunks(id) ON DELETE SET NULL,
        feedback_type VARCHAR(50) NOT NULL,
        query_text TEXT,
        response_text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- User Topic Affinity
    CREATE TABLE IF NOT EXISTS user_topic_affinity (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        topic VARCHAR(100) NOT NULL,
        affinity_score FLOAT DEFAULT 0.5,
        query_count INTEGER DEFAULT 0,
        success_count INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, topic)
    );

    -- ML Models
    CREATE TABLE IF NOT EXISTS ml_models (
        id SERIAL PRIMARY KEY,
        model_name VARCHAR(100) NOT NULL,
        model_version VARCHAR(50) NOT NULL,
        model_path VARCHAR(500) NOT NULL,
        model_type VARCHAR(50) DEFAULT 'catboost',
        is_active BOOLEAN DEFAULT FALSE,
        metrics JSONB,
        feature_names TEXT[],
        trained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        trained_by INTEGER REFERENCES users(id),
        training_samples INTEGER,
        UNIQUE(model_name, model_version)
    );

    -- ML Training Jobs
    CREATE TABLE IF NOT EXISTS ml_training_jobs (
        id SERIAL PRIMARY KEY,
        job_name VARCHAR(100) NOT NULL,
        job_type VARCHAR(20) NOT NULL DEFAULT 'manual',
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        trigger_condition VARCHAR(100),
        start_time TIMESTAMP,
        end_time TIMESTAMP,
        duration_seconds INTEGER,
        training_samples INTEGER,
        model_id INTEGER REFERENCES ml_models(id),
        error_message TEXT,
        created_by INTEGER REFERENCES users(id),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- ML Training Samples
    CREATE TABLE IF NOT EXISTS ml_training_samples (
        id SERIAL PRIMARY KEY,
        job_id INTEGER NOT NULL REFERENCES ml_training_jobs(id) ON DELETE CASCADE,
        query TEXT NOT NULL,
        chunk_text TEXT,
        source_file VARCHAR(255),
        intent VARCHAR(50),
        relevance_label INTEGER DEFAULT 1,
        score NUMERIC(5,3),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- ML Training Schedules
    CREATE TABLE IF NOT EXISTS ml_training_schedules (
        id SERIAL PRIMARY KEY,
        schedule_name VARCHAR(100) NOT NULL,
        trigger_type VARCHAR(50) NOT NULL,
        trigger_value VARCHAR(100) NOT NULL,
        is_active BOOLEAN DEFAULT FALSE,
        last_triggered_at TIMESTAMP,
        next_trigger_at TIMESTAMP,
        created_by INTEGER REFERENCES users(id),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Dialog oturumları
    CREATE TABLE IF NOT EXISTS dialogs (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title VARCHAR(255),
        source_type VARCHAR(50) DEFAULT 'vyra_chat',
        status VARCHAR(20) DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        closed_at TIMESTAMP
    );

    -- Dialog mesajları
    CREATE TABLE IF NOT EXISTS dialog_messages (
        id SERIAL PRIMARY KEY,
        dialog_id INTEGER NOT NULL REFERENCES dialogs(id) ON DELETE CASCADE,
        role VARCHAR(20) NOT NULL,
        content TEXT NOT NULL,
        content_type VARCHAR(20) DEFAULT 'text',
        metadata JSONB,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- System Assets
    CREATE TABLE IF NOT EXISTS system_assets (
        id SERIAL PRIMARY KEY,
        asset_key VARCHAR(100) NOT NULL UNIQUE,
        asset_name VARCHAR(255) NOT NULL,
        mime_type VARCHAR(100) NOT NULL,
        asset_data BYTEA NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- System Settings
    CREATE TABLE IF NOT EXISTS system_settings (
        id SERIAL PRIMARY KEY,
        setting_key VARCHAR(100) NOT NULL UNIQUE,
        setting_value TEXT NOT NULL,
        description VARCHAR(255),
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_by INTEGER REFERENCES users(id)
    );

    INSERT INTO system_settings (setting_key, setting_value, description) VALUES
        ('app_version', '2.40.0', 'Uygulama versiyonu'),
        ('cl_interval_minutes', '30', 'Sürekli öğrenme aralığı (dakika)'),
        ('cl_is_active', 'true', 'Sürekli öğrenme aktiflik durumu'),
        ('maturity_enhance_threshold', '80', 'Maturity iyileştirme eşik değeri (0-100)')
    ON CONFLICT (setting_key) DO NOTHING;

    -- Document Topics
    CREATE TABLE IF NOT EXISTS document_topics (
        id SERIAL PRIMARY KEY,
        topic_name VARCHAR(100) NOT NULL UNIQUE,
        keywords TEXT[] NOT NULL DEFAULT '{}',
        source_file_ids INTEGER[] DEFAULT '{}',
        auto_generated BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # =========================================================
    # 2. Tüm Indexler
    # =========================================================

    op.execute("""
    -- Users
    CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
    CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
    CREATE INDEX IF NOT EXISTS idx_users_role_id ON users(role_id);
    CREATE INDEX IF NOT EXISTS idx_users_is_approved ON users(is_approved);
    CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone);

    -- Tickets
    CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id);
    CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
    CREATE INDEX IF NOT EXISTS idx_tickets_created_at ON tickets(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_tickets_source_type ON tickets(source_type);

    -- Ticket Steps
    CREATE INDEX IF NOT EXISTS idx_ticket_steps_ticket_id ON ticket_steps(ticket_id);
    CREATE INDEX IF NOT EXISTS idx_ticket_steps_order ON ticket_steps(ticket_id, step_order);

    -- Ticket Messages
    CREATE INDEX IF NOT EXISTS idx_ticket_messages_ticket_id ON ticket_messages(ticket_id);
    CREATE INDEX IF NOT EXISTS idx_ticket_messages_created ON ticket_messages(created_at DESC);

    -- Solution Logs
    CREATE INDEX IF NOT EXISTS idx_solution_logs_ticket_id ON solution_logs(ticket_id);
    CREATE INDEX IF NOT EXISTS idx_solution_logs_user_id ON solution_logs(user_id);
    CREATE INDEX IF NOT EXISTS idx_solution_logs_created_at ON solution_logs(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_solution_logs_source_type ON solution_logs(source_type);

    -- LLM Config
    CREATE INDEX IF NOT EXISTS idx_llm_config_is_active ON llm_config(is_active);
    CREATE INDEX IF NOT EXISTS idx_llm_config_vendor_code ON llm_config(vendor_code);

    -- System Logs
    CREATE INDEX IF NOT EXISTS idx_system_logs_level ON system_logs(level);
    CREATE INDEX IF NOT EXISTS idx_system_logs_created_at ON system_logs(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_system_logs_user_id ON system_logs(user_id);
    CREATE INDEX IF NOT EXISTS idx_system_logs_module ON system_logs(module);

    -- Prompt Templates
    CREATE INDEX IF NOT EXISTS idx_prompt_templates_is_active ON prompt_templates(is_active);
    CREATE INDEX IF NOT EXISTS idx_prompt_templates_category ON prompt_templates(category);

    -- Uploaded Files
    CREATE INDEX IF NOT EXISTS idx_uploaded_files_file_name ON uploaded_files(file_name);
    CREATE INDEX IF NOT EXISTS idx_uploaded_files_uploaded_by ON uploaded_files(uploaded_by);
    CREATE INDEX IF NOT EXISTS idx_uploaded_files_uploaded_at ON uploaded_files(uploaded_at DESC);
    CREATE INDEX IF NOT EXISTS idx_uploaded_files_file_type ON uploaded_files(file_type);

    -- RAG Chunks
    CREATE INDEX IF NOT EXISTS idx_rag_chunks_file_id ON rag_chunks(file_id);
    CREATE INDEX IF NOT EXISTS idx_rag_chunks_chunk_index ON rag_chunks(file_id, chunk_index);
    CREATE INDEX IF NOT EXISTS idx_rag_chunks_quality ON rag_chunks(quality_score DESC);
    CREATE INDEX IF NOT EXISTS idx_rag_chunks_topic ON rag_chunks(topic_label);

    -- Organization Groups
    CREATE INDEX IF NOT EXISTS idx_org_groups_is_active ON organization_groups(is_active);
    CREATE INDEX IF NOT EXISTS idx_org_groups_org_code ON organization_groups(org_code);

    -- User Organizations
    CREATE INDEX IF NOT EXISTS idx_user_orgs_user ON user_organizations(user_id);
    CREATE INDEX IF NOT EXISTS idx_user_orgs_org ON user_organizations(org_id);

    -- Document Organizations
    CREATE INDEX IF NOT EXISTS idx_doc_orgs_file ON document_organizations(file_id);
    CREATE INDEX IF NOT EXISTS idx_doc_orgs_org ON document_organizations(org_id);

    -- Document Images
    CREATE INDEX IF NOT EXISTS idx_document_images_file_id ON document_images(file_id);
    CREATE INDEX IF NOT EXISTS idx_document_images_context ON document_images(file_id, context_chunk_index);

    -- User Feedback
    CREATE INDEX IF NOT EXISTS idx_user_feedback_user ON user_feedback(user_id);
    CREATE INDEX IF NOT EXISTS idx_user_feedback_chunk ON user_feedback(chunk_id);
    CREATE INDEX IF NOT EXISTS idx_user_feedback_ticket ON user_feedback(ticket_id);
    CREATE INDEX IF NOT EXISTS idx_user_feedback_type ON user_feedback(feedback_type);
    CREATE INDEX IF NOT EXISTS idx_user_feedback_created ON user_feedback(created_at DESC);

    -- User Topic Affinity
    CREATE INDEX IF NOT EXISTS idx_user_affinity_user ON user_topic_affinity(user_id);
    CREATE INDEX IF NOT EXISTS idx_user_affinity_topic ON user_topic_affinity(topic);
    CREATE INDEX IF NOT EXISTS idx_user_affinity_score ON user_topic_affinity(affinity_score DESC);

    -- ML Models
    CREATE INDEX IF NOT EXISTS idx_ml_models_active ON ml_models(is_active);
    CREATE INDEX IF NOT EXISTS idx_ml_models_name ON ml_models(model_name);

    -- ML Training Jobs
    CREATE INDEX IF NOT EXISTS idx_ml_training_jobs_status ON ml_training_jobs(status);
    CREATE INDEX IF NOT EXISTS idx_ml_training_jobs_created ON ml_training_jobs(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_ml_training_jobs_job_type ON ml_training_jobs(job_type);
    CREATE INDEX IF NOT EXISTS idx_ml_training_jobs_model_id ON ml_training_jobs(model_id);
    CREATE INDEX IF NOT EXISTS idx_ml_training_jobs_created_by ON ml_training_jobs(created_by);

    -- ML Training Samples
    CREATE INDEX IF NOT EXISTS idx_training_samples_job ON ml_training_samples(job_id);

    -- ML Training Schedules
    CREATE INDEX IF NOT EXISTS idx_ml_schedules_is_active ON ml_training_schedules(is_active);
    CREATE INDEX IF NOT EXISTS idx_ml_schedules_trigger_type ON ml_training_schedules(trigger_type);

    -- Dialogs
    CREATE INDEX IF NOT EXISTS idx_dialogs_user ON dialogs(user_id);
    CREATE INDEX IF NOT EXISTS idx_dialogs_status ON dialogs(status);
    CREATE INDEX IF NOT EXISTS idx_dialogs_updated ON dialogs(updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_dialogs_source_type ON dialogs(source_type);

    -- Dialog Messages
    CREATE INDEX IF NOT EXISTS idx_dialog_messages_dialog ON dialog_messages(dialog_id);
    CREATE INDEX IF NOT EXISTS idx_dialog_messages_created ON dialog_messages(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_dialog_messages_role ON dialog_messages(role);

    -- System Assets
    CREATE INDEX IF NOT EXISTS idx_system_assets_key ON system_assets(asset_key);

    -- System Settings
    CREATE INDEX IF NOT EXISTS idx_system_settings_key ON system_settings(setting_key);

    -- Document Topics
    CREATE INDEX IF NOT EXISTS idx_document_topics_name ON document_topics(topic_name);
    """)


def downgrade() -> None:
    """Tüm tabloları ters bağımlılık sırasıyla kaldırır."""
    tables = [
        "document_topics",
        "system_settings",
        "system_assets",
        "dialog_messages",
        "dialogs",
        "ml_training_schedules",
        "ml_training_samples",
        "ml_training_jobs",
        "ml_models",
        "user_topic_affinity",
        "user_feedback",
        "document_images",
        "document_organizations",
        "rag_chunks",
        "uploaded_files",
        "prompt_templates",
        "system_logs",
        "llm_config",
        "solution_logs",
        "ticket_messages",
        "ticket_steps",
        "tickets",
        "user_organizations",
        "users",
        "organization_groups",
        "roles",
    ]
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
