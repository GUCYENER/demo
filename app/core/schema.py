"""
VYRA L1 Support API - Database Schema
======================================
PostgreSQL tablo şemaları ve index tanımları.
Tüm CREATE TABLE ve CREATE INDEX ifadeleri burada bulunur.

Version: 2.0.0 (Organization-Based Authorization)
"""

SCHEMA_SQL = """
-- =====================================================
-- VYRA L1 Support API - PostgreSQL Schema
-- Version: 2.0.0 (Organization-Based Authorization)
-- =====================================================

-- Roller tablosu
CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    description VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Varsayılan roller
INSERT INTO roles (name, description) VALUES 
    ('admin', 'Sistem yöneticisi - Tüm yetkiler'),
    ('user', 'Standart kullanıcı')
ON CONFLICT (name) DO NOTHING;

-- Organizasyon Grupları (Yeni)
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

-- Kullanıcılar tablosu
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

-- Users indexes
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role_id ON users(role_id);
CREATE INDEX IF NOT EXISTS idx_users_is_approved ON users(is_approved);

-- Kullanıcı-Organizasyon İlişkisi (Many-to-Many) (Yeni)
CREATE TABLE IF NOT EXISTS user_organizations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id INTEGER NOT NULL REFERENCES organization_groups(id) ON DELETE CASCADE,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    assigned_by INTEGER REFERENCES users(id),
    UNIQUE(user_id, org_id)
);

-- Ticket'lar tablosu
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
    llm_evaluation TEXT,  -- Corpix AI Değerlendirmesi
    rag_results JSONB DEFAULT '[]',  -- 🆕 RAG sonuçları (chunk listesi)
    interaction_type VARCHAR(50) DEFAULT 'rag_only',  -- 🆕 rag_only, user_selection, ai_evaluation
    source_org_ids INTEGER[] DEFAULT '{}',  -- 🔒 Ticket oluşturulurken kullanılan org grupları
    status VARCHAR(50) NOT NULL DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tickets indexes
CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_created_at ON tickets(created_at DESC);

-- Migration: llm_evaluation alanını ekle (yoksa)
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS llm_evaluation TEXT;

-- Migration: rag_results ve interaction_type alanlarını ekle (v2.23.0)
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS rag_results JSONB DEFAULT '[]';
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS interaction_type VARCHAR(50) DEFAULT 'rag_only';

-- Ticket adımları
CREATE TABLE IF NOT EXISTS ticket_steps (
    id SERIAL PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    step_title VARCHAR(500) NOT NULL,
    step_body TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Ticket mesajları (chat history)
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

-- Yüklenen dosyalar (RAG için - dosya içeriği BYTEA olarak saklanır)
CREATE TABLE IF NOT EXISTS uploaded_files (
    id SERIAL PRIMARY KEY,
    file_name VARCHAR(500) NOT NULL,
    file_type VARCHAR(50) NOT NULL,
    file_size_bytes BIGINT,
    file_content BYTEA NOT NULL,  -- Dosya binary olarak saklanır
    mime_type VARCHAR(100),
    chunk_count INTEGER DEFAULT 0,  -- RAG için oluşturulan chunk sayısı
    maturity_score REAL DEFAULT NULL,  -- Dosya olgunluk skoru (0-100)
    status VARCHAR(20) DEFAULT 'completed',  -- Dosya işleme durumu: processing, completed, failed
    uploaded_by INTEGER REFERENCES users(id),
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- RAG Chunk'ları (vektör araması için)
CREATE TABLE IF NOT EXISTS rag_chunks (
    id SERIAL PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding FLOAT[] DEFAULT NULL,  -- Vektör embedding (384 boyut)
    metadata JSONB,  -- Sayfa numarası, başlık vb.
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Doküman-Organizasyon İlişkisi (Many-to-Many) (Yeni)
CREATE TABLE IF NOT EXISTS document_organizations (
    id SERIAL PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
    org_id INTEGER NOT NULL REFERENCES organization_groups(id) ON DELETE CASCADE,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    assigned_by INTEGER REFERENCES users(id),
    UNIQUE(file_id, org_id)
);

-- Doküman içi görseller (RAG yanıtlarında gösterim için)
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
    next_heading VARCHAR(500),
    page_number INTEGER,
    context_chunk_index INTEGER,
    alt_text TEXT DEFAULT '',
    ocr_text TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_document_images_file_id ON document_images(file_id);
CREATE INDEX IF NOT EXISTS idx_document_images_context ON document_images(file_id, context_chunk_index);
CREATE INDEX IF NOT EXISTS idx_document_images_heading ON document_images(file_id, context_heading);

-- v3.4.8: Görsel heading matrisi ve sayfa bilgisi
ALTER TABLE document_images ADD COLUMN IF NOT EXISTS next_heading VARCHAR(500);
ALTER TABLE document_images ADD COLUMN IF NOT EXISTS page_number INTEGER;

-- =====================================================
-- Performance Indexes
-- =====================================================

-- Users indexes
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role_id ON users(role_id);
CREATE INDEX IF NOT EXISTS idx_users_is_approved ON users(is_approved);
CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone);

-- Tickets indexes
CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_created_at ON tickets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tickets_source_type ON tickets(source_type);  -- 🆕 v2.33.2

-- Ticket Steps indexes
CREATE INDEX IF NOT EXISTS idx_ticket_steps_ticket_id ON ticket_steps(ticket_id);
CREATE INDEX IF NOT EXISTS idx_ticket_steps_order ON ticket_steps(ticket_id, step_order);  -- 🆕 v2.33.2 composite

-- Ticket Messages indexes (YENİ)
CREATE INDEX IF NOT EXISTS idx_ticket_messages_ticket_id ON ticket_messages(ticket_id);
CREATE INDEX IF NOT EXISTS idx_ticket_messages_created ON ticket_messages(created_at DESC);  -- 🆕 v2.33.2

-- Solution Logs indexes (YENİ)
CREATE INDEX IF NOT EXISTS idx_solution_logs_ticket_id ON solution_logs(ticket_id);
CREATE INDEX IF NOT EXISTS idx_solution_logs_user_id ON solution_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_solution_logs_created_at ON solution_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_solution_logs_source_type ON solution_logs(source_type);  -- 🆕 v2.33.2

-- LLM Config indexes
CREATE INDEX IF NOT EXISTS idx_llm_config_is_active ON llm_config(is_active);
CREATE INDEX IF NOT EXISTS idx_llm_config_vendor_code ON llm_config(vendor_code);

-- System Logs indexes
CREATE INDEX IF NOT EXISTS idx_system_logs_level ON system_logs(level);
CREATE INDEX IF NOT EXISTS idx_system_logs_created_at ON system_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_system_logs_user_id ON system_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_system_logs_module ON system_logs(module);

-- Prompt Templates indexes
CREATE INDEX IF NOT EXISTS idx_prompt_templates_is_active ON prompt_templates(is_active);
CREATE INDEX IF NOT EXISTS idx_prompt_templates_category ON prompt_templates(category);

-- Uploaded Files indexes
CREATE INDEX IF NOT EXISTS idx_uploaded_files_file_name ON uploaded_files(file_name);
CREATE INDEX IF NOT EXISTS idx_uploaded_files_uploaded_by ON uploaded_files(uploaded_by);
CREATE INDEX IF NOT EXISTS idx_uploaded_files_uploaded_at ON uploaded_files(uploaded_at DESC);
CREATE INDEX IF NOT EXISTS idx_uploaded_files_file_type ON uploaded_files(file_type);  -- 🆕 v2.33.2

-- RAG Chunks indexes
CREATE INDEX IF NOT EXISTS idx_rag_chunks_file_id ON rag_chunks(file_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_chunk_index ON rag_chunks(file_id, chunk_index);

-- Organization Groups indexes
CREATE INDEX IF NOT EXISTS idx_org_groups_is_active ON organization_groups(is_active);
CREATE INDEX IF NOT EXISTS idx_org_groups_org_code ON organization_groups(org_code);

-- User-Organization indexes
CREATE INDEX IF NOT EXISTS idx_user_orgs_user ON user_organizations(user_id);
CREATE INDEX IF NOT EXISTS idx_user_orgs_org ON user_organizations(org_id);

-- Document-Organization indexes
CREATE INDEX IF NOT EXISTS idx_doc_orgs_file ON document_organizations(file_id);
CREATE INDEX IF NOT EXISTS idx_doc_orgs_org ON document_organizations(org_id);

-- =====================================================
-- CatBoost Hybrid Model Tables (v2.13.0)
-- =====================================================

-- RAG Chunks tablosuna yeni sütunlar (CatBoost için)
ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS quality_score FLOAT DEFAULT 0.5;
ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS topic_label VARCHAR(100);

-- Kullanıcı Feedback Tablosu (Feedback Loop)
CREATE TABLE IF NOT EXISTS user_feedback (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
    chunk_id INTEGER REFERENCES rag_chunks(id) ON DELETE SET NULL,
    feedback_type VARCHAR(50) NOT NULL,  -- 'helpful', 'not_helpful', 'copied'
    query_text TEXT,
    response_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Kullanıcı Konu Affinitesi (Kişiselleştirme)
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

-- CatBoost Model Versiyonları
CREATE TABLE IF NOT EXISTS ml_models (
    id SERIAL PRIMARY KEY,
    model_name VARCHAR(100) NOT NULL,
    model_version VARCHAR(50) NOT NULL,
    model_path VARCHAR(500) NOT NULL,
    model_type VARCHAR(50) DEFAULT 'catboost',  -- 'catboost', 'xgboost', 'lightgbm'
    is_active BOOLEAN DEFAULT FALSE,
    metrics JSONB,  -- accuracy, ndcg, f1_score vb.
    feature_names TEXT[],  -- eğitimde kullanılan feature isimleri
    trained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    trained_by INTEGER REFERENCES users(id),
    training_samples INTEGER,
    UNIQUE(model_name, model_version)
);

-- ML Training Jobs (Eğitim Geçmişi)
CREATE TABLE IF NOT EXISTS ml_training_jobs (
    id SERIAL PRIMARY KEY,
    job_name VARCHAR(100) NOT NULL,
    job_type VARCHAR(20) NOT NULL DEFAULT 'manual',  -- 'manual', 'scheduled', 'continuous'
    status VARCHAR(20) NOT NULL DEFAULT 'pending',   -- 'pending', 'running', 'completed', 'failed'
    trigger_condition VARCHAR(100),  -- 'feedback_count:500', 'manual'
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    duration_seconds INTEGER,
    training_samples INTEGER,
    model_id INTEGER REFERENCES ml_models(id),
    error_message TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ML Training Samples (Eğitim Örnekleri Detayı)
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

CREATE INDEX IF NOT EXISTS idx_training_samples_job ON ml_training_samples(job_id);

-- ML Training Schedule (Zamanlanmış Eğitim Ayarları)
CREATE TABLE IF NOT EXISTS ml_training_schedules (
    id SERIAL PRIMARY KEY,
    schedule_name VARCHAR(100) NOT NULL,
    trigger_type VARCHAR(50) NOT NULL,  -- 'feedback_count', 'interval_days', 'cron'
    trigger_value VARCHAR(100) NOT NULL,  -- '500', '7', '0 3 * * MON'
    is_active BOOLEAN DEFAULT FALSE,
    last_triggered_at TIMESTAMP,
    next_trigger_at TIMESTAMP,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- CatBoost Performance Indexes
-- =====================================================

-- User Feedback indexes
CREATE INDEX IF NOT EXISTS idx_user_feedback_user ON user_feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_user_feedback_chunk ON user_feedback(chunk_id);
CREATE INDEX IF NOT EXISTS idx_user_feedback_ticket ON user_feedback(ticket_id);
CREATE INDEX IF NOT EXISTS idx_user_feedback_type ON user_feedback(feedback_type);
CREATE INDEX IF NOT EXISTS idx_user_feedback_created ON user_feedback(created_at DESC);

-- User Topic Affinity indexes
CREATE INDEX IF NOT EXISTS idx_user_affinity_user ON user_topic_affinity(user_id);
CREATE INDEX IF NOT EXISTS idx_user_affinity_topic ON user_topic_affinity(topic);
CREATE INDEX IF NOT EXISTS idx_user_affinity_score ON user_topic_affinity(affinity_score DESC);

-- RAG Chunks yeni indexler (CatBoost için)
CREATE INDEX IF NOT EXISTS idx_rag_chunks_quality ON rag_chunks(quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_topic ON rag_chunks(topic_label);

-- ML Models indexes
CREATE INDEX IF NOT EXISTS idx_ml_models_active ON ml_models(is_active);
CREATE INDEX IF NOT EXISTS idx_ml_models_name ON ml_models(model_name);

-- ML Training Jobs indexes
CREATE INDEX IF NOT EXISTS idx_ml_training_jobs_status ON ml_training_jobs(status);
CREATE INDEX IF NOT EXISTS idx_ml_training_jobs_created ON ml_training_jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ml_training_jobs_job_type ON ml_training_jobs(job_type);  -- 🆕 v2.33.2
CREATE INDEX IF NOT EXISTS idx_ml_training_jobs_model_id ON ml_training_jobs(model_id);  -- 🆕 v2.33.2
CREATE INDEX IF NOT EXISTS idx_ml_training_jobs_created_by ON ml_training_jobs(created_by);  -- 🆕 v2.33.2

-- ML Training Schedules indexes (🆕 v2.33.2 - Daha önce hiç index yoktu!)
CREATE INDEX IF NOT EXISTS idx_ml_schedules_is_active ON ml_training_schedules(is_active);
CREATE INDEX IF NOT EXISTS idx_ml_schedules_trigger_type ON ml_training_schedules(trigger_type);

-- =====================================================
-- Dialog Chat System Tables (v2.14.0)
-- =====================================================

-- Dialog oturumları (WhatsApp tarzı çoklu mesaj)
CREATE TABLE IF NOT EXISTS dialogs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255),
    source_type VARCHAR(50) DEFAULT 'vyra_chat',  -- v2.24.0: 'vyra_chat' only
    status VARCHAR(20) DEFAULT 'active',  -- active, closed, archived
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP
);

-- Migration: dialogs source_type kolonu ekle (yoksa)
ALTER TABLE dialogs ADD COLUMN IF NOT EXISTS source_type VARCHAR(50) DEFAULT 'vyra_chat';

-- Dialog mesajları
CREATE TABLE IF NOT EXISTS dialog_messages (
    id SERIAL PRIMARY KEY,
    dialog_id INTEGER NOT NULL REFERENCES dialogs(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,  -- 'user', 'assistant', 'system'
    content TEXT NOT NULL,
    content_type VARCHAR(20) DEFAULT 'text',  -- text, image, audio, quick_reply
    metadata JSONB,  -- OCR result, RAG chunks, quick buttons, feedback
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- Dialog Chat System Indexes
-- =====================================================

-- Dialogs indexes
CREATE INDEX IF NOT EXISTS idx_dialogs_user ON dialogs(user_id);
CREATE INDEX IF NOT EXISTS idx_dialogs_status ON dialogs(status);
CREATE INDEX IF NOT EXISTS idx_dialogs_updated ON dialogs(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_dialogs_source_type ON dialogs(source_type);  -- 🆕 v2.33.2

-- Dialog Messages indexes
CREATE INDEX IF NOT EXISTS idx_dialog_messages_dialog ON dialog_messages(dialog_id);
CREATE INDEX IF NOT EXISTS idx_dialog_messages_created ON dialog_messages(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dialog_messages_role ON dialog_messages(role);

-- =====================================================
-- System Assets Table (v2.22.0) - Reset'te Korunur
-- =====================================================

-- Sistem görselleri (logo, favicon vb.) - BLOB olarak saklanır
CREATE TABLE IF NOT EXISTS system_assets (
    id SERIAL PRIMARY KEY,
    asset_key VARCHAR(100) NOT NULL UNIQUE,  -- 'favicon', 'login_logo', 'sidebar_logo'
    asset_name VARCHAR(255) NOT NULL,        -- Orijinal dosya adı
    mime_type VARCHAR(100) NOT NULL,         -- 'image/png', 'image/svg+xml'
    asset_data BYTEA NOT NULL,               -- Binary görsel verisi
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- System Assets indexes
CREATE INDEX IF NOT EXISTS idx_system_assets_key ON system_assets(asset_key);

-- =====================================================
-- System Settings Table (v2.33.0) - Key-Value Config
-- =====================================================

-- Sistem ayarları (versiyon, CL config vb.) - Reset'te korunur
CREATE TABLE IF NOT EXISTS system_settings (
    id SERIAL PRIMARY KEY,
    setting_key VARCHAR(100) NOT NULL UNIQUE,
    setting_value TEXT NOT NULL,
    description VARCHAR(255),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by INTEGER REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_system_settings_key ON system_settings(setting_key);

-- Varsayılan ayarlar
INSERT INTO system_settings (setting_key, setting_value, description) VALUES
    ('app_version', '3.4.10', 'Uygulama versiyonu'),
    ('cl_interval_minutes', '30', 'Sürekli öğrenme aralığı (dakika)'),
    ('cl_is_active', 'true', 'Sürekli öğrenme aktiflik durumu'),
    ('maturity_enhance_threshold', '80', 'Maturity iyileştirme eşik değeri (0-100)')
ON CONFLICT (setting_key) DO NOTHING;

-- =====================================================
-- Document Topics Table (v2.34.0) - Dinamik Topic Keywords
-- =====================================================

-- Dosya yüklenirken chunk içeriklerinden otomatik çıkarılan topic keyword'ler
-- CatBoost feature extractor topic detection'da kullanılır
CREATE TABLE IF NOT EXISTS document_topics (
    id SERIAL PRIMARY KEY,
    topic_name VARCHAR(100) NOT NULL UNIQUE,
    keywords TEXT[] NOT NULL DEFAULT '{}',
    source_file_ids INTEGER[] DEFAULT '{}',
    auto_generated BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_document_topics_name ON document_topics(topic_name);

-- =====================================================
-- LDAP/Active Directory Integration (v2.46.0)
-- =====================================================

-- LDAP Settings tablosu
CREATE TABLE IF NOT EXISTS ldap_settings (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(200) NOT NULL,
    url VARCHAR(500) NOT NULL,
    bind_dn VARCHAR(500) NOT NULL,
    bind_password VARCHAR(500) NOT NULL,
    search_base VARCHAR(500) NOT NULL,
    search_filter VARCHAR(500) DEFAULT '(sAMAccountName={{username}})',
    allowed_orgs TEXT[] DEFAULT '{ICT-AO-MD}',
    enabled BOOLEAN DEFAULT TRUE,
    use_ssl BOOLEAN DEFAULT FALSE,
    timeout INTEGER DEFAULT 10,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    created_by INTEGER REFERENCES users(id),
    updated_by INTEGER REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_ldap_settings_domain ON ldap_settings(domain);
CREATE INDEX IF NOT EXISTS idx_ldap_settings_enabled ON ldap_settings(enabled);

-- =====================================================
-- Domain ↔ Organizasyon Yetki Tablosu (v2.46.0)
-- =====================================================

CREATE TABLE IF NOT EXISTS domain_org_permissions (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(100) NOT NULL,
    org_code VARCHAR(100) NOT NULL,
    description VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(domain, org_code)
);

CREATE INDEX IF NOT EXISTS idx_domain_org_perm_domain ON domain_org_permissions(domain);
CREATE INDEX IF NOT EXISTS idx_domain_org_perm_active ON domain_org_permissions(is_active);

-- Users tablosuna LDAP ek alanları
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_type VARCHAR(20) DEFAULT 'local';
ALTER TABLE users ADD COLUMN IF NOT EXISTS domain VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS department VARCHAR(200);
ALTER TABLE users ADD COLUMN IF NOT EXISTS title VARCHAR(200);
ALTER TABLE users ADD COLUMN IF NOT EXISTS organization VARCHAR(200);
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_users_auth_type ON users(auth_type);
CREATE INDEX IF NOT EXISTS idx_users_domain ON users(domain);

-- Role Permissions tablosu (RBAC için, yoksa oluştur)
CREATE TABLE IF NOT EXISTS role_permissions (
    id SERIAL PRIMARY KEY,
    role_name VARCHAR(50) NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    resource_id VARCHAR(100) NOT NULL,
    resource_label VARCHAR(200),
    parent_resource_id VARCHAR(100),
    can_view BOOLEAN DEFAULT FALSE,
    can_create BOOLEAN DEFAULT FALSE,
    can_update BOOLEAN DEFAULT FALSE,
    can_delete BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(role_name, resource_type, resource_id)
);

CREATE INDEX IF NOT EXISTS idx_role_permissions_role ON role_permissions(role_name);

-- =====================================================
-- Learned Q&A Cache (v2.51.0)
-- =====================================================

-- CL eğitimi sırasında üretilen soru-cevap çiftleri
-- Sorgu zamanında embedding similarity ile hızlı eşleştirme
CREATE TABLE IF NOT EXISTS learned_answers (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    intent VARCHAR(50),
    source_file VARCHAR(255),
    chunk_id INTEGER REFERENCES rag_chunks(id) ON DELETE SET NULL,
    embedding FLOAT[],
    quality_score FLOAT DEFAULT 0.0,
    hit_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_learned_answers_intent ON learned_answers(intent);
CREATE INDEX IF NOT EXISTS idx_learned_answers_source ON learned_answers(source_file);
CREATE INDEX IF NOT EXISTS idx_learned_answers_quality ON learned_answers(quality_score DESC);

-- =====================================================
-- Widget API Keys (v2.60.0)
-- =====================================================

-- Web widget entegrasyon anahtarları
-- Her key bir organizasyona bağlıdır ve domain whitelist destekler
CREATE TABLE IF NOT EXISTS widget_api_keys (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    key_prefix VARCHAR(12) NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    widget_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    org_id INTEGER REFERENCES organization_groups(id) ON DELETE CASCADE,
    allowed_domains JSONB DEFAULT '[]',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by INTEGER REFERENCES users(id),
    last_used_at TIMESTAMP,
    prompt_id INTEGER REFERENCES prompt_templates(id) ON DELETE SET NULL,
    llm_config_id INTEGER REFERENCES llm_config(id) ON DELETE SET NULL,
    use_rag BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_widget_api_keys_hash ON widget_api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_widget_api_keys_active ON widget_api_keys(is_active);
CREATE INDEX IF NOT EXISTS idx_widget_api_keys_org ON widget_api_keys(org_id);

-- =====================================================
-- Türkiye Adres Tabloları (v2.53.0)
-- =====================================================

CREATE TABLE IF NOT EXISTS address_provinces (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS address_districts (
    id INTEGER PRIMARY KEY,
    province_id INTEGER NOT NULL REFERENCES address_provinces(id),
    name VARCHAR(100) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_address_districts_province ON address_districts(province_id);

CREATE TABLE IF NOT EXISTS address_neighborhoods (
    id SERIAL PRIMARY KEY,
    district_id INTEGER NOT NULL REFERENCES address_districts(id),
    name VARCHAR(200) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_address_neighborhoods_district ON address_neighborhoods(district_id);

-- =====================================================
-- Companies (Multi-Tenant) Table (v2.53.0)
-- =====================================================

CREATE TABLE IF NOT EXISTS companies (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,                -- Firma ünvanı
    tax_type VARCHAR(4) NOT NULL DEFAULT 'vd', -- 'vd' veya 'tckn'
    tax_number VARCHAR(11) NOT NULL UNIQUE,   -- VD veya TCKN numarası (benzersiz)
    address_il VARCHAR(100),                   -- İl
    address_ilce VARCHAR(100),                 -- İlçe
    address_mahalle VARCHAR(200),              -- Mahalle
    address_text TEXT,                          -- Serbest adres alanı
    phone VARCHAR(20) NOT NULL,
    email VARCHAR(255) NOT NULL,
    website VARCHAR(500),                      -- Canlı web adresi
    contact_name VARCHAR(100) NOT NULL,        -- Yetkili kişi adı
    contact_surname VARCHAR(100) NOT NULL,     -- Yetkili kişi soyadı
    logo_data BYTEA,                           -- Firma logosu (binary)
    logo_mime VARCHAR(50),                     -- 'image/png', 'image/jpeg' vb.
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by INTEGER REFERENCES users(id)
);

-- Companies indexes
CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(name);
CREATE INDEX IF NOT EXISTS idx_companies_tax ON companies(tax_number);
CREATE INDEX IF NOT EXISTS idx_companies_active ON companies(is_active);

-- =====================================================
-- Multi-Tenant Migration: company_id FK to existing tables
-- =====================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);
ALTER TABLE llm_config ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);
ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);
ALTER TABLE uploaded_files ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);
ALTER TABLE widget_api_keys ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);
ALTER TABLE dialogs ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);
ALTER TABLE ldap_settings ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);
ALTER TABLE organization_groups ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);

-- company_id indexes
CREATE INDEX IF NOT EXISTS idx_users_company ON users(company_id);
CREATE INDEX IF NOT EXISTS idx_llm_config_company ON llm_config(company_id);
CREATE INDEX IF NOT EXISTS idx_prompt_templates_company ON prompt_templates(company_id);
CREATE INDEX IF NOT EXISTS idx_uploaded_files_company ON uploaded_files(company_id);
CREATE INDEX IF NOT EXISTS idx_widget_api_keys_company ON widget_api_keys(company_id);
CREATE INDEX IF NOT EXISTS idx_tickets_company ON tickets(company_id);
CREATE INDEX IF NOT EXISTS idx_dialogs_company ON dialogs(company_id);
CREATE INDEX IF NOT EXISTS idx_ldap_settings_company ON ldap_settings(company_id);
CREATE INDEX IF NOT EXISTS idx_org_groups_company ON organization_groups(company_id);

-- Varsayılan firma (migration: mevcut veriler için)
INSERT INTO companies (name, tax_type, tax_number, phone, email, contact_name, contact_surname)
VALUES ('Varsayılan Firma', 'vd', '0000000000', '-', 'info@default.com', 'Admin', 'User')
ON CONFLICT (tax_number) DO NOTHING;

-- Mevcut kayıtlara varsayılan firma ata (admin HARİÇ — admin firmaya bağlı değildir)
UPDATE users SET company_id = (SELECT id FROM companies WHERE tax_number = '0000000000' LIMIT 1) WHERE company_id IS NULL AND is_admin = FALSE;
UPDATE llm_config SET company_id = (SELECT id FROM companies WHERE tax_number = '0000000000' LIMIT 1) WHERE company_id IS NULL;
UPDATE prompt_templates SET company_id = (SELECT id FROM companies WHERE tax_number = '0000000000' LIMIT 1) WHERE company_id IS NULL;
UPDATE uploaded_files SET company_id = (SELECT id FROM companies WHERE tax_number = '0000000000' LIMIT 1) WHERE company_id IS NULL;
UPDATE tickets SET company_id = (SELECT id FROM companies WHERE tax_number = '0000000000' LIMIT 1) WHERE company_id IS NULL;
UPDATE dialogs SET company_id = (SELECT id FROM companies WHERE tax_number = '0000000000' LIMIT 1) WHERE company_id IS NULL;
UPDATE organization_groups SET company_id = (SELECT id FROM companies WHERE tax_number = '0000000000' LIMIT 1) WHERE company_id IS NULL;

-- Veri Kaynakları (v2.55.0)
CREATE TABLE IF NOT EXISTS data_sources (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    source_type VARCHAR(50) NOT NULL,
    db_type VARCHAR(50),
    host VARCHAR(500),
    port INTEGER,
    db_name VARCHAR(200),
    db_user VARCHAR(200),
    db_password_encrypted VARCHAR(500),
    file_server_path VARCHAR(1000),
    description TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_data_sources_company ON data_sources(company_id);
CREATE INDEX IF NOT EXISTS idx_data_sources_type ON data_sources(source_type);
CREATE INDEX IF NOT EXISTS idx_data_sources_active ON data_sources(is_active);

-- =====================================================
-- DB Learning / Discovery Tables (v2.56.0)
-- =====================================================

-- Keşif İş Takibi (her adım bir job kaydı)
CREATE TABLE IF NOT EXISTS ds_discovery_jobs (
    id SERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    job_type VARCHAR(50) NOT NULL,         -- 'technology', 'objects', 'samples', 'learning'
    status VARCHAR(20) DEFAULT 'pending',  -- 'pending','running','completed','failed'
    result_summary JSONB,
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    duration_ms INTEGER,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ds_disc_jobs_source ON ds_discovery_jobs(source_id);
CREATE INDEX IF NOT EXISTS idx_ds_disc_jobs_company ON ds_discovery_jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_ds_disc_jobs_type ON ds_discovery_jobs(job_type);
CREATE INDEX IF NOT EXISTS idx_ds_disc_jobs_status ON ds_discovery_jobs(status);
CREATE INDEX IF NOT EXISTS idx_ds_disc_jobs_created ON ds_discovery_jobs(created_at DESC);

-- Keşfedilen DB Objeleri (tablolar, view'lar)
CREATE TABLE IF NOT EXISTS ds_db_objects (
    id SERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
    schema_name VARCHAR(100),
    object_name VARCHAR(200) NOT NULL,
    object_type VARCHAR(50) NOT NULL,      -- 'table', 'view', 'materialized_view'
    column_count INTEGER DEFAULT 0,
    row_count_estimate BIGINT DEFAULT 0,
    columns_json JSONB,                     -- [{name, data_type, is_nullable, is_pk, default_val}]
    discovered_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ds_db_objects_source ON ds_db_objects(source_id);
CREATE INDEX IF NOT EXISTS idx_ds_db_objects_type ON ds_db_objects(object_type);

-- FK İlişkileri
CREATE TABLE IF NOT EXISTS ds_db_relationships (
    id SERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
    from_schema VARCHAR(100),
    from_table VARCHAR(200) NOT NULL,
    from_column VARCHAR(200) NOT NULL,
    to_schema VARCHAR(100),
    to_table VARCHAR(200) NOT NULL,
    to_column VARCHAR(200) NOT NULL,
    constraint_name VARCHAR(200),
    discovered_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ds_db_rels_source ON ds_db_relationships(source_id);

-- Tablolardan Alınan Örnek Veriler
CREATE TABLE IF NOT EXISTS ds_db_samples (
    id SERIAL PRIMARY KEY,
    object_id INTEGER NOT NULL REFERENCES ds_db_objects(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
    sample_query TEXT NOT NULL,
    sample_data JSONB NOT NULL,
    row_count INTEGER DEFAULT 0,
    fetched_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ds_db_samples_obj ON ds_db_samples(object_id);
CREATE INDEX IF NOT EXISTS idx_ds_db_samples_source ON ds_db_samples(source_id);

-- Kaynak Bazlı Öğrenme Zamanlaması
CREATE TABLE IF NOT EXISTS ds_learning_schedules (
    id SERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE UNIQUE,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    schedule_type VARCHAR(50) NOT NULL,    -- 'interval_hours', 'daily', 'manual_only'
    interval_value INTEGER DEFAULT 24,
    is_active BOOLEAN DEFAULT TRUE,
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ds_learn_sched_source ON ds_learning_schedules(source_id);
CREATE INDEX IF NOT EXISTS idx_ds_learn_sched_active ON ds_learning_schedules(is_active);

-- Öğrenme Sonuçları (RAG aranabilir)
CREATE TABLE IF NOT EXISTS ds_learning_results (
    id SERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    job_id INTEGER REFERENCES ds_discovery_jobs(id) ON DELETE SET NULL,
    content_type VARCHAR(50) NOT NULL,     -- 'schema_description', 'sample_insight', 'relationship_map'
    content_text TEXT NOT NULL,
    embedding FLOAT[],
    metadata JSONB,
    score FLOAT DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Migration: Mevcut tabloya eksik sütunları ekle
ALTER TABLE ds_learning_results ADD COLUMN IF NOT EXISTS score FLOAT DEFAULT 0.0;

-- Migration: ds_learning_schedules UNIQUE constraint (ON CONFLICT için)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ds_learning_schedules_source_id_key'
    ) THEN
        ALTER TABLE ds_learning_schedules ADD CONSTRAINT ds_learning_schedules_source_id_key UNIQUE (source_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_ds_learn_results_source ON ds_learning_results(source_id);
CREATE INDEX IF NOT EXISTS idx_ds_learn_results_company ON ds_learning_results(company_id);
CREATE INDEX IF NOT EXISTS idx_ds_learn_results_type ON ds_learning_results(content_type);

-- =====================================================
-- SQL Audit Log (v2.58.0) - Hybrid Router SQL İzleme
-- =====================================================

-- Çalıştırılan her SQL sorgusunun audit kaydı
CREATE TABLE IF NOT EXISTS sql_audit_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    source_id INTEGER,
    source_name VARCHAR(200),
    sql_text TEXT NOT NULL,
    dialect VARCHAR(50),
    status VARCHAR(30) NOT NULL DEFAULT 'success',  -- success, error, security_rejected, timeout
    row_count INTEGER DEFAULT 0,
    elapsed_ms NUMERIC(10,2) DEFAULT 0,
    error_msg TEXT,
    generation_method VARCHAR(30) DEFAULT 'template',  -- template, llm, manual
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sql_audit_log_user ON sql_audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_sql_audit_log_company ON sql_audit_log(company_id);
CREATE INDEX IF NOT EXISTS idx_sql_audit_log_status ON sql_audit_log(status);
CREATE INDEX IF NOT EXISTS idx_sql_audit_log_created ON sql_audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sql_audit_log_source ON sql_audit_log(source_id);

-- =====================================================
-- Company Themes (v2.59.0) - Multi-Tenant Branding
-- =====================================================

-- Firma bazlı CSS tema tanımları
CREATE TABLE IF NOT EXISTS company_themes (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    code VARCHAR(50) NOT NULL UNIQUE,
    description VARCHAR(255),
    css_variables JSONB NOT NULL DEFAULT '{}',
    preview_colors JSONB NOT NULL DEFAULT '[]',
    login_headline TEXT,
    login_subtitle TEXT,
    features_json JSONB,
    sort_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_company_themes_code ON company_themes(code);
CREATE INDEX IF NOT EXISTS idx_company_themes_active ON company_themes(is_active);
CREATE INDEX IF NOT EXISTS idx_company_themes_sort ON company_themes(sort_order);

-- Companies tablosuna branding alanları ekle
ALTER TABLE companies ADD COLUMN IF NOT EXISTS app_name VARCHAR(200) DEFAULT 'VYRA';
ALTER TABLE companies ADD COLUMN IF NOT EXISTS theme_id INTEGER REFERENCES company_themes(id) ON DELETE SET NULL;

-- v3.1.1: Mevcut NGSSAI app_name'leri VYRA'ya güncelle
UPDATE companies SET app_name = 'VYRA' WHERE app_name = 'NGSSAI';
ALTER TABLE companies ALTER COLUMN app_name SET DEFAULT 'VYRA';

CREATE INDEX IF NOT EXISTS idx_companies_theme ON companies(theme_id);

-- v2.60.0: Özel tema desteği
ALTER TABLE company_themes ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE;
ALTER TABLE company_themes ADD COLUMN IF NOT EXISTS is_custom BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_company_themes_company ON company_themes(company_id);

-- v2.60.0: Firma-tema atamaları (bir firmaya birden fazla tema atanabilir)
CREATE TABLE IF NOT EXISTS company_theme_assignments (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    theme_id INTEGER NOT NULL REFERENCES company_themes(id) ON DELETE CASCADE,
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(company_id, theme_id)
);

CREATE INDEX IF NOT EXISTS idx_cta_company ON company_theme_assignments(company_id);
CREATE INDEX IF NOT EXISTS idx_cta_theme ON company_theme_assignments(theme_id);

-- =====================================================
-- 10 Hazır SaaS Tema (Default Data)
-- =====================================================

INSERT INTO company_themes (name, code, description, css_variables, preview_colors, login_headline, login_subtitle, features_json, sort_order) VALUES
(
    'Okyanus Mavisi', 'ocean_blue', 'Profesyonel mavi-mor gradient, kurumsal görünüm',
    '{
        "dark": {
            "--gold": "#4D99FF", "--gold-2": "#7C3AED",
            "--gold-dim": "rgba(77,153,255,0.12)", "--gold-glow": "rgba(77,153,255,0.18)",
            "--gold-subtle": "rgba(77,153,255,0.07)",
            "--border-accent": "rgba(77,153,255,0.30)",
            "--text-gold": "#7DB8FF",
            "--grad-logo": "linear-gradient(135deg, #4D99FF 0%, #7C3AED 100%)",
            "--grad-btn": "linear-gradient(135deg, #4D99FF 0%, #7C3AED 100%)",
            "--grad-acc": "linear-gradient(135deg, #4D99FF, #7C3AED)",
            "--shadow-btn": "0 4px 20px rgba(77,153,255,0.25), 0 0 0 1px rgba(77,153,255,0.12)",
            "--shadow-input": "0 0 0 2px rgba(77,153,255,0.35), 0 0 16px rgba(77,153,255,0.08)",
            "--orb-a": "rgba(77,153,255,0.12)", "--orb-b": "rgba(124,58,237,0.08)"
        },
        "light": {
            "--gold": "#2563EB", "--gold-2": "#7C3AED",
            "--gold-dim": "rgba(37,99,235,0.08)", "--gold-glow": "rgba(37,99,235,0.12)",
            "--gold-subtle": "rgba(37,99,235,0.05)",
            "--border-accent": "rgba(37,99,235,0.25)",
            "--text-gold": "#1D4ED8",
            "--grad-logo": "linear-gradient(135deg, #2563EB 0%, #7C3AED 100%)",
            "--grad-btn": "linear-gradient(135deg, #2563EB 0%, #7C3AED 100%)",
            "--grad-acc": "linear-gradient(135deg, #2563EB, #7C3AED)",
            "--shadow-btn": "0 4px 20px rgba(37,99,235,0.20), 0 0 0 1px rgba(37,99,235,0.10)",
            "--shadow-input": "0 0 0 2px rgba(37,99,235,0.28), 0 0 12px rgba(37,99,235,0.06)",
            "--orb-a": "rgba(37,99,235,0.06)", "--orb-b": "rgba(124,58,237,0.05)"
        }
    }',
    '["#4D99FF", "#7C3AED"]',
    'Yapay zeka ile,<br><strong>kurumsal bilgi yönetimi</strong>',
    'Dokümanlardan anında yanıt üretme, akıllı diyalog yönetimi ve RAG tabanlı bilgi tabanı platformu.',
    '[{"title":"Akıllı Diyalog Yönetimi","desc":"Çoklu LLM desteği · Bağlam duyarlı yanıtlar","icon":"accent"},{"title":"RAG Bilgi Tabanı","desc":"PDF · DOCX · TXT doküman yükleme ve anlık sorgulama","icon":"blue"},{"title":"Organizasyon ve Yetkilendirme","desc":"Rol tabanlı erişim · Çoklu organizasyon desteği","icon":"green"}]',
    1
),
(
    'Altın Sarısı', 'golden_amber', 'Sıcak altın-turuncu tonlar, dikkat çekici ve enerjik',
    '{
        "dark": {
            "--gold": "#F59E0B", "--gold-2": "#EF4444",
            "--gold-dim": "rgba(245,158,11,0.12)", "--gold-glow": "rgba(245,158,11,0.18)",
            "--gold-subtle": "rgba(245,158,11,0.07)",
            "--border-accent": "rgba(245,158,11,0.30)",
            "--text-gold": "#FCD34D",
            "--grad-logo": "linear-gradient(135deg, #F59E0B 0%, #EF4444 100%)",
            "--grad-btn": "linear-gradient(135deg, #F59E0B 0%, #EF4444 100%)",
            "--grad-acc": "linear-gradient(135deg, #F59E0B, #EF4444)",
            "--shadow-btn": "0 4px 20px rgba(245,158,11,0.25), 0 0 0 1px rgba(245,158,11,0.12)",
            "--shadow-input": "0 0 0 2px rgba(245,158,11,0.35), 0 0 16px rgba(245,158,11,0.08)",
            "--orb-a": "rgba(245,158,11,0.12)", "--orb-b": "rgba(239,68,68,0.08)"
        },
        "light": {
            "--gold": "#D97706", "--gold-2": "#DC2626",
            "--gold-dim": "rgba(217,119,6,0.08)", "--gold-glow": "rgba(217,119,6,0.12)",
            "--gold-subtle": "rgba(217,119,6,0.05)",
            "--border-accent": "rgba(217,119,6,0.25)",
            "--text-gold": "#B45309",
            "--grad-logo": "linear-gradient(135deg, #D97706 0%, #DC2626 100%)",
            "--grad-btn": "linear-gradient(135deg, #D97706 0%, #DC2626 100%)",
            "--grad-acc": "linear-gradient(135deg, #D97706, #DC2626)",
            "--shadow-btn": "0 4px 20px rgba(217,119,6,0.20), 0 0 0 1px rgba(217,119,6,0.10)",
            "--shadow-input": "0 0 0 2px rgba(217,119,6,0.28), 0 0 12px rgba(217,119,6,0.06)",
            "--orb-a": "rgba(217,119,6,0.06)", "--orb-b": "rgba(220,38,38,0.05)"
        }
    }',
    '["#F59E0B", "#EF4444"]',
    'Dijital dönüşümle,<br><strong>verimlilik artışı</strong>',
    'Kurumsal bilgi yönetim süreçlerinizi yapay zeka ile hızlandırın ve optimize edin.',
    '[{"title":"Hızlı Çözüm Üretimi","desc":"Saniyeler içinde doğru yanıtlar · Akıllı arama","icon":"accent"},{"title":"Doküman Analizi","desc":"Otomatik içerik çıkarma · Anlık sorgulama","icon":"blue"},{"title":"Güvenli Erişim","desc":"Kurumsal yetkilendirme · LDAP entegrasyonu","icon":"green"}]',
    2
),
(
    'Zümrüt Orman', 'emerald_forest', 'Doğal yeşil tonlar, güven veren kurumsal',
    '{
        "dark": {
            "--gold": "#10B981", "--gold-2": "#059669",
            "--gold-dim": "rgba(16,185,129,0.12)", "--gold-glow": "rgba(16,185,129,0.18)",
            "--gold-subtle": "rgba(16,185,129,0.07)",
            "--border-accent": "rgba(16,185,129,0.30)",
            "--text-gold": "#6EE7B7",
            "--grad-logo": "linear-gradient(135deg, #10B981 0%, #059669 100%)",
            "--grad-btn": "linear-gradient(135deg, #10B981 0%, #059669 100%)",
            "--grad-acc": "linear-gradient(135deg, #10B981, #059669)",
            "--shadow-btn": "0 4px 20px rgba(16,185,129,0.25), 0 0 0 1px rgba(16,185,129,0.12)",
            "--shadow-input": "0 0 0 2px rgba(16,185,129,0.35), 0 0 16px rgba(16,185,129,0.08)",
            "--orb-a": "rgba(16,185,129,0.12)", "--orb-b": "rgba(5,150,105,0.08)"
        },
        "light": {
            "--gold": "#059669", "--gold-2": "#047857",
            "--gold-dim": "rgba(5,150,105,0.08)", "--gold-glow": "rgba(5,150,105,0.12)",
            "--gold-subtle": "rgba(5,150,105,0.05)",
            "--border-accent": "rgba(5,150,105,0.25)",
            "--text-gold": "#047857",
            "--grad-logo": "linear-gradient(135deg, #059669 0%, #047857 100%)",
            "--grad-btn": "linear-gradient(135deg, #059669 0%, #047857 100%)",
            "--grad-acc": "linear-gradient(135deg, #059669, #047857)",
            "--shadow-btn": "0 4px 20px rgba(5,150,105,0.20), 0 0 0 1px rgba(5,150,105,0.10)",
            "--shadow-input": "0 0 0 2px rgba(5,150,105,0.28), 0 0 12px rgba(5,150,105,0.06)",
            "--orb-a": "rgba(5,150,105,0.06)", "--orb-b": "rgba(4,120,87,0.05)"
        }
    }',
    '["#10B981", "#059669"]',
    'Sürdürülebilir teknoloji,<br><strong>akıllı çözümler</strong>',
    'Yeşil teknoloji yaklaşımıyla kurumsal bilgi yönetimini geleceğe taşıyın.',
    '[{"title":"Çevik Destek Sistemi","desc":"7/24 erişim · Anlık yanıt mekanizması","icon":"accent"},{"title":"Kapsamlı Doküman Yönetimi","desc":"Çoklu format desteği · Otomatik sınıflandırma","icon":"blue"},{"title":"Ekip İşbirliği","desc":"Paylaşımlı bilgi tabanı · Rol bazlı erişim","icon":"green"}]',
    3
),
(
    'Gün Batımı', 'sunset_coral', 'Sıcak kırmızı-pembe gradient, yaratıcı ve modern',
    '{
        "dark": {
            "--gold": "#F43F5E", "--gold-2": "#EC4899",
            "--gold-dim": "rgba(244,63,94,0.12)", "--gold-glow": "rgba(244,63,94,0.18)",
            "--gold-subtle": "rgba(244,63,94,0.07)",
            "--border-accent": "rgba(244,63,94,0.30)",
            "--text-gold": "#FDA4AF",
            "--grad-logo": "linear-gradient(135deg, #F43F5E 0%, #EC4899 100%)",
            "--grad-btn": "linear-gradient(135deg, #F43F5E 0%, #EC4899 100%)",
            "--grad-acc": "linear-gradient(135deg, #F43F5E, #EC4899)",
            "--shadow-btn": "0 4px 20px rgba(244,63,94,0.25), 0 0 0 1px rgba(244,63,94,0.12)",
            "--shadow-input": "0 0 0 2px rgba(244,63,94,0.35), 0 0 16px rgba(244,63,94,0.08)",
            "--orb-a": "rgba(244,63,94,0.12)", "--orb-b": "rgba(236,72,153,0.08)"
        },
        "light": {
            "--gold": "#E11D48", "--gold-2": "#DB2777",
            "--gold-dim": "rgba(225,29,72,0.08)", "--gold-glow": "rgba(225,29,72,0.12)",
            "--gold-subtle": "rgba(225,29,72,0.05)",
            "--border-accent": "rgba(225,29,72,0.25)",
            "--text-gold": "#BE123C",
            "--grad-logo": "linear-gradient(135deg, #E11D48 0%, #DB2777 100%)",
            "--grad-btn": "linear-gradient(135deg, #E11D48 0%, #DB2777 100%)",
            "--grad-acc": "linear-gradient(135deg, #E11D48, #DB2777)",
            "--shadow-btn": "0 4px 20px rgba(225,29,72,0.20), 0 0 0 1px rgba(225,29,72,0.10)",
            "--shadow-input": "0 0 0 2px rgba(225,29,72,0.28), 0 0 12px rgba(225,29,72,0.06)",
            "--orb-a": "rgba(225,29,72,0.06)", "--orb-b": "rgba(219,39,119,0.05)"
        }
    }',
    '["#F43F5E", "#EC4899"]',
    'Yenilikçi yaklaşımla,<br><strong>destek deneyimi</strong>',
    'Modern yapay zeka teknolojileriyle müşteri destek süreçlerinizi dönüştürün.',
    '[{"title":"Dinamik Yanıt Motoru","desc":"Bağlam duyarlı AI · Kişiselleştirilmiş öneriler","icon":"accent"},{"title":"Zengin Bilgi Havuzu","desc":"API entegrasyonu · Çapraz referans arama","icon":"blue"},{"title":"Detaylı Analitik","desc":"Performans metrikleri · Trend analizi","icon":"green"}]',
    4
),
(
    'Buzul Beyazı', 'arctic_ice', 'Soğuk cyan-mavi tonlar, temiz ve profesyonel',
    '{
        "dark": {
            "--gold": "#06B6D4", "--gold-2": "#3B82F6",
            "--gold-dim": "rgba(6,182,212,0.12)", "--gold-glow": "rgba(6,182,212,0.18)",
            "--gold-subtle": "rgba(6,182,212,0.07)",
            "--border-accent": "rgba(6,182,212,0.30)",
            "--text-gold": "#67E8F9",
            "--grad-logo": "linear-gradient(135deg, #06B6D4 0%, #3B82F6 100%)",
            "--grad-btn": "linear-gradient(135deg, #06B6D4 0%, #3B82F6 100%)",
            "--grad-acc": "linear-gradient(135deg, #06B6D4, #3B82F6)",
            "--shadow-btn": "0 4px 20px rgba(6,182,212,0.25), 0 0 0 1px rgba(6,182,212,0.12)",
            "--shadow-input": "0 0 0 2px rgba(6,182,212,0.35), 0 0 16px rgba(6,182,212,0.08)",
            "--orb-a": "rgba(6,182,212,0.12)", "--orb-b": "rgba(59,130,246,0.08)"
        },
        "light": {
            "--gold": "#0891B2", "--gold-2": "#2563EB",
            "--gold-dim": "rgba(8,145,178,0.08)", "--gold-glow": "rgba(8,145,178,0.12)",
            "--gold-subtle": "rgba(8,145,178,0.05)",
            "--border-accent": "rgba(8,145,178,0.25)",
            "--text-gold": "#0E7490",
            "--grad-logo": "linear-gradient(135deg, #0891B2 0%, #2563EB 100%)",
            "--grad-btn": "linear-gradient(135deg, #0891B2 0%, #2563EB 100%)",
            "--grad-acc": "linear-gradient(135deg, #0891B2, #2563EB)",
            "--shadow-btn": "0 4px 20px rgba(8,145,178,0.20), 0 0 0 1px rgba(8,145,178,0.10)",
            "--shadow-input": "0 0 0 2px rgba(8,145,178,0.28), 0 0 12px rgba(8,145,178,0.06)",
            "--orb-a": "rgba(8,145,178,0.06)", "--orb-b": "rgba(37,99,235,0.05)"
        }
    }',
    '["#06B6D4", "#3B82F6"]',
    'Berrak ve hızlı,<br><strong>bilgi erişimi</strong>',
    'Kristal netliğinde yanıtlarla kurumsal bilgi akışınızı optimize edin.',
    '[{"title":"Ultra Hızlı Arama","desc":"Milisaniye düzeyinde sonuçlar · Akıllı sıralama","icon":"accent"},{"title":"Çok Katmanlı Güvenlik","desc":"Şifreli iletişim · Rol bazlı erişim kontrolü","icon":"blue"},{"title":"Esnek Entegrasyon","desc":"RESTful API · Webhook desteği","icon":"green"}]',
    5
),
(
    'Volkanik Kırmızı', 'volcanic_red', 'Güçlü kırmızı tonlar, dikkat çekici ve cesur',
    '{
        "dark": {
            "--gold": "#EF4444", "--gold-2": "#B91C1C",
            "--gold-dim": "rgba(239,68,68,0.12)", "--gold-glow": "rgba(239,68,68,0.18)",
            "--gold-subtle": "rgba(239,68,68,0.07)",
            "--border-accent": "rgba(239,68,68,0.30)",
            "--text-gold": "#FCA5A5",
            "--grad-logo": "linear-gradient(135deg, #EF4444 0%, #B91C1C 100%)",
            "--grad-btn": "linear-gradient(135deg, #EF4444 0%, #B91C1C 100%)",
            "--grad-acc": "linear-gradient(135deg, #EF4444, #B91C1C)",
            "--shadow-btn": "0 4px 20px rgba(239,68,68,0.25), 0 0 0 1px rgba(239,68,68,0.12)",
            "--shadow-input": "0 0 0 2px rgba(239,68,68,0.35), 0 0 16px rgba(239,68,68,0.08)",
            "--orb-a": "rgba(239,68,68,0.12)", "--orb-b": "rgba(185,28,28,0.08)"
        },
        "light": {
            "--gold": "#DC2626", "--gold-2": "#991B1B",
            "--gold-dim": "rgba(220,38,38,0.08)", "--gold-glow": "rgba(220,38,38,0.12)",
            "--gold-subtle": "rgba(220,38,38,0.05)",
            "--border-accent": "rgba(220,38,38,0.25)",
            "--text-gold": "#B91C1C",
            "--grad-logo": "linear-gradient(135deg, #DC2626 0%, #991B1B 100%)",
            "--grad-btn": "linear-gradient(135deg, #DC2626 0%, #991B1B 100%)",
            "--grad-acc": "linear-gradient(135deg, #DC2626, #991B1B)",
            "--shadow-btn": "0 4px 20px rgba(220,38,38,0.20), 0 0 0 1px rgba(220,38,38,0.10)",
            "--shadow-input": "0 0 0 2px rgba(220,38,38,0.28), 0 0 12px rgba(220,38,38,0.06)",
            "--orb-a": "rgba(220,38,38,0.06)", "--orb-b": "rgba(153,27,27,0.05)"
        }
    }',
    '["#EF4444", "#B91C1C"]',
    'Güçlü teknoloji,<br><strong>kesintisiz destek</strong>',
    'Kritik iş süreçleriniz için güvenilir ve hızlı yapay zeka destekli çözümler.',
    '[{"title":"Kritik Destek Yönetimi","desc":"Öncelikli yanıt · Eskalasyon otomasyonu","icon":"accent"},{"title":"Kapsamlı İzleme","desc":"Gerçek zamanlı dashboard · Alarm sistemi","icon":"blue"},{"title":"Yüksek Erişilebilirlik","desc":"7/24 hizmet · Çoklu kanal desteği","icon":"green"}]',
    6
),
(
    'Kraliyet Moru', 'royal_purple', 'Zarif mor tonlar, premium ve sofistike',
    '{
        "dark": {
            "--gold": "#8B5CF6", "--gold-2": "#6D28D9",
            "--gold-dim": "rgba(139,92,246,0.12)", "--gold-glow": "rgba(139,92,246,0.18)",
            "--gold-subtle": "rgba(139,92,246,0.07)",
            "--border-accent": "rgba(139,92,246,0.30)",
            "--text-gold": "#C4B5FD",
            "--grad-logo": "linear-gradient(135deg, #8B5CF6 0%, #6D28D9 100%)",
            "--grad-btn": "linear-gradient(135deg, #8B5CF6 0%, #6D28D9 100%)",
            "--grad-acc": "linear-gradient(135deg, #8B5CF6, #6D28D9)",
            "--shadow-btn": "0 4px 20px rgba(139,92,246,0.25), 0 0 0 1px rgba(139,92,246,0.12)",
            "--shadow-input": "0 0 0 2px rgba(139,92,246,0.35), 0 0 16px rgba(139,92,246,0.08)",
            "--orb-a": "rgba(139,92,246,0.12)", "--orb-b": "rgba(109,40,217,0.08)"
        },
        "light": {
            "--gold": "#7C3AED", "--gold-2": "#5B21B6",
            "--gold-dim": "rgba(124,58,237,0.08)", "--gold-glow": "rgba(124,58,237,0.12)",
            "--gold-subtle": "rgba(124,58,237,0.05)",
            "--border-accent": "rgba(124,58,237,0.25)",
            "--text-gold": "#6D28D9",
            "--grad-logo": "linear-gradient(135deg, #7C3AED 0%, #5B21B6 100%)",
            "--grad-btn": "linear-gradient(135deg, #7C3AED 0%, #5B21B6 100%)",
            "--grad-acc": "linear-gradient(135deg, #7C3AED, #5B21B6)",
            "--shadow-btn": "0 4px 20px rgba(124,58,237,0.20), 0 0 0 1px rgba(124,58,237,0.10)",
            "--shadow-input": "0 0 0 2px rgba(124,58,237,0.28), 0 0 12px rgba(124,58,237,0.06)",
            "--orb-a": "rgba(124,58,237,0.06)", "--orb-b": "rgba(91,33,182,0.05)"
        }
    }',
    '["#8B5CF6", "#6D28D9"]',
    'Premium deneyim,<br><strong>üstün performans</strong>',
    'Kurumsal sınıf yapay zeka ile bilgi yönetiminde premium çözümler.',
    '[{"title":"Gelişmiş AI Motoru","desc":"GPT-4 seviye doğruluk · Çoklu dil desteği","icon":"accent"},{"title":"Akıllı Öğrenme","desc":"Sürekli gelişen model · Feedback döngüsü","icon":"blue"},{"title":"Premium Destek","desc":"Öncelikli müdahale · Özel danışmanlık","icon":"green"}]',
    7
),
(
    'Gece Mavisi', 'midnight_teal', 'Sakin teal tonları, güvenilir ve modern',
    '{
        "dark": {
            "--gold": "#14B8A6", "--gold-2": "#0D9488",
            "--gold-dim": "rgba(20,184,166,0.12)", "--gold-glow": "rgba(20,184,166,0.18)",
            "--gold-subtle": "rgba(20,184,166,0.07)",
            "--border-accent": "rgba(20,184,166,0.30)",
            "--text-gold": "#5EEAD4",
            "--grad-logo": "linear-gradient(135deg, #14B8A6 0%, #0D9488 100%)",
            "--grad-btn": "linear-gradient(135deg, #14B8A6 0%, #0D9488 100%)",
            "--grad-acc": "linear-gradient(135deg, #14B8A6, #0D9488)",
            "--shadow-btn": "0 4px 20px rgba(20,184,166,0.25), 0 0 0 1px rgba(20,184,166,0.12)",
            "--shadow-input": "0 0 0 2px rgba(20,184,166,0.35), 0 0 16px rgba(20,184,166,0.08)",
            "--orb-a": "rgba(20,184,166,0.12)", "--orb-b": "rgba(13,148,136,0.08)"
        },
        "light": {
            "--gold": "#0D9488", "--gold-2": "#0F766E",
            "--gold-dim": "rgba(13,148,136,0.08)", "--gold-glow": "rgba(13,148,136,0.12)",
            "--gold-subtle": "rgba(13,148,136,0.05)",
            "--border-accent": "rgba(13,148,136,0.25)",
            "--text-gold": "#0F766E",
            "--grad-logo": "linear-gradient(135deg, #0D9488 0%, #0F766E 100%)",
            "--grad-btn": "linear-gradient(135deg, #0D9488 0%, #0F766E 100%)",
            "--grad-acc": "linear-gradient(135deg, #0D9488, #0F766E)",
            "--shadow-btn": "0 4px 20px rgba(13,148,136,0.20), 0 0 0 1px rgba(13,148,136,0.10)",
            "--shadow-input": "0 0 0 2px rgba(13,148,136,0.28), 0 0 12px rgba(13,148,136,0.06)",
            "--orb-a": "rgba(13,148,136,0.06)", "--orb-b": "rgba(15,118,110,0.05)"
        }
    }',
    '["#14B8A6", "#0D9488"]',
    'Güvenilir teknoloji,<br><strong>akıllı asistan</strong>',
    'Sakin ve güvenilir yapay zeka desteğiyle kurumsal süreçlerinizi kolaylaştırın.',
    '[{"title":"Proaktif Destek","desc":"Otomatik uyarı · Önleyici bakım önerileri","icon":"accent"},{"title":"Entegre Bilgi Yönetimi","desc":"Merkezi doküman havuzu · Versiyon kontrolü","icon":"blue"},{"title":"Kolay Yönetim","desc":"Sezgisel arayüz · Hızlı kurulum","icon":"green"}]',
    8
),
(
    'Karbon Çeliği', 'carbon_steel', 'Minimal gri tonlar, endüstriyel ve sade',
    '{
        "dark": {
            "--gold": "#9CA3AF", "--gold-2": "#6B7280",
            "--gold-dim": "rgba(156,163,175,0.12)", "--gold-glow": "rgba(156,163,175,0.18)",
            "--gold-subtle": "rgba(156,163,175,0.07)",
            "--border-accent": "rgba(156,163,175,0.30)",
            "--text-gold": "#D1D5DB",
            "--grad-logo": "linear-gradient(135deg, #9CA3AF 0%, #6B7280 100%)",
            "--grad-btn": "linear-gradient(135deg, #9CA3AF 0%, #6B7280 100%)",
            "--grad-acc": "linear-gradient(135deg, #9CA3AF, #6B7280)",
            "--shadow-btn": "0 4px 20px rgba(156,163,175,0.25), 0 0 0 1px rgba(156,163,175,0.12)",
            "--shadow-input": "0 0 0 2px rgba(156,163,175,0.35), 0 0 16px rgba(156,163,175,0.08)",
            "--orb-a": "rgba(156,163,175,0.12)", "--orb-b": "rgba(107,114,128,0.08)"
        },
        "light": {
            "--gold": "#6B7280", "--gold-2": "#4B5563",
            "--gold-dim": "rgba(107,114,128,0.08)", "--gold-glow": "rgba(107,114,128,0.12)",
            "--gold-subtle": "rgba(107,114,128,0.05)",
            "--border-accent": "rgba(107,114,128,0.25)",
            "--text-gold": "#4B5563",
            "--grad-logo": "linear-gradient(135deg, #6B7280 0%, #4B5563 100%)",
            "--grad-btn": "linear-gradient(135deg, #6B7280 0%, #4B5563 100%)",
            "--grad-acc": "linear-gradient(135deg, #6B7280, #4B5563)",
            "--shadow-btn": "0 4px 20px rgba(107,114,128,0.20), 0 0 0 1px rgba(107,114,128,0.10)",
            "--shadow-input": "0 0 0 2px rgba(107,114,128,0.28), 0 0 12px rgba(107,114,128,0.06)",
            "--orb-a": "rgba(107,114,128,0.06)", "--orb-b": "rgba(75,85,99,0.05)"
        }
    }',
    '["#9CA3AF", "#6B7280"]',
    'Endüstriyel güç,<br><strong>minimalist tasarım</strong>',
    'Sade ve işlevsel arayüzle kurumsal bilgi yönetiminde verimlilik odaklı çözümler.',
    '[{"title":"Verimli İş Akışı","desc":"Otomatik yönlendirme · İş kuralları motoru","icon":"accent"},{"title":"Endüstriyel Kalite","desc":"Yüksek uptime · Ölçeklenebilir mimari","icon":"blue"},{"title":"Standart Uyumluluk","desc":"ISO sertifikalı · KVKK uyumlu","icon":"green"}]',
    9
),
(
    'Neon Elektrik', 'neon_electric', 'Canlı mor-pembe gradient, enerjik ve genç',
    '{
        "dark": {
            "--gold": "#A855F7", "--gold-2": "#EC4899",
            "--gold-dim": "rgba(168,85,247,0.12)", "--gold-glow": "rgba(168,85,247,0.18)",
            "--gold-subtle": "rgba(168,85,247,0.07)",
            "--border-accent": "rgba(168,85,247,0.30)",
            "--text-gold": "#D8B4FE",
            "--grad-logo": "linear-gradient(135deg, #A855F7 0%, #EC4899 100%)",
            "--grad-btn": "linear-gradient(135deg, #A855F7 0%, #EC4899 100%)",
            "--grad-acc": "linear-gradient(135deg, #A855F7, #EC4899)",
            "--shadow-btn": "0 4px 20px rgba(168,85,247,0.25), 0 0 0 1px rgba(168,85,247,0.12)",
            "--shadow-input": "0 0 0 2px rgba(168,85,247,0.35), 0 0 16px rgba(168,85,247,0.08)",
            "--orb-a": "rgba(168,85,247,0.12)", "--orb-b": "rgba(236,72,153,0.08)"
        },
        "light": {
            "--gold": "#9333EA", "--gold-2": "#DB2777",
            "--gold-dim": "rgba(147,51,234,0.08)", "--gold-glow": "rgba(147,51,234,0.12)",
            "--gold-subtle": "rgba(147,51,234,0.05)",
            "--border-accent": "rgba(147,51,234,0.25)",
            "--text-gold": "#7E22CE",
            "--grad-logo": "linear-gradient(135deg, #9333EA 0%, #DB2777 100%)",
            "--grad-btn": "linear-gradient(135deg, #9333EA 0%, #DB2777 100%)",
            "--grad-acc": "linear-gradient(135deg, #9333EA, #DB2777)",
            "--shadow-btn": "0 4px 20px rgba(147,51,234,0.20), 0 0 0 1px rgba(147,51,234,0.10)",
            "--shadow-input": "0 0 0 2px rgba(147,51,234,0.28), 0 0 12px rgba(147,51,234,0.06)",
            "--orb-a": "rgba(147,51,234,0.06)", "--orb-b": "rgba(219,39,119,0.05)"
        }
    }',
    '["#A855F7", "#EC4899"]',
    'Geleceğin teknolojisi,<br><strong>bugünün çözümü</strong>',
    'En son yapay zeka teknolojileriyle donatılmış next-gen bilgi yönetim platformu.',
    '[{"title":"Next-Gen AI","desc":"Son nesil dil modelleri · Çok modlu analiz","icon":"accent"},{"title":"Anında İçgörü","desc":"Gerçek zamanlı veri analizi · Trend tespiti","icon":"blue"},{"title":"Sınırsız Ölçekleme","desc":"Bulut yerel mimari · Mikro servisler","icon":"green"}]',
    10
),
(
    'Sarı Siyah', 'yellow_black', 'VYRA klasik sarı-siyah, güçlü kontrast ve dikkat çekici',
    '{
        "dark": {
            "--gold": "#EAB308", "--gold-2": "#CA8A04",
            "--gold-dim": "rgba(234,179,8,0.12)", "--gold-glow": "rgba(234,179,8,0.18)",
            "--gold-subtle": "rgba(234,179,8,0.07)",
            "--border-accent": "rgba(234,179,8,0.30)",
            "--text-gold": "#FDE047",
            "--grad-logo": "linear-gradient(135deg, #EAB308 0%, #CA8A04 100%)",
            "--grad-btn": "linear-gradient(135deg, #EAB308 0%, #CA8A04 100%)",
            "--grad-acc": "linear-gradient(135deg, #EAB308, #CA8A04)",
            "--shadow-btn": "0 4px 20px rgba(234,179,8,0.25), 0 0 0 1px rgba(234,179,8,0.12)",
            "--shadow-input": "0 0 0 2px rgba(234,179,8,0.35), 0 0 16px rgba(234,179,8,0.08)",
            "--orb-a": "rgba(234,179,8,0.12)", "--orb-b": "rgba(202,138,4,0.08)"
        },
        "light": {
            "--gold": "#CA8A04", "--gold-2": "#A16207",
            "--gold-dim": "rgba(202,138,4,0.08)", "--gold-glow": "rgba(202,138,4,0.12)",
            "--gold-subtle": "rgba(202,138,4,0.05)",
            "--border-accent": "rgba(202,138,4,0.25)",
            "--text-gold": "#A16207",
            "--grad-logo": "linear-gradient(135deg, #CA8A04 0%, #A16207 100%)",
            "--grad-btn": "linear-gradient(135deg, #CA8A04 0%, #A16207 100%)",
            "--grad-acc": "linear-gradient(135deg, #CA8A04, #A16207)",
            "--shadow-btn": "0 4px 20px rgba(202,138,4,0.20), 0 0 0 1px rgba(202,138,4,0.10)",
            "--shadow-input": "0 0 0 2px rgba(202,138,4,0.28), 0 0 12px rgba(202,138,4,0.06)",
            "--orb-a": "rgba(202,138,4,0.06)", "--orb-b": "rgba(161,98,7,0.05)"
        }
    }',
    '["#EAB308", "#CA8A04"]',
    'Güçlü ve kararlı,<br><strong>kurumsal destek platformu</strong>',
    'Sarı-siyah kontrastıyla dikkat çeken, yüksek performanslı kurumsal bilgi yönetim sistemi.',
    '[{"title":"Kurumsal Çözüm Merkezi","desc":"Tek noktadan destek · Hızlı erişim","icon":"accent"},{"title":"Güçlü Bilgi Tabanı","desc":"Yapılandırılmış dokümanlar · Akıllı arama","icon":"blue"},{"title":"Merkezi Yönetim","desc":"Firma bazlı izolasyon · Tam kontrol","icon":"green"}]',
    11
)
ON CONFLICT (code) DO NOTHING;

-- =====================================================
-- v3.3.0: Enhancement Geçmişi
-- =====================================================
CREATE TABLE IF NOT EXISTS enhancement_history (
    id SERIAL PRIMARY KEY,
    file_name VARCHAR(500) NOT NULL,
    file_hash VARCHAR(64),                -- MD5 hash (ilk 1MB)
    original_file_type VARCHAR(20),       -- Orijinal dosya formatı (pdf, xlsx, pptx, ...)
    user_id INTEGER REFERENCES users(id),
    session_id VARCHAR(100),              -- Enhancement session ID
    total_sections INTEGER DEFAULT 0,
    enhanced_sections INTEGER DEFAULT 0,
    maturity_score_before REAL,           -- İyileştirme öncesi olgunluk skoru
    maturity_score_after REAL,            -- İyileştirme sonrası olgunluk skoru (veya NULL)
    sections_summary JSONB,              -- Her section'ın change_type ve integrity_score bilgisi
    uploaded_to_rag BOOLEAN DEFAULT FALSE, -- Sonuç bilgi tabanına yüklendi mi?
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    company_id INTEGER REFERENCES companies(id)
);

CREATE INDEX IF NOT EXISTS idx_enhancement_history_file ON enhancement_history(file_name);
CREATE INDEX IF NOT EXISTS idx_enhancement_history_user ON enhancement_history(user_id);
CREATE INDEX IF NOT EXISTS idx_enhancement_history_date ON enhancement_history(created_at DESC);

-- =====================================================
-- v3.3.0 [A4]: Dosya Versiyonlama
-- =====================================================
-- Her dosya yeniden yüklendiğinde eski versiyon is_active=false olur,
-- yeni versiyon file_version+1 ile eklenir.
ALTER TABLE uploaded_files ADD COLUMN IF NOT EXISTS file_version INTEGER DEFAULT 1;
ALTER TABLE uploaded_files ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
ALTER TABLE uploaded_files ADD COLUMN IF NOT EXISTS file_hash VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_uploaded_files_active ON uploaded_files(is_active);
CREATE INDEX IF NOT EXISTS idx_uploaded_files_hash ON uploaded_files(file_hash);
CREATE INDEX IF NOT EXISTS idx_uploaded_files_version ON uploaded_files(file_name, file_version DESC);

-- =====================================================
-- v3.3.0 [A8]: pgvector Migration
-- =====================================================
-- pgvector extension varsa FLOAT[] → vector(384) dönüşümü.
-- Extension yoksa hiçbir şey yapmaz (güvenli migration).

DO $$
BEGIN
    -- pgvector extension oluşturmayı dene
    CREATE EXTENSION IF NOT EXISTS vector;
    RAISE NOTICE 'pgvector extension aktif';
    
    -- rag_chunks.embedding: FLOAT[] → vector(384)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'rag_chunks' AND column_name = 'embedding' AND data_type = 'ARRAY'
    ) THEN
        ALTER TABLE rag_chunks ALTER COLUMN embedding TYPE vector(384) 
        USING embedding::vector(384);
        RAISE NOTICE 'rag_chunks.embedding → vector(384) migration tamamlandı';
    END IF;
    
    -- learned_answers.embedding: FLOAT[] → vector(384)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'learned_answers' AND column_name = 'embedding' AND data_type = 'ARRAY'
    ) THEN
        ALTER TABLE learned_answers ALTER COLUMN embedding TYPE vector(384) 
        USING embedding::vector(384);
        RAISE NOTICE 'learned_answers.embedding → vector(384) migration tamamlandı';
    END IF;
    
    -- ds_learning_results.embedding: FLOAT[] → vector(384)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'ds_learning_results' AND column_name = 'embedding' AND data_type = 'ARRAY'
    ) THEN
        ALTER TABLE ds_learning_results ALTER COLUMN embedding TYPE vector(384) 
        USING embedding::vector(384);
        RAISE NOTICE 'ds_learning_results.embedding → vector(384) migration tamamlandı';
    END IF;
    
    -- IVFFlat index oluştur (büyük veri kümelerinde ~10x hız)
    -- 1000+ chunk olduğunda faydalı
    CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding_ivfflat 
    ON rag_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
    
EXCEPTION
    WHEN OTHERS THEN
        -- pgvector yoksa veya yetki yoksa sessizce devam et
        RAISE NOTICE 'pgvector migration atlandı: %', SQLERRM;
END
$$;

-- =====================================================
-- v3.3.0: RAG Pipeline Optimization Migrations
-- =====================================================

-- uploaded_files: Dosya versiyonlama, soft-delete ve hash desteği
ALTER TABLE uploaded_files ADD COLUMN IF NOT EXISTS file_version INTEGER DEFAULT 1;
ALTER TABLE uploaded_files ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
ALTER TABLE uploaded_files ADD COLUMN IF NOT EXISTS file_hash VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_uploaded_files_active ON uploaded_files(is_active);
CREATE INDEX IF NOT EXISTS idx_uploaded_files_hash ON uploaded_files(file_hash);

-- Enhancement History tablosu — iyileştirme geçmişi ve etki ölçümü
CREATE TABLE IF NOT EXISTS enhancement_history (
    id SERIAL PRIMARY KEY,
    file_name VARCHAR(500) NOT NULL,
    file_hash VARCHAR(64),
    original_file_type VARCHAR(20),
    session_id VARCHAR(50),
    user_id INTEGER REFERENCES users(id),
    total_sections INTEGER DEFAULT 0,
    enhanced_sections INTEGER DEFAULT 0,
    maturity_score_before REAL,
    maturity_score_after REAL,
    sections_summary JSONB,
    uploaded_to_rag BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_enhancement_history_file ON enhancement_history(file_name);
CREATE INDEX IF NOT EXISTS idx_enhancement_history_user ON enhancement_history(user_id);
CREATE INDEX IF NOT EXISTS idx_enhancement_history_created ON enhancement_history(created_at DESC);

"""
