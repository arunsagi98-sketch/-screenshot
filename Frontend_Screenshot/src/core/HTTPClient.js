/**
 * HTTP Client - Centralized HTTP communication layer
 * Handles all API requests with error handling, timeouts, and request/response logging
 */

import CONFIG from '../constants/config.js';

class HTTPClient {
  constructor() {
    this.baseURL = CONFIG.API.BASE_URL;
    this.timeout = CONFIG.API.TIMEOUT;
    this.requestInterceptors = [];
    this.responseInterceptors = [];
  }

  /**
   * Make a GET request
   * @param {string} endpoint - API endpoint
   * @param {object} options - Request options
   * @returns {Promise<any>}
   */
  async get(endpoint, options = {}) {
    return this.request(endpoint, { ...options, method: 'GET' });
  }

  /**
   * Make a POST request
   * @param {string} endpoint - API endpoint
   * @param {any} data - Request body
   * @param {object} options - Request options
   * @returns {Promise<any>}
   */
  async post(endpoint, data, options = {}) {
    return this.request(endpoint, {
      ...options,
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Make a DELETE request
   * @param {string} endpoint - API endpoint
   * @param {object} options - Request options
   * @returns {Promise<any>}
   */
  async delete(endpoint, options = {}) {
    return this.request(endpoint, { ...options, method: 'DELETE' });
  }

  /**
   * Main request method with timeout and error handling
   * @param {string} endpoint - API endpoint
   * @param {object} options - Fetch options
   * @returns {Promise<any>}
   */
  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    const config = {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      ...options,
    };

    // Request interceptors
    for (const interceptor of this.requestInterceptors) {
      await interceptor(config);
    }

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), this.timeout);

      const response = await fetch(url, {
        ...config,
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      // Response interceptors
      for (const interceptor of this.responseInterceptors) {
        await interceptor(response);
      }

      if (!response.ok) {
        const error = new Error(`HTTP ${response.status}`);
        error.status = response.status;
        error.response = response;
        throw error;
      }

      const contentType = response.headers.get('content-type') || '';
      if (contentType.includes('application/json')) {
        return await response.json();
      }
      return response;
    } catch (error) {
      this._handleError(error);
      throw error;
    }
  }

  /**
   * Stream request for SSE/streaming responses
   * @param {string} endpoint - API endpoint
   * @param {object} options - Request options
   * @param {Function} onChunk - Callback for each chunk
   * @returns {Promise<void>}
   */
  async stream(endpoint, options = {}, onChunk) {
    const url = `${this.baseURL}${endpoint}`;
    const config = {
      method: options.method || 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
    };

    try {
      const response = await fetch(url, config);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
          if (line.trim()) {
            try {
              const data = JSON.parse(line);
              onChunk(data);
            } catch (e) {
              console.warn('Failed to parse stream chunk:', line);
            }
          }
        }
      }

      if (buffer.trim()) {
        try {
          const data = JSON.parse(buffer);
          onChunk(data);
        } catch (e) {
          console.warn('Failed to parse final stream chunk:', buffer);
        }
      }
    } catch (error) {
      this._handleError(error);
      throw error;
    }
  }

  /**
   * Add request interceptor
   * @param {Function} interceptor - Interceptor function
   */
  addRequestInterceptor(interceptor) {
    this.requestInterceptors.push(interceptor);
  }

  /**
   * Add response interceptor
   * @param {Function} interceptor - Interceptor function
   */
  addResponseInterceptor(interceptor) {
    this.responseInterceptors.push(interceptor);
  }

  /**
   * Handle errors with logging
   * @private
   * @param {Error} error
   */
  _handleError(error) {
    console.error('HTTP Error:', {
      message: error.message,
      status: error.status,
      timestamp: new Date().toISOString(),
    });
  }
}

export default new HTTPClient();
