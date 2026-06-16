/**
 * DOM Utilities — element access + helpers
 */

export const DOM = {
  getElements() {
    return {
      // URL input
      urlInput:        document.getElementById('url-input'),
      urlCount:        document.getElementById('url-count'),
      clearUrlBtn:     document.getElementById('clear-url-btn'),
      uploadTxtBtn:    document.getElementById('upload-txt-btn'),
      txtFileInput:    document.getElementById('txt-file-input'),

      // Image upload
      fileInput:       document.getElementById('file-input'),
      uploadZone:      document.getElementById('upload-zone'),
      uploadPreview:   document.getElementById('upload-preview'),
      imageCount:      document.getElementById('image-count'),
      galleryCount:    document.getElementById('gallery-count'),
      clearImagesBtn:  document.getElementById('clear-images-btn'),
      uploadFilesBtn:  document.getElementById('upload-files-btn'),

      // VPN
      vpnProvider:     document.getElementById('vpn-provider'),
      vpnCountry:      document.getElementById('vpn-country'),
      vpnCountryGroup: document.getElementById('vpn-country-group'),
      vpnCustomGroup:  document.getElementById('vpn-custom-group'),
      vpnCustomCmd:    document.getElementById('vpn-custom-cmd'),
      vpnToggleBtn:    document.getElementById('vpn-toggle-btn'),
      vpnIpVal:        document.getElementById('vpn-ip-val'),
      vpnLocationVal:  document.getElementById('vpn-location-val'),

      // Results table (tbody)
      resultsGrid:     document.getElementById('results-grid'),
      resultsCount:    document.getElementById('results-count'),
      resultsSearch:   document.getElementById('results-search'),
      selectAllCb:     document.getElementById('select-all-cb'),
      tableInfo:       document.getElementById('table-info'),
      pagination:      document.getElementById('pagination'),

      // Action buttons
      startBtn:        document.getElementById('start-btn'),
      refreshBtn:      document.getElementById('refresh-btn'),
      bulkDeleteBtn:   document.getElementById('bulk-delete-btn'),
      exportPptBtn:    document.getElementById('export-ppt-btn'),

      // Legacy null stubs — Application.js references these; DOM.addEventListener handles null
      selectAllBtn:    null,
      deselectAllBtn:  null,

      // Status
      backendStatus:   document.getElementById('backend-status'),

      // Progress modal
      progressModal:         document.getElementById('progress-modal'),
      finishProgressBtn:     document.getElementById('finish-progress-btn'),
      closeProgressBtn:      document.getElementById('close-progress-btn'),
      progressMainTitle:     document.getElementById('progress-main-title'),
      progressSubtitle:      document.getElementById('progress-subtitle'),
      progressSpinner:       document.getElementById('progress-spinner'),
      progressBarFill:       document.getElementById('progress-bar-fill'),
      progressCreativesList: document.getElementById('progress-creatives-list'),
      progressLog:           document.getElementById('progress-log'),

      // Export modal
      pptModal:          document.getElementById('ppt-modal'),
      closeModalBtn:     document.getElementById('close-modal-btn'),
      generatePptBtn:    document.getElementById('generate-ppt-btn'),
      pdfCampaignTitle:  document.getElementById('pdf-campaign-title'),
      pdfStartDate:      document.getElementById('pdf-start-date'),
      pdfEndDate:        document.getElementById('pdf-end-date'),
      pdfFormat:         document.getElementById('pdf-format'),
    };
  },

  addEventListener(element, eventType, handler) {
    if (!element) return () => {};
    element.addEventListener(eventType, handler);
    return () => element.removeEventListener(eventType, handler);
  },

  addClass(element, classes) {
    if (!element) return;
    const arr = Array.isArray(classes) ? classes : [classes];
    element.classList.add(...arr);
  },

  removeClass(element, classes) {
    if (!element) return;
    const arr = Array.isArray(classes) ? classes : [classes];
    element.classList.remove(...arr);
  },

  toggleClass(element, className, force) {
    if (!element) return;
    element.classList.toggle(className, force);
  },

  show(element) { if (element) element.style.display = ''; },
  hide(element) { if (element) element.style.display = 'none'; },

  setAttributes(element, attributes) {
    if (!element) return;
    Object.entries(attributes).forEach(([k, v]) => {
      if (v === null || v === undefined) element.removeAttribute(k);
      else element.setAttribute(k, v);
    });
  },

  clear(element) { if (element) element.innerHTML = ''; },

  createElement(tag, options = {}) {
    const el = document.createElement(tag);
    if (options.className)  el.className   = options.className;
    if (options.id)         el.id          = options.id;
    if (options.text)       el.textContent = options.text;
    if (options.html)       el.innerHTML   = options.html;
    if (options.attributes) Object.entries(options.attributes).forEach(([k, v]) => el.setAttribute(k, v));
    if (options.styles)     Object.assign(el.style, options.styles);
    return el;
  },

  query(selector, context = document)    { return context.querySelector(selector); },
  queryAll(selector, context = document) { return Array.from(context.querySelectorAll(selector)); },
};

export default DOM;
