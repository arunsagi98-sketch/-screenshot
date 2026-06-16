/**
 * Common Utilities - Reusable helper functions
 * Pure functions for data transformation and validation
 */

import CONFIG from '../constants/config.js';

export const URLUtils = {
  /**
   * Parse URLs from text input
   * @param {string} text - Input text with URLs
   * @returns {string[]} Valid URLs
   */
  parseUrls(text) {
    return text
      .split(/[\n,]+/)
      .map((url) => url.trim())
      .filter((url) => url.length > 0 && this.isValidUrl(url));
  },

  /**
   * Validate URL format
   * @param {string} url - URL to validate
   * @returns {boolean}
   */
  isValidUrl(url) {
    try {
      new URL(url);
      return true;
    } catch {
      return false;
    }
  },

  /**
   * Extract domain from URL
   * @param {string} url - URL string
   * @returns {string} Domain name
   */
  getDomain(url) {
    try {
      const urlObj = new URL(url);
      return urlObj.hostname.replace('www.', '');
    } catch {
      return url;
    }
  },

  /**
   * Shorten URL for display
   * @param {string} url - URL string
   * @param {number} maxLength - Max length
   * @returns {string} Shortened URL
   */
  shortenUrl(url, maxLength = 50) {
    const cleaned = url.replace(/https?:\/\/(www\.)?/, '');
    return cleaned.length > maxLength ? cleaned.substring(0, maxLength) + '...' : cleaned;
  },
};

export const DateUtils = {
  /**
   * Format date to display string
   * @param {string|Date} dateInput - Date to format
   * @returns {string} Formatted date
   */
  formatDate(dateInput) {
    const date = new Date(dateInput);
    if (Number.isNaN(date.getTime())) return dateInput;

    const options = {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    };

    return date.toLocaleDateString('en-US', options);
  },

  /**
   * Format date to short format (e.g., "Feb'26")
   * @param {string} dateStr - Date string
   * @returns {string} Short formatted date
   */
  formatShortDate(dateStr) {
    try {
      const clean = dateStr.replace(/(\d+)(st|nd|rd|th)/, '$1');
      const d = new Date(clean);

      if (Number.isNaN(d.getTime())) return dateStr;

      const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      return `${months[d.getMonth()]}'${d.getFullYear().toString().slice(-2)}`;
    } catch {
      return dateStr;
    }
  },

  /**
   * Get date range string
   * @param {string} startDate - Start date
   * @param {string} endDate - End date
   * @returns {string} Date range string
   */
  getDateRange(startDate, endDate) {
    return `${this.formatShortDate(startDate)} to ${this.formatShortDate(endDate)}`;
  },
};

export const FileUtils = {
  /**
   * Validate file type
   * @param {File} file - File object
   * @returns {boolean}
   */
  isValidImageFile(file) {
    return CONFIG.UPLOAD.ALLOWED_TYPES.includes(file.type);
  },

  /**
   * Validate file size
   * @param {File} file - File object
   * @returns {boolean}
   */
  isValidFileSize(file) {
    return file.size <= CONFIG.UPLOAD.MAX_FILE_SIZE;
  },

  /**
   * Get file extension
   * @param {string} filename - Filename
   * @returns {string} Extension
   */
  getExtension(filename) {
    return filename.substring(filename.lastIndexOf('.'));
  },

  /**
   * Format file size for display
   * @param {number} bytes - File size in bytes
   * @returns {string} Formatted size
   */
  formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';

    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));

    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
  },

  /**
   * Get image dimensions from File
   * @param {File} file - Image file
   * @returns {Promise<{width: number, height: number}>}
   */
  async getImageDimensions(file) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        resolve({ width: img.width, height: img.height });
      };
      img.onerror = reject;
      img.src = URL.createObjectURL(file);
    });
  },
};

export const StringUtils = {
  /**
   * Truncate string with ellipsis
   * @param {string} text - Text to truncate
   * @param {number} maxLength - Max length
   * @returns {string} Truncated text
   */
  truncate(text, maxLength = 50) {
    return text.length > maxLength ? text.substring(0, maxLength) + '...' : text;
  },

  /**
   * Capitalize first letter
   * @param {string} text - Text to capitalize
   * @returns {string} Capitalized text
   */
  capitalize(text) {
    return text.charAt(0).toUpperCase() + text.slice(1);
  },

  /**
   * Convert to slug format
   * @param {string} text - Text to convert
   * @returns {string} Slug format
   */
  toSlug(text) {
    return text
      .toLowerCase()
      .replace(/[^\w\s-]/g, '')
      .replace(/\s+/g, '-');
  },

  /**
   * Count words in string
   * @param {string} text - Text to count
   * @returns {number} Word count
   */
  countWords(text) {
    return text.trim().split(/\s+/).length;
  },
};

export const NumberUtils = {
  /**
   * Format number with comma separators
   * @param {number} num - Number to format
   * @returns {string} Formatted number
   */
  format(num) {
    return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  },

  /**
   * Generate random number in range
   * @param {number} min - Minimum
   * @param {number} max - Maximum
   * @returns {number} Random number
   */
  random(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;
  },

  /**
   * Clamp number between min and max
   * @param {number} num - Number
   * @param {number} min - Minimum
   * @param {number} max - Maximum
   * @returns {number} Clamped number
   */
  clamp(num, min, max) {
    return Math.max(min, Math.min(max, num));
  },
};

export const ArrayUtils = {
  /**
   * Remove duplicate items from array
   * @param {any[]} arr - Array
   * @returns {any[]} Unique items
   */
  unique(arr) {
    return [...new Set(arr)];
  },

  /**
   * Flatten nested array
   * @param {any[]} arr - Array
   * @returns {any[]} Flattened array
   */
  flatten(arr) {
    return arr.reduce((flat, item) => {
      return flat.concat(Array.isArray(item) ? this.flatten(item) : item);
    }, []);
  },

  /**
   * Chunk array into groups
   * @param {any[]} arr - Array
   * @param {number} size - Chunk size
   * @returns {any[][]} Chunks
   */
  chunk(arr, size) {
    const chunks = [];
    for (let i = 0; i < arr.length; i += size) {
      chunks.push(arr.slice(i, i + size));
    }
    return chunks;
  },

  /**
   * Find difference between two arrays
   * @param {any[]} arr1 - First array
   * @param {any[]} arr2 - Second array
   * @returns {any[]} Difference
   */
  difference(arr1, arr2) {
    return arr1.filter((item) => !arr2.includes(item));
  },
};

export default {
  URLUtils,
  DateUtils,
  FileUtils,
  StringUtils,
  NumberUtils,
  ArrayUtils,
};
