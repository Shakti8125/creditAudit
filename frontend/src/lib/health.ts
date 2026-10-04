import { API_BASE } from '@/lib/http';

const HEALTH_TIMEOUT_MS = 4000;

/**
 * True only when the API answers `GET /health` with a JSON body `{"status": "ok"}`.
 *
 * The status code alone proves nothing: with no backend behind it, Vercel's SPA
 * fallback answers `/api/health` with `index.html` and status 200.
 */
export async function isBackendOnline(): Promise<boolean> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE}/health`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
      signal: controller.signal,
    });
    if (!response.ok) return false;
    const body: unknown = await response.json();
    return (
      typeof body === 'object' && body !== null && (body as { status?: unknown }).status === 'ok'
    );
  } catch {
    // Network error, timeout, or a non-JSON body (the SPA fallback).
    return false;
  } finally {
    window.clearTimeout(timer);
  }
}
