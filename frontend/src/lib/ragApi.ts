/**
 * Typed client for the RAG telemetry / feedback / evaluation endpoints (contract §2.3–2.4).
 *
 * Kept in its own module (not lib/api.ts) so it merges cleanly alongside other API work.
 * DTOs are snake_case exactly as sent by the backend; query-string values must be strings.
 */
import { apiFetch } from '@/lib/http';
import type {
  EvalCase,
  EvalCaseInput,
  EvalCaseList,
  EvalRunCreateInput,
  EvalRunCreateResponse,
  EvalRunDetail,
  EvalRunList,
  EvalRunResults,
  EvalRunSummary,
  RagDashboard,
  RagEndpointFilter,
  RagFeedbackInput,
  RagFeedbackRecord,
  RagTraceDetail,
  RagTraceList,
  RagWindow,
  RestoreDefaultsResult,
  TraceStatusFilter,
} from '@/lib/ragTypes';

const enc = encodeURIComponent;

// ---- telemetry (T1–T5)

export const getRagDashboard = (window: RagWindow, endpoint: RagEndpointFilter) =>
  apiFetch<RagDashboard>('/rag/telemetry/dashboard', { query: { window, endpoint } });

export const listRagTraces = (p: {
  window: RagWindow;
  endpoint: RagEndpointFilter;
  status: TraceStatusFilter;
  mine: boolean;
  limit: number;
  offset: number;
}) =>
  apiFetch<RagTraceList>('/rag/traces', {
    query: {
      window: p.window,
      endpoint: p.endpoint,
      status: p.status,
      mine: String(p.mine),
      limit: String(p.limit),
      offset: String(p.offset),
    },
  });

export const getRagTrace = (id: string) => apiFetch<RagTraceDetail>(`/rag/traces/${enc(id)}`);

export const submitRagFeedback = (input: RagFeedbackInput) =>
  apiFetch<RagFeedbackRecord>('/rag/feedback', { method: 'POST', body: input });

export const deleteRagFeedback = (traceId: string) =>
  apiFetch<void>(`/rag/feedback/${enc(traceId)}`, { method: 'DELETE' });

// ---- golden dataset (E1–E5)

export const listEvalCases = (includeInactive = true) =>
  apiFetch<EvalCaseList>('/rag/eval/cases', {
    query: { include_inactive: String(includeInactive) },
  });

export const createEvalCase = (input: EvalCaseInput) =>
  apiFetch<EvalCase>('/rag/eval/cases', { method: 'POST', body: input });

export const updateEvalCase = (id: string, input: Partial<EvalCaseInput>) =>
  apiFetch<EvalCase>(`/rag/eval/cases/${enc(id)}`, { method: 'PATCH', body: input });

export const deleteEvalCase = (id: string) =>
  apiFetch<void>(`/rag/eval/cases/${enc(id)}`, { method: 'DELETE' });

export const restoreDefaultEvalCases = () =>
  apiFetch<RestoreDefaultsResult>('/rag/eval/cases/restore-defaults', { method: 'POST' });

// ---- evaluation runs (E6–E11)

export const createEvalRuns = (input: EvalRunCreateInput) =>
  apiFetch<EvalRunCreateResponse>('/rag/eval/runs', { method: 'POST', body: input });

export const listEvalRuns = (limit = 20, offset = 0) =>
  apiFetch<EvalRunList>('/rag/eval/runs', {
    query: { limit: String(limit), offset: String(offset) },
  });

export const getEvalRun = (id: string) => apiFetch<EvalRunDetail>(`/rag/eval/runs/${enc(id)}`);

export const getEvalRunResults = (id: string) =>
  apiFetch<EvalRunResults>(`/rag/eval/runs/${enc(id)}/results`);

export const cancelEvalRun = (id: string) =>
  apiFetch<EvalRunSummary>(`/rag/eval/runs/${enc(id)}/cancel`, { method: 'POST' });

export const deleteEvalRun = (id: string) =>
  apiFetch<void>(`/rag/eval/runs/${enc(id)}`, { method: 'DELETE' });

// ---- documents (scope picker for golden cases)

/** Minimal document shape needed by the eval-case scope picker. */
export interface EvalDocumentOption {
  id: string;
  filename: string;
  status: string;
}

/**
 * Lists the tenant's documents for the case editor's scope `<select>`.
 * Self-contained (reads the existing `GET /documents` endpoint) so this module does not
 * depend on lib/api.ts or lib/adapters.ts.
 */
export async function listEvalDocuments(): Promise<EvalDocumentOption[]> {
  const dto = await apiFetch<unknown>('/documents');
  const raw: unknown[] = Array.isArray(dto)
    ? dto
    : Array.isArray((dto as { documents?: unknown[] } | null)?.documents)
      ? ((dto as { documents: unknown[] }).documents)
      : [];
  const out: EvalDocumentOption[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const d = item as Record<string, unknown>;
    if (typeof d.id !== 'string') continue;
    out.push({
      id: d.id,
      filename: typeof d.filename === 'string' ? d.filename : d.id,
      status: typeof d.status === 'string' ? d.status : '',
    });
  }
  return out;
}
