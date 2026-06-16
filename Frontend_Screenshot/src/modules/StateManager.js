/**
 * State Management Module
 * Centralized state management with event-driven updates
 */

import EventEmitter from '../core/EventEmitter.js';
import { APP_EVENTS } from '../constants/events.js';
import Logger from '../core/Logger.js';

class AppState extends EventEmitter {
  constructor() {
    super();

    this.state = {
      // Scan State
      scan: {
        isRunning: false,
        urls: [],
        progress: 0,
        currentUrl: null,
        error: null,
      },

      // Results State
      results: {
        items: [],
        selectedIds: new Set(),
        isLoading: false,
        lastUpdated: null,
      },

      // Upload State
      uploads: {
        files: [],
        isUploading: false,
        progress: 0,
      },

      // VPN State
      vpn: {
        isConnected: false,
        provider: 'NordVPN',
        country: 'United States',
        currentIp: null,
        location: null,
        isLoading: false,
      },

      // UI State
      ui: {
        modals: {
          ppt: false,
          progress: false,
        },
        toasts: [],
        theme: 'dark',
      },

      // Export State
      export: {
        isPptGenerating: false,
        isPdfGenerating: false,
      },
    };
  }

  /**
   * Get full state
   * @returns {object}
   */
  getState() {
    return this.state;
  }

  /**
   * Get nested state value
   * @param {string} path - Dot notation path (e.g., 'scan.isRunning')
   * @returns {any}
   */
  getValue(path) {
    return path.split('.').reduce((obj, key) => obj?.[key], this.state);
  }

  /**
   * Update state
   * @param {string} path - Dot notation path
   * @param {any} value - New value
   * @param {string} eventName - Event to emit
   */
  setValue(path, value, eventName) {
    const keys = path.split('.');
    const lastKey = keys.pop();
    let obj = this.state;

    for (const key of keys) {
      obj = obj[key];
    }

    const oldValue = obj[lastKey];
    if (oldValue === value) return;

    obj[lastKey] = value;

    Logger.debug('State updated', { path, oldValue, newValue: value });

    if (eventName) {
      this.emit(eventName, { path, oldValue, newValue: value });
    }
  }

  /**
   * Merge state
   * @param {string} path - Dot notation path
   * @param {object} updates - Object to merge
   * @param {string} eventName - Event to emit
   */
  mergeValue(path, updates, eventName) {
    const keys = path.split('.');
    const lastKey = keys.pop();
    let obj = this.state;

    for (const key of keys) {
      obj = obj[key];
    }

    obj[lastKey] = { ...obj[lastKey], ...updates };

    Logger.debug('State merged', { path, updates });

    if (eventName) {
      this.emit(eventName, { path, updates });
    }
  }

  // --- SCAN STATE METHODS ---

  setScanRunning(isRunning) {
    this.setValue('scan.isRunning', isRunning, APP_EVENTS.SCAN_STARTED);
  }

  setScanUrls(urls) {
    this.setValue('scan.urls', urls);
  }

  setScanProgress(progress) {
    this.setValue('scan.progress', progress, APP_EVENTS.SCAN_PROGRESS);
  }

  setScanCurrentUrl(url) {
    this.setValue('scan.currentUrl', url);
  }

  setScanError(error) {
    this.setValue('scan.error', error, APP_EVENTS.SCAN_FAILED);
  }

  resetScan() {
    this.mergeValue('scan', {
      isRunning: false,
      urls: [],
      progress: 0,
      currentUrl: null,
      error: null,
    });
  }

  // --- RESULTS STATE METHODS ---

  setResults(items) {
    this.mergeValue('results', {
      items,
      lastUpdated: new Date().toISOString(),
    }, APP_EVENTS.RESULTS_UPDATED);
  }

  addResult(result) {
    const items = [result, ...this.state.results.items];
    this.setResults(items);
  }

  removeResult(id) {
    const items = this.state.results.items.filter((r) => r.id !== id);
    this.setResults(items);
    this.emit(APP_EVENTS.RESULT_DELETED, { id });
  }

  selectResult(id) {
    this.state.results.selectedIds.add(id);
    this.emit(APP_EVENTS.RESULTS_UPDATED);
  }

  deselectResult(id) {
    this.state.results.selectedIds.delete(id);
    this.emit(APP_EVENTS.RESULTS_UPDATED);
  }

  selectAllResults() {
    this.state.results.items.forEach((r) => {
      this.state.results.selectedIds.add(r.id);
    });
    this.emit(APP_EVENTS.RESULTS_UPDATED);
  }

  deselectAllResults() {
    this.state.results.selectedIds.clear();
    this.emit(APP_EVENTS.RESULTS_UPDATED);
  }

  getSelectedResults() {
    return this.state.results.items.filter((r) => this.state.results.selectedIds.has(r.id));
  }

  getSelectedResultIds() {
    return Array.from(this.state.results.selectedIds);
  }

  clearResults() {
    this.setResults([]);
    this.deselectAllResults();
    this.emit(APP_EVENTS.RESULTS_CLEARED);
  }

  // --- UPLOAD STATE METHODS ---

  addUploadedFile(file) {
    this.state.uploads.files.push(file);
    this.emit(APP_EVENTS.FILES_UPLOADED, { files: [file] });
  }

  addUploadedFiles(files) {
    this.state.uploads.files.push(...files);
    this.emit(APP_EVENTS.FILES_UPLOADED, { files });
  }

  removeUploadedFile(filename) {
    this.state.uploads.files = this.state.uploads.files.filter((f) => f.name !== filename);
    this.emit(APP_EVENTS.FILE_REMOVED, { filename });
  }

  getUploadedFiles() {
    return this.state.uploads.files;
  }

  clearUploads() {
    this.state.uploads.files = [];
    this.emit(APP_EVENTS.UPLOADS_CLEARED);
  }

  setUploadProgress(progress) {
    this.setValue('uploads.progress', progress);
  }

  // --- VPN STATE METHODS ---

  setVpnConnected(isConnected) {
    this.setValue('vpn.isConnected', isConnected, APP_EVENTS.VPN_CONNECTED);
  }

  setVpnStatus(ip, location) {
    this.mergeValue('vpn', { currentIp: ip, location }, APP_EVENTS.VPN_STATUS_UPDATED);
  }

  setVpnProvider(provider) {
    this.setValue('vpn.provider', provider);
  }

  setVpnCountry(country) {
    this.setValue('vpn.country', country);
  }

  // --- UI STATE METHODS ---

  openModal(modalName) {
    this.setValue(`ui.modals.${modalName}`, true, APP_EVENTS.MODAL_OPENED);
  }

  closeModal(modalName) {
    this.setValue(`ui.modals.${modalName}`, false, APP_EVENTS.MODAL_CLOSED);
  }

  addToast(message, type = 'info') {
    const toast = {
      id: Date.now(),
      message,
      type,
    };
    this.state.ui.toasts.push(toast);
    this.emit(APP_EVENTS.TOAST_SHOWN, toast);
    return toast.id;
  }

  removeToast(toastId) {
    this.state.ui.toasts = this.state.ui.toasts.filter((t) => t.id !== toastId);
    this.emit(APP_EVENTS.TOAST_HIDDEN, { toastId });
  }

  // --- EXPORT STATE METHODS ---

  setExporting(type, isExporting) {
    const key = type === 'ppt' ? 'isPptGenerating' : 'isPdfGenerating';
    this.setValue(`export.${key}`, isExporting);
  }

  isPptExporting() {
    return this.state.export.isPptGenerating;
  }

  isPdfExporting() {
    return this.state.export.isPdfGenerating;
  }
}

export default new AppState();
