/**
 * Logger Utility - Centralized logging with levels and filtering
 * Provides consistent logging across the application
 */

export const LOG_LEVEL = {
  DEBUG: 0,
  INFO: 1,
  WARN: 2,
  ERROR: 3,
  SILENT: 4,
};

class Logger {
  constructor(level = LOG_LEVEL.INFO) {
    this.level = level;
    this.logs = [];
    this.maxLogs = 1000;
  }

  /**
   * Set log level
   * @param {number} level - Log level from LOG_LEVEL
   */
  setLevel(level) {
    this.level = level;
  }

  /**
   * Log debug message
   * @param {string} message - Message to log
   * @param {any} data - Additional data
   */
  debug(message, data) {
    this._log(LOG_LEVEL.DEBUG, message, data, '#888');
  }

  /**
   * Log info message
   * @param {string} message - Message to log
   * @param {any} data - Additional data
   */
  info(message, data) {
    this._log(LOG_LEVEL.INFO, message, data, '#0088ff');
  }

  /**
   * Log warning message
   * @param {string} message - Message to log
   * @param {any} data - Additional data
   */
  warn(message, data) {
    this._log(LOG_LEVEL.WARN, message, data, '#ff8800');
  }

  /**
   * Log error message
   * @param {string} message - Message to log
   * @param {Error|any} error - Error object or data
   */
  error(message, error) {
    this._log(LOG_LEVEL.ERROR, message, error, '#ff0000');
  }

  /**
   * Log group start
   * @param {string} label - Group label
   */
  group(label) {
    if (this.level <= LOG_LEVEL.INFO) {
      console.group(label);
    }
  }

  /**
   * Log group end
   */
  groupEnd() {
    if (this.level <= LOG_LEVEL.INFO) {
      console.groupEnd();
    }
  }

  /**
   * Get all logs
   * @returns {object[]}
   */
  getLogs() {
    return this.logs;
  }

  /**
   * Clear logs
   */
  clearLogs() {
    this.logs = [];
  }

  /**
   * Export logs as JSON
   * @returns {string}
   */
  exportLogs() {
    return JSON.stringify(this.logs, null, 2);
  }

  /**
   * Internal logging method
   * @private
   * @param {number} level - Log level
   * @param {string} message - Message
   * @param {any} data - Data
   * @param {string} color - Console color
   */
  _log(level, message, data, color) {
    if (level < this.level) return;

    const timestamp = new Date().toISOString();
    const levelName = Object.keys(LOG_LEVEL).find((key) => LOG_LEVEL[key] === level);

    const logEntry = {
      timestamp,
      level: levelName,
      message,
      data,
    };

    this.logs.push(logEntry);

    // Keep logs bounded
    if (this.logs.length > this.maxLogs) {
      this.logs.shift();
    }

    // Console output
    const prefix = `[${timestamp}] ${levelName}`;
    if (data) {
      console.log(`%c${prefix}%c ${message}`, `color: ${color}; font-weight: bold;`, '', data);
    } else {
      console.log(`%c${prefix}%c ${message}`, `color: ${color}; font-weight: bold;`, '');
    }
  }
}

export default new Logger(LOG_LEVEL.INFO);
