"""
VYRA L1 Support API - Configuration Module
==========================================
Merkezi konfigürasyon yönetimi. PostgreSQL bağlantısı ve uygulama ayarları.
"""

from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator

# Proje kök dizini (vyra_l1_fastapi klasörü)
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """
    Uygulama ayarları.
    
    Tüm ayarlar .env dosyasından veya environment variable'lardan okunabilir.
    """
    
    # -------------------------------------------------
    #  Genel API ayarları
    # -------------------------------------------------
    app_name: str = "VYRA"
    debug: bool = True
    APP_VERSION: str = "3.36.0"  # v3.36.0 Smart Discovery Completion (F6-F22): F6 WHERE AST fix + F7 multi-column endpoint + F8/F8b LLM suggestion slots (table_id round-trip) + F9 generate-report LLM endpoint + Çalıştır popup + F10b saved-reports flat fallback route + post_save_report_flat + F11/F11b DbSmartChart popup + Oracle DD-MON-YY date detection + chart z-index 11050 + F13 picker FK multi-hop graph (adjacency BFS, abort controller) + F14 metric step accordion+search+multi-checkbox + F15 allowed_tables case-insensitive + F16 save modal z-index 11100 + INSERT 500 root cause + F17 AST explain/patch graceful 422 + F19-F21 retro (report detail modal route prefix, edit-mode hydration step1 chips, Çalıştır SSE, AST undo/redo + last-step Next + Maliyet badge removal) + F22 saved-report rerun dialect resolution (omit FE, BE alias normalization) + edit-mode source_id snake/camel hydration + picker initialSelection round-trip (primary+joins) + cost badge UI removal. v3.34.3 post-test fixes (picker z-index 1100→1300, wizard step1 source readonly badge, saved_reports × is-filled toggle verify) + v3.34.2 picker 6 enhancement (schema accordion, Tümünü Temizle, Sadece Seçilenler toggle, search × icon, persistence, FK warning). v3.34.0 vyraFetch helper + Frontend HTTP migrasyonu (~30 modülde Türkçe defansif hata kontratı: 502/503/504, network failure, 401/403) + MemPalace freshness gate (HEAD-hash short-circuit, MINE_TIMEOUT 600s) + v3.33.1 fix bundle (rapor şablonu prompt, display SQL, multi-tenant RLS tanılaması, picker limit 500, wizard tablo arama %% escape) + archive housekeeping (v3.30 agentic_master + v3.34 paketi). v3.33.0 Akıllı Veri Keşfi (Smart Data Discovery): saved-reports card grid (Ajan-B) + modal wizard wrapper (ESC/overlay/focus-trap/return-focus, HEBE polish) + SaaS modern dialog (glass-morphism + gradient stepper) + i18n loader bootstrap fix (auto-init + bundle entry) + backend RLS-aware /sources & duplicate/delete endpoints (Ajan-D) + admin company_id NULL data-fix. v3.32.0 Query Builder execute path + JOIN HINTS smart search + Fernet rotation + admin learning widgets. v3.29.11 Dedupe L2 pgvector guard (FK Loop poison fix) — dedupe_service.check_duplicate Layer 2 artık question_embedding kolonu `vector` değilse (float8[]/array) sessizce atlanır; aksi halde `<=> ::vector` operatörü tip uyumsuzluğunda transaction'ı poison'lıyordu (psycopg2.errors.InFailedSqlTransaction) ve fk_synthetic_generator'da 58/58 attempt fail oluyordu. learned_queries_service._detect_embedding_column_type lazy import. + detect_objects response'una declared_count/inferred_count/total_relationships eklendi (UI ayrı gösterim). v3.29.10 Housekeeping closure + 2 bug fix (heatmap 500 + enrichment empty-state onclick null) — see README. v3.29.9 Multi-dialect FK Inference Layer — RC1: fk_inference_service.py (convention-based: naming patterns + type compat + sample validation, 4 dialect adapters PG/Oracle/MSSQL/MySQL via Protocol + factory) + migration 031 (ds_db_relationships → is_inferred/inference_method/evidence_json/admin_verified/verified_by/verified_at/rejected_at + system_settings FK_INFERENCE_DEPLOY_TS) + 50 test. RC2: 6 admin endpoint (POST /infer-fks, GET /inferred-relationships, POST /verify, POST /reject, POST /bulk-verify, GET /fk-inference-stats) + auto-trigger in ds_learning_service Step 2. RC3: v3.29.8 integration — multi_signal_rank.build_centrality_index (confidence-weighted: declared=1.0, inferred unverified=0.5×conf, verified=1.0, rejected=0) + analyze_signal_weights min_event_age_hours filter (fk_centrality samples filtered pre-Pearson) + signal_weight_api /current adds fk_inference_recent_deploy/age_hours + text_to_sql FK SELECT filter (rejected NULL, is_inferred=FALSE OR verified OR conf≥0.70). RC4: signal_weight_tuner deploy banner + agentic_observability "FK Inference" tab + ds_learning_module "FK Çıkarımını Yenile" button + Inferred/Declared rozetleri. 89 test green.

    # Frontend & API prefix
    api_prefix: str = "/api"
    frontend_origin: str = "http://localhost:5500"

    # CORS için kullanılan origin listesi
    # Production'da .env'den oku: CORS_ORIGINS=https://vyra.company.com
    # Birden fazla origin virgülle ayrılarak tanımlanabilir
    CORS_ORIGINS: str = ""
    
    backend_cors_origins: List[str] = [
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8002",
        "http://127.0.0.1:8002",
        "http://localhost:5000",
        "http://127.0.0.1:5000",
    ]

    @model_validator(mode='after')
    def _merge_cors_origins(self) -> 'Settings':
        """Production .env'den CORS_ORIGINS varsa listeye ekle. Replit domain otomatik eklenir."""
        import os
        replit_domain = os.environ.get("REPLIT_DEV_DOMAIN", "")
        if replit_domain:
            for scheme in ["https://", "http://"]:
                origin = f"{scheme}{replit_domain}"
                if origin not in self.backend_cors_origins:
                    self.backend_cors_origins.append(origin)
        replit_domains = os.environ.get("REPLIT_DOMAINS", "")
        if replit_domains:
            for domain in replit_domains.split(","):
                domain = domain.strip()
                if domain:
                    for scheme in ["https://", "http://"]:
                        origin = f"{scheme}{domain}"
                        if origin not in self.backend_cors_origins:
                            self.backend_cors_origins.append(origin)
        if self.CORS_ORIGINS:
            extra_origins = [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
            for origin in extra_origins:
                if origin not in self.backend_cors_origins:
                    self.backend_cors_origins.append(origin)
        return self

    # -------------------------------------------------
    #  JWT ayarları
    # -------------------------------------------------
    JWT_SECRET: str = ""  # ⚠️ ZORUNLU: .env dosyasından ayarlanmalı
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 1 saat
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    def validate_jwt_secret(self) -> None:
        """JWT_SECRET'ın güvenli bir şekilde ayarlandığını doğrular."""
        insecure_values = ["", "CHANGE_ME_IN_.ENV", "your-secret-key", "secret", "changeme"]
        if self.JWT_SECRET in insecure_values or len(self.JWT_SECRET) < 32:
            raise RuntimeError(
                "\n" + "=" * 60 + "\n"
                "🔒 GÜVENLİK HATASI: JWT_SECRET ayarlanmamış!\n"
                "=" * 60 + "\n"
                "JWT_SECRET değeri .env dosyasında tanımlanmalıdır.\n"
                "En az 32 karakter uzunluğunda güvenli bir değer kullanın.\n\n"
                "Örnek (.env dosyasına ekleyin):\n"
                "JWT_SECRET=your-super-secret-key-at-least-32-characters-long\n"
                "=" * 60
            )

    # -------------------------------------------------
    #  PostgreSQL Veritabanı Ayarları
    # -------------------------------------------------
    # Standalone PostgreSQL kurulumu
    PGSQL_DIR: str = str(BASE_DIR / "pgsql")
    
    # Bağlantı parametreleri
    # ⚠️ GÜVENLİK: Üretimde 'postgres' superuser yerine 
    # kısıtlı yetkili 'vyra_app' kullanıcısını kullanın.
    # Bkz: scripts/create_app_user.sql
    DB_HOST: str = "localhost"
    DB_PORT: int = 5005  # Standalone kurulum için özel port
    DB_NAME: str = "vyra"
    DB_USER: str = "postgres"      # .env: DB_USER=vyra_app (önerilen)
    DB_PASSWORD: str = "postgres"  # .env: DB_PASSWORD=guclu_sifre

    # -------------------------------------------------
    #  RAG / Dosya Yükleme ayarları
    # -------------------------------------------------
    # Desteklenen dosya formatları
    SUPPORTED_FILE_EXTENSIONS: List[str] = [
        ".pdf", ".docx", ".doc",
        ".xlsx", ".xls",
        ".pptx", ".ppt",
        ".txt", ".csv"  # v3.3.0: CSV desteği
    ]
    
    # Maksimum dosya boyutu (MB)
    MAX_FILE_SIZE_MB: int = 50
    
    # ChromaDB embedding model
    EMBEDDING_MODEL: str = "paraphrase-multilingual-MiniLM-L12-v2"
    
    # Chunk ayarları
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 100
    
    # v3.3.0 [A6]: RAG chunk konfigürasyon — .env ile override edilebilir
    RAG_PDF_CHUNK_SIZE: int = 2000       # PDF section max chunk boyutu
    RAG_PDF_CHUNK_OVERLAP: int = 100     # PDF chunk overlap
    RAG_MIN_CHUNK_LENGTH: int = 30       # Minimum chunk karakter uzunluğu
    RAG_LLM_MAX_CONTENT_CHARS: int = 6000  # Enhancement LLM'e gönderilecek max karakter
    
    # -------------------------------------------------
    #  Cache & Performans Ayarları
    # -------------------------------------------------
    EMBEDDING_CACHE_SIZE: int = 500  # Max cached embedding sayısı
    FUZZY_CACHE_SIZE: int = 500  # Max cached fuzzy match sayısı
    LLM_BYPASS_THRESHOLD: float = 0.70  # RAG skoru bu değerin üzerindeyse LLM atlanır
    PGVECTOR_INDEX: bool = True  # pgvector index kullanımı etkin mi
    REDIS_URL: str = "redis://localhost:6380/1"  # 🔧 v2.60.2: Port 6380 (6379 çakışma önleme)
    
    # 🆕 v2.57.0: Hybrid Router & Safe SQL Executor
    SQL_EXEC_TIMEOUT: int = 5       # SQL sorgu timeout (saniye)
    SQL_MAX_ROWS: int = 100         # Maksimum döndürülen satır sayısı

    # v3.15.0: Long-running DB query — kullanıcı beklemek istediği sürece sabretmek için
    # SSE wait-loop maks bekleme süresi (saniye). Bu süre dolunca kullanıcıya
    # "X dakika içinde tamamlanamadı" mesajı gösterilir; SQL hala arka planda kalmaz
    # (executor thread bırakılır). Nginx proxy_read_timeout bunun üzerinde olmalı.
    DB_QUERY_MAX_WAIT_SECONDS: int = 900  # 15 dakika
    
    # -------------------------------------------------
    #  Scheduler & System Ayarları (v2.27.2)
    # -------------------------------------------------
    SCHEDULER_INTERVAL_SECONDS: int = 300  # İnaktif dialog kapatma interval (5 dk)
    
    # RAG Arama Parametreleri
    RAG_DEFAULT_RESULTS: int = 5  # Varsayılan RAG sonuç sayısı
    RAG_MIN_SCORE: float = 0.30  # 🔧 v2.33.2: 0.40'tan düşürüldü - PDF dokümanları için
    
    # DB Connection Yönetimi
    DB_MAX_RETRIES: int = 15  # Veritabanı bağlantı deneme sayısı

    # -------------------------------------------------
    # Synthetic Q/SQL Generator (v3.28.0 — Faz 5 G2)
    # -------------------------------------------------
    # Synthetic generate_db_query_pairs günlük LLM bütçe sınırı (USD).
    # 0 = sınırsız (önerilmez). Aşıldığında üretim erken durur.
    MAX_LLM_DAILY_BUDGET_USD: float = 1.0

    # -------------------------------------------------
    # FK Graph Resolver (v3.29.5 — Faz 7 carry-over)
    # -------------------------------------------------
    # K-shortest path arama parametreleri. Çok-tablolu sorular için path
    # patlamasını sınırlar. Yüksek değerler latency artışı getirir.
    FK_GRAPH_DEFAULT_K: int = 5            # Maks alternatif yol sayısı
    FK_GRAPH_DEFAULT_MAX_HOPS: int = 5     # Tek yol için maks zincir uzunluğu

    # -------------------------------------------------
    # Code Value Auto Re-scan (v3.29.5 — Faz 7 carry-over)
    # -------------------------------------------------
    # ds_db_samples güncellendikten sonra ds_code_values otomatik yenileme.
    # 0 = devre dışı (manuel admin tetikleme). >0 ise scheduler interval'inin
    # bir katı olarak çalışır (SCHEDULER_INTERVAL_SECONDS × bu çarpan).
    CODE_VALUE_AUTO_RESCAN_INTERVAL_MULT: int = 0   # 0 = off; örn 12 = ~1 saat
    CODE_VALUE_AUTO_RESCAN_MIN_AGE_MINUTES: int = 60  # Son tarama bu kadar eskiyse yeniden tara

    # -------------------------------------------------
    # Signal Weight Analyzer (v3.29.8 — Layer 2)
    # -------------------------------------------------
    # multi_signal_rank ağırlıklarının offline Pearson korelasyon
    # tabanlı önerilerini üreten analyzer. Önerileri sadece
    # signal_weight_suggestions tablosuna yazar; admin onayı (Layer 3)
    # olmadan asıl ağırlıkları değiştirmez.
    # 0 = devre dışı (manuel admin tetikleme). >0 ise scheduler interval'inin
    # bir katı olarak çalışır (SCHEDULER_INTERVAL_SECONDS × bu çarpan).
    # Default 288 → 288 × 300s ≈ 24 saat (günde 1 kez).
    SIGNAL_WEIGHT_ANALYZER_INTERVAL_MULT: int = 0    # 0 = off; öneri 288 (~24h)
    SIGNAL_WEIGHT_ANALYZER_WINDOW_DAYS: int = 7       # Pencere
    SIGNAL_WEIGHT_ANALYZER_MIN_SAMPLE_SIZE: int = 50  # Sample yetersizse skip
    SIGNAL_WEIGHT_ANALYZER_LAMBDA: float = 0.3        # Yumuşak ayarlama katsayısı

    # -------------------------------------------------
    # DB Smart Wizard — Scheduled Reports (v3.30.0 FAZ 3 P17)
    # -------------------------------------------------
    # dbsmart_saved_reports.schedule_cron olan kayıtların periyodik yeniden
    # çalıştırılması. 0 = off; >0 ise scheduler interval'inin (SCHEDULER_INTERVAL_SECONDS=300s)
    # katı olarak tick. Default 12 → 12 × 300s = 60 dk (saatlik kontrol).
    # Her tick: schedule_next_run <= NOW() olan raporlar çalıştırılır,
    # last_run_snapshot JSONB'ye yazılır, croniter ile bir sonraki çalışma zamanı set'lenir.
    # E-mail/PDF delivery KAPSAM DIŞI (v3.30.0 plan kararı — in-app snapshot).
    DBSMART_SCHEDULE_INTERVAL_MULT: int = 12          # 0 = off; 12 ≈ saatlik
    DBSMART_SCHEDULE_MAX_PER_TICK: int = 20           # Tick başına max çalışan rapor
    DBSMART_SCHEDULE_QUERY_TIMEOUT_S: int = 60        # Schedule SQL timeout
    DBSMART_SCHEDULE_MAX_ROWS: int = 5_000            # Snapshot row limit

    # -------------------------------------------------
    # Langfuse Observability (v3.26.0 Faz 5 P2-b — opsiyonel)
    # -------------------------------------------------
    # Boş bırakılırsa Langfuse devre dışı kalır. pipeline_events DB-tabanlı
    # observability her hâlükârda çalışmaya devam eder.
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # -------------------------------------------------
    # OpenTelemetry + Prometheus (v3.30.0 FAZ 5 P36)
    # -------------------------------------------------
    # OTel OTLP HTTP trace endpoint (örn. http://otel-collector:4318/v1/traces).
    # Boş bırakılırsa OTel devre dışı (no-op tracer). pipeline_events DB-tabanlı
    # observability her hâlükârda çalışmaya devam eder.
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    # Prometheus custom metric kayıtları (wizard_completed_total vs.) için ana flag.
    # False ise tüm metric helper'ları no-op olur; /metrics endpoint 403/503 döner.
    PROMETHEUS_ENABLED: bool = False
    # /metrics endpoint IP allowlist (virgülle ayrılmış). Boş = kapalı (default).
    # Örn: "10.0.0.5,10.0.0.6". Dev için "0.0.0.0/0" → explicit open.
    METRICS_IP_ALLOWLIST: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -------------------------------------------------
    #  Computed Properties
    # -------------------------------------------------
    
    @property
    def DATABASE_URL(self) -> str:
        """SQLAlchemy için PostgreSQL connection string"""
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    @property
    def PGSQL_BIN_DIR(self) -> Path:
        """PostgreSQL binary dizini"""
        return Path(self.PGSQL_DIR) / "bin"


settings = Settings()

# 🔒 Startup güvenlik kontrolü
settings.validate_jwt_secret()
