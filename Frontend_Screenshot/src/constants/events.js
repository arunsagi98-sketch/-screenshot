/**
 * Application Event Constants
 * Standardized event names for application-wide event communication
 */

export const APP_EVENTS = {
  // Scan Events
  SCAN_STARTED: 'scan:started',
  SCAN_PROGRESS: 'scan:progress',
  SCAN_COMPLETED: 'scan:completed',
  SCAN_FAILED: 'scan:failed',

  // Results Events
  RESULTS_LOADED: 'results:loaded',
  RESULTS_UPDATED: 'results:updated',
  RESULT_DELETED: 'result:deleted',
  RESULTS_CLEARED: 'results:cleared',

  // UI Events
  MODAL_OPENED: 'modal:opened',
  MODAL_CLOSED: 'modal:closed',
  TOAST_SHOWN: 'toast:shown',
  TOAST_HIDDEN: 'toast:hidden',

  // Upload Events
  FILES_UPLOADED: 'files:uploaded',
  FILE_REMOVED: 'file:removed',
  UPLOADS_CLEARED: 'uploads:cleared',

  // Export Events
  EXPORT_STARTED: 'export:started',
  EXPORT_COMPLETED: 'export:completed',
  EXPORT_FAILED: 'export:failed',

  // VPN Events
  VPN_CONNECTED: 'vpn:connected',
  VPN_DISCONNECTED: 'vpn:disconnected',
  VPN_STATUS_UPDATED: 'vpn:statusUpdated',

  // Error Events
  ERROR_OCCURRED: 'error:occurred',
  WARNING_OCCURRED: 'warning:occurred',
};

export default APP_EVENTS;
