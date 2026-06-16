/**
 * Toast Notification Component
 * Handles toast notifications with auto-dismiss
 */

import { DOM } from '../core/DOM.js';
import CONFIG from '../constants/config.js';
import Logger from '../core/Logger.js';

export class ToastComponent {
  constructor() {
    this.toasts = new Map();
    this._ensureContainer();
  }

  /**
   * Ensure toast container exists
   * @private
   */
  _ensureContainer() {
    let container = document.getElementById('toast-container');
    if (!container) {
      container = DOM.createElement('div', {
        id: 'toast-container',
      });
      document.body.appendChild(container);
    }
    return container;
  }

  /**
   * Show a toast notification
   * @param {string} message - Toast message
   * @param {string} type - Toast type: 'info', 'success', 'error', 'warning'
   * @param {number} duration - Auto-dismiss duration in ms
   * @returns {string} Toast ID
   */
  show(message, type = 'info', duration = CONFIG.UI.TOAST_DURATION) {
    const container = this._ensureContainer();
    const toastId = Date.now().toString();

    const iconMap = {
      success: 'bxs-check-circle',
      error: 'bxs-error-circle',
      warning: 'bxs-error',
      info: 'bxs-info-circle',
    };

    const toast = DOM.createElement('div', {
      className: `toast ${type}`,
      html: `
        <i class='bx ${iconMap[type] || 'bxs-info-circle'}'></i>
        <span>${message}</span>
      `,
      attributes: { 'data-toast-id': toastId },
    });

    container.appendChild(toast);
    this.toasts.set(toastId, toast);

    Logger.debug('Toast shown', { message, type });

    // Auto dismiss
    if (duration > 0) {
      setTimeout(() => this.dismiss(toastId), duration);
    }

    return toastId;
  }

  /**
   * Dismiss a toast
   * @param {string} toastId - Toast ID
   */
  dismiss(toastId) {
    const toast = this.toasts.get(toastId);
    if (!toast) return;

    DOM.addClass(toast, 'dismissing');
    setTimeout(() => {
      toast.remove();
      this.toasts.delete(toastId);
    }, 300);
  }

  /**
   * Clear all toasts
   */
  clearAll() {
    this.toasts.forEach((_, toastId) => this.dismiss(toastId));
  }
}

export default ToastComponent;
