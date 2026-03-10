# ============================================
# VYRA L1 Support API - Dockerfile
# ============================================
# Multi-stage build: minimal production image
# v2.30.1
# ============================================

# --- Stage 1: Builder ---
FROM python:3.13-slim AS builder

WORKDIR /build

# Sistem bağımlılıkları (derleme için)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Python bağımlılıkları
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# --- Stage 2: Runtime ---
FROM python:3.13-slim

WORKDIR /app

# Runtime sistem bağımlılıkları
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Python paketlerini builder'dan kopyala
COPY --from=builder /install /usr/local

# Uygulama dosyaları
COPY app/ ./app/
COPY frontend/ ./frontend/
COPY models/ ./models/
COPY scripts/ ./scripts/
COPY requirements.txt .
COPY .env.example ./.env.example

# Non-root kullanıcı (güvenlik)
RUN groupadd -r vyra && useradd -r -g vyra -d /app vyra \
    && chown -R vyra:vyra /app
USER vyra

# Port'lar
EXPOSE 8002 5500

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import requests; r = requests.get('http://localhost:8002/api/health'); exit(0 if r.status_code == 200 else 1)" || exit 1

# Başlatma
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8002"]
