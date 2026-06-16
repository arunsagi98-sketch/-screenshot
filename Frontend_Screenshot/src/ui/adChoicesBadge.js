export const updateAdChoicesBadge = (badge) => {
  if (!badge) return;

  badge.style.position = 'absolute';
  badge.style.top = '10px';
  badge.style.right = '10px';
  badge.style.zIndex = '99999';
  badge.style.display = 'inline-flex';
  badge.style.alignItems = 'center';
  badge.style.justifyContent = 'space-between';
  badge.style.minHeight = '36px';
  badge.style.padding = '10px 14px';
  badge.style.background = 'linear-gradient(180deg, rgba(255,255,255,0.96) 0%, rgba(245,245,245,0.88) 100%)';
  badge.style.border = '1px solid rgba(220, 220, 220, 0.75)';
  badge.style.borderRadius = '20px';
  badge.style.boxShadow = '0 14px 32px rgba(15, 23, 42, 0.08)';
  badge.style.backdropFilter = 'blur(16px)';
  badge.style.color = '#111';
  badge.style.fontSize = '12px';
  badge.style.fontWeight = '700';
  badge.style.lineHeight = '1';
  badge.style.gap = '10px';
  badge.style.pointerEvents = 'auto';

  badge.innerHTML = `
    <div style="display: inline-flex; align-items: center; gap: 10px;">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style="flex-shrink: 0;">
        <circle cx="12" cy="12" r="11" fill="#FFFFFF" stroke="#000000" stroke-opacity="0.12" stroke-width="1.5" />
        <path d="M8.5 11.5C8.5 9.29 10.29 7.5 12.5 7.5C14.71 7.5 16.5 9.29 16.5 11.5C16.5 13.71 14.71 15.5 12.5 15.5C10.29 15.5 8.5 13.71 8.5 11.5Z" fill="#111" />
        <path d="M11.5 9.25H12.5V11.5H11.5V9.25Z" fill="#FFFFFF" />
        <path d="M11.5 12.5H12.5V15.25H11.5V12.5Z" fill="#FFFFFF" />
      </svg>
      <span style="letter-spacing: 0.06em;">AdChoices</span>
    </div>
    <div style="width:1px; height:20px; background: rgba(0,0,0,0.14);"></div>
    <div style="display: inline-flex; align-items: center; gap: 10px;">
      <button type="button" aria-label="AdChoices info" style="background: transparent; border: none; padding: 0; display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; cursor: pointer;">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="12" cy="12" r="11" fill="#111" fill-opacity="0.08" />
          <path d="M12 7.75C11.3096 7.75 10.75 8.30964 10.75 9.0C10.75 9.69036 11.3096 10.25 12 10.25C12.6904 10.25 13.25 9.69036 13.25 9.0C13.25 8.30964 12.6904 7.75 12 7.75Z" fill="#111" />
          <path d="M12 12.5V16" stroke="#111" stroke-width="1.8" stroke-linecap="round" />
        </svg>
      </button>
      <div style="display: inline-flex; flex-direction: column; gap: 3px;">
        <span style="width: 4px; height: 4px; border-radius: 50%; background: #111;"></span>
        <span style="width: 4px; height: 4px; border-radius: 50%; background: #111;"></span>
        <span style="width: 4px; height: 4px; border-radius: 50%; background: #111;"></span>
      </div>
    </div>
  `;
};
