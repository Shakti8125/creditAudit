import { clearTokens, getAccessToken, getTokens, setTokens } from '@/lib/auth';

const BASE =
  ((import.meta as any).env.VITE_API_BASE_URL as string | undefined) || '/api';

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
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

async function toApiError(response: Response): Promise<ApiError> {
  let detail = response.statusText;
  try {
    const data = await response.json();
    if (data && typeof data === 'object' && typeof data.detail === 'string' && data.detail) {
      detail = data.detail;
    }
  } catch {
    // Ignore body parse failures; fall back to status text.
  }
  return new ApiError(response.status, detail);
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