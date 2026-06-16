/**
 * Application Configuration Constants
 * Centralized configuration for API endpoints, UI settings, and defaults
 */

const getApiBaseUrl = () => {
  if (window.API_BASE_URL) return window.API_BASE_URL.replace(/\/$/, '');

  const { protocol, hostname, origin, port } = window.location;
  const isLocalHost = hostname === 'localhost' || hostname === '127.0.0.1';

  if (protocol === 'file:') return 'http://127.0.0.1:8001';
  if (protocol === 'http:' || protocol === 'https:') return origin;

  return 'http://127.0.0.1:8000';
};

const CONFIG = {
  // API Configuration
  API: {
    BASE_URL: getApiBaseUrl(),
    ENDPOINTS: {
      PROCESS: '/process',
      RESULTS: '/results',
      RESULTS_DELETE: (id) => `/results/${id}`,
      EXPORT_PDF: '/results/export-pdf',
      PPT_ASSETS: '/ppt-export-assets',
      IMAGE_BASE64: '/get-image-base64',
    },
    TIMEOUT: 30000,
  },

  // File Upload Configuration
  UPLOAD: {
    MAX_FILE_SIZE: 10 * 1024 * 1024, // 10MB
    ALLOWED_TYPES: ['image/png', 'image/jpeg', 'image/jpg', 'image/webp'],
    ALLOWED_EXTENSIONS: ['.png', '.jpg', '.jpeg', '.webp'],
  },

  // UI Settings
  UI: {
    TOAST_DURATION: 3000,
    MODAL_ANIMATION_DURATION: 300,
    DEBOUNCE_DELAY: 300,
  },

  // VPN Configuration
  VPN: {
    PROVIDERS: ['NordVPN', 'ExpressVPN', 'Surfshark', 'Custom'],
    DEFAULT_PROVIDER: 'NordVPN',
    COUNTRIES: [
      'United States',
      'United Kingdom',
      'Germany',
      'Singapore',
      'India',
      'Australia',
      'Canada',
    ],
  },

  // PPT Export Configuration
  PPT: {
    SLIDE_WIDTH: 3250.67 / 25.4,
    SLIDE_HEIGHT: 120.5 / 25.4,
    DEFAULT_THEME: {
      accent: '6366F1',
      background: 'F8FAFC',
      title: '1E293B',
      text: '334155',
      gradientTop: 'EEF2FF',
      gradientBottom: 'C7D2FE',
    },
    DESKTOP_IMAGE: {
      MAX_WIDTH: 327,
      MAX_HEIGHT: 161,
    },
    MOBILE_IMAGE: {
      MAX_WIDTH: 98.7,
      MAX_HEIGHT: 176,
    },
  },

  // Scan Progress Settings
  SCAN: {
    STATUS: {
      RUNNING: 'Scanner Running...',
      COMPLETE: 'Close & View Results',
      FAILED: 'Dismiss',
      WAITING: 'Waiting for scanner...',
    },
  },
};

export default CONFIG;
