import { apiFetch } from '@/lib/http';

export async function login(email: string, password: string): Promise<any> {
  return apiFetch('/auth/login', {
    method: 'POST',
    body: { email, password },
  });
}

export async function register(
  email: string,
  password: string,
  tenantName: string,
): Promise<any> {
  return apiFetch('/auth/register', {
    method: 'POST',
    body: { email, password, tenant_name: tenantName },
  });
}

export async function refreshToken(refresh: string): Promise<any> {
  return apiFetch('/auth/refresh', {
    method: 'POST',
    body: { refresh_token: refresh },
  });
}

export async function listModels(): Promise<any> {
  return apiFetch('/models');
}

export async function getModel(id: string): Promise<any> {
  return apiFetch(`/models/${id}`);
}

export async function createModel(input: {
  name: string;
  type: string;
  description?: string;
  initialVersion?: string;
  portfolio?: string;
  algorithm?: string;
}): Promise<any> {
  return apiFetch('/models', {
    method: 'POST',
    body: {
      name: input.name,
      type: input.type,
      description: input.description,
      initial_version: input.initialVersion ?? '1.0',
      portfolio: input.portfolio,
      algorithm: input.algorithm,
    },
  });
}

export async function getModelVersions(id: string): Promise<any> {
  return apiFetch(`/models/${id}/versions`);
}

export async function getModelExport(id: string): Promise<any> {
  return apiFetch(`/models/${id}/export-data`);
}

export async function getPopulationDeciles(id: string): Promise<any> {
  return apiFetch(`/models/${id}/metrics/population-deciles`);
}

export async function compareModels(
  modelIdA: string,
  modelIdB: string,
): Promise<any> {
  return apiFetch('/models/compare', {
    method: 'POST',
    body: { model_id_a: modelIdA, model_id_b: modelIdB },
  });
}

export async function getDashboardMetrics(): Promise<any> {
  return apiFetch('/dashboard/metrics');
}

export async function getSettings(): Promise<any> {
  return apiFetch('/settings');
}

export async function updateSettings(
  input: Record<string, unknown>,
): Promise<any> {
  return apiFetch('/settings', {
    method: 'PUT',
    body: input,
  });
}

export async function listNotifications(): Promise<any> {
  return apiFetch('/notifications');
}

export async function markNotificationRead(id: string): Promise<any> {
  return apiFetch(`/notifications/${id}/read`, { method: 'POST' });
}

export async function globalSearch(q: string): Promise<any> {
  return apiFetch('/search', { query: { q } });
}

export async function getUserProfile(): Promise<any> {
  return apiFetch('/users/me');
}

export async function listDocuments(): Promise<any> {
  return apiFetch('/documents');
}

export async function getDocument(id: string): Promise<any> {
  return apiFetch(`/documents/${id}`);
}

export async function deleteDocument(id: string): Promise<any> {
  return apiFetch(`/documents/${id}`, { method: 'DELETE' });
}

export async function uploadDocument(
  modelVersionId: string,
  file: File,
): Promise<any> {
  const fd = new FormData();
  fd.append('model_version_id', modelVersionId);
  fd.append('file', file);
  return apiFetch('/documents/upload', {
    method: 'POST',
    formData: fd,
  });
}

export async function runGapAnalysis(documentId: string): Promise<any> {
  return apiFetch('/gap-analysis', {
    method: 'POST',
    body: { document_id: documentId },
  });
}

export async function compareDocuments(
  documentIdA: string,
  documentIdB: string,
  focusAreas?: string[],
): Promise<any> {
  return apiFetch('/compare', {
    method: 'POST',
    body: {
      document_id_a: documentIdA,
      document_id_b: documentIdB,
      focus_areas: focusAreas ?? [],
    },
  });
}

export async function listRegulatoryStandards(): Promise<any> {
  return apiFetch('/regulatory/standards');
}

export async function regulatorySearch(question: string): Promise<any> {
  return apiFetch('/regulatory/search', {
    method: 'POST',
    body: { question },
  });
}

export async function maskText(
  text: string,
  sessionId?: string,
): Promise<any> {
  return apiFetch('/privacy/mask', {
    method: 'POST',
    body: { text, session_id: sessionId ?? null },
  });
}

export async function getRedactions(sessionId: string): Promise<any> {
  return apiFetch('/privacy/redactions', { query: { session_id: sessionId } });
}