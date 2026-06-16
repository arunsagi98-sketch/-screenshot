/**
 * Application Controller — AdVision AI
 */

import { DOM } from '../core/DOM.js';
import Logger from '../core/Logger.js';
import CONFIG from '../constants/config.js';
import { APP_EVENTS } from '../constants/events.js';
import { URLUtils, FileUtils } from '../lib/utils.js';
import AppState from './StateManager.js';
import { ScanService, ResultsService, UploadService, HealthService, PPTService } from './apiServices.js';
import { ToastComponent } from './ToastComponent.js';
import ResultsRenderer from './ResultsRenderer.js';

// ─── Helpers ────────────────────────────────────────────────────────────────

const formatBytes = (bytes) => {
  if (!bytes || bytes === 0) return '';
  if (bytes < 1024)             return `${bytes} B`;
  if (bytes < 1024 * 1024)      return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

// ─── Application ────────────────────────────────────────────────────────────

export default class Application {
  constructor() {
    this.elements        = null;
    this.resultsRenderer = null;
    this.toastComponent  = new ToastComponent();
    this.isInitialized   = false;
  }

  /* ═══════════════════════════════════════════
     INIT
  ═══════════════════════════════════════════ */
  async initialize() {
    try {
      Logger.info('Initializing AdVision AI');
      this.elements        = DOM.getElements();
      this.resultsRenderer = new ResultsRenderer(this.elements.resultsGrid);

      this._setupEventListeners();
      this._setupStateListeners();
      await this._checkBackendHealth();
      await Promise.all([this.loadResults(), this.loadCreatives()]);

      this.isInitialized = true;
      this.toastComponent.show('Application ready!', 'success');
    } catch (err) {
      Logger.error('Init failed', err);
      this.toastComponent.show('Failed to initialize application', 'error');
    }
  }

  /* ═══════════════════════════════════════════
     EVENT WIRING
  ═══════════════════════════════════════════ */
  _setupEventListeners() {
    // ── Scan ──────────────────────────────
    DOM.addEventListener(this.elements.startBtn,   'click', () => this._handleStartScan());
    DOM.addEventListener(this.elements.refreshBtn, 'click', () => this.loadResults());

    // ── Modals ────────────────────────────
    DOM.addEventListener(this.elements.finishProgressBtn, 'click', () => this._closeProgressModal());
    DOM.addEventListener(this.elements.closeProgressBtn,  'click', () => this._closeProgressModal());
    DOM.addEventListener(this.elements.closeModalBtn,     'click', () => this._closeModal());
    DOM.addEventListener(this.elements.generatePptBtn, 'click', () => this._handleGeneratePPT());
    // "Export All" directly triggers export — no extra modal click needed
    DOM.addEventListener(this.elements.exportPptBtn,   'click', () => this._handleGeneratePPT());

    // ── Upload Zone ───────────────────────
    DOM.addEventListener(this.elements.uploadZone,    'dragover',  (e) => this._onDragOver(e));
    DOM.addEventListener(this.elements.uploadZone,    'dragleave', ()  => DOM.removeClass(this.elements.uploadZone, 'dragover'));
    DOM.addEventListener(this.elements.uploadZone,    'drop',      (e) => this._onDrop(e));
    DOM.addEventListener(this.elements.fileInput,     'change',    (e) => this._handleFileSelect(e));
    DOM.addEventListener(this.elements.uploadFilesBtn,'click',     ()  => this.elements.fileInput.click());

    // ── Gallery delete (delegated) ─────────
    DOM.addEventListener(this.elements.uploadPreview, 'click', (e) => {
      const btn = e.target.closest('[data-action="delete-creative"]');
      if (btn) this._handleDeleteCreative(btn.dataset.filename);
    });

    // ── Clear ─────────────────────────────
    DOM.addEventListener(this.elements.clearUrlBtn,    'click', () => this._clearUrls());
    DOM.addEventListener(this.elements.clearImagesBtn, 'click', () => this._clearImages());

    // ── URL input ─────────────────────────
    DOM.addEventListener(this.elements.urlInput, 'input', () => this._updateUrlCount());

    // ── .txt upload ───────────────────────
    DOM.addEventListener(this.elements.uploadTxtBtn, 'click',
      () => this.elements.txtFileInput && this.elements.txtFileInput.click());
    DOM.addEventListener(this.elements.txtFileInput, 'change', (e) => this._handleTxtUpload(e));

    // ── Results table ─────────────────────
    DOM.addEventListener(this.elements.bulkDeleteBtn, 'click',  () => this._handleBulkDelete());
    DOM.addEventListener(this.elements.selectAllCb,  'change', (e) => this.resultsRenderer.setSelectAll(e.target.checked));
    DOM.addEventListener(this.elements.resultsSearch,'input',  (e) => this.resultsRenderer.setSearch(e.target.value));

    DOM.addEventListener(this.elements.resultsGrid, 'change', (e) => {
      if (e.target.classList.contains('result-checkbox')) {
        const id = parseInt(e.target.value);
        if (e.target.checked) this.resultsRenderer.selectResult(id);
        else                  this.resultsRenderer.deselectResult(id);
      }
    });
    DOM.addEventListener(this.elements.resultsGrid, 'click', (e) => {
      const delBtn  = e.target.closest('[data-action="delete-result"]');
      const urlCell = e.target.closest('.url-cell[data-href]');
      if (delBtn)  this._handleDeleteResult(parseInt(delBtn.dataset.resultId));
      if (urlCell) window.open(urlCell.dataset.href, '_blank');
    });

    // ── VPN stub ──────────────────────────
    DOM.addEventListener(this.elements.vpnToggleBtn, 'click', () =>
      this.toastComponent.show('VPN functionality coming soon', 'info'));

    // ── Sidebar toggle ────────────────────
    const hamburger = document.getElementById('sidebar-toggle');
    if (hamburger) hamburger.addEventListener('click', () => document.body.classList.toggle('sidebar-collapsed'));
  }

  _setupStateListeners() {
    // NOTE: SCAN_COMPLETED is emitted from _handleScanEvent on 'finished'.
    // Do NOT emit it again from _handleStartScan to avoid double-loading.
    AppState.on(APP_EVENTS.SCAN_COMPLETED, () => {
      this.loadResults();
      this._closeProgressModal();
      this.toastComponent.show('Campaign completed! Results are ready.', 'success');
    });

    AppState.on(APP_EVENTS.SCAN_FAILED, (ev) => {
      const msg = ev?.newValue?.message || ev?.message || 'Unknown error';
      this._closeProgressModal();
      this.toastComponent.show(`Scan failed: ${msg}`, 'error');
    });
  }

  /* ═══════════════════════════════════════════
     BACKEND HEALTH
  ═══════════════════════════════════════════ */
  async _checkBackendHealth() {
    const el = this.elements.backendStatus;
    try {
      await HealthService.check();
      if (el) { el.textContent = 'All Systems Operational'; el.className = 'sys-status-sub ok'; }
    } catch {
      if (el) { el.textContent = 'Backend Offline'; el.className = 'sys-status-sub offline'; }
    }
  }

  /* ═══════════════════════════════════════════
     RESULTS
  ═══════════════════════════════════════════ */
  async loadResults() {
    try {
      const raw = await ResultsService.getResults();
      const sorted = Array.isArray(raw)
        ? [...raw].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
        : [];
      AppState.setResults(sorted);
      this.resultsRenderer.render(sorted);
      // Re-apply active search filter
      const q = this.elements.resultsSearch?.value;
      if (q) this.resultsRenderer.setSearch(q);
    } catch (err) {
      Logger.error('Failed to load results', err);
      this.toastComponent.show('Could not load results — is the backend running?', 'error');
    }
  }

  /* ═══════════════════════════════════════════
     CREATIVES GALLERY — load from server on startup
  ═══════════════════════════════════════════ */
  async loadCreatives() {
    try {
      const res = await fetch(`${CONFIG.API.BASE_URL}/creatives`);
      if (!res.ok) return;
      const data  = await res.json();
      const files = data.files || [];
      if (files.length === 0) return;

      const gallery = this.elements.uploadPreview;
      const emptyEl = gallery && gallery.querySelector('.gallery-empty');
      if (emptyEl) emptyEl.remove();

      for (const f of files) {
        const imgUrl = `${CONFIG.API.BASE_URL}/creatives/${encodeURIComponent(f.name)}`;
        this._appendGalleryItem(f.name, imgUrl, f.width, f.height, f.size);
      }
      this._updateImageCount();
    } catch {
      // Non-fatal — backend may not be running yet
    }
  }

  /* ═══════════════════════════════════════════
     SCAN — only starts on button click
  ═══════════════════════════════════════════ */
  async _handleStartScan() {
    // Validate URLs
    const urls = URLUtils.parseUrls(this.elements.urlInput.value);
    if (urls.length === 0) {
      this.toastComponent.show('Please enter at least one valid URL', 'error');
      return;
    }

    // Validate images — check gallery DOM (covers both freshly uploaded and
    // pre-existing server files, not just in-memory AppState)
    const gallery   = this.elements.uploadPreview;
    const imgCount  = gallery ? gallery.querySelectorAll('.gal-item').length : 0;
    if (imgCount === 0) {
      this.toastComponent.show('Please upload at least one creative image', 'error');
      return;
    }

    try {
      AppState.setScanRunning(true);
      this.elements.startBtn.disabled = true;
      this._openProgressModal();

      // Stream scan — SCAN_COMPLETED is emitted inside _handleScanEvent
      // when the backend sends {"type":"finished"}. Do NOT emit it here again.
      await ScanService.startScan(urls, (ev) => this._handleScanEvent(ev));

    } catch (err) {
      Logger.error('Scan error', err);
      AppState.emit(APP_EVENTS.SCAN_FAILED, { message: err.message });
    } finally {
      AppState.setScanRunning(false);
      this.elements.startBtn.disabled = false;
    }
  }

  _handleScanEvent(event) {
    const { type, payload = {} } = event;
    Logger.debug('Scan event', { type, payload });

    switch (type) {
      case 'progress':
        if (this.elements.progressBarFill)
          this.elements.progressBarFill.style.width = `${payload.progress || 0}%`;
        break;

      case 'site_start':
        this._logProgress(`Scanning: ${payload.url}`, 'info');
        AppState.setScanCurrentUrl(payload.url);
        break;

      case 'match_success':
        this._logProgress(`✓ Matched creative on ${payload.url}`, 'success');
        break;

      case 'no_match':
        this._logProgress(`— No match found for ${payload.url}`, 'bullet');
        break;

      case 'error':
        this._logProgress(`✗ Error on ${payload.url || 'unknown'}: ${payload.message}`, 'error');
        break;

      case 'finished':
        this._logProgress('All URLs processed — results saved to database.', 'success');
        if (this.elements.progressBarFill) this.elements.progressBarFill.style.width = '100%';
        if (this.elements.finishProgressBtn) {
          this.elements.finishProgressBtn.disabled      = false;
          this.elements.finishProgressBtn.style.opacity = '1';
          this.elements.finishProgressBtn.style.cursor  = 'pointer';
          this.elements.finishProgressBtn.textContent   = 'Close & View Results';
        }
        // Single authoritative emit — state listener calls loadResults()
        AppState.emit(APP_EVENTS.SCAN_COMPLETED);
        break;
    }
  }

  /* ═══════════════════════════════════════════
     FILE UPLOAD
  ═══════════════════════════════════════════ */
  async _handleFileSelect(e) {
    const raw   = Array.from(e.target.files || []);
    const files = raw.filter(f => FileUtils.isValidImageFile(f));

    if (files.length === 0) {
      this.toastComponent.show('Select valid images (PNG, JPG, WEBP)', 'error');
      return;
    }

    // Show uploading state
    const icon = this.elements.uploadZone?.querySelector('.up-ic');
    if (icon) icon.className = 'bx bx-loader-alt bx-spin up-ic';

    try {
      await UploadService.uploadCreatives(files);
      AppState.addUploadedFiles(files);

      // Add each file to the gallery with real dimensions + size
      files.forEach(f => {
        const objectUrl = URL.createObjectURL(f);
        const img       = new Image();

        const addItem = (w, h) => {
          this._appendGalleryItem(f.name, objectUrl, w, h, f.size);
          this._updateImageCount();
        };

        img.onload  = () => addItem(img.naturalWidth, img.naturalHeight);
        img.onerror = () => addItem(null, null);   // still show even if preview fails
        img.src     = objectUrl;
      });

      this.toastComponent.show(`✓ ${files.length} image(s) uploaded`, 'success');
    } catch (err) {
      Logger.error('Upload failed', err);
      this.toastComponent.show(`Upload failed: ${err.message}`, 'error');
    } finally {
      if (icon) icon.className = 'bx bx-cloud-upload up-ic';
      // Reset file input so same file can be re-selected if needed
      if (e.target) e.target.value = '';
    }
  }

  /* ─── Gallery item ────────────────────────────────────────────────────── */
  _appendGalleryItem(name, src, w, h, size) {
    const gallery = this.elements.uploadPreview;
    if (!gallery) return;

    // Remove empty-state placeholder
    const emptyEl = gallery.querySelector('.gallery-empty');
    if (emptyEl) emptyEl.remove();

    // Prevent duplicates
    const exists = Array.from(gallery.querySelectorAll('[data-gal-name]'))
      .some(el => el.dataset.galName === name);
    if (exists) return;

    const dimLabel  = (w && h) ? `${w}×${h}` : '';
    const sizeLabel = formatBytes(size);

    const item = document.createElement('div');
    item.className     = 'gal-item';
    item.dataset.galName = name;

    item.innerHTML = `
      <div class="gal-img-wrap">
        <img src="${src}" alt="${name}" loading="lazy"
          onerror="this.style.display='none';this.parentElement.querySelector('.gal-no-img').style.display='flex'">
        <div class="gal-no-img" style="display:none">
          <i class='bx bx-image-x'></i>
        </div>
        ${dimLabel ? `<span class="gal-size">${dimLabel}</span>` : ''}
        <button class="gal-del-btn" data-action="delete-creative" data-filename="${name}" title="Remove image">
          <i class='bx bx-x'></i>
        </button>
      </div>
      <span class="gal-name" title="${name}">${name}</span>
      ${sizeLabel ? `<span class="gal-file-size">${sizeLabel}</span>` : ''}
    `;

    gallery.appendChild(item);
  }

  _updateImageCount() {
    const gallery = this.elements.uploadPreview;
    const count   = gallery ? gallery.querySelectorAll('.gal-item').length : 0;
    if (this.elements.imageCount)   this.elements.imageCount.textContent   = `Total Images: ${count}`;
    if (this.elements.galleryCount) this.elements.galleryCount.textContent = count;
  }

  _onDragOver(e) {
    e.preventDefault(); e.stopPropagation();
    DOM.addClass(this.elements.uploadZone, 'dragover');
  }

  _onDrop(e) {
    e.preventDefault(); e.stopPropagation();
    DOM.removeClass(this.elements.uploadZone, 'dragover');
    this._handleFileSelect({ target: { files: e.dataTransfer.files } });
  }

  async _handleTxtUpload(e) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    try {
      const text    = await file.text();
      const current = this.elements.urlInput.value.trim();
      this.elements.urlInput.value = current ? `${current}\n${text.trim()}` : text.trim();
      this._updateUrlCount();
      this.toastComponent.show('URLs imported from file', 'success');
    } catch {
      this.toastComponent.show('Failed to read .txt file', 'error');
    }
  }

  /* ═══════════════════════════════════════════
     DELETE CREATIVE
  ═══════════════════════════════════════════ */
  async _handleDeleteCreative(filename) {
    try {
      const res = await fetch(
        `${CONFIG.API.BASE_URL}/delete-creative?filename=${encodeURIComponent(filename)}`,
        { method: 'DELETE' }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const gallery = this.elements.uploadPreview;
      if (gallery) {
        const item = Array.from(gallery.querySelectorAll('[data-gal-name]'))
          .find(el => el.dataset.galName === filename);
        if (item) item.remove();
        if (gallery.querySelectorAll('.gal-item').length === 0) {
          gallery.innerHTML = '<div class="gallery-empty">No images uploaded yet</div>';
        }
      }
      AppState.removeUploadedFile(filename);
      this._updateImageCount();
      this.toastComponent.show(`Removed: ${filename}`, 'success');
    } catch (err) {
      this.toastComponent.show(`Failed to delete: ${err.message}`, 'error');
    }
  }

  /* ═══════════════════════════════════════════
     CLEAR
  ═══════════════════════════════════════════ */
  _clearUrls() {
    if (this.elements.urlInput) this.elements.urlInput.value = '';
    this._updateUrlCount();
  }

  _clearImages() {
    AppState.clearUploads();
    if (this.elements.uploadPreview)
      this.elements.uploadPreview.innerHTML = '<div class="gallery-empty">No images uploaded yet</div>';
    this._updateImageCount();
  }

  /* ═══════════════════════════════════════════
     URL COUNT
  ═══════════════════════════════════════════ */
  _updateUrlCount() {
    const urls = URLUtils.parseUrls(this.elements.urlInput.value);
    if (this.elements.urlCount)
      this.elements.urlCount.textContent = `Total URLs: ${urls.length}`;
  }

  /* ═══════════════════════════════════════════
     DELETE RESULT
  ═══════════════════════════════════════════ */
  async _handleDeleteResult(resultId) {
    if (!confirm('Delete this result?')) return;
    try {
      await ResultsService.deleteResult(resultId);
      AppState.removeResult(resultId);
      this.resultsRenderer.removeResult(resultId);
      this.toastComponent.show('Result deleted', 'success');
    } catch {
      this.toastComponent.show('Failed to delete result', 'error');
    }
  }

  async _handleBulkDelete() {
    const ids = this.resultsRenderer.getSelectedIds();
    if (ids.length === 0) {
      this.toastComponent.show('Select at least one result first', 'error');
      return;
    }
    if (!confirm(`Delete ${ids.length} selected result(s)?`)) return;
    try {
      if (this.elements.bulkDeleteBtn) {
        this.elements.bulkDeleteBtn.disabled  = true;
        this.elements.bulkDeleteBtn.innerHTML = '<i class="bx bx-loader-alt bx-spin"></i> Deleting...';
      }
      await Promise.all(ids.map(id => ResultsService.deleteResult(id).catch(() => null)));
      ids.forEach(id => {
        AppState.removeResult(id);
        this.resultsRenderer.removeResult(id);
      });
      this.toastComponent.show(`Deleted ${ids.length} result(s)`, 'success');
    } catch {
      this.toastComponent.show('Bulk delete failed', 'error');
    } finally {
      if (this.elements.bulkDeleteBtn) {
        this.elements.bulkDeleteBtn.disabled  = false;
        this.elements.bulkDeleteBtn.innerHTML = '<i class="bx bx-trash"></i> Delete Selected';
      }
    }
  }

  /* ═══════════════════════════════════════════
     PPT EXPORT
  ═══════════════════════════════════════════ */
  _openModal()  { AppState.openModal('ppt');  DOM.show(this.elements.pptModal); }
  _closeModal() { AppState.closeModal('ppt'); DOM.hide(this.elements.pptModal); }

  /**
   * Called by both "Export All" button AND "Generate Report" inside the modal.
   * Fetches fresh IDs from the API — never relies on stale AppState.
   */
  async _handleGeneratePPT() {
    // Determine which IDs to export
    // 1. Checked rows in the table (user hand-picked)
    // 2. Fall back: fetch ALL results live from API
    const selectedIds = this.resultsRenderer.getSelectedIds();

    let exportIds = selectedIds;

    if (exportIds.length === 0) {
      // Fetch current results fresh from the server
      try {
        const fresh = await ResultsService.getResults();
        exportIds = Array.isArray(fresh) ? fresh.map(r => r.id) : [];
      } catch {
        this.toastComponent.show('Could not reach backend — is it running?', 'error');
        return;
      }
    }

    if (exportIds.length === 0) {
      this.toastComponent.show('No scan results to export. Run a campaign first.', 'error');
      return;
    }

    // Update button state
    const btn = this.elements.generatePptBtn || this.elements.exportPptBtn;
    const origHtml = btn ? btn.innerHTML : '';
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<i class="bx bx-loader-alt bx-spin"></i> Generating…';
    }

    this.toastComponent.show(`Building PPT for ${exportIds.length} result(s)…`, 'info');

    try {
      const res = await fetch(`${CONFIG.API.BASE_URL}/results/export-ppt`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ ids: exportIds }),
      });

      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.message || `HTTP ${res.status}`);
      }

      const blob     = await res.blob();
      const blobUrl  = URL.createObjectURL(blob);
      const a        = document.createElement('a');
      a.href         = blobUrl;
      a.download     = `campaign_report_${new Date().toISOString().slice(0, 10)}.pptx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);

      this.toastComponent.show('✓ PPT downloaded successfully!', 'success');
      this._closeModal();
    } catch (err) {
      Logger.error('PPT export failed', err);
      this.toastComponent.show(`Export failed: ${err.message}`, 'error');
    } finally {
      if (btn) {
        btn.disabled  = false;
        btn.innerHTML = origHtml;
      }
    }
  }

  /* ═══════════════════════════════════════════
     PROGRESS MODAL
  ═══════════════════════════════════════════ */
  _openProgressModal() {
    if (this.elements.progressLog)       this.elements.progressLog.innerHTML      = '';
    if (this.elements.progressBarFill)   this.elements.progressBarFill.style.width = '0%';
    if (this.elements.progressMainTitle) this.elements.progressMainTitle.textContent = 'Running Campaign...';
    if (this.elements.progressSubtitle)  this.elements.progressSubtitle.textContent  = 'Launching Playwright Chromium browser...';
    if (this.elements.finishProgressBtn) {
      this.elements.finishProgressBtn.disabled      = true;
      this.elements.finishProgressBtn.style.opacity = '0.5';
      this.elements.finishProgressBtn.style.cursor  = 'not-allowed';
      this.elements.finishProgressBtn.textContent   = 'Waiting for scanner...';
    }
    DOM.show(this.elements.progressModal);
  }

  _closeProgressModal() {
    DOM.hide(this.elements.progressModal);
    AppState.closeModal('progress');
  }

  _logProgress(msg, type = 'bullet') {
    const log = this.elements.progressLog;
    if (!log) return;
    const div       = document.createElement('div');
    div.className   = `log-item ${type}`;
    div.textContent = msg;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }
}
