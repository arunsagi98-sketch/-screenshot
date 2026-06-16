export const parseUrls = (value) =>
  String(value || '')
    .split(/[\n,]+/)
    .map((url) => url.trim())
    .filter((url) => url);

export const isImageFile = (file) => file && file.type && file.type.startsWith('image/');

export const formatDate = (dateString) => {
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return String(dateString || '');
  return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

export const createElementFromHTML = (html) => {
  const template = document.createElement('template');
  template.innerHTML = html.trim();
  return template.content.firstElementChild;
};

export const safeText = (value) => String(value ?? '').trim();
