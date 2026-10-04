import { clearTokens, getAccessToken, getTokens, setTokens } from '@/lib/auth';

const BASE =
  ((import.meta as any).env.VITE_API_BASE_URL as string | undefined) || '/api';

export { BASE as API_BASE };

/**
 * Typed error body of POST /compare and POST /gap-analysis:
 * `{"detail": "<human string>", "code": "<code>", "retryable": <bool>}`.
 * Other endpoints return `{"detail": ...}` only, so `code` and `retryable` are optional.
 */
export interface ApiErrorExtra {
  /** Stable machine-readable code, e.g. `structured_output_truncated`. */
  code?: string;
  /** Whether trying the same request again may succeed. */
  retryable?: boolean;
}

export class ApiError extends Error {
  status: number;
  detail: string;
  code?: string;
  retryable?: boolean;

  constructor(status: number, detail: string, extra?: ApiErrorExtra) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.code = extra?.code;
    this.retryable = extra?.retryable;
  }
}

interface ApiFetchOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string>;
  formData?: FormData;
}

interface RefreshTokenResponse {
  access_token: string;
  refresh_token: string;
}

function buildUrl(path: string, query?: Record<string, string>): string {
  const url = `${BASE}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    params.append(key, value);
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

/** Builds the ApiError for a non-OK response, reading `detail` and the typed `code` / `retryable`. */
export async function toApiError(response: Response): Promise<ApiError> {
  let detail = response.statusText;
  const extra: ApiErrorExtra = {};
  try {
    const data = await response.json();
    if (data && typeof data === 'object') {
      if (typeof data.code === 'string' && data.code) extra.code = data.code;
      if (typeof data.retryable === 'boolean') extra.retryable = data.retryable;
      if (typeof data.detail === 'string' && data.detail) {
        detail = data.detail;
      } else if (Array.isArray(data.detail) && data.detail.length > 0) {
        detail = data.detail
          .map((err: any) => {
            if (typeof err === 'string') return err;
            if (err && typeof err === 'object') {
              const loc = Array.isArray(err.loc)
                ? err.loc.filter((l: any) => l !== 'body').join('.')
                : '';
              const msg = err.msg || JSON.stringify(err);
              return loc ? `${loc}: ${msg}` : msg;
            }
            return String(err);
          })
          .join(', ');
      } else if (typeof data.message === 'string' && data.message) {
        detail = data.message;
      }
    }
  } catch {
    // Ignore body parse failures; fall back to status text.
  }
  return new ApiError(response.status, detail, extra);
}

async function request(path: string, opts?: ApiFetchOptions): Promise<Response> {
  const headers: Record<string, string> = {};
  const token = getAccessToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let body: BodyInit | undefined;
  if (opts?.formData) {
    body = opts.formData;
  } else if (opts?.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
  }

  return fetch(buildUrl(path, opts?.query), {
    method: opts?.method ?? 'GET',
    headers,
    body,
  });
}

async function tryRefresh(): Promise<boolean> {
  const tokens = getTokens();
  if (!tokens) return false;

  let response: Response;
  try {
    response = await fetch(`${BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: tokens.refresh }),
    });
  } catch {
    return false;
  }

  if (!response.ok) return false;

  try {
    const data = (await response.json()) as RefreshTokenResponse;
    setTokens(data.access_token, data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  opts?: ApiFetchOptions,
): Promise<T> {
  let response = await request(path, opts);

  if (response.status === 401) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      response = await request(path, opts);
    } else {
      clearTokens();
    }
  }

  if (!response.ok) {
    throw await toApiError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}