import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { motion } from 'motion/react';
import { Activity, CheckCircle2, ChevronDown, X, XCircle } from 'lucide-react';
import { getRagTrace } from '@/lib/ragApi';
import type { RagTraceDetail } from '@/lib/ragTypes';
import {
  ENDPOINT_LABEL,
  MODE_LABEL,
  SCORE_KIND_LABEL,
  TAG_LABEL,
  fmtCompact,
  fmtDateTime,
  fmtFullDateTime,
  fmtMs,
  fmtPct,
  fmtRelative,
  fmtScore,
  ragLoadError,
} from '@/lib/ragFormat';
import { DataTable, niceTicks, useElementWidth } from './charts';
import { AXIS, GRID, WATERFALL } from './palette';
import FeedbackControl from './FeedbackControl';
import { Chip, ErrorState, LoadingState, MaskedText, TraceStatusBadge, useEscape } from './ui';

interface TraceDetailDrawerProps {
  isOpen: boolean;
  traceId: string | null;
  onClose: () => void;
  /** Fired when the viewer changes their feedback (parent can refresh aggregates). */
  onFeedbackChange?: () => void;
}

export default function TraceDetailDrawer({
  isOpen,
  traceId,
  onClose,
  onFeedbackChange,
}: TraceDetailDrawerProps) {
  const [detail, setDetail] = useState<RagTraceDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  const load = useCallback(
    async (quiet = false) => {
      if (!traceId) return;
      const my = ++seq.current;
      if (!quiet) {
        setLoading(true);
        setError(null);
      }
      try {
        const res = await getRagTrace(traceId);
        if (my !== seq.current) return;
        setDetail(res);
        setError(null);
      } catch (err) {
        if (my !== seq.current) return;
        if (!quiet) setError(ragLoadError(err, 'Trace detail'));
      } finally {
        if (my === seq.current) setLoading(false);
      }
    },
    [traceId],
  );

  useEffect(() => {
    if (!isOpen || !traceId) return;
    setDetail(null);
    void load();
    return () => {
      seq.current += 1;
    };
  }, [isOpen, traceId, load]);

  useEscape(isOpen, onClose);

  if (!isOpen || !traceId) return null;

  return (
    <>
      <motion.div
        onClick={onClose}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-sm"
      />
      <motion.aside
        initial={{ x: '100%' }}
        animate={{ x: 0 }}
        transition={{ type: 'tween', duration: 0.25, ease: 'easeOut' }}
        role="dialog"
        aria-modal="true"
        aria-label="RAG trace detail"
        className="glass-drawer fixed bottom-0 right-0 top-0 z-50 flex w-full flex-col overflow-hidden sm:w-[560px]"
      >
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 bg-slate-50/50 p-5 sm:p-6">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-indigo-100 bg-indigo-50 text-indigo-600">
              <Activity className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h2 className="font-display text-lg font-bold tracking-tight text-slate-900">Trace detail</h2>
              {detail ? (
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <TraceStatusBadge status={detail.status} reason={detail.guardrail_reason} />
                  <span>{ENDPOINT_LABEL[detail.endpoint] ?? detail.endpoint}</span>
                  <span aria-hidden>·</span>
                  <span title={fmtFullDateTime(detail.created_at)}>{fmtDateTime(detail.created_at)}</span>
                </div>
              ) : (
                <p className="mt-0.5 font-mono text-[11px] text-slate-400">{traceId}</p>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close trace detail"
            className="cursor-pointer rounded-full p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 sm:p-6">
          {loading && !detail && <LoadingState label="Loading trace…" />}
          {error && !detail && <ErrorState message={error} onRetry={() => void load()} />}
          {detail && (
            <TraceBody
              detail={detail}
              onFeedback={() => {
                void load(true);
                onFeedbackChange?.();
              }}
            />
          )}
        </div>
      </motion.aside>
    </>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2.5">
      <h3 className="text-[11px] font-bold uppercase tracking-wider text-slate-400">{title}</h3>
      {children}
    </section>
  );
}

function TraceBody({ detail, onFeedback }: { detail: RagTraceDetail; onFeedback: () => void }) {
  const [showFused, setShowFused] = useState(false);
  const guardrails = [
    detail.guardrail_reason && { k: 'Input guardrail', v: detail.guardrail_reason },
    detail.output_guardrail_reason && { k: 'Output guardrail', v: detail.output_guardrail_reason },
    detail.error_type && { k: 'Error type', v: detail.error_type },
    detail.error_stage && { k: 'Error stage', v: detail.error_stage },
  ].filter((x): x is { k: string; v: string } => Boolean(x));

  return (
    <div className="space-y-7">
      <Section title="Query (masked)">
        <p className="whitespace-pre-line break-words rounded-2xl border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed text-slate-800">
          {detail.query_masked ? (
            <MaskedText text={detail.query_masked} />
          ) : (
            <span className="italic text-slate-400">Not stored (masking unavailable)</span>
          )}
        </p>
        <div className="flex flex-wrap gap-1.5">
          <Chip tone="indigo">{MODE_LABEL[detail.retrieval_mode] ?? detail.retrieval_mode}</Chip>
          {detail.document_filename && <Chip title="Document scope">{detail.document_filename}</Chip>}
          {!detail.document_id && <Chip>Regulatory corpus</Chip>}
          <Chip>{detail.query_chars} chars</Chip>
        </div>
      </Section>

      <Section title="Latency waterfall">
        <Waterfall detail={detail} />
      </Section>

      <Section title="Retrieval">
        <dl className="grid grid-cols-3 gap-2 text-center sm:grid-cols-5">
          {[
            ['Dense', detail.dense_count],
            ['BM25', detail.bm25_count],
            ['Fused', detail.fused_count],
            ['Final', detail.reranked_count],
            ['top_k', detail.top_k],
          ].map(([k, v]) => (
            <div key={k} className="rounded-xl border border-slate-200 bg-slate-50 px-2 py-2">
              <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{k}</dt>
              <dd className="text-base font-bold tabular-nums text-slate-900">{v}</dd>
            </div>
          ))}
        </dl>
        <div className="flex flex-wrap gap-1.5">
          <Flag on={detail.rerank_applied} label="Rerank applied" good />
          <Flag on={detail.rerank_fallback} label="Rerank fallback" />
          <Flag on={detail.dense_empty} label="Dense empty" />
          {detail.score_kind && (
            <Chip title="Top-score scorer">{SCORE_KIND_LABEL[detail.score_kind] ?? detail.score_kind}</Chip>
          )}
          <Chip title="Top relevance (normalised)">Top relevance {fmtScore(detail.top_score_norm)}</Chip>
          <Chip title="Share of answer content tokens found in retrieved context">
            Groundedness {fmtPct(detail.groundedness)}
          </Chip>
        </div>

        <h4 className="pt-1 text-xs font-semibold text-slate-700">
          Retrieved (final) · {detail.answer_citation_count} cited in answer
        </h4>
        <ScoreList items={detail.scores} empty="No passages were retrieved." />

        {detail.fused_scores.length > 0 && (
          <div>
            <button
              type="button"
              onClick={() => setShowFused((v) => !v)}
              aria-expanded={showFused}
              className="inline-flex cursor-pointer items-center gap-1 text-xs font-semibold text-slate-500 hover:text-slate-800"
            >
              <ChevronDown className={`h-3.5 w-3.5 transition-transform ${showFused ? 'rotate-180' : ''}`} />
              Before rerank ({detail.fused_scores.length})
            </button>
            {showFused && (
              <div className="mt-2">
                <ScoreList items={detail.fused_scores} empty="—" />
              </div>
            )}
          </div>
        )}
      </Section>

      <Section title="Answer preview">
        {detail.answer_preview ? (
          <div className="max-h-64 overflow-y-auto whitespace-pre-line break-words rounded-2xl border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed text-slate-800">
            {detail.answer_preview}
          </div>
        ) : (
          <p className="text-xs italic text-slate-400">No answer was generated.</p>
        )}
      </Section>

      <Section title="LLM calls">
        {detail.llm_calls.length === 0 ? (
          <p className="text-xs italic text-slate-400">No provider calls recorded.</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-100">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="px-3 py-2 font-semibold">Method</th>
                  <th className="px-3 py-2 font-semibold">Provider / model</th>
                  <th className="px-3 py-2 text-right font-semibold">Latency</th>
                  <th className="px-3 py-2 text-right font-semibold">Attempt</th>
                  <th className="px-3 py-2 font-semibold">Result</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                {detail.llm_calls.map((c, i) => (
                  <tr key={i}>
                    <td className="whitespace-nowrap px-3 py-1.5 font-mono">{c.method}</td>
                    <td className="px-3 py-1.5">
                      <span className="font-semibold">{c.provider}</span>
                      <span className="block max-w-[180px] truncate text-slate-400" title={c.model}>
                        {c.model}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">{fmtMs(c.latency_ms)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{c.attempt + 1}</td>
                    <td className="whitespace-nowrap px-3 py-1.5">
                      {c.success ? (
                        <span className="inline-flex items-center gap-1 text-emerald-700">
                          <CheckCircle2 className="h-3.5 w-3.5" /> OK
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-rose-700">
                          <XCircle className="h-3.5 w-3.5" /> {c.error_type ?? 'Failed'}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-xs text-slate-500">
          Tokens ≈ {detail.est_prompt_tokens != null ? fmtCompact(detail.est_prompt_tokens) : '—'} prompt ·{' '}
          ≈ {detail.est_completion_tokens != null ? fmtCompact(detail.est_completion_tokens) : '—'} completion
          <span className="text-slate-400"> (estimated, chars ÷ 4)</span>
        </p>
      </Section>

      {guardrails.length > 0 && (
        <Section title="Guardrails & errors">
          <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {guardrails.map((g) => (
              <div key={g.k} className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2">
                <dt className="text-[10px] font-bold uppercase tracking-wider text-amber-700">{g.k}</dt>
                <dd className="break-words font-mono text-xs text-amber-900">{g.v}</dd>
              </div>
            ))}
          </dl>
        </Section>
      )}

      <Section title="Feedback">
        <FeedbackControl traceId={detail.id} initialRating={detail.my_rating} onChange={onFeedback} />
        {detail.feedback.length === 0 ? (
          <p className="text-xs italic text-slate-400">No feedback yet.</p>
        ) : (
          <ul className="space-y-2">
            {detail.feedback.map((f) => (
              <li key={f.id} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`font-bold ${f.rating === 1 ? 'text-indigo-700' : 'text-rose-700'}`}>
                    {f.rating === 1 ? '▲ Helpful' : '▼ Not helpful'}
                  </span>
                  {f.is_mine && <Chip tone="indigo">You</Chip>}
                  <span className="text-slate-400" title={fmtFullDateTime(f.created_at)}>
                    {fmtRelative(f.created_at)}
                  </span>
                </div>
                {f.tags.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {f.tags.map((t) => (
                      <Chip key={t}>{TAG_LABEL[t] ?? t}</Chip>
                    ))}
                  </div>
                )}
                {f.comment && <p className="mt-1.5 whitespace-pre-line break-words text-slate-700">{f.comment}</p>}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

function Flag({ on, label, good = false }: { on: boolean; label: string; good?: boolean }) {
  if (!on) return null;
  return (
    <Chip tone={good ? 'emerald' : 'amber'}>
      {good ? '✓ ' : '! '}
      {label}
    </Chip>
  );
}

function ScoreList({ items, empty }: { items: RagTraceDetail['scores']; empty: string }) {
  if (items.length === 0) return <p className="text-xs italic text-slate-400">{empty}</p>;
  return (
    <ol className="space-y-1.5">
      {items.map((s) => (
        <li
          key={`${s.rank}-${s.source}-${s.section}`}
          className="flex items-start gap-2.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs"
        >
          <span className="w-6 shrink-0 font-bold tabular-nums text-slate-400">#{s.rank}</span>
          <span className="min-w-0 flex-1">
            <span className="block truncate font-semibold text-slate-800" title={s.source}>
              {s.source}
            </span>
            <span className="block truncate text-slate-500" title={s.section}>
              {s.section}
            </span>
          </span>
          <span className="shrink-0 text-right">
            <span className="block font-semibold tabular-nums text-slate-800">{fmtScore(s.score, 3)}</span>
            <span className="block text-[10px] text-slate-400">{s.retrieval_method}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

// ---------------------------------------------------------------------------
// Waterfall: one row per stage, each bar starting where the previous one ends.
// ---------------------------------------------------------------------------

interface Segment {
  key: string;
  label: string;
  ms: number;
  color: string;
}

function buildSegments(d: RagTraceDetail): Segment[] {
  const segs: Segment[] = [];
  const push = (key: string, label: string, ms: number | null, color: string) => {
    if (ms != null && Number.isFinite(ms) && ms > 0) segs.push({ key, label, ms, color });
  };
  push('dense', 'Dense', d.dense_ms, WATERFALL.dense);
  push('bm25', 'BM25', d.bm25_ms, WATERFALL.bm25);
  push('fusion', 'RRF fusion', d.fusion_ms, WATERFALL.fusion);
  push('rerank', 'Rerank', d.rerank_ms, WATERFALL.rerank);
  const retrievalParts = [d.dense_ms, d.bm25_ms, d.fusion_ms, d.rerank_ms].reduce<number>(
    (s, v) => s + (v ?? 0),
    0,
  );
  if (d.retrieval_ms != null && d.retrieval_ms - retrievalParts > 0.5) {
    push('retrieval_other', 'Retrieval (other)', d.retrieval_ms - retrievalParts, WATERFALL.retrievalOther);
  } else if (retrievalParts === 0) {
    push('retrieval', 'Retrieval', d.retrieval_ms, WATERFALL.dense);
  }
  push('masking', 'Privacy masking', d.masking_ms, WATERFALL.masking);
  push('generation', 'Generation', d.generation_ms, WATERFALL.generation);
  const sum = segs.reduce((s, x) => s + x.ms, 0);
  if (d.total_ms != null && d.total_ms - sum > 0.5) push('other', 'Other', d.total_ms - sum, WATERFALL.other);
  return segs;
}

function Waterfall({ detail }: { detail: RagTraceDetail }) {
  const [ref, width] = useElementWidth<HTMLDivElement>(480);
  const [hover, setHover] = useState<number | null>(null);
  const segs = buildSegments(detail);
  if (segs.length === 0) {
    return <p className="text-xs italic text-slate-400">No stage timings were recorded for this trace.</p>;
  }
  const total = Math.max(detail.total_ms ?? 0, segs.reduce((s, x) => s + x.ms, 0), 1);
  const labelW = Math.min(118, Math.max(84, width * 0.28));
  const valueW = 52;
  const pw = Math.max(20, width - labelW - valueW);
  const ticks = niceTicks(total, { target: Math.max(2, Math.min(5, Math.floor(pw / 70))) });
  const scaleMax = ticks[ticks.length - 1] || total;
  const xAt = (ms: number) => labelW + (ms / scaleMax) * pw;
  const ROW = 22;
  const BAR = 12;
  const height = segs.length * ROW + 26;
  const ttft = detail.ttft_ms;
  let offset = 0;
  const rows = segs.map((s) => {
    const start = offset;
    offset += s.ms;
    return { ...s, start };
  });

  return (
    <div>
      <div ref={ref} className="relative w-full">
        <svg
          width="100%"
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={`Latency waterfall, end-to-end ${fmtMs(detail.total_ms)}`}
          className="block"
          onPointerLeave={() => setHover(null)}
        >
          {ticks.map((t, k) => (
            <g key={t} aria-hidden>
              <line
                x1={xAt(t)}
                x2={xAt(t)}
                y1={0}
                y2={segs.length * ROW}
                stroke={t === 0 ? '#cbd5e1' : GRID}
                strokeWidth={1}
                shapeRendering="crispEdges"
              />
              <text
                x={xAt(t)}
                y={segs.length * ROW + 13}
                fontSize={10}
                fill={AXIS}
                textAnchor={k === 0 ? 'start' : k === ticks.length - 1 ? 'end' : 'middle'}
                style={{ fontVariantNumeric: 'tabular-nums' }}
              >
                {fmtMs(t)}
              </text>
            </g>
          ))}
          {ttft != null && ttft > 0 && ttft <= scaleMax && (
            <g aria-hidden>
              <line
                x1={xAt(ttft)}
                x2={xAt(ttft)}
                y1={0}
                y2={segs.length * ROW}
                stroke="#0f172a"
                strokeWidth={1}
                shapeRendering="crispEdges"
              />
            </g>
          )}
          {rows.map((r, i) => {
            const y = i * ROW + (ROW - BAR) / 2;
            const x = xAt(r.start);
            const w = Math.max(2, xAt(r.start + r.ms) - x);
            return (
              <g
                key={r.key}
                tabIndex={0}
                aria-label={`${r.label}: ${fmtMs(r.ms)}, starts at ${fmtMs(r.start)}`}
                onPointerEnter={() => setHover(i)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                style={{ outline: 'none' }}
              >
                <rect x={0} y={i * ROW} width={width} height={ROW} fill={hover === i ? '#f1f5f9' : 'transparent'} />
                <text x={0} y={i * ROW + ROW / 2} dy="0.32em" fontSize={11} fill="#334155">
                  {r.label}
                </text>
                <rect x={x} y={y} width={w} height={BAR} rx={3} fill={r.color} />
                <text
                  x={Math.min(xAt(r.start + r.ms) + 5, width - 2)}
                  y={i * ROW + ROW / 2}
                  dy="0.32em"
                  fontSize={10}
                  fill="#475569"
                  textAnchor={xAt(r.start + r.ms) + 5 + 40 > width ? 'end' : 'start'}
                  stroke="#ffffff"
                  strokeWidth={3}
                  paintOrder="stroke"
                  style={{ fontVariantNumeric: 'tabular-nums' }}
                >
                  {fmtMs(r.ms)}
                </text>
              </g>
            );
          })}
        </svg>
        {hover != null && rows[hover] && (
          <div
            className="pointer-events-none absolute z-10 rounded-xl border border-slate-200 bg-white/95 px-3 py-2 text-xs shadow-lg"
            style={{
              top: hover * ROW + ROW + 2,
              left: Math.max(0, Math.min(width - 190, xAt(rows[hover].start))),
            }}
          >
            <div className="font-semibold text-slate-700">{rows[hover].label}</div>
            <div className="text-slate-500">
              <span className="font-bold tabular-nums text-slate-900">{fmtMs(rows[hover].ms)}</span> · starts at{' '}
              {fmtMs(rows[hover].start)} · {fmtPct(rows[hover].ms / total)} of total
            </div>
          </div>
        )}
      </div>
      <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
        <span>
          End-to-end <strong className="text-slate-800">{fmtMs(detail.total_ms)}</strong>
        </span>
        <span>
          Retrieval <strong className="text-slate-800">{fmtMs(detail.retrieval_ms)}</strong>
        </span>
        {ttft != null && (
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-3 w-px bg-slate-900" />
            Time to first token <strong className="text-slate-800">{fmtMs(ttft)}</strong>
          </span>
        )}
      </p>
      <DataTable
        caption="Stage timings"
        columns={['Stage', 'Starts at', 'Duration']}
        rows={rows.map((r) => [r.label, fmtMs(r.start), fmtMs(r.ms)])}
      />
    </div>
  );
}
