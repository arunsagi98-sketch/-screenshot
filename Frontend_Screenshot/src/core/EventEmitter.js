/**
 * Event Emitter - Simple pubsub pattern for app-wide event communication
 * Allows decoupled communication between different modules
 */

class EventEmitter {
  constructor() {
    this.events = new Map();
  }

  /**
   * Register an event listener
   * @param {string} eventName - Name of the event
   * @param {Function} listener - Callback function
   * @returns {Function} Unsubscribe function
   */
  on(eventName, listener) {
    if (!this.events.has(eventName)) {
      this.events.set(eventName, []);
    }
    this.events.get(eventName).push(listener);

    // Return unsubscribe function
    return () => this.off(eventName, listener);
  }

  /**
   * Register a one-time event listener
   * @param {string} eventName - Name of the event
   * @param {Function} listener - Callback function
   */
  once(eventName, listener) {
    const onceWrapper = (data) => {
      listener(data);
      this.off(eventName, onceWrapper);
    };
    this.on(eventName, onceWrapper);
  }

  /**
   * Remove an event listener
   * @param {string} eventName - Name of the event
   * @param {Function} listener - Callback function to remove
   */
  off(eventName, listener) {
    if (!this.events.has(eventName)) return;
    const listeners = this.events.get(eventName);
    const index = listeners.indexOf(listener);
    if (index > -1) {
      listeners.splice(index, 1);
    }
  }

  /**
   * Emit an event to all listeners
   * @param {string} eventName - Name of the event
   * @param {*} data - Data to pass to listeners
   */
  emit(eventName, data) {
    if (!this.events.has(eventName)) return;
    const listeners = this.events.get(eventName);
    listeners.forEach((listener) => {
      try {
        listener(data);
      } catch (error) {
        console.error(`Error in event listener for ${eventName}:`, error);
      }
    });
  }

  /**
   * Remove all listeners for an event
   * @param {string} eventName - Name of the event
   */
  clear(eventName) {
    if (eventName) {
      this.events.delete(eventName);
    } else {
      this.events.clear();
    }
  }
}

export default EventEmitter;
