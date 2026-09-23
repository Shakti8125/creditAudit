import { useCallback, useEffect, useRef, useState } from 'react';
import { motion } from 'motion/react';
import { Ban, CheckCircle2, ChevronDown, ListChecks, X, XCircle } from 'lucide-react';
import { getEvalRunResults } from '@/lib/ragApi';
import type { EvalCaseResult, EvalRunSummary } from '@/lib/ragTypes';
import { MODE_LABEL, fmtDateTime, fmtMs, fmtScore, ragLoadError } from '@/lib/ragFormat';
import { Chip, EmptyState, ErrorState, LoadingState, RunStatusBadge, useEscape } from './ui';

interface EvalRunResultsDrawerProps {
  isOpen: boolean;
  run: EvalRunSummary | null;
  focusCaseId?: string;
  onClose: () => void;
}

const JUDGE_BADGE: Record<EvalCaseResult['judge_method'], { label: string; tone: 'indigo' | 'slate' }> = {
  llm: { label: 'LLM judge', tone: 'indigo' },
  deterministic: { label: 'Proxy', tone: 'slate' },
  none: { label: '—', tone: 'slate' },
};

export default function EvalRunResultsDrawer({ isOpen, run, focusCaseId, onClose }: EvalRunResultsDrawerProps) {
  const [results, setResults] = useState<EvalCaseResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [onlyMisses, setOnlyMisses] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const seq = useRef(0);
  const runId = run?.id ?? null;
  const runKey = run ? `${run.id}:${run.status}:${run.completed_cases}:${run.failed_cases}` : '';

  const load = useCallback(async () => {
    if (!runId) return;
    const my = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const res = await getEvalRunResults(runId);
      if (my !== seq.current) return;
      setResults(res.results);
    } catch (err) {
      if (my !== seq.current) return;
      setError(ragLoadError(err, 'Run results'));
    } finally {
      if (my === seq.current) setLoading(false);
    }
  }, [runId]);

  // New run: reset view state.
  useEffect(() => {
    if (!isOpen) return;
    setResults(null);
    setOnlyMisses(false);
  }, [isOpen, runId]);

  // (Re)load when opened and whenever a running run makes progress.
  useEffect(() => {
    if (!isOpen || !runId) return;
    void load();
    return () => {
      seq.current += 1;
    };
  }, [isOpen, runId, runKey, load]);

  useEffect(() => {
    if (isOpen) setExpanded(new Set(focusCaseId ? [focusCaseId] : []));
  }, [isOpen, runId, focusCaseId]);

  useEscape(isOpen, onClose);

  if (!isOpen) return null;

  const visible = (results ?? []).filter(
    (r) => !onlyMisses || r.status === 'error' || r.hit === false || r.first_relevant_rank == null,
  );
  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

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
        aria-label="Evaluation run results"
        className="glass-drawer fixed bottom-0 right-0 top-0 z-50 flex w-full flex-col overflow-hidden sm:w-[680px]"
      >
        <div className="border-b border-slate-100 bg-slate-50/50 p-5 sm:p-6">
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-indigo-100 bg-indigo-50 text-indigo-600">
                <ListChecks className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <h2 className="font-display text-lg font-bold tracking-tight text-slate-900">
                  {run ? MODE_LABEL[run.mode] : 'Run results'}
                </h2>
                {run && (
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <RunStatusBadge status={run.status} />
                    <span>k={run.top_k}</span>
                    {run.label && <span className="truncate">· {run.label}</span>}
                    <span>· {fmtDateTime(run.created_at)}</span>
                  </div>
                )}
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close run results"
              className="cursor-pointer rounded-full p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
          {run && (
            <dl className="mt-4 grid grid-cols-3 gap-2 text-center sm:grid-cols-6">
              {[
                ['Hit', fmtScore(run.metrics.hit_rate)],
                ['Recall', fmtScore(run.metrics.recall)],
                ['MRR', fmtScore(run.metrics.mrr)],
                ['nDCG', fmtScore(run.metrics.ndcg)],
                ['Faithful.', fmtScore(run.metrics.faithfulness)],
                ['p95', fmtMs(run.metrics.p95_latency_ms)],
              ].map(([k, v]) => (
                <div key={k} className="rounded-xl border border-slate-200 bg-white px-2 py-1.5">
                  <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{k}</dt>
                  <dd className="text-sm font-bold tabular-nums text-slate-900">{v}</dd>
                </div>
              ))}
            </dl>
          )}
          <label className="mt-4 flex w-fit cursor-pointer items-center gap-2 text-xs font-semibold text-slate-600">
            <input
              type="checkbox"
              checked={onlyMisses}
              onChange={(e) => setOnlyMisses(e.target.checked)}
              className="h-4 w-4 cursor-pointer accent-indigo-600"
            />
            Only misses / errors
          </label>
        </div>

        <div className="flex-1 overflow-y-auto p-5 sm:p-6">
          {!run && <ErrorState message="This run no longer exists." />}
          {run && results == null && loading && <LoadingState label="Loading results…" />}
          {run && results == null && !loading && error && <ErrorState message={error} onRetry={() => void load()} />}
          {results != null && (
            <>
              {error && (
                <div className="mb-3">
                  <ErrorState compact message={error} onRetry={() => void load()} />
                </div>
              )}
              {visible.length === 0 ? (
                <EmptyState
                  icon={ListChecks}
                  title={results.length === 0 ? 'No results yet' : 'No misses or errors'}
                  body={
                    results.length === 0
                      ? run && (run.status === 'pending' || run.status === 'running')
                        ? 'Per-case results appear as the run progresses.'
                        : 'This run produced no per-case results.'
                      : 'Every case retrieved at least one relevant passage.'
                  }
                />
              ) : (
                <ul className="space-y-2.5">
                  {visible.map((r) => (
                    <ResultItem
                      key={r.id}
                      result={r}
                      open={expanded.has(r.case_id)}
                      focused={r.case_id === focusCaseId}
                      onToggle={() => toggle(r.case_id)}
                    />
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      </motion.aside>
    </>
  );
}

function HitIcon({ r }: { r: EvalCaseResult }) {
  if (r.status === 'error') return <Ban className="h-4 w-4 shrink-0 text-slate-500" aria-label="Error" />;
  if (r.hit) return <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" aria-label="Hit" />;
  return <XCircle className="h-4 w-4 shrink-0 text-rose-600" aria-label="Miss" />;
}

function ResultItem({
  result: r,
  open,
  focused,
  onToggle,
}: {
  result: EvalCaseResult;
  open: boolean;
  focused: boolean;
  onToggle: () => void;
}) {
  const ref = useRef<HTMLLIElement | null>(null);
  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [focused]);
  const judge = JUDGE_BADGE[r.judge_method] ?? JUDGE_BADGE.none;
  const d = r.diagnostics;

  return (
    <li
      ref={ref}
      className={`rounded-2xl border bg-white ${focused ? 'border-indigo-300 ring-2 ring-indigo-100' : 'border-slate-200'}`}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full cursor-pointer items-start gap-3 px-4 py-3 text-left"
      >
        <HitIcon r={r} />
        <span className="min-w-0 flex-1">
          <span className="block break-words text-xs font-medium text-slate-800">
            {r.question_masked || <span className="italic text-slate-400">Question unavailable (masking failed)</span>}
          </span>
          <span className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] tabular-nums text-slate-500">
            <span>
              Rank{' '}
              <strong className="text-slate-800">
                {r.status === 'error' ? 'error' : r.first_relevant_rank != null ? `#${r.first_relevant_rank}` : 'miss'}
              </strong>
            </span>
            <span>
              Recall <strong className="text-slate-800">{fmtScore(r.recall)}</strong>
            </span>
            <span>
              nDCG <strong className="text-slate-800">{fmtScore(r.ndcg)}</strong>
            </span>
            {r.judge_method !== 'none' && (
              <>
                <span>
                  Faithful <strong className="text-slate-800">{fmtScore(r.faithfulness)}</strong>
                </span>
                <span>
                  Relevance <strong className="text-slate-800">{fmtScore(r.answer_relevance)}</strong>
                </span>
                <span>
                  Correct <strong className="text-slate-800">{fmtScore(r.answer_correctness)}</strong>
                </span>
              </>
            )}
            <span>
              Targets <strong className="text-slate-800">{r.targets_matched}/{r.n_targets}</strong>
            </span>
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <Chip tone={judge.tone}>{judge.label}</Chip>
          <ChevronDown className={`h-4 w-4 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} />
        </span>
      </button>

      {open && (
        <div className="space-y-4 border-t border-slate-100 px-4 py-3 text-xs">
          {(r.error_type || r.error_stage) && (
            <p className="rounded-xl border border-rose-100 bg-rose-50 px-3 py-2 text-rose-700">
              Failed{r.error_stage ? ` at ${r.error_stage}` : ''}
              {r.error_type ? ` (${r.error_type})` : ''}
            </p>
          )}

          <div>
            <h4 className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">Retrieved</h4>
            {r.retrieved.length === 0 ? (
              <p className="italic text-slate-400">Nothing retrieved.</p>
            ) : (
              <ol className="space-y-1.5">
                {r.retrieved.map((it) => (
                  <li
                    key={it.rank}
                    className={`rounded-xl border px-3 py-2 ${
                      it.relevant ? 'border-emerald-200 bg-emerald-50/40' : 'border-slate-200 bg-white'
                    }`}
                  >
                    <div className="flex items-start gap-2">
                      <span className="w-6 shrink-0 font-bold tabular-nums text-slate-400">#{it.rank}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-semibold text-slate-800" title={it.source}>
                          {it.source}
                        </span>
                        <span className="block truncate text-slate-500" title={it.section}>
                          {it.section}
                        </span>
                      </span>
                      <span className="shrink-0 text-right">
                        <span className="block font-semibold tabular-nums text-slate-800">{fmtScore(it.score, 3)}</span>
                        <span className="block text-[10px] text-slate-400">{it.retrieval_method}</span>
                      </span>
                    </div>
                    {it.relevant && (
                      <p className="mt-1 inline-flex items-center gap-1 pl-8 font-semibold text-emerald-700">
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        matches target{it.matched_targets.length === 1 ? '' : 's'}{' '}
                        {it.matched_targets.map((t) => `#${t + 1}`).join(', ')}
                      </p>
                    )}
                    {it.snippet && (
                      <p className="mt-1 line-clamp-3 break-words pl-8 text-slate-500">{it.snippet}</p>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </div>

          {r.answer && (
            <div>
              <h4 className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">Answer</h4>
              <div className="max-h-56 overflow-y-auto whitespace-pre-line break-words rounded-xl border border-slate-200 bg-slate-50 p-3 text-slate-800">
                {r.answer}
              </div>
            </div>
          )}

          {r.judge_rationale && (
            <div>
              <h4 className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">Judge rationale</h4>
              <p className="whitespace-pre-line break-words text-slate-600">{r.judge_rationale}</p>
            </div>
          )}

          <div>
            <h4 className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">Diagnostics</h4>
            <div className="flex flex-wrap gap-1.5">
              <Chip>Retrieval {fmtMs(r.retrieval_ms)}</Chip>
              {r.generation_ms != null && <Chip>Generation {fmtMs(r.generation_ms)}</Chip>}
              {r.judge_ms != null && <Chip>Judge {fmtMs(r.judge_ms)}</Chip>}
              {d && (
                <>
                  {d.dense_ms != null && <Chip>Dense {fmtMs(d.dense_ms)}</Chip>}
                  {d.bm25_ms != null && <Chip>BM25 {fmtMs(d.bm25_ms)}</Chip>}
                  {d.fusion_ms != null && <Chip>Fusion {fmtMs(d.fusion_ms)}</Chip>}
                  {d.rerank_ms != null && <Chip>Rerank {fmtMs(d.rerank_ms)}</Chip>}
                  <Chip>
                    {d.dense_count} dense · {d.bm25_count} BM25 · {d.fused_count} fused · {d.final_count} final
                  </Chip>
                  {d.dense_empty && <Chip tone="amber">! Dense empty</Chip>}
                  {d.rerank_fallback && <Chip tone="amber">! Rerank fallback</Chip>}
                  {d.unresolved_chunk_targets > 0 && (
                    <Chip tone="amber">! {d.unresolved_chunk_targets} unresolved chunk target(s)</Chip>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </li>
  );
}
