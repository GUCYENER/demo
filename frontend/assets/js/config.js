/**
 * VYRA L1 Support API - Configuration
 * =====================================
 * Merkezi API ve WebSocket URL konfigürasyonu.
 * Tüm modüller bu dosyadaki değerleri kullanmalıdır.
 *
 * v2.48.0: Production-ready dynamic URL detection.
 * - localhost → development (port 8002)
 * - Diğer hostname → production (aynı origin, Nginx reverse proxy)
 */

// --- Dynamic API Base URL ---
// Development: Frontend serve.py (port 5500) → Backend farklı port (8002)
// Production:  Nginx reverse proxy (port 80/443) → aynı origin
const _isDevServer = window.location.port === '5500';

const API_BASE_URL = _isDevServer
    ? 'http://localhost:8002'
    : window.location.origin;  // Nginx: aynı origin (port 80/443)

// WebSocket URL (ws → wss otomatik HTTPS desteği)
const WS_BASE_URL = _isDevServer
    ? 'ws://localhost:8002/api/ws'
    : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/api/ws`;

// Global erişim: Diğer modüller window.API_BASE_URL ile erişir
window.API_BASE_URL = API_BASE_URL;
window.WS_BASE_URL = WS_BASE_URL;

const API_ENDPOINTS = {
    auth: {
        login: '/api/auth/login',
        register: '/api/auth/register',
        refresh: '/api/auth/refresh'
    },
    users: {
        list: '/api/users/list',
        approve: '/api/users/approve',
        me: '/api/users/me'
    },
    organizations: {
        list: '/api/organizations',
        create: '/api/organizations',
        detail: (id) => `/api/organizations/${id}`,
        update: (id) => `/api/organizations/${id}`,
        delete: (id) => `/api/organizations/${id}`
    },
    rag: {
        files: '/api/rag/files',
        upload: '/api/rag/upload-files',
        search: '/api/rag/search'
    }
};
