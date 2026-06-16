/**
 * ResultsRenderer — renders results into a <tbody> as table rows.
 * Supports pagination + client-side search filtering.
 */

import CONFIG from '../constants/config.js';

const PAGE_SIZE = 8;

const getScreenshotUrl = (path) => {
  if (!path) return null;
  if (path.startsWith('http')) return path;
  const clean = path.replace(/\\/g, '/').replace(/^\/+/, '');
  return `${CONFIG.API.BASE_URL}/${clean}`;
};

const getCreativeUrl = (name) => {
  if (!name) return null;
  return `${CONFIG.API.BASE_URL}/creatives/${encodeURIComponent(name)}`;
};

const formatDate = (iso) => {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
      + '  ' + d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  } catch { return iso; }
};

const formatPlacement = (size) => {
  if (!size) return '—';
  const map = {
    '728x90':  'Top Banner',
    '300x250': 'Medium Rectangle',
    '160x600': 'Wide Skyscraper',
    '300x600': 'Half Page',
    '320x50':  'Mobile Banner',
    '970x250': 'Billboard',
    '468x60':  'Full Banner',
    '336x280': 'Large Rectangle',
  };
  const label = map[size] || 'Ad Slot';
  return `${label} (${size})`;
};

const buildRow = (result, index) => {
  const tr = document.createElement('tr');
  tr.dataset.resultId = result.id;

  const ssUrl  = getScreenshotUrl(result.screenshot_path);
  const criUrl = getCreativeUrl(result.matched_creative_name);
  const isOk   = result.status === 'success';

  const ssThumb = ssUrl
    ? `<img class="thumb-screenshot" src="${ssUrl}" alt="Screenshot"
         title="Click to open full screenshot"
         onerror="this.outerHTML='<div class=\\'no-thumb\\'><i class=\\'bx bx-image-x\\'></i></div>'">`
    : `<div class="no-thumb"><i class='bx bx-image-x'></i></div>`;

  const criThumb = criUrl
    ? `<img class="thumb-img" src="${criUrl}" alt="${result.matched_creative_name || ''}"
         onerror="this.outerHTML='<div class=\\'no-thumb\\'><i class=\\'bx bx-image-x\\'></i></div>'">`
    : `<div class="no-thumb"><i class='bx bx-image-x'></i></div>`;

  tr.innerHTML = `
    <td><input type="checkbox" class="result-checkbox" value="${result.id}"></td>
    <td style="color:var(--text-sec)">${index + 1}</td>
    <td>
      <div class="url-cell" title="${result.url}" data-href="${result.url}">
        ${(result.url || '').replace(/^https?:\/\//, '').substring(0, 40)}${(result.url || '').length > 50 ? '…' : ''}
        <i class='bx bx-link-external'></i>
      </div>
    </td>
    <td>${criThumb}</td>
    <td><span class="placement-txt">${formatPlacement(result.matched_creative_size)}</span></td>
    <td class="ss-cell">${ssThumb}</td>
    <td><span class="status-pill ${isOk ? 's-ok' : 's-fail'}">${isOk ? 'Completed' : 'Failed'}</span></td>
    <td>
      <div class="act-btns">
        <button class="act-btn" data-action="view" data-url="${ssUrl || ''}" title="View screenshot"><i class='bx bx-show'></i></button>
        <button class="act-btn" data-action="download" data-url="${ssUrl || ''}" data-id="${result.id}" title="Download"><i class='bx bx-download'></i></button>
        <button class="act-btn del" data-action="delete-result" data-result-id="${result.id}" title="Delete"><i class='bx bx-trash'></i></button>
      </div>
    </td>
    <td class="date-cell">${formatDate(result.created_at_ist || result.created_at)}</td>
  `;

  return tr;
};

export default class ResultsRenderer {
  constructor(tbodyElement) {
    this.tbody    = tbodyElement;
    this._all     = [];   // full result set
    this._filtered = [];  // after search filter
    this._page    = 1;
    this._search  = '';
    this._selectedIds = new Set();

    // Wire up click delegation on tbody
    if (this.tbody) {
      this.tbody.addEventListener('click', (e) => this._handleClick(e));
    }
  }

  /** Render full result set, reset to page 1 */
  render(results) {
    this._all = Array.isArray(results) ? results : [];
    this._page = 1;
    this._selectedIds.clear();
    this._applyFilter();
  }

  /** Remove a single row by id */
  removeResult(id) {
    this._all      = this._all.filter(r => r.id !== id);
    this._filtered = this._filtered.filter(r => r.id !== id);
    this._selectedIds.delete(id);
    this._renderPage();
    this._updateCountBadge();
  }

  /** Apply search string */
  setSearch(query) {
    this._search = (query || '').toLowerCase().trim();
    this._page = 1;
    this._applyFilter();
  }

  /** Select / deselect all visible rows */
  setSelectAll(checked) {
    this._filtered.forEach(r => {
      if (checked) this._selectedIds.add(r.id);
      else         this._selectedIds.delete(r.id);
    });
    this.tbody && this.tbody.querySelectorAll('.result-checkbox').forEach(cb => {
      cb.checked = checked;
    });
  }

  getSelectedIds()   { return Array.from(this._selectedIds); }
  selectResult(id)   { this._selectedIds.add(id); }
  deselectResult(id) { this._selectedIds.delete(id); }

  // ── Private ──────────────────────────────────────────────────

  _applyFilter() {
    this._filtered = this._search
      ? this._all.filter(r => (r.url || '').toLowerCase().includes(this._search))
      : [...this._all];
    this._renderPage();
    this._updateCountBadge();
  }

  _renderPage() {
    if (!this.tbody) return;
    const total = this._filtered.length;
    const start = (this._page - 1) * PAGE_SIZE;
    const slice = this._filtered.slice(start, start + PAGE_SIZE);

    if (total === 0) {
      this.tbody.innerHTML = `<tr><td colspan="9" class="empty-td">No results found.</td></tr>`;
    } else {
      this.tbody.innerHTML = '';
      slice.forEach((r, i) => {
        const tr = buildRow(r, start + i);
        // Restore checkbox state
        if (this._selectedIds.has(r.id)) {
          const cb = tr.querySelector('.result-checkbox');
          if (cb) cb.checked = true;
        }
        this.tbody.appendChild(tr);
      });
    }

    this._renderPagination(total);
    this._renderTableInfo(total, start, start + slice.length);
  }

  _renderPagination(total) {
    const pgEl = document.getElementById('pagination');
    if (!pgEl) return;
    const pages = Math.ceil(total / PAGE_SIZE);
    if (pages <= 1) { pgEl.innerHTML = ''; return; }

    let html = '';
    html += `<button class="pg-btn" data-pg="${this._page - 1}" ${this._page === 1 ? 'disabled' : ''}><i class='bx bx-chevron-left'></i></button>`;
    for (let p = 1; p <= pages; p++) {
      html += `<button class="pg-btn ${p === this._page ? 'active' : ''}" data-pg="${p}">${p}</button>`;
    }
    html += `<button class="pg-btn" data-pg="${this._page + 1}" ${this._page === pages ? 'disabled' : ''}><i class='bx bx-chevron-right'></i></button>`;
    pgEl.innerHTML = html;

    pgEl.querySelectorAll('.pg-btn:not([disabled])').forEach(btn => {
      btn.addEventListener('click', () => {
        this._page = parseInt(btn.dataset.pg);
        this._renderPage();
      });
    });
  }

  _renderTableInfo(total, from, to) {
    const el = document.getElementById('table-info');
    if (!el) return;
    el.textContent = total === 0
      ? 'Showing 0 results'
      : `Showing ${from + 1} to ${to} of ${total} results`;
  }

  _updateCountBadge() {
    const badge = document.getElementById('results-count');
    if (badge) badge.textContent = this._all.length;
  }

  _handleClick(e) {
    const action = e.target.closest('[data-action]');
    if (!action) return;
    const type = action.dataset.action;

    if (type === 'view') {
      const url = action.dataset.url;
      if (url) window.open(url, '_blank');
    }
    if (type === 'download') {
      const url = action.dataset.url;
      if (url) {
        const a = document.createElement('a');
        a.href = url; a.download = `screenshot_${action.dataset.id}.png`;
        a.click();
      }
    }
    // delete-result is handled by Application.js via delegation on tbody
  }
}
