# NGSSAI AIOps Platform

## Overview
NGSSAI is a Turkish-language AIOps platform (formerly VYRA) built with FastAPI (backend) and static HTML/JS/CSS (frontend). It features RAG-based knowledge search, dialog management, ticket handling, ML training, LDAP authentication, organization management, and an embeddable **Web Widget** (JS chatbot add-on).

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
  login.html         - Login page (NGSSAI branded, self-contained with inline CSS/JS)
  home.html          - Main app page (NGSSAI chat-centric design, inline CSS, sidebar+topbar+tabs+chat+status bar)
  assets/            - JS, CSS, images, vendor libs
  partials/          - HTML partial templates
  build.mjs          - esbuild bundle builder (config.js must be first in JS_FILES)
  dist/              - Built bundles (bundle.min.js, bundle.min.css)
migrations/          - Alembic database migrations
tests/               - Pytest test suite
```

## Key Configuration
- Environment variables set via Replit Secrets: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, JWT_SECRET
- CORS configured to allow Replit proxy domains automatically
- Frontend config.js uses `window.location.origin` for API base URL (production mode)
- Admin credentials: admin / admin1234

## Running
- Single workflow: `python3 -m uvicorn app.api.main:app --host 0.0.0.0 --port 5000`
- Database migrations run automatically on startup via Alembic
- Default admin user created on first run (username: admin)
- Frontend rebuild: `cd frontend && node build.mjs`

## Notes
- Heavy ML packages (sentence-transformers, catboost, easyocr) are not installed due to disk constraints; RAG/ML features will show warnings but app runs fine
- Redis is optional; app falls back to in-memory caching
- Frontend is served directly by FastAPI (no separate frontend server needed)
- Login page is self-contained (inline CSS/JS) with the NGSSAI modern design (dark/light theme toggle, brand panel with feature cards)
- Home page is self-contained (inline CSS) with the NGSSAI chat-centric design: sidebar (nav, user info, session timer), topbar (agent info, action buttons), tabs (Bilgi Tabani / Gecmis Cozumler), chat area with input zone, status bar
- Sidebar and section_dialog are built directly into home.html (not loaded as partials); partial_loader.js loads 7 remaining partials (section_history, section_parameters, section_knowledge, section_auth, section_org, section_profile, modals)
- Section switching: dialog section = chat area (main view); other sections load into #otherSections wrapper; topBar/mainTabBar shown only for dialog/history views
- The `window.VYRA_API` global variable name is kept for internal compatibility across many JS modules
- Inner pages (Parameters, Knowledge Base, Authorization, Organizations, Profile) use shared NGSSAI design system with CSS classes: .page-head, .ph-icon, .ph-text, .sub-tabs/.sub-tab, .card, .sec-head/.sec-title, .data-table, .badge/.badge-green/.badge-amber/.badge-red/.badge-blue/.badge-purple, .inp/.inp-wrap, .toggle/.toggle-wrap, .stat-grid/.stat-card, .model-card, .form-grid/.fg-label, .pager/.pg-btn, .action-btns/.act-btn, .search-bar, .drop-zone, .profile-avatar-block, .slider
- LLM cards render using .model-card layout with .toggle switch, .act-btn edit/delete buttons
- Prompt cards render using .card with .sec-head header
- User table renders with .data-table, inline avatar circles, .badge status badges, .inp role select
- Org table renders with .data-table, .badge org codes, .act-btn action buttons
- Design reference file: attached_assets/ngssai-pages_1773154303462.html (DO NOT serve, use as CSS/design reference only)

## Web Widget (v2.60.0)
Standalone embeddable chatbot widget for any website via a single `<script>` tag.

- **Widget JS**: `frontend/widget/widget.src.js` → built to `frontend/widget/dist/widget.js` via `node frontend/widget/build.mjs`
- **Static serve**: Served at `/widget/widget.js` by FastAPI StaticFiles mount
- **Auth flow**: Admin creates API key (admin panel → Parametreler → Web Widget) → widget JS uses key to get short-lived JWT via `POST /api/widget/token` → JWT used with existing dialog endpoints
- **Backend**: `app/api/routes/widget.py` — public token endpoint + admin CRUD for API keys
- **DB table**: `widget_api_keys` (id, name, key_prefix, key_hash, widget_user_id, org_id, allowed_domains JSONB, is_active, created_at, created_by, last_used_at)
- **CORS**: `/api/widget/token` allows wildcard origin (custom middleware in main.py); other endpoints use normal auth
- **Admin UI**: Parametreler → Web Widget tab — key list, create modal, snippet generator (`frontend/assets/js/modules/widget_module.js`)
- **Test page**: `/widget/test.html` — interactive token test + live widget preview
- **Shadow DOM**: Widget is isolated from host site CSS (no conflicts)
- **DB note**: `widget_api_keys` uses RealDictCursor; all row access in widget.py must use dict keys (`row['id']`) not tuple index (`row[0]`)
