export const API_BASE_URL =
    window.location.protocol === 'http:' || window.location.protocol === 'https:'
        ? window.location.origin
        : 'http://127.0.0.1:8000';
