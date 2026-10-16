import axios from 'axios';

const getApiBase = (): string => {
  if (import.meta.env?.VITE_API_URL) {
    return import.meta.env.VITE_API_URL;
  }
  if (typeof window !== 'undefined' && window.location.hostname) {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return 'http://127.0.0.1:8000';
};

export const apiClient = axios.create({
  baseURL: getApiBase(),
  timeout: 30000,
  withCredentials: true,
});

let inMemoryToken: string | null = null;

export const setAuthToken = (token: string | null): void => {
  inMemoryToken = token;
};

export const getAuthToken = (): string | null => inMemoryToken;

type UnauthorizedHandler = () => void;
let onUnauthorizedCallback: UnauthorizedHandler | null = null;

export const setOnUnauthorized = (handler: UnauthorizedHandler | null): void => {
  onUnauthorizedCallback = handler;
};

apiClient.interceptors.request.use((config) => {
  if (inMemoryToken && !config.headers.Authorization) {
    config.headers.Authorization = `Bearer ${inMemoryToken}`;
  }
  return config;
});

export interface PydanticValidationError {
  loc?: (string | number)[];
  msg?: string;
  type?: string;
  message?: string;
  [key: string]: unknown;
}

/**
 * Formats API errors (including FastAPI/Pydantic structured validation errors)
 * into human-readable strings, avoiding "[object Object]".
 */
export function formatApiErrorMessage(
  detail: unknown,
  fallback = 'An error occurred'
): string {
  if (detail == null) {
    return fallback;
  }

  if (typeof detail === 'string') {
    const trimmed = detail.trim();
    return trimmed.length > 0 ? trimmed : fallback;
  }

  if (Array.isArray(detail)) {
    if (detail.length === 0) {
      return fallback;
    }

    const formattedItems = detail
      .map((item) => {
        if (item == null) return '';
        if (typeof item === 'string') return item.trim();
        if (typeof item === 'object') {
          const pydanticItem = item as PydanticValidationError;
          const msg = (pydanticItem.msg || pydanticItem.message || '').trim();
          let fieldPath = '';
          if (Array.isArray(pydanticItem.loc) && pydanticItem.loc.length > 0) {
            // Strip out root container specifiers like 'body', 'query', 'header'
            const filteredLoc = pydanticItem.loc.filter(
              (part, idx) => !(idx === 0 && (part === 'body' || part === 'query' || part === 'header'))
            );
            fieldPath = filteredLoc.join('.');
          }

          if (fieldPath && msg) {
            return `${fieldPath}: ${msg}`;
          }
          if (msg) {
            return msg;
          }
          try {
            const str = JSON.stringify(item);
            return str === '{}' ? '' : str;
          } catch {
            return '';
          }
        }
        return String(item);
      })
      .filter((m) => m.length > 0);

    return formattedItems.length > 0 ? formattedItems.join(', ') : fallback;
  }

  if (typeof detail === 'object') {
    const obj = detail as Record<string, unknown>;
    const msg =
      typeof obj.msg === 'string'
        ? obj.msg.trim()
        : typeof obj.message === 'string'
        ? obj.message.trim()
        : '';
    let fieldPath = '';
    if (Array.isArray(obj.loc) && obj.loc.length > 0) {
      const filteredLoc = obj.loc.filter(
        (part, idx) => !(idx === 0 && (part === 'body' || part === 'query' || part === 'header'))
      );
      fieldPath = filteredLoc.join('.');
    }
    if (fieldPath && msg) {
      return `${fieldPath}: ${msg}`;
    }
    if (msg) {
      return msg;
    }
    if (typeof obj.detail === 'string' && obj.detail.trim()) {
      return obj.detail.trim();
    }
    try {
      const str = JSON.stringify(detail);
      return str === '{}' ? fallback : str;
    } catch {
      return fallback;
    }
  }

  return String(detail);
}

apiClient.interceptors.response.use(
  (r) => r,
  (err) => {
    const isLoginEndpoint = err.config?.url?.includes('/api/auth/login');
    const isInitialMeEndpoint = err.config?.url?.includes('/api/auth/me');

    if (err.response?.status === 401) {
      // Clear token and trigger unauthenticated handler if a session was revoked or expired
      if (!isLoginEndpoint && !isInitialMeEndpoint) {
        setAuthToken(null);
        if (onUnauthorizedCallback) {
          onUnauthorizedCallback();
        }
      }
    }

    const fallback = err.message || 'An error occurred';
    const rawDetail =
      err.response?.data?.detail ??
      err.response?.data?.message ??
      (typeof err.response?.data === 'string' ? err.response.data : undefined);
    const msg = formatApiErrorMessage(rawDetail, fallback);
    return Promise.reject(new Error(msg));
  }
);

export default apiClient;

