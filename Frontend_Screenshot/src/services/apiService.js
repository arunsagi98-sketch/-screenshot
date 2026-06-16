import { API_BASE_URL } from '../config/apiConfig.js';

// ── Auth helpers ──────────────────────────────────────────────────────────────

export const getToken   = () => localStorage.getItem('access_token');
export const getRole    = () => localStorage.getItem('user_role');
export const getUsername = () => localStorage.getItem('username');

export const logout = () => {
  localStorage.removeItem('access_token');
  localStorage.removeItem('user_role');
  localStorage.removeItem('username');
  window.location.href = 'login.html';
};

/** Return headers with Authorization Bearer token attached. */
const authHeaders = (extra = {}) => {
  const token = getToken();
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  };
};

/** Fetch wrapper that redirects to login on 401. */
const apiFetch = async (url, options = {}) => {
  const res = await fetch(url, {
    ...options,
    headers: {
      ...authHeaders(options.headers || {}),
    },
  });
  if (res.status === 401) {
    logout();
    throw new Error('Session expired — redirecting to login');
  }
  return res;
};

// ── Guard: redirect to login if no token ─────────────────────────────────────

export const requireAuth = () => {
  if (!getToken() && !window.location.pathname.endsWith('login.html')) {
    window.location.href = 'login.html';
  }
};

// ── Existing API functions (now auth-aware) ───────────────────────────────────

const jsonHeaders = { 'Content-Type': 'application/json' };

const parseJsonResponse = async (response) => {
  const text = await response.text();
  try {
    return text ? JSON.parse(text) : {};
  } catch {
    return { error: text };
  }
};

export const getResultImageUrl = (path) => {
  if (!path) return null;
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE_URL}${cleanPath}`;
};

export const uploadCreatives = async (files) => {
  const formData = new FormData();
  files.forEach((file) => formData.append('files', file));

  const response = await apiFetch(`${API_BASE_URL}/upload-creatives`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) throw new Error(`Upload failed (${response.status})`);
  return response.json();
};

export const deleteCreative = async (filename) => {
  const response = await apiFetch(
    `${API_BASE_URL}/delete-creative?filename=${encodeURIComponent(filename)}`,
    { method: 'DELETE' }
  );
  return response.ok;
};

export const processScanStream = async (urls, onEvent) => {
  const response = await apiFetch(`${API_BASE_URL}/process`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ urls }),
  });

  if (!response.ok) throw new Error(`Failed with server status code: ${response.status}`);
  if (!response.body) throw new Error('Streaming response is unavailable in this browser.');

  const reader  = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();

    for (const line of lines) {
      if (!line.trim()) continue;
      try { onEvent(JSON.parse(line)); }
      catch (error) { console.error('Failed to parse progress event:', error, line); }
    }
  }

  if (buffer.trim()) {
    try { onEvent(JSON.parse(buffer)); }
    catch (error) { console.error('Failed to parse final progress event:', error, buffer); }
  }
};

export const fetchResults = async () => {
  const response = await apiFetch(`${API_BASE_URL}/results`);
  if (!response.ok) throw new Error(`Failed to fetch results (${response.status})`);
  return response.json();
};

export const deleteResult = async (id) => {
  const response = await apiFetch(`${API_BASE_URL}/results/${id}`, { method: 'DELETE' });
  return response.ok;
};

export const exportResultsPDF = async (ids) => {
  const response = await apiFetch(`${API_BASE_URL}/results/export-pdf`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ ids }),
  });

  if (!response.ok) {
    const parsed = await parseJsonResponse(response);
    throw new Error(parsed.message || `Export failed (${response.status})`);
  }

  const contentType = response.headers.get('Content-Type') || '';
  if (!contentType.includes('application/pdf')) {
    const parsed = await parseJsonResponse(response);
    throw new Error(parsed.message || 'Unexpected response from server');
  }

  return response.blob();
};

export const fetchPptAssets = async () => {
  try {
    const response = await apiFetch(`${API_BASE_URL}/ppt-export-assets`);
    if (!response.ok) return null;
    return response.json();
  } catch { return null; }
};

export const fetchImageBase64 = async (path) => {
  const response = await apiFetch(`${API_BASE_URL}/get-image-base64?path=${encodeURIComponent(path)}`);
  if (!response.ok) throw new Error(`Failed to fetch base64 image (${response.status})`);
  return response.json();
};

export const checkBackendStatus = async (timeoutMs = 3000) => {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const token = getToken();
    const resp = await fetch(`${API_BASE_URL}/results`, {
      method: 'GET',
      signal: controller.signal,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    clearTimeout(id);
    if (resp.ok) return { ok: true, status: resp.status };
    const parsed = await parseJsonResponse(resp);
    return { ok: false, status: resp.status, message: parsed?.message || parsed?.error || 'Non-ok response' };
  } catch (err) {
    clearTimeout(id);
    return { ok: false, message: err.name === 'AbortError' ? 'timeout' : err.message };
  }
};
