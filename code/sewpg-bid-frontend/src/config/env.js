const toNumber = (value, fallback) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const toBoolean = (value, fallback = false) => {
  if (value === undefined || value === null || value === '') return fallback;
  if (typeof value === 'boolean') return value;
  const normalized = String(value).trim().toLowerCase();
  return ['1', 'true', 'yes', 'on'].includes(normalized);
};

const trimSlash = (value) => (value || '').replace(/\/+$/, '');

export const ENV = {
  APP_ENV: import.meta.env.VITE_APP_ENV || import.meta.env.MODE || 'development',
  API_BASE_URL: trimSlash(import.meta.env.VITE_API_BASE_URL || '/api'),
  API_TIMEOUT_MS: toNumber(import.meta.env.VITE_API_TIMEOUT_MS, 12000),
  API_RETRY_COUNT: toNumber(import.meta.env.VITE_API_RETRY_COUNT, 1),
  API_ENABLE_TRACE: toBoolean(import.meta.env.VITE_API_ENABLE_TRACE, true),
  ONLYOFFICE_DOCUMENT_SERVER_URL: trimSlash(
    import.meta.env.VITE_ONLYOFFICE_DOCUMENT_SERVER_URL || '/ds',
  ),
  ONLYOFFICE_HEALTHCHECK_PATH: import.meta.env.VITE_ONLYOFFICE_HEALTHCHECK_PATH || '/healthcheck',
};
