import { getResultImageUrl } from '../services/apiService.js';
import { formatDate } from '../utils/helpers.js';

const resultsGrid = () => document.getElementById('results-grid');
const resultsCount = () => document.getElementById('results-count');

const tidyUrl = (url) => url.replace(/^https?:\/\//, '');

export const getSelectedResultIds = () =>
  Array.from(document.querySelectorAll('.result-checkbox:checked')).map((checkbox) =>
    Number(checkbox.value)
  );

const renderEmptyState = () => {
  const grid = resultsGrid();
  if (!grid) return;
  grid.innerHTML = `
    <div class="empty-state">
      <i class='bx bx-history'></i>
      <p>No successful mockups yet. Upload your creatives and run a scan to see your screenshots!</p>
    </div>
  `;
};

const createResultCard = (result) => {
  const card = document.createElement('div');
  card.className = 'result-card';

  const afterUrl = getResultImageUrl(result.screenshot_path);
  const isSuccess = result.status === 'success';

  card.innerHTML = `
    <div class="card-header">
      <div style="display: flex; align-items: center; gap: 8px; overflow: hidden;">
        <input type="checkbox" class="result-checkbox" value="${result.id}" style="cursor: pointer; width: 16px; height: 16px;">
        <div class="card-url" title="${result.url}">${tidyUrl(result.url)}</div>
      </div>
      <div style="display: flex; gap: 8px; align-items: center;">
        <div class="status-tag ${isSuccess ? 'status-success' : 'status-failed'}">
          ${result.status}
        </div>
        <button class="delete-btn" data-result-id="${result.id}" title="Delete Result">
          <i class='bx bx-trash'></i>
        </button>
      </div>
    </div>

    <div class="card-image" style="position: relative;">
      ${
        afterUrl
          ? `<img
               class="result-img"
               src="${afterUrl}"
               alt="Ad-injected screenshot of ${result.url}"
               loading="lazy"
               style="width:100%; height:100%; object-fit:cover; display:block;"
               onerror="this.parentElement.innerHTML='<div class=\\'no-image\\'><i class=\\'bx bx-image-x\\' style=\\'font-size:3rem;margin-bottom:10px;color:#ef4444;\\'></i><p>Image not found</p></div>'"
             >`
          : `<div class="no-image"><i class='bx bx-image-x' style="font-size: 3rem; margin-bottom: 10px;"></i><p>No screenshot</p></div>`
      }
    </div>

    <div class="card-footer" style="flex-direction: column; align-items: stretch; gap: 8px;">
      <div style="display: flex; justify-content: space-between; font-size: 0.85rem;">
        <div class="stat" title="Matched Creative">
          <i class='bx bx-image' style="color: var(--accent-color);"></i>
          <span style="font-weight: 500; color: var(--text-primary);">${result.matched_creative_name ? result.matched_creative_name.substring(0, 15) : 'Auto'}</span>
          ${result.matched_creative_size ? `<span style="opacity: 0.7; font-size: 0.75rem;">(${result.matched_creative_size})</span>` : ''}
        </div>
        <div class="stat" title="Ads detected / Ads replaced">
          <i class='bx bx-target-lock'></i> ${result.matches_found}/${result.ads_found} matches
        </div>
      </div>
      <div style="display: flex; justify-content: space-between; border-top: 1px solid var(--panel-border); padding-top: 8px;">
        <div class="stat" style="opacity: 0.8;">
          <i class='bx ${result.device === 'Mobile' ? 'bx-mobile' : 'bx-desktop'}'></i> ${result.device || 'Desktop'}
        </div>
        <div class="stat" style="color: var(--accent-color); font-weight: 500;">
          <i class='bx bx-time-five'></i> ${formatDate(result.created_at)}
        </div>
      </div>
      ${afterUrl ? `
      <div style="border-top: 1px solid var(--panel-border); padding-top: 8px; display: flex; justify-content: flex-end;">
        <button
          class="export-image-btn"
          data-url="${afterUrl}"
          data-filename="screenshot_${result.id}.png"
          data-result-id="${result.id}"
          style="display:flex;align-items:center;gap:6px;padding:5px 12px;border-radius:6px;
                 border:1px solid rgba(99,102,241,.35);background:rgba(99,102,241,.1);
                 color:#818cf8;font-size:12px;cursor:pointer;transition:.15s;"
        >
          <i class='bx bx-download'></i> Export Image
        </button>
      </div>` : ''}
    </div>
  `;

  return card;
};

export const renderResults = (results) => {
  const grid = resultsGrid();
  if (!grid) return;

  const filtered = Array.isArray(results)
    ? results.filter((item) => item.status === 'success' && item.screenshot_path)
    : [];

  filtered.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

  const countElement = resultsCount();
  if (countElement) {
    countElement.textContent = `${filtered.length} result${filtered.length !== 1 ? 's' : ''}`;
  }

  grid.innerHTML = '';

  if (filtered.length === 0) {
    renderEmptyState();
    return;
  }

  filtered.forEach((item) => {
    const card = createResultCard(item);
    grid.appendChild(card);
  });
};

