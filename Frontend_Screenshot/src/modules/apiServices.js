/**
 * API Service Layer - Modular API endpoints
 * Organizes all backend API calls by feature/domain
 */

import HTTPClient from '../core/HTTPClient.js';
import CONFIG from '../constants/config.js';
import Logger from '../core/Logger.js';

/**
 * Scan Service - Handle scan operations
 */
export const ScanService = {
  /**
   * Start a new scan with streaming response
   * @param {string[]} urls - Target URLs
   * @param {Function} onChunk - Callback for each stream chunk
   * @returns {Promise<void>}
   */
  async startScan(urls, onChunk) {
    Logger.info('Starting scan', { urls });
    return HTTPClient.stream(
      CONFIG.API.ENDPOINTS.PROCESS,
      {
        method: 'POST',
        body: { urls },
      },
      onChunk
    );
  },
};

/**
 * Results Service - Handle results operations
 */
export const ResultsService = {
  /**
   * Fetch all results
   * @returns {Promise<object[]>}
   */
  async getResults() {
    Logger.info('Fetching results');
    return HTTPClient.get(CONFIG.API.ENDPOINTS.RESULTS);
  },

  /**
   * Delete a result by ID
   * @param {number} id - Result ID
   * @returns {Promise<object>}
   */
  async deleteResult(id) {
    Logger.info('Deleting result', { id });
    return HTTPClient.delete(CONFIG.API.ENDPOINTS.RESULTS_DELETE(id));
  },

  /**
   * Delete multiple results
   * @param {number[]} ids - Result IDs
   * @returns {Promise<{deleted: number}>}
   */
  async deleteMultiple(ids) {
    Logger.info('Bulk deleting results', { count: ids.length });
    const deletePromises = ids.map((id) => this.deleteResult(id).catch(() => null));
    const results = await Promise.all(deletePromises);
    return { deleted: results.filter((r) => r !== null).length };
  },
};

/**
 * PPT Export Service - Handle PowerPoint export
 */
export const PPTService = {
  /**
   * Get PPT export assets (templates, themes, etc.)
   * @returns {Promise<object>}
   */
  async getExportAssets() {
    Logger.info('Fetching PPT export assets');
    try {
      return await HTTPClient.get(CONFIG.API.ENDPOINTS.PPT_ASSETS);
    } catch (error) {
      Logger.warn('Failed to fetch PPT assets, using defaults', error);
      return { theme: CONFIG.PPT.DEFAULT_THEME };
    }
  },

  /**
   * Get image as base64
   * @param {string} filename - Image filename
   * @returns {Promise<{dataUrl: string}>}
   */
  async getImageBase64(filename) {
    Logger.debug('Fetching image base64', { filename });
    return HTTPClient.get(`${CONFIG.API.ENDPOINTS.IMAGE_BASE64}?path=${filename}`);
  },

  /**
   * Get multiple images as base64
   * @param {string[]} filenames - Image filenames
   * @returns {Promise<object>}
   */
  async getImagesBase64(filenames) {
    Logger.info('Fetching multiple images');
    const results = {};
    for (const filename of filenames) {
      try {
        results[filename] = await this.getImageBase64(filename);
      } catch (error) {
        Logger.warn(`Failed to fetch image: ${filename}`, error);
      }
    }
    return results;
  },
};

/**
 * Upload Service - Handle file uploads
 */
export const UploadService = {
  /**
   * Upload creative files
   * @param {File[]} files - Files to upload
   * @returns {Promise<object>}
   */
  async uploadCreatives(files) {
    Logger.info('Uploading creatives', { count: files.length });

    const formData = new FormData();
    files.forEach((file) => {
      formData.append('files', file);
    });

    const response = await fetch(`${CONFIG.API.BASE_URL}/upload-creatives`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`Upload failed: HTTP ${response.status}`);
    }

    return response.json();
  },

  /**
   * Delete a creative by filename
   * @param {string} filename - Filename
   * @returns {Promise<object>}
   */
  async deleteCreative(filename) {
    Logger.info('Deleting creative', { filename });
    return HTTPClient.post(`${CONFIG.API.BASE_URL}/delete-creative`, { filename });
  },
};

/**
 * VPN Service - Handle VPN operations
 */
export const VPNService = {
  /**
   * Connect VPN
   * @param {object} config - VPN configuration
   * @returns {Promise<object>}
   */
  async connect(config) {
    Logger.info('Connecting VPN', { provider: config.provider });
    return HTTPClient.post(`${CONFIG.API.BASE_URL}/vpn/connect`, config);
  },

  /**
   * Disconnect VPN
   * @returns {Promise<object>}
   */
  async disconnect() {
    Logger.info('Disconnecting VPN');
    return HTTPClient.post(`${CONFIG.API.BASE_URL}/vpn/disconnect`, {});
  },

  /**
   * Get VPN status
   * @returns {Promise<object>}
   */
  async getStatus() {
    Logger.debug('Fetching VPN status');
    return HTTPClient.get(`${CONFIG.API.BASE_URL}/vpn/status`);
  },
};

/**
 * Health Service - Check backend health
 */
export const HealthService = {
  /**
   * Check backend health
   * @returns {Promise<object>}
   */
  async check() {
    Logger.debug('Checking backend health');
    try {
      return await HTTPClient.get(`${CONFIG.API.BASE_URL}/health`, { timeout: 5000 });
    } catch (error) {
      Logger.warn('Backend health check failed', error);
      throw error;
    }
  },
};

export default {
  ScanService,
  ResultsService,
  PPTService,
  UploadService,
  VPNService,
  HealthService,
};
