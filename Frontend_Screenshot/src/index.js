/**
 * LEGACY — monolithic entry point, superseded by the modular system.
 *
 * Active path: src/main.js → src/modules/Application.js
 * This file is no longer imported by index.html or any active module.
 * It can be deleted once the modular system fully covers all functionality.
 */

import { state } from './state/appState.js';
import { parseUrls, isImageFile, formatDate } from './utils/helpers.js';
import {
  uploadCreatives,
  deleteCreative,
  processScanStream,
  fetchResults as fetchResultsApi,
  deleteResult as deleteResultApi,
  fetchPptAssets,
  fetchImageBase64,
  checkBackendStatus,
} from './services/apiService.js';
import { showToast } from './ui/toast.js';
import { renderResults, getSelectedResultIds } from './ui/resultsRenderer.js';

const elements = {
  urlInput: document.getElementById('url-input'),
  urlCount: document.getElementById('url-count'),
  fileInput: document.getElementById('file-input'),
  uploadZone: document.getElementById('upload-zone'),
  uploadPreview: document.getElementById('upload-preview'),
  startBtn: document.getElementById('start-btn'),
  refreshBtn: document.getElementById('refresh-btn'),
  bulkDeleteBtn: document.getElementById('bulk-delete-btn'),
  exportPptBtn: document.getElementById('export-ppt-btn'),
  selectAllBtn: document.getElementById('select-all-btn'),
  deselectAllBtn: document.getElementById('deselect-all-btn'),
  resultsGrid: document.getElementById('results-grid'),
  backendStatus: document.getElementById('backend-status'),
  progressModal: document.getElementById('progress-modal'),
  finishProgressBtn: document.getElementById('finish-progress-btn'),
  closeProgressBtn: document.getElementById('close-progress-btn'),
  progressMainTitle: document.getElementById('progress-main-title'),
  progressSubtitle: document.getElementById('progress-subtitle'),
  progressSpinner: document.getElementById('progress-spinner'),
  progressBarFill: document.getElementById('progress-bar-fill'),
  progressCreativesList: document.getElementById('progress-creatives-list'),
  progressLog: document.getElementById('progress-log'),
  pptModal: document.getElementById('ppt-modal'),
  closeModalBtn: document.getElementById('close-modal-btn'),
  generatePptBtn: document.getElementById('generate-ppt-btn'),
  vpnProvider: document.getElementById('vpn-provider'),
  vpnCountryGroup: document.getElementById('vpn-country-group'),
  vpnCountry: document.getElementById('vpn-country'),
  vpnCustomGroup: document.getElementById('vpn-custom-group'),
  vpnCustomCmd: document.getElementById('vpn-custom-cmd'),
  vpnToggleBtn: document.getElementById('vpn-toggle-btn'),
};

let totalCreativesCount = 0;
let matchedCreativesCount = 0;

const setUrlCount = () => {
  const urls = parseUrls(elements.urlInput.value);
  elements.urlCount.textContent = `${urls.length} valid URL${urls.length !== 1 ? 's' : ''}`;
};

const updateVpnFields = () => {
  if (!elements.vpnProvider || !elements.vpnCountryGroup || !elements.vpnCustomGroup) return;
  const isCustom = elements.vpnProvider.value === 'Custom';
  elements.vpnCountryGroup.style.display = isCustom ? 'none' : 'block';
  elements.vpnCustomGroup.style.display = isCustom ? 'block' : 'none';
};

const showProgressModal = () => {
  if (!elements.progressModal) return;
  elements.progressModal.style.display = 'flex';
};

const hideProgressModal = () => {
  if (!elements.progressModal) return;
  elements.progressModal.style.display = 'none';
};

const addLog = (message, type = 'bullet') => {
  const progressLog = elements.progressLog;
  if (!progressLog) return;

  const logItem = document.createElement('div');
  logItem.className = `log-item ${type}`;

  let icon = '•';
  if (type === 'success') icon = '✔';
  else if (type === 'error') icon = '✖';
  else if (type === 'warning') icon = '⚠';
  else if (type === 'info') icon = 'ℹ';

  logItem.innerHTML = `<span style="margin-right: 6px; opacity: 0.7; font-weight: bold;">${icon}</span>${message}`;
  progressLog.appendChild(logItem);
  progressLog.scrollTop = progressLog.scrollHeight;
};

const resetProgressState = () => {
  if (!elements.progressMainTitle || !elements.progressSubtitle || !elements.progressSpinner || !elements.progressBarFill || !elements.progressCreativesList || !elements.progressLog || !elements.finishProgressBtn || !elements.closeProgressBtn) {
    return;
  }

  elements.progressMainTitle.textContent = 'Launching Scan Engine...';
  elements.progressSubtitle.textContent = 'Initializing browser containers...';
  elements.progressSpinner.innerHTML = `<i class='bx bx-loader-alt bx-spin' style='font-size: 2.5rem; color: var(--accent-color);'></i>`;
  elements.progressBarFill.style.width = '0%';
  elements.progressBarFill.style.background = 'var(--accent-gradient)';
  elements.progressCreativesList.innerHTML = '';
  elements.progressLog.innerHTML = '';
  elements.finishProgressBtn.setAttribute('disabled', 'true');
  elements.finishProgressBtn.style.opacity = '0.6';
  elements.finishProgressBtn.style.cursor = 'not-allowed';
  elements.finishProgressBtn.textContent = 'Scanner Running...';
  elements.closeProgressBtn.style.display = 'none';
};

const updateCreativeStatus = (cleanName, status, label, statusClass) => {
  const item = document.getElementById(`creative-item-${cleanName}`);
  const statusTag = document.getElementById(`creative-status-${cleanName}`);
  if (!item || !statusTag) return;
  item.className = `progress-creative-item ${statusClass}`;
  statusTag.className = `creative-status-tag ${statusClass}`;
  statusTag.innerHTML = `<i class='bx ${label.icon}' style="font-size: 1.1rem; vertical-align: middle;"></i> ${label.text}`;
};

const handleScanEvent = (event) => {
  if (!event || !event.type) return;
  const { type, payload = {} } = event;

  switch (type) {
    case 'started': {
      const creatives = Array.isArray(payload.creatives) ? payload.creatives : [];
      const total = creatives.length;
      totalCreativesCount = total;
      matchedCreativesCount = 0;
      elements.progressBarFill.style.width = '0%';
      elements.progressCreativesList.innerHTML = '';

      if (total === 0) {
        elements.progressCreativesList.innerHTML = `
          <div style="text-align: center; color: var(--text-secondary); font-size: 0.85rem; padding: 10px;">
            No creatives found in input_images. Direct upload needed!
          </div>
        `;
      } else {
        creatives.forEach((creative) => {
          const cleanName = creative.name.replace(/[^a-zA-Z0-9]/g, '_');
          const item = document.createElement('div');
          item.className = 'progress-creative-item';
          item.id = `creative-item-${cleanName}`;
          item.innerHTML = `
            <div class="creative-name-container">
              <span class="creative-name" title="${creative.name}">${creative.name}</span>
              <span class="creative-meta"><i class='bx bx-crop'></i> ${creative.width} x ${creative.height} px</span>
            </div>
            <div class="creative-status-tag pending" id="creative-status-${cleanName}">
              <i class='bx bx-time' style="vertical-align: middle;"></i> Pending
            </div>
          `;
          elements.progressCreativesList.appendChild(item);
        });
      }

      addLog(`Found ${total} creative banner asset(s). Starting automation...`, 'info');
      break;
    }
    case 'pass_start': {
      const passNum = payload.pass_num;
      if (passNum === 1) {
        elements.progressMainTitle.textContent = `Processing Initial Pass (1:1)...`;
        elements.progressSubtitle.textContent = `Testing creative size matching against website ad containers...`;
        addLog(`Pass 1 running: active matching strategy initialized...`, 'info');
      } else if (passNum === 2) {
        elements.progressMainTitle.textContent = `Retrying Leftover Creatives (Pass 2)...`;
        elements.progressSubtitle.textContent = `Attempting reload-based detection for leftover creatives...`;
        addLog(`Pass 2 retry running for ${payload.remaining_creatives.length} unmatched creative(s).`, 'warning');
      }
      break;
    }
    case 'site_start': {
      const cleanUrl = payload.url.replace(/https?:\/\//, '').split('/')[0];
      elements.progressSubtitle.textContent = `Opening website: ${cleanUrl}...`;
      break;
    }
    case 'site_loading': {
      const loadUrl = payload.url.replace(/https?:\/\//, '').split('/')[0];
      elements.progressSubtitle.textContent = `Loading DOM components for ${loadUrl}...`;
      addLog(`Opening URL: ${payload.url}`, 'bullet');
      break;
    }
    case 'site_scrolling': {
      elements.progressSubtitle.textContent = `Mimicking user scrolls to trigger lazy ads...`;
      break;
    }
    case 'site_detecting': {
      elements.progressSubtitle.textContent = `Analyzing page viewport and ad containers...`;
      break;
    }
    case 'match_success': {
      matchedCreativesCount += 1;
      const matchedName = payload.creative_name || '';
      const siteDomain = (payload.url || '').replace(/https?:\/\//, '').split('/')[0];
      const cleanName = matchedName.replace(/[^a-zA-Z0-9]/g, '_');
      const percent = totalCreativesCount ? Math.round((matchedCreativesCount / totalCreativesCount) * 100) : 100;
      elements.progressBarFill.style.width = `${percent}%`;
      updateCreativeStatus(cleanName, 'success', { icon: 'bx-check-circle', text: siteDomain }, 'matched');
      addLog(`Matched ${matchedName} on ${siteDomain} (${payload.dimensions})!`, 'success');
      break;
    }
    case 'no_match_on_site': {
      const skipDomain = (payload.url || '').replace(/https?:\/\//, '').split('/')[0];
      addLog(`No dimension match found on ${skipDomain} in Pass ${payload.pass_num}.`, 'bullet');
      break;
    }
    case 'site_failed': {
      const failDomain = (payload.url || '').replace(/https?:\/\//, '').split('/')[0];
      addLog(`Failed scanning ${failDomain} (Pass ${payload.pass_num}): ${payload.error}`, 'error');
      break;
    }
    case 'creative_failed': {
      const failName = payload.creative_name || payload.name || '';
      const cleanName = failName.replace(/[^a-zA-Z0-9]/g, '_');
      updateCreativeStatus(cleanName, 'failed', { icon: 'bx-x-circle', text: 'Failed' }, 'failed');
      addLog(`Exhausted all retries for ${failName} (${payload.width}x${payload.height}).`, 'error');
      break;
    }
    case 'finished': {
      elements.progressMainTitle.textContent = `Scan Process Completed!`;
      elements.progressSubtitle.textContent = `Headless browser session terminated. Check results below!`;
      elements.progressSpinner.innerHTML = `<i class='bx bxs-check-circle' style="font-size: 3rem; color: var(--success); filter: drop-shadow(0 0 10px rgba(16, 185, 129, 0.4));"></i>`;
      elements.progressBarFill.style.width = '100%';
      elements.finishProgressBtn.removeAttribute('disabled');
      elements.finishProgressBtn.style.opacity = '1';
      elements.finishProgressBtn.style.cursor = 'pointer';
      elements.finishProgressBtn.textContent = 'Close & View Results';
      elements.closeProgressBtn.style.display = 'block';
      addLog(`Automation run complete. Matched mockups stored in PostgreSQL database.`, 'success');
      showToast('Scan completed successfully!');
      fetchResults();
      break;
    }
    case 'error': {
      elements.progressMainTitle.textContent = `Scan Process Interrupted`;
      elements.progressSubtitle.textContent = payload.message || 'Unknown automation failure';
      elements.progressSpinner.innerHTML = `<i class='bx bxs-error-circle' style="font-size: 3rem; color: var(--danger);"></i>`;
      elements.progressBarFill.style.background = 'var(--danger)';
      elements.finishProgressBtn.removeAttribute('disabled');
      elements.finishProgressBtn.style.opacity = '1';
      elements.finishProgressBtn.style.cursor = 'pointer';
      elements.finishProgressBtn.textContent = 'Dismiss';
      elements.closeProgressBtn.style.display = 'block';
      addLog(`Scanner run failed: ${payload.message}`, 'error');
      showToast('Scan process failed to complete.', 'error');
      break;
    }
    default:
      break;
  }
};

const uploadPreviewChip = (file, objectUrl) => {
  const chip = document.createElement('div');
  chip.className = 'preview-chip';
  chip.innerHTML = `
    <i class='bx bx-loader-alt bx-spin'></i>
    <span>${file.name.substring(0, 12)}...</span>
  `;

  const img = new Image();
  img.onload = () => {
    chip.innerHTML = `
      <img src="${objectUrl}" style="width: 18px; height: 18px; object-fit: cover; border-radius: 4px; border: 1px solid var(--panel-border);" />
      <span style="font-weight: 500;">${file.name.substring(0, 10)}${file.name.length > 10 ? '...' : ''}</span>
      <span style="color: var(--text-secondary); font-size: 0.7rem; font-family: monospace; font-weight: 600;">(${img.width}x${img.height})</span>
      <button class="delete-creative-btn" style="background: transparent; border: none; color: var(--text-secondary); cursor: pointer; display: flex; align-items: center; justify-content: center; padding: 2px; margin-left: 4px; transition: color 0.2s;" title="Remove Creative">
        <i class='bx bx-x' style="font-size: 1rem;"></i>
      </button>
    `;

    const deleteBtn = chip.querySelector('.delete-creative-btn');
    deleteBtn?.addEventListener('click', async (event) => {
      event.stopPropagation();
      const success = await deleteCreative(file.name);
      if (success) {
        state.uploadedFiles = state.uploadedFiles.filter((name) => name !== file.name);
        chip.remove();
        showToast(`Removed creative: ${file.name}`);
      } else {
        showToast('Failed to delete creative', 'error');
      }
    });
  };

  img.onerror = () => {
    chip.innerHTML = `<i class='bx bx-image-x' style='color: var(--danger);'></i> <span>${file.name.substring(0, 12)}...</span>`;
  };

  img.src = objectUrl;
  return chip;
};

const handleFiles = async (fileList) => {
  const files = Array.from(fileList).filter(isImageFile);
  if (!files.length) return;

  const formFiles = [];
  files.forEach((file) => {
    formFiles.push(file);
    state.uploadedFiles.push(file.name);
    const objectUrl = URL.createObjectURL(file);
    const chip = uploadPreviewChip(file, objectUrl);
    elements.uploadPreview.appendChild(chip);
  });

  if (formFiles.length === 0) return;

  const uploadIcon = elements.uploadZone?.querySelector('i');
  if (uploadIcon) uploadIcon.className = 'bx bx-loader-alt bx-spin';

  try {
    await uploadCreatives(formFiles);
    showToast(`Successfully uploaded ${formFiles.length} image(s)`);
  } catch (error) {
    console.error(error);
    showToast('Failed to upload images', 'error');
  } finally {
    if (uploadIcon) uploadIcon.className = 'bx bx-cloud-upload';
  }
};

const selectAllResults = () => {
  document.querySelectorAll('.result-checkbox').forEach((checkbox) => {
    checkbox.checked = true;
  });
};

const deselectAllResults = () => {
  document.querySelectorAll('.result-checkbox').forEach((checkbox) => {
    checkbox.checked = false;
  });
};

const startScan = async () => {
  const urls = parseUrls(elements.urlInput.value);
  if (!urls.length) {
    showToast('Please enter at least one URL', 'error');
    return;
  }
  if (!state.uploadedFiles.length) {
    showToast('Please upload at least one creative image', 'error');
    return;
  }

  resetProgressState();
  showProgressModal();

  try {
    await processScanStream(urls, handleScanEvent);
  } catch (error) {
    console.error(error);
    handleScanEvent({ type: 'error', payload: { message: error.message || 'Connection error. Check backend server logs.' } });
  }
};

const fetchResults = async () => {
  if (elements.refreshBtn) elements.refreshBtn.innerHTML = `<i class='bx bx-loader-alt bx-spin'></i>`;
  try {
    const results = await fetchResultsApi();
    renderResults(results);
    showToast('Results updated');
  } catch (error) {
    console.error(error);
    showToast('Failed to load recent results', 'error');
  } finally {
    if (elements.refreshBtn) elements.refreshBtn.innerHTML = `<i class='bx bx-refresh'></i> Refresh`;
  }
};

const exportSelectedToPPT = async () => {
  const selectedIds = getSelectedResultIds();
  if (selectedIds.length === 0) {
    showToast('Please select at least one result to export', 'error');
    return;
  }

  const title = document.getElementById('pdf-campaign-title')?.value || 'Campaign Title';
  const startDate = document.getElementById('pdf-start-date')?.value || 'Start Date';
  const endDate = document.getElementById('pdf-end-date')?.value || 'End Date';
  const formatStr = document.getElementById('pdf-format')?.value || 'Banner';

  elements.generatePptBtn.innerHTML = `<i class='bx bx-loader-alt bx-spin'></i> Generating...`;
  elements.generatePptBtn.disabled = true;

  try {
    const exportPack = await fetchPptAssets();
    let themeHex = exportPack?.theme || {
      accent: '6366F1',
      background: 'F8FAFC',
      title: '1E293B',
      text: '334155',
      gradientTop: 'EEF2FF',
      gradientBottom: 'C7D2FE',
    };

    const makeGradientDataUrl = (w, h, topHex, botHex) => {
      const canvas = document.createElement('canvas');
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext('2d');
      const top = String(topHex || 'EEF2FF').replace(/^#/, '');
      const bottom = String(botHex || 'C7D2FE').replace(/^#/, '');
      const gradient = ctx.createLinearGradient(0, 0, 0, h);
      gradient.addColorStop(0, `#${top}`);
      gradient.addColorStop(1, `#${bottom}`);
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, w, h);
      return canvas.toDataURL('image/png');
    };

    const loadDataUrlImage = (src) =>
      new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error('Failed to load image'));
        img.src = src;
      });

    const createPatternTextImage = async ({ title, dateRange, startDate, endDate, formatStr, patternDataUrl }) => {
      const canvas = document.createElement('canvas');
      canvas.width = 1680;
      canvas.height = 460;
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      let fillStyle = '#080812';
      if (patternDataUrl) {
        try {
          const patternImg = await loadDataUrlImage(patternDataUrl);
          fillStyle = ctx.createPattern(patternImg, 'repeat');
        } catch (
          error) {
          const gradient = ctx.createLinearGradient(0, 0, canvas.width, 0);
          gradient.addColorStop(0, `#${String(themeHex.accent).replace(/^#/, '')}`);
          gradient.addColorStop(1, `#${String(themeHex.title).replace(/^#/, '')}`);
          fillStyle = gradient;
        }
      } else {
        const gradient = ctx.createLinearGradient(0, 0, canvas.width, 0);
        gradient.addColorStop(0, `#${String(themeHex.accent).replace(/^#/, '')}`);
        gradient.addColorStop(0.45, `#${String(themeHex.title).replace(/^#/, '')}`);
        gradient.addColorStop(1, `#${String(themeHex.text).replace(/^#/, '')}`);
        fillStyle = gradient;
      }

      const drawPatternText = (text, x, y, size) => {
        ctx.save();
        ctx.font = `800 ${size}px Segoe UI, Arial, sans-serif`;
        ctx.textBaseline = 'top';
        ctx.lineJoin = 'round';
        ctx.shadowColor = 'rgba(0,0,0,0.72)';
        ctx.shadowBlur = 0;
        ctx.shadowOffsetX = 2;
        ctx.shadowOffsetY = 2;
        ctx.fillStyle = fillStyle;
        ctx.fillText(text, x, y);
        ctx.globalAlpha = 0.55;
        ctx.strokeStyle = 'rgba(0,0,0,0.32)';
        ctx.lineWidth = 1.1;
        ctx.strokeText(text, x, y);
        ctx.restore();
      };

      drawPatternText(title, 0, 0, 58);
      drawPatternText(dateRange, 0, 76, 58);
      drawPatternText(`Start Date: ${startDate}`, 0, 206, 34);
      drawPatternText(`End Date: ${endDate}`, 0, 200, 34);
      drawPatternText(`Format: ${formatStr}`, 0, 302, 34);
      return canvas.toDataURL('image/png');
    };

    const makeBackgroundDataUrl = async () => {
      const coverDataUrl = exportPack?.cover || null;
      if (coverDataUrl) return coverDataUrl;
      try {
        const response = await fetchImageBase64('cover_bg.jpg');
        return response.dataUrl;
      } catch {
        return makeGradientDataUrl(1920, 1080, themeHex.gradientTop, themeHex.gradientBottom);
      }
    };

    const bgCover = await makeBackgroundDataUrl();
    const bgGradient = exportPack?.gradient || makeGradientDataUrl(1920, 1080, themeHex.gradientTop, themeHex.gradientBottom);
    const logoData = exportPack?.logo ?? null;
    const textFill = exportPack?.textFill ?? null;

    const PptxGenJS = window.PptxGenJS;
    if (!PptxGenJS) {
      throw new Error('PptxGenJS is not loaded.');
    }

    const pptx = new PptxGenJS();
    pptx.defineLayout({ name: 'CUSTOM', width: 338.67 / 25.4, height: 190.5 / 25.4 });
    pptx.layout = 'CUSTOM';

    const formatShortDate = (dateStr) => {
      try {
        const clean = dateStr.replace(/(\d+)(st|nd|rd|th)/, '$1');
        const d = new Date(clean);
        if (Number.isNaN(d.getTime())) return dateStr;
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        return `${months[d.getMonth()]}'${d.getFullYear().toString().slice(-2)}`;
      } catch {
        return dateStr;
      }
    };

    const patternImage = await createPatternTextImage({
      title,
      dateRange: `${formatShortDate(startDate)} to ${formatShortDate(endDate)}`,
      startDate,
      endDate,
      formatStr,
      patternDataUrl: textFill,
    });

    const makeGradientBackground = (slide, dataUrl) => {
      slide.addImage({ data: dataUrl, x: 0, y: 0, w: 13.33, h: 7.5 });
    };

    const makeCoverSlide = () => {
      const slide = pptx.addSlide();
      makeGradientBackground(slide, bgCover || bgGradient);
      slide.addShape(pptx.ShapeType.roundRect, {
        x: 1437053 / 914400,
        y: 983501 / 914400,
        w: 9382565 / 914400,
        h: 2837730 / 914400,
        fill: { color: 'FFFFFF' },
        line: { color: themeHex.accent, width: 1 },
      });
      slide.addImage({
        data: patternImage,
        x: 1863297 / 914400,
        y: 1233574 / 914400,
        w: 8546733 / 914400,
        h: 2339102 / 914400,
      });
      if (logoData) {
        slide.addImage({
          data: logoData,
          x: 3989041 / 914400,
          y: 5455562 / 914400,
          w: 3483624 / 914400,
          h: 1323778 / 914400,
        });
      }
    };

    const loadImageFromBase64 = async (source) => {
      const img = new Image();
      return new Promise((resolve, reject) => {
        img.onload = () => resolve(img);
        img.onerror = reject;
        img.src = source;
      });
    };

    const selectedImageDetails = async () => {
      const cards = Array.from(document.querySelectorAll('.result-checkbox:checked')).map((checkbox) => checkbox.closest('.result-card'));
      const results = [];

      for (const card of cards) {
        const urlLabel = card.querySelector('.card-url')?.textContent || '';
        const imageEl = card.querySelector('img');
        if (!imageEl) continue;
        const imageUrl = imageEl.src;
        const segments = new URL(imageUrl).pathname.split('/');
        const filename = segments.pop();
        const response = await fetchImageBase64(filename);
        const rawDataUrl = response.dataUrl;
        const loadedImage = await loadImageFromBase64(rawDataUrl);
        const canvas = document.createElement('canvas');
        canvas.width = loadedImage.width;
        canvas.height = loadedImage.height;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#FFFFFF';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(loadedImage, 0, 0);
        results.push({
          url: urlLabel,
          base64: canvas.toDataURL('image/jpeg', 0.95),
          width: canvas.width,
          height: canvas.height,
        });
      }
      return results;
    };

    makeCoverSlide();

    const images = await selectedImageDetails();
    const desktopImages = images.filter((img) => img.width >= img.height && img.width >= 600);
    const mobileImages = images.filter((img) => img.height > img.width || img.width < 600);

    const addDesktopSlides = () => {
      desktopImages.forEach((img) => {
        const slide = pptx.addSlide();
        makeGradientBackground(slide, bgGradient);
        slide.addShape(pptx.ShapeType.roundRect, { x: 4.68 / 25.4, y: 5.06 / 25.4, w: 103.52 / 25.4, h: 14.03 / 25.4, fill: { color: 'FFFFFF' }, line: { show: false } });
        slide.addShape(pptx.ShapeType.roundRect, { x: 130.32 / 25.4, y: 5.06 / 25.4, w: 88.02 / 25.4, h: 14.03 / 25.4, fill: { color: 'FFFFFF' }, line: { show: false } });
        slide.addShape(pptx.ShapeType.roundRect, { x: 244.28 / 25.4, y: 5.06 / 25.4, w: 88.02 / 25.4, h: 14.03 / 25.4, fill: { color: 'FFFFFF' }, line: { show: false } });

        const drawLabelValue = (slideItem, label, value, x_mm, y_mm) => {
          slideItem.addText(
            [
              { text: `${label} `, options: { bold: true, fontFace: 'Segoe UI', fontSize: 18, color: themeHex.title } },
              { text: value, options: { bold: false, fontFace: 'Segoe UI', fontSize: 18, color: themeHex.text } },
            ],
            { x: x_mm / 25.4, y: (y_mm - 5) / 25.4, w: 4, h: 0.5, valign: 'middle' }
          );
        };

        drawLabelValue(slide, 'Site:', img.url.length > 25 ? img.url.substring(0, 22) + '...' : img.url, 10, 14);
        drawLabelValue(slide, 'Ad Size:', 'Auto-detected', 136, 14);
        drawLabelValue(slide, 'Device:', 'Desktop', 250, 14);

        const maxW = 327;
        const maxH = 161;
        const ratio = Math.min(maxW / img.width, maxH / img.height);
        const w = img.width * ratio;
        const h = img.height * ratio;
        const x = 5.7 + (maxW - w) / 2;
        const y = 23.3;

        slide.addImage({ data: img.base64, x: x / 25.4, y: y / 25.4, w: w / 25.4, h: h / 25.4 });
      });
    };

    const addMobileSlides = () => {
      const chunk = 2;
      for (let i = 0; i < mobileImages.length; i += chunk) {
        const slide = pptx.addSlide();
        makeGradientBackground(slide, bgGradient);
        const img1 = mobileImages[i];
        const img2 = mobileImages[i + 1];

        const drawMobileText = (slideItem, imgObj, x_mm, y_mm) => {
          let currentY = (y_mm - 5) / 25.4;
          const lines = [
            ['Site:', imgObj.url.length > 25 ? imgObj.url.substring(0, 22) + '...' : imgObj.url],
            ['Ad Size:', 'Auto-detected'],
            ['Device:', 'Mobile'],
          ];
          lines.forEach(([label, value]) => {
            slideItem.addText(
              [
                { text: `${label} `, options: { bold: true, fontFace: 'Segoe UI', fontSize: 18, color: themeHex.title } },
                { text: value, options: { bold: false, fontFace: 'Segoe UI', fontSize: 18, color: themeHex.text } },
              ],
              { x: x_mm / 25.4, y: currentY, w: 3.5, h: 0.5, valign: 'middle' }
            );
            currentY += 8.5 / 25.4;
          });
        };

        if (img1) {
          drawMobileText(slide, img1, 5, 12);
          const ratio1 = Math.min(98.7 / img1.width, 161 / img1.height);
          slide.addImage({ data: img1.base64, x: 5 / 25.4, y: 27 / 25.4, w: (img1.width * ratio1) / 25.4, h: (img1.height * ratio1) / 25.4 });
        }

        if (img2) {
          drawMobileText(slide, img2, 110, 12);
          const ratio2 = Math.min(98.7 / img2.width, 161 / img2.height);
          slide.addImage({ data: img2.base64, x: 110 / 25.4, y: 27 / 25.4, w: (img2.width * ratio2) / 25.4, h: (img2.height * ratio2) / 25.4 });
        }
      }
    };

    addDesktopSlides();
    addMobileSlides();

    await pptx.writeFile({ fileName: 'screenshot_report.pptx' });
    showToast('PPT downloaded successfully!');

    // Save to PPT Store (background — non-blocking)
    try {
      const { API_BASE_URL } = await import('./config/apiConfig.js');
      const titleVal = document.getElementById('pdf-campaign-title')?.value?.trim() || 'campaign_report';
      await fetch(`${API_BASE_URL}/ppt-store/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: selectedIds, title: titleVal }),
      });
      showToast('Report saved to PPT Store ✓', 'success');
    } catch (_) {
      // Non-fatal — PPT was already downloaded locally
    }
  } catch (error) {
    console.error(error);
    showToast(`Error generating PPT: ${error.message || 'Unknown error'}`, 'error');
  } finally {
    elements.generatePptBtn.innerHTML = `<i class='bx bxs-file-export'></i> Generate Report`;
    elements.generatePptBtn.disabled = false;
  }
};

const bulkDeleteSelected = async () => {
  const selectedIds = getSelectedResultIds();
  if (!selectedIds.length) {
    showToast('Please select at least one result to delete', 'error');
    return;
  }
  if (!confirm(`Are you sure you want to delete ${selectedIds.length} selected results?`)) return;

  elements.bulkDeleteBtn.innerHTML = `<i class='bx bx-loader-alt bx-spin'></i> Deleting...`;
  elements.bulkDeleteBtn.disabled = true;

  try {
    const deletePromises = selectedIds.map((id) => deleteResultApi(id));
    const results = await Promise.all(deletePromises);
    const successCount = results.filter(Boolean).length;
    showToast(`Successfully deleted ${successCount} result(s)`);
    await fetchResults();
  } catch (error) {
    console.error(error);
    showToast('Error occurred during bulk deletion', 'error');
  } finally {
    elements.bulkDeleteBtn.innerHTML = `<i class='bx bx-trash'></i> Delete Selected`;
    elements.bulkDeleteBtn.disabled = false;
  }
};

const setupEventHandlers = () => {
  if (elements.urlInput) {
    elements.urlInput.addEventListener('input', setUrlCount);
  }

  if (elements.uploadZone) {
    elements.uploadZone.addEventListener('dragover', (event) => {
      event.preventDefault();
      elements.uploadZone.style.borderColor = 'var(--accent-color)';
    });
    elements.uploadZone.addEventListener('dragleave', () => {
      elements.uploadZone.style.borderColor = 'var(--panel-border)';
    });
    elements.uploadZone.addEventListener('drop', (event) => {
      event.preventDefault();
      elements.uploadZone.style.borderColor = 'var(--panel-border)';
      if (event.dataTransfer.files.length) {
        handleFiles(event.dataTransfer.files);
      }
    });
  }

  if (elements.fileInput) {
    elements.fileInput.addEventListener('change', () => {
      if (elements.fileInput.files.length) {
        handleFiles(elements.fileInput.files);
      }
    });
  }

  elements.startBtn?.addEventListener('click', startScan);
  elements.refreshBtn?.addEventListener('click', fetchResults);
  elements.bulkDeleteBtn?.addEventListener('click', bulkDeleteSelected);
  elements.selectAllBtn?.addEventListener('click', selectAllResults);
  elements.deselectAllBtn?.addEventListener('click', deselectAllResults);
  elements.exportPptBtn?.addEventListener('click', () => {
    if (elements.pptModal) elements.pptModal.style.display = 'flex';
  });
  elements.closeModalBtn?.addEventListener('click', () => {
    if (elements.pptModal) elements.pptModal.style.display = 'none';
  });
  elements.generatePptBtn?.addEventListener('click', exportSelectedToPPT);

  elements.finishProgressBtn?.addEventListener('click', hideProgressModal);
  elements.closeProgressBtn?.addEventListener('click', hideProgressModal);

  elements.vpnProvider?.addEventListener('change', updateVpnFields);
  updateVpnFields();

  elements.resultsGrid?.addEventListener('click', async (event) => {
    // Delete button
    const deleteTarget = event.target.closest('.delete-btn');
    if (deleteTarget) {
      const id = Number(deleteTarget.dataset.resultId);
      if (!id) return;
      const success = await deleteResultApi(id);
      if (success) {
        showToast('Result deleted successfully');
        await fetchResults();
      } else {
        showToast('Failed to delete result', 'error');
      }
      return;
    }

    // Export Image button
    const exportTarget = event.target.closest('.export-image-btn');
    if (exportTarget) {
      const imgUrl  = exportTarget.dataset.url;
      const fname   = exportTarget.dataset.filename;
      const resultId = Number(exportTarget.dataset.resultId);

      // 1. Download the image
      try {
        const resp = await fetch(imgUrl);
        const blob = await resp.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = fname;
        a.click();
        URL.revokeObjectURL(a.href);
      } catch (e) {
        showToast('Image download failed', 'error');
        return;
      }

      // 2. Save to PPT Store (background — generate a single-slide PPT via backend)
      try {
        const { API_BASE_URL } = await import('./config/apiConfig.js');
        await fetch(`${API_BASE_URL}/ppt-store/export`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids: [resultId], title: `result_${resultId}` }),
        });
        showToast('Image exported & saved to PPT Store ✓', 'success');
      } catch (_) {
        // Non-fatal — image was already downloaded
        showToast('Image downloaded (PPT Store save failed)', 'error');
      }
      return;
    }
  });
};

// Update backend badge UI based on health check result
const updateBackendUI = (ok, info) => {
  const el = elements.backendStatus;
  if (!el) return;
  if (ok) {
    el.innerHTML = `<i class='bx bxs-circle' style='color: var(--success)'></i> Local Backend`;
    el.style.background = 'rgba(16, 185, 129, 0.06)';
    el.style.color = 'var(--success)';
    el.style.border = '1px solid rgba(16,185,129,0.15)';
  } else {
    el.innerHTML = `<i class='bx bxs-error-circle' style='color: var(--danger)'></i> Backend Unavailable`;
    el.style.background = 'rgba(239,68,68,0.04)';
    el.style.color = 'var(--danger)';
    el.style.border = '1px solid rgba(239,68,68,0.12)';
  }
  // Optionally show tooltip with details
  el.title = info ? String(info) : '';
};

const checkAndUpdateBackend = async () => {
  try {
    const res = await checkBackendStatus(3000);
    updateBackendUI(res.ok, res.message || res.status);
  } catch (e) {
    updateBackendUI(false, e.message);
  }
};

// Start a periodic backend polling loop (non-blocking)
const startBackendPolling = () => {
  checkAndUpdateBackend();
  setInterval(checkAndUpdateBackend, 10000);
};

const initialize = async () => {
  setupEventHandlers();
  setUrlCount();
  startBackendPolling();
  await fetchResults();
};

document.addEventListener('DOMContentLoaded', initialize);
