# VYRA L1 Support API

## Overview
VYRA is a Turkish-language L1 support chatbot platform built with FastAPI (backend) and static HTML/JS/CSS (frontend). It features RAG-based knowledge search, dialog management, ticket handling, ML training, LDAP authentication, and organization management.

## Architecture
- **Backend**: FastAPI (Python 3.11), served via uvicorn on port 5000
- **Frontend**: Static HTML/JS/CSS files served by FastAPI's StaticFiles mount
- **Database**: PostgreSQL (Replit built-in, via DATABASE_URL env var)
- **Auth**: JWT-based authentication with bcrypt password hashing
- **ML/RAG**: sentence-transformers for embeddings, Google Generative AI for LLM (optional heavy deps)

## Project Structure
```
app/
  api/
    main.py          - FastAPI app creation, middleware, routes
    routes/          - API route handlers (auth, chat, rag, tickets, etc.)
    schemas/         - Pydantic request/response models
  core/
    config.py        - Settings via pydantic-settings (reads env vars)
    db.py            - PostgreSQL connection pool (psycopg2)
    schema.py        - SQL schema definitions
    default_data.py  - Default seed data
  models/
    schemas.py       - Database models
  services/          - Business logic (RAG, dialog, tickets, ML training, etc.)
frontend/
  login.html         - Login page (served at /)
  home.html          - Main app page
  assets/            - JS, CSS, images, vendor libs
  partials/          - HTML partial templates
migrations/          - Alembic database migrations
tests/               - Pytest test suite
```

## Key Configuration
- Environment variables set via Replit Secrets: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, JWT_SECRET
- CORS configured to allow Replit proxy domains automatically
- Frontend config.js uses `window.location.origin` for API base URL (production mode)

## Running
- Single workflow: `python3 -m uvicorn app.api.main:app --host 0.0.0.0 --port 5000`
- Database migrations run automatically on startup via Alembic
- Default admin user created on first run (username: admin)

## Notes
- Heavy ML packages (sentence-transformers, catboost, easyocr) are not installed due to disk constraints; RAG/ML features will show warnings but app runs fine
- Redis is optional; app falls back to in-memory caching
- Frontend is served directly by FastAPI (no separate frontend server needed)
