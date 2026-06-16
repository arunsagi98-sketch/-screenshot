/**
 * Application Entry Point
 * Initialize and start the application
 */

import Application from './modules/Application.js';
import Logger, { LOG_LEVEL } from './core/Logger.js';

// Set logger level based on environment
const isDevelopment = true; // Change based on your environment
Logger.setLevel(isDevelopment ? LOG_LEVEL.DEBUG : LOG_LEVEL.INFO);

Logger.info('Starting application...');

// Initialize application when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeApp);
} else {
  initializeApp();
}

async function initializeApp() {
  try {
    const app = new Application();
    await app.initialize();

    // Make app globally available for debugging
    if (isDevelopment) {
      window.__APP__ = app;
      window.__LOGGER__ = Logger;
      console.log('App available at window.__APP__');
      console.log('Logger available at window.__LOGGER__');
    }
  } catch (error) {
    Logger.error('Failed to start application', error);
  }
}
