import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AlertTriangle, ArrowDown, ArrowUp, Ban, CheckCircle2, GitCompareArrows, X, XCircle } from 'lucide-react';
import { getEvalRun, getEvalRunResults } from '@/lib/ragApi';
import type { EvalCaseResult, EvalRunDetail, EvalRunMetrics, EvalRunSummary } from '@/lib/ragTypes';
import { MODE_LABEL, fmtDateTime, fmtDelta, fmtMs, fmtScore, ragLoadError, truncate } from '@/lib/ragFormat';
import { GroupedBarChart, HBarPairChart, LineChart, type BarSeries, type LineSeries } from './charts';
import { SERIES, STAGE_P50, STAGE_P95 } from './palette';
import { Banner, Card, EmptyState, ErrorState, LoadingState } from './ui';

export interface SelectedRun {
  run: EvalRunSummary;
  slot: number;
}

interface EvalRunComparisonProps {
  selected: SelectedRun[];
  hasAnyRuns: boolean;
  onRemove: (runId: string) => void;
  onOpenCase: (runId: string, caseId: string) => void;
}

type MetricKey = keyof EvalRunMetrics;

const RETRIEVAL_METRICS: { key: MetricKey; label: string }[] = [
  { key: 'hit_rate', label: 'Hit' },
  { key: 'recall', label: 'Recall' },
  { key: 'precision', label: 'Precision' },
  { key: 'mrr', label: 'MRR' },
  { key: 'ndcg', label: 'nDCG' },
];
const ANSWER_METRICS: { key: MetricKey; label: string }[] = [
  { key: 'faithfulness', label: 'Faithfulness' },
  { key: 'answer_relevance', label: 'Relevance' },
  { key: 'answer_correctness', label: 'Correctness' },
];
const DELTA_ROWS: { key: MetricKey; label: string; ms?: boolean; gen?: boolean }[] = [
  { key: 'hit_rate', label: 'Hit@k' },
  { key: 'recall', label: 'Recall@k' },
  { key: 'precision', label: 'Precision@k' },
  { key: 'mrr', label: 'MRR' },
  { key: 'ndcg', label: 'nDCG@k' },
  { key: 'faithfulness', label: 'Faithfulness', gen: true },
  { key: 'answer_relevance', label: 'Answer relevance', gen: true },
  { key: 'answer_correctness', label: 'Answer correctness', gen: true },
  { key: 'p50_latency_ms', label: 'p50 latency', ms: true },
  { key: 'p95_latency_ms', label: 'p95 latency', ms: true },
];

const score2 = (v: number) => v.toFixed(2);

function runLabels(selected: SelectedRun[]): Map<string, string> {
  const base = (r: EvalRunSummary) => `${MODE_LABEL[r.mode] ?? r.mode}${r.label ? ` · ${r.label}` : ''}`;
  const counts = new Map<string, number>();
  selected.forEach(({ run }) => counts.set(base(run), (counts.get(base(run)) ?? 0) + 1));
  const withK = (r: EvalRunSummary) => (counts.get(base(r))! > 1 ? `${base(r)} · k=${r.top_k}` : base(r));
  const counts2 = new Map<string, number>();
  selected.forEach(({ run }) => counts2.set(withK(run), (counts2.get(withK(run)) ?? 0) + 1));
  return new Map(
    selected.map(({ run }) => [
      run.id,
      counts2.get(withK(run))! > 1 ? `${withK(run)} · ${fmtDateTime(run.created_at)}` : withK(run),
    ]),
  );
}

interface RunData {
  key: string;
  detail?: EvalRunDetail;
  results?: EvalCaseResult[];
  error?: string;
}

function fetchKey(r: EvalRunSummary): string {
  return `${r.id}:${r.status}:${r.completed_cases}:${r.failed_cases}:${r.finished_at ?? ''}`;
}

export default function EvalRunComparison({ selected, hasAnyRuns, onRemove, onOpenCase }: EvalRunComparisonProps) {
  const [data, setData] = useState<Record<string, RunData>>({});
  const requested = useRef<Record<string, string>>({});
  const [retryNonce, setRetryNonce] = useState(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const keys = selected.map((s) => fetchKey(s.run)).join('|');
  useEffect(() => {
    for (const { run } of selected) {
      const key = fetchKey(run);
      if (requested.current[run.id] === key) continue;
      requested.current[run.id] = key;
      void Promise.all([getEvalRun(run.id), getEvalRunResults(run.id)])
        .then(([detail, res]) => {
          if (!mounted.current || requested.current[run.id] !== key) return;
          setData((prev) => ({ ...prev, [run.id]: { key, detail, results: res.results } }));
        })
        .catch((err: unknown) => {
          if (!mounted.current || requested.current[run.id] !== key) return;
          delete requested.current[run.id];
          setData((prev) => ({ ...prev, [run.id]: { key, error: ragLoadError(err, 'Run detail') } }));
        });
    }
  }, [keys, retryNonce]);

  const retry = (id: string) => {
    delete requested.current[id];
    setData((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
    setRetryNonce((n) => n + 1);
  };

  const labels = useMemo(() => runLabels(selected), [selected]);

  if (selected.length === 0) {
    return (
      <Card title="Compare runs">
        <EmptyState
          icon={GitCompareArrows}
          title={hasAnyRuns ? 'Select runs to compare' : 'Nothing to compare yet'}
          body={
            hasAnyRuns
              ? 'Tick up to 4 finished runs in the table above.'
              : 'Once an evaluation finishes, its retrieval metrics, k-curves, latency and per-case matrix appear here.'
          }
        />
      </Card>
    );
  }

  const color = (slot: number) => SERIES[slot % SERIES.length];
  const anyGen = selected.some((s) => s.run.include_generation);
  const details = selected.map((s) => data[s.run.id]?.detail);
  const loadingAny = selected.some((s) => !data[s.run.id]);
  const errors = selected
    .map((s) => ({ id: s.run.id, error: data[s.run.id]?.error }))
    .filter((e): e is { id: string; error: string } => Boolean(e.error));
  const denseEmptyMax = Math.max(0, ...details.map((d) => d?.degraded.dense_empty ?? 0));

  const barSeries = (metrics: { key: MetricKey }[], withJudge: boolean): BarSeries[] =>
    selected.map((s, i) => ({
      key: s.run.id,
      label: labels.get(s.run.id) ?? s.run.mode,
      color: color(s.slot),
      values: metrics.map((m) => s.run.metrics[m.key]),
      notes: withJudge
        ? metrics.map(() => {
            const jb = details[i]?.judge_breakdown;
            if (!s.run.include_generation) return 'Answers not evaluated';
            return jb ? `Judge: ${jb.llm} LLM · ${jb.deterministic} proxy · ${jb.none} none` : null;
          })
        : undefined,
    }));

  const kMax = Math.max(0, ...details.map((d) => d?.curves?.k.length ?? 0));
  const kLabels = Array.from({ length: kMax }, (_, i) => String(i + 1));
  const curveSeries = (field: 'hit' | 'recall'): LineSeries[] =>
    selected.map((s, i) => {
      const c = details[i]?.curves;
      return {
        key: s.run.id,
        label: labels.get(s.run.id) ?? s.run.mode,
        color: color(s.slot),
        values: kLabels.map((_, k) => {
          const idx = c ? c.k.indexOf(k + 1) : -1;
          const v = idx >= 0 ? c?.[field][idx] : undefined;
          return v != null && Number.isFinite(v) ? v : null;
        }),
      };
    });

  return (
    <div className="space-y-6">
      <Card
        title="Compare runs"
        subtitle="Baseline is the first selected run; Δ is measured against it. Colours stay with the run while it is selected."
      >
        <ul className="flex flex-wrap gap-2">
          {selected.map((s, i) => (
            <li
              key={s.run.id}
              className="inline-flex max-w-full items-center gap-2 rounded-full border border-slate-200 bg-white py-1 pl-2.5 pr-1 text-xs text-slate-700"
            >
              <span aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ backgroundColor: color(s.slot) }} />
              <span className="min-w-0 truncate font-semibold">{labels.get(s.run.id)}</span>
              <span className="shrink-0 text-slate-400">
                k={s.run.top_k}
                {i === 0 ? ' · baseline' : ''}
              </span>
              <button
                type="button"
                onClick={() => onRemove(s.run.id)}
                aria-label={`Remove ${labels.get(s.run.id)} from comparison`}
                className="cursor-pointer rounded-full p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              >
                <X className="h-3 w-3" />
              </button>
            </li>
          ))}
        </ul>

        {errors.map((e) => (
          <div key={e.id} className="mt-3">
            <ErrorState compact message={`${labels.get(e.id)}: ${e.error}`} onRetry={() => retry(e.id)} />
          </div>
        ))}

        {denseEmptyMax > 0 && (
          <div className="mt-4">
            <Banner tone="warning">
              <p>
                Dense retrieval unavailable for {denseEmptyMax} case{denseEmptyMax === 1 ? '' : 's'} — dense/hybrid
                numbers reflect BM25 only (Pinecone or embedding provider unreachable).
              </p>
            </Banner>
          </div>
        )}
      </Card>

      <div className={`grid grid-cols-1 gap-6 ${anyGen ? 'lg:grid-cols-2' : ''}`}>
        <Card title="Retrieval metrics @k" subtitle="Mean over cases; 1.0 is perfect">
          <GroupedBarChart
            categories={RETRIEVAL_METRICS.map((m) => m.label)}
            series={barSeries(RETRIEVAL_METRICS, false)}
            yMax={1}
            yFormat={score2}
            ariaLabel="Retrieval metrics at k per selected run"
          />
        </Card>
        {anyGen && (
          <Card title="Answer quality" subtitle="Judge scores for generated answers (0–1)">
            <GroupedBarChart
              categories={ANSWER_METRICS.map((m) => m.label)}
              series={barSeries(ANSWER_METRICS, true)}
              yMax={1}
              yFormat={score2}
              ariaLabel="Answer quality metrics per selected run"
            />
          </Card>
        )}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {(['hit', 'recall'] as const).map((field) => (
          <Card
            key={field}
            title={field === 'hit' ? 'Hit@k curve' : 'Recall@k curve'}
            subtitle={field === 'hit' ? 'Share of cases with a relevant passage in the top k' : 'Share of targets found in the top k'}
          >
            {kMax > 0 ? (
              <LineChart
                xLabels={kLabels}
                xTooltipLabels={kLabels.map((k) => `k = ${k}`)}
                xTitle="k"
                series={curveSeries(field)}
                yMax={1}
                yFormat={score2}
                directLabels={false}
                maxXLabels={20}
                ariaLabel={`${field === 'hit' ? 'Hit' : 'Recall'} at k curve per selected run`}
              />
            ) : loadingAny ? (
              <LoadingState label="Loading curves…" />
            ) : (
              <p className="py-8 text-center text-sm text-slate-400">No curve data for the selected runs.</p>
            )}
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <Card title="Latency p50 / p95 per run" subtitle="Retrieval plus generation time per case">
          <HBarPairChart
            rows={selected.map((s) => ({
              key: s.run.id,
              label: labels.get(s.run.id) ?? s.run.mode,
              a: s.run.metrics.p50_latency_ms,
              b: s.run.metrics.p95_latency_ms,
              swatch: color(s.slot),
            }))}
            aLabel="p50"
            bLabel="p95"
            aColor={STAGE_P50}
            bColor={STAGE_P95}
            format={fmtMs}
            labelTitle="Run"
            ariaLabel="Latency p50 and p95 per selected run"
          />
        </Card>

        <Card title="Deltas vs baseline" subtitle="↑ higher / ↓ lower than the baseline run (Δ in brackets)">
          <DeltaTable selected={selected} labels={labels} anyGen={anyGen} color={color} />
        </Card>
      </div>

      <CaseMatrix selected={selected} labels={labels} data={data} color={color} onOpenCase={onOpenCase} />
    </div>
  );
}

function DeltaTable({
  selected,
  labels,
  anyGen,
  color,
}: {
  selected: SelectedRun[];
  labels: Map<string, string>;
  anyGen: boolean;
  color: (slot: number) => string;
}) {
  const baseline = selected[0].run;
  const rows = DELTA_ROWS.filter((r) => anyGen || !r.gen);
  return (
    <div className="-mx-1 overflow-x-auto">
      <table className="w-full min-w-[360px] text-left text-xs">
        <thead className="text-slate-500">
          <tr className="border-b border-slate-100">
            <th scope="col" className="px-1 py-2 font-semibold">
              Metric
            </th>
            {selected.map((s, i) => (
              <th key={s.run.id} scope="col" className="px-1 py-2 text-right font-semibold">
                <span className="inline-flex items-center justify-end gap-1.5">
                  <span aria-hidden className="h-2 w-2 shrink-0 rounded-[2px]" style={{ backgroundColor: color(s.slot) }} />
                  <span className="max-w-[110px] truncate" title={labels.get(s.run.id)}>
                    {i === 0 ? 'Baseline' : `Run ${String.fromCharCode(65 + i)}`}
                  </span>
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 tabular-nums text-slate-700">
          {rows.map((row) => {
            const base = baseline.metrics[row.key];
            return (
              <tr key={row.key}>
                <th scope="row" className="whitespace-nowrap px-1 py-2 font-medium text-slate-700">
                  {row.label}
                </th>
                {selected.map((s, i) => {
                  const v = s.run.metrics[row.key];
                  const fmt = (x: number | null) => (row.ms ? fmtMs(x) : fmtScore(x));
                  if (i === 0) {
                    return (
                      <td key={s.run.id} className="whitespace-nowrap px-1 py-2 text-right font-semibold text-slate-900">
                        {fmt(v)}
                      </td>
                    );
                  }
                  const d = v != null && base != null ? v - base : null;
                  return (
                    <td key={s.run.id} className="whitespace-nowrap px-1 py-2 text-right">
                      <span className="font-semibold text-slate-900">{fmt(v)}</span>
                      {d != null && <DeltaText d={d} ms={row.ms} />}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
      <ul className="mt-2 space-y-0.5 text-[11px] text-slate-500">
        {selected.map((s, i) => (
          <li key={s.run.id} className="truncate">
            <strong className="font-semibold text-slate-600">
              {i === 0 ? 'Baseline' : `Run ${String.fromCharCode(65 + i)}`}:
            </strong>{' '}
            {labels.get(s.run.id)} (k={s.run.top_k})
          </li>
        ))}
      </ul>
    </div>
  );
}

function DeltaText({ d, ms }: { d: number; ms?: boolean }) {
  const zero = ms ? Math.abs(d) < 0.5 : Math.abs(d) < 0.005;
  const text = ms ? `${d > 0 ? '+' : d < 0 ? '-' : '±'}${fmtMs(Math.abs(d))}` : fmtDelta(d);
  return (
    <span className="ml-1.5 inline-flex items-center gap-0.5 text-slate-500">
      {!zero && (d > 0 ? <ArrowUp className="h-3 w-3" aria-label="higher" /> : <ArrowDown className="h-3 w-3" aria-label="lower" />)}
      ({text})
    </span>
  );
}

// ---------------------------------------------------------------------------
// Case matrix
// ---------------------------------------------------------------------------

type CellKind = 'top' | 'ranked' | 'miss' | 'error' | 'absent';

function cellOf(r: EvalCaseResult | undefined): { kind: CellKind; text: string } {
  if (!r) return { kind: 'absent', text: '—' };
  if (r.status === 'error') return { kind: 'error', text: 'error' };
  if (r.first_relevant_rank == null) return { kind: 'miss', text: 'miss' };
  if (r.first_relevant_rank === 1) return { kind: 'top', text: '#1' };
  return { kind: 'ranked', text: `#${r.first_relevant_rank}` };
}

const CELL_STYLE: Record<CellKind, { cls: string; icon: ReactNode }> = {
  top: { cls: 'bg-emerald-50 text-emerald-700 border-emerald-200', icon: <CheckCircle2 className="h-3 w-3" /> },
  ranked: { cls: 'bg-amber-50 text-amber-800 border-amber-200', icon: <AlertTriangle className="h-3 w-3" /> },
  miss: { cls: 'bg-rose-50 text-rose-700 border-rose-200', icon: <XCircle className="h-3 w-3" /> },
  error: { cls: 'bg-slate-100 text-slate-600 border-slate-300', icon: <Ban className="h-3 w-3" /> },
  absent: { cls: 'border-transparent text-slate-300', icon: null },
};

function CaseMatrix({
  selected,
  labels,
  data,
  color,
  onOpenCase,
}: {
  selected: SelectedRun[];
  labels: Map<string, string>;
  data: Record<string, RunData>;
  color: (slot: number) => string;
  onOpenCase: (runId: string, caseId: string) => void;
}) {
  const [onlyDisagree, setOnlyDisagree] = useState(false);
  const ready = selected.every((s) => data[s.run.id]?.results || data[s.run.id]?.error);

  const rows = useMemo(() => {
    const byRun = selected.map((s) => {
      const m = new Map<string, EvalCaseResult>();
      for (const r of data[s.run.id]?.results ?? []) m.set(r.case_id, r);
      return m;
    });
    const order: { caseId: string; pos: number; question: string }[] = [];
    const seen = new Set<string>();
    byRun.forEach((m, runIdx) => {
      for (const r of m.values()) {
        if (seen.has(r.case_id)) continue;
        seen.add(r.case_id);
        order.push({ caseId: r.case_id, pos: runIdx * 100000 + r.position, question: r.question_masked ?? '' });
      }
    });
    order.sort((a, b) => a.pos - b.pos);
    return order.map((o) => {
      const cells = byRun.map((m) => cellOf(m.get(o.caseId)));
      const question =
        o.question || byRun.map((m) => m.get(o.caseId)?.question_masked).find((q) => q) || '(question unavailable)';
      const distinct = new Set(cells.filter((c) => c.kind !== 'absent').map((c) => c.text));
      return { caseId: o.caseId, question, cells, disagree: distinct.size > 1 };
    });
  }, [selected, data]);

  const visible = onlyDisagree ? rows.filter((r) => r.disagree) : rows;
  const disagreeCount = rows.filter((r) => r.disagree).length;

  return (
    <Card
      title="Case matrix"
      subtitle="Rank of the first relevant passage per case. Click a cell to open that run's results for the case."
      action={
        <label className="flex cursor-pointer items-center gap-2 text-xs font-semibold text-slate-600">
          <input
            type="checkbox"
            checked={onlyDisagree}
            onChange={(e) => setOnlyDisagree(e.target.checked)}
            className="h-4 w-4 cursor-pointer accent-indigo-600"
            disabled={selected.length < 2}
          />
          Only cases where runs disagree{selected.length >= 2 ? ` (${disagreeCount})` : ''}
        </label>
      }
    >
      {!ready ? (
        <LoadingState label="Loading per-case results…" />
      ) : rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-slate-400">No per-case results for the selected runs.</p>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
            {(['top', 'ranked', 'miss', 'error'] as const).map((k) => (
              <span key={k} className="inline-flex items-center gap-1">
                <span className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-px font-semibold ${CELL_STYLE[k].cls}`}>
                  {CELL_STYLE[k].icon}
                  {k === 'top' ? '#1' : k === 'ranked' ? '#2–#k' : k}
                </span>
                {k === 'top' ? 'first hit' : k === 'ranked' ? 'found lower' : k === 'miss' ? 'not in top k' : 'case failed'}
              </span>
            ))}
          </div>
          <div className="-mx-5 max-h-[520px] overflow-auto sm:-mx-6">
            <table className="w-full min-w-[480px] text-left text-xs">
              <thead className="sticky top-0 z-10 bg-white text-slate-500">
                <tr className="border-b border-slate-100">
                  <th scope="col" className="py-2 pl-5 pr-3 font-semibold sm:pl-6">
                    Question (masked)
                  </th>
                  {selected.map((s, i) => (
                    <th key={s.run.id} scope="col" className="px-2 py-2 text-center font-semibold last:pr-5 sm:last:pr-6">
                      <span className="inline-flex items-center gap-1" title={labels.get(s.run.id)}>
                        <span aria-hidden className="h-2 w-2 rounded-[2px]" style={{ backgroundColor: color(s.slot) }} />
                        {i === 0 ? 'Baseline' : `Run ${String.fromCharCode(65 + i)}`}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {visible.map((row) => (
                  <tr key={row.caseId} className="hover:bg-slate-50/70">
                    <td className="max-w-[360px] py-2 pl-5 pr-3 sm:pl-6">
                      <button
                        type="button"
                        onClick={() => onOpenCase(selected[0].run.id, row.caseId)}
                        className="line-clamp-2 cursor-pointer text-left text-slate-700 hover:text-indigo-700"
                        title={row.question}
                      >
                        {truncate(row.question, 140)}
                      </button>
                    </td>
                    {row.cells.map((cell, i) => {
                      const s = selected[i];
                      return (
                        <td key={s.run.id} className="px-2 py-2 text-center last:pr-5 sm:last:pr-6">
                          {cell.kind === 'absent' ? (
                            <span className="text-slate-300" aria-label="Not in this run">
                              —
                            </span>
                          ) : (
                            <button
                              type="button"
                              onClick={() => onOpenCase(s.run.id, row.caseId)}
                              aria-label={`${labels.get(s.run.id)}: ${cell.text}. Open results`}
                              className={`inline-flex cursor-pointer items-center gap-1 rounded-md border px-1.5 py-0.5 font-semibold tabular-nums hover:brightness-95 ${CELL_STYLE[cell.kind].cls}`}
                            >
                              {CELL_STYLE[cell.kind].icon}
                              {cell.text}
                            </button>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
                {visible.length === 0 && (
                  <tr>
                    <td colSpan={selected.length + 1} className="py-6 text-center text-slate-400">
                      All selected runs agree on every case.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>
  );
}
