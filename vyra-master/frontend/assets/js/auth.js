/**
 * VYRA L1 Support API - Authentication Module
 */

function isAuthenticated() {
    const token = localStorage.getItem('access_token');
    if (!token) return false;

    try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        const expireTime = payload.exp * 1000;
        if (Date.now() > expireTime) {
            localStorage.removeItem('access_token');
            return false;
        }
        return true;
    } catch {
        return false;
    }
}

function getCurrentUser() {
    const token = localStorage.getItem('access_token');
    if (!token) return null;

    try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        return {
            user_id: payload.user_id,
            username: payload.sub,
            role: payload.role,
            is_admin: payload.is_admin === true
        };
    } catch {
        return null;
    }
}

function getAuthToken() {
    return localStorage.getItem('access_token');
}

function setAuthToken(token) {
    localStorage.setItem('access_token', token);
}

function clearAuth() {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
}
