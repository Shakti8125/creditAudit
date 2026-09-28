/**
 * Formatting helpers and label maps for the RAG Performance page.
 *
 * Backend timestamps are naive UTC ISO-8601 strings without a zone suffix
 * (e.g. "2026-09-23T10:15:02.123456"); always go through parseUtc().
 */
import { ApiError } from '@/lib/http';
import type {
  EvalRunStatus,
  FeedbackTag,
  JudgeMode,
  RagEndpoint,
  RetrievalMode,
  ScoreKind,
  StageName,
  TraceStatus,
} from '@/lib/ragTypes';

const ZONE_SUFFIX = /(?:[zZ]|[+-]\d{2}:?\d{2})$/;

/** Parses a backend timestamp as UTC (appends 'Z' when no zone suffix is present). */
export function parseUtc(ts: string): Date {
  return new Date(ZONE_SUFFIX.test(ts) ? ts : `${ts}Z`);
}

const DASH = '—';

/** "—", "0.4 ms", "850 ms", or "2.3 s" at 1000 ms and above. */
export function fmtMs(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return DASH;
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
  if (ms > 0 && ms < 10) return `${ms.toFixed(1)} ms`;
  return `${Math.round(ms)} ms`;
}

/** Fraction (0–1) as a percentage. */
export function fmtPct(x: number | null | undefined, digits = 0): string {
  if (x == null || !Number.isFinite(x)) return DASH;
  return `${(x * 100).toFixed(digits)}%`;
}

export function fmtScore(x: number | null | undefined, digits = 2): string {
  if (x == null || !Number.isFinite(x)) return DASH;
  return x.toFixed(digits);
}

const compactFmt = /* @__PURE__ */ new Intl.NumberFormat('en-US', {
  notation: 'compact',
  maximumFractionDigits: 1,
});

/** 1,284 / 12.9K / 4.2M. */
export function fmtCompact(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return DASH;
  if (Math.abs(n) < 10_000) return Math.round(n).toLocaleString('en-US');
  return compactFmt.format(n);
}

/** Signed delta, e.g. "+0.12" / "-0.05" / "±0.00". */
export function fmtDelta(d: number | null | undefined, digits = 2): string {
  if (d == null || !Number.isFinite(d)) return DASH;
  const fixed = Math.abs(d).toFixed(digits);
  if (Number(fixed) === 0) return `±${fixed}`;
  return `${d > 0 ? '+' : '-'}${fixed}`;
}

const dateTimeFmt = /* @__PURE__ */ new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});
const fullFmt = /* @__PURE__ */ new Intl.DateTimeFormat('en-US', {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});
const hourFmt = /* @__PURE__ */ new Intl.DateTimeFormat('en-US', {
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});
const dayUtcFmt = /* @__PURE__ */ new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  timeZone: 'UTC',
});

function valid(d: Date): boolean {
  return !Number.isNaN(d.getTime());
}

/** "Sep 23, 14:05" in the viewer's local time. */
export function fmtDateTime(ts: string | null | undefined): string {
  if (!ts) return DASH;
  const d = parseUtc(ts);
  return valid(d) ? dateTimeFmt.format(d) : DASH;
}

/** Full local timestamp for `title` attributes. */
export function fmtFullDateTime(ts: string | null | undefined): string {
  if (!ts) return '';
  const d = parseUtc(ts);
  return valid(d) ? fullFmt.format(d) : '';
}

/** "just now", "5 min ago", "3 h ago", "2 d ago", then an absolute date. */
export function fmtRelative(ts: string | null | undefined, now: number = Date.now()): string {
  if (!ts) return DASH;
  const d = parseUtc(ts);
  if (!valid(d)) return DASH;
  const sec = Math.round((now - d.getTime()) / 1000);
  if (sec < 45) return 'just now';
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} h ago`;
  const day = Math.round(hr / 24);
  if (day < 7) return `${day} d ago`;
  return dateTimeFmt.format(d);
}

/**
 * Axis/tooltip label for a dashboard bucket. Hourly buckets show local "14:00";
 * daily buckets are UTC-aligned days, so they are labelled with the UTC date ("Sep 21").
 */
export function fmtBucket(ts: string, bucket: 'hour' | 'day'): string {
  const d = parseUtc(ts);
  if (!valid(d)) return '';
  return bucket === 'hour' ? hourFmt.format(d) : dayUtcFmt.format(d);
}

export function fmtBucketLong(ts: string, bucket: 'hour' | 'day'): string {
  const d = parseUtc(ts);
  if (!valid(d)) return '';
  return bucket === 'hour' ? dateTimeFmt.format(d) : `${dayUtcFmt.format(d)} (UTC day)`;
}

export function truncate(text: string | null | undefined, max: number): string {
  if (!text) return '';
  return text.length > max ? `${text.slice(0, Math.max(0, max - 1)).trimEnd()}…` : text;
}

/** Human-readable message for any thrown value (ApiError detail first). */
export function errorMessage(err: unknown, fallback = 'Something went wrong'): string {
  if (err instanceof ApiError) return err.detail || fallback;
  if (err instanceof Error) return err.message || fallback;
  return fallback;
}

/** Friendlier message when the RAG endpoints are missing on an older backend. */
export function ragLoadError(err: unknown, what: string): string {
  if (err instanceof ApiError && err.status === 404) {
    return `${what} is not available on this server yet (endpoint not found).`;
  }
  return errorMessage(err, `Unable to load ${what.toLowerCase()}`);
}

// ---- label maps

export const MODE_ORDER: RetrievalMode[] = ['dense', 'bm25', 'hybrid', 'hybrid_rerank'];

export const MODE_LABEL: Record<RetrievalMode, string> = {
  dense: 'Dense only',
  bm25: 'BM25 only',
  hybrid: 'Hybrid (RRF)',
  hybrid_rerank: 'Hybrid + rerank (production)',
};

/** Short mode names for tight spaces (tables, legends on phones). */
export const MODE_SHORT: Record<RetrievalMode, string> = {
  dense: 'Dense',
  bm25: 'BM25',
  hybrid: 'Hybrid',
  hybrid_rerank: 'Hybrid + rerank',
};

export const STAGE_LABEL: Record<StageName, string> = {
  masking: 'Privacy masking',
  dense: 'Dense (embed + Pinecone)',
  bm25: 'BM25',
  fusion: 'RRF fusion',
  rerank: 'Rerank',
  retrieval: 'Retrieval total',
  generation: 'Generation',
  ttft: 'Time to first token',
  total: 'End-to-end',
};

export const ENDPOINT_LABEL: Record<RagEndpoint, string> = {
  query: 'AI Analyst chat',
  regulatory_search: 'Regulatory Q&A',
};

export const FEEDBACK_TAGS: FeedbackTag[] = [
  'irrelevant_sources',
  'wrong_citation',
  'hallucination',
  'incomplete',
  'outdated',
  'too_slow',
  'other',
];

export const TAG_LABEL: Record<FeedbackTag, string> = {
  irrelevant_sources: 'Irrelevant sources',
  wrong_citation: 'Wrong citation',
  hallucination: 'Hallucination',
  incomplete: 'Incomplete',
  outdated: 'Outdated',
  too_slow: 'Too slow',
  other: 'Other',
};

export const SCORE_KIND_LABEL: Record<ScoreKind, string> = {
  rerank_nvidia: 'NVIDIA rerank',
  rerank_gemini: 'Gemini rerank',
  rerank: 'Rerank (other)',
  rrf: 'RRF fusion',
  dense: 'Dense cosine',
  bm25: 'BM25',
};

export const TRACE_STATUS_LABEL: Record<TraceStatus, string> = {
  ok: 'OK',
  error: 'Error',
  blocked: 'Blocked',
  cancelled: 'Cancelled',
};

export const RUN_STATUS_LABEL: Record<EvalRunStatus, string> = {
  pending: 'Pending',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

export const JUDGE_LABEL: Record<JudgeMode, string> = {
  auto: 'LLM judge with deterministic fallback',
  deterministic: 'Deterministic only',
};

export function isRunActive(status: EvalRunStatus): boolean {
  return status === 'pending' || status === 'running';
}

/**
 * Client-side mirror of the §2.4 `estimated_llm_calls` formula, summed over modes × cases:
 * +1 embed if the mode uses dense, +1 rerank for hybrid_rerank, +1 generation, +1 judge (auto).
 */
export function estimateLlmCalls(
  modes: RetrievalMode[],
  caseCount: number,
  includeGeneration: boolean,
  judge: JudgeMode,
): number {
  let perCase = 0;
  for (const m of modes) {
    if (m === 'dense' || m === 'hybrid' || m === 'hybrid_rerank') perCase += 1;
    if (m === 'hybrid_rerank') perCase += 1;
    if (includeGeneration) perCase += 1;
    if (includeGeneration && judge === 'auto') perCase += 1;
  }
  return perCase * caseCount;
}
