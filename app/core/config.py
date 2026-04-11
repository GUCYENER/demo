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
    APP_VERSION: str = "3.5.6"  # UI/UX fixes: DB Lock fix and Show Approved toggle

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
    
    # -------------------------------------------------
    #  Scheduler & System Ayarları (v2.27.2)
    # -------------------------------------------------
    SCHEDULER_INTERVAL_SECONDS: int = 300  # İnaktif dialog kapatma interval (5 dk)
    
    # RAG Arama Parametreleri
    RAG_DEFAULT_RESULTS: int = 5  # Varsayılan RAG sonuç sayısı
    RAG_MIN_SCORE: float = 0.30  # 🔧 v2.33.2: 0.40'tan düşürüldü - PDF dokümanları için
    
    # DB Connection Yönetimi
    DB_MAX_RETRIES: int = 15  # Veritabanı bağlantı deneme sayısı

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
