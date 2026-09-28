import { Fragment } from 'react';
import { Ban, Eye, FlaskConical, Loader2, Trash2 } from 'lucide-react';
import type { EvalRunSummary } from '@/lib/ragTypes';
import {
  MODE_SHORT,
  MODE_LABEL,
  fmtDateTime,
  fmtFullDateTime,
  fmtMs,
  fmtScore,
  isRunActive,
} from '@/lib/ragFormat';
import { SERIES } from './palette';
import { Card, EmptyState, ErrorState, LoadingState, RunStatusBadge } from './ui';

interface EvalRunsTableProps {
  runs: EvalRunSummary[] | null;
  loading: boolean;
  error: string | null;
  actionError: string | null;
  onRetry: () => void;
  slotById: Map<string, number>;
  canSelectMore: boolean;
  onToggleCompare: (id: string) => void;
  onViewResults: (id: string) => void;
  onCancel: (id: string) => void;
  onDelete: (id: string) => void;
  busyIds: Set<string>;
}

interface Group {
  id: string;
  label: string | null;
  createdAt: string;
  runs: EvalRunSummary[];
}

function groupRuns(runs: EvalRunSummary[]): Group[] {
  const groups: Group[] = [];
  const index = new Map<string, Group>();
  for (const r of runs) {
    let g = index.get(r.group_id);
    if (!g) {
      g = { id: r.group_id, label: r.label, createdAt: r.created_at, runs: [] };
      index.set(r.group_id, g);
      groups.push(g);
    }
    g.runs.push(r);
    if (r.created_at < g.createdAt) g.createdAt = r.created_at;
  }
  return groups;
}

const COLS = 12;

export default function EvalRunsTable({
  runs,
  loading,
  error,
  actionError,
  onRetry,
  slotById,
  canSelectMore,
  onToggleCompare,
  onViewResults,
  onCancel,
  onDelete,
  busyIds,
}: EvalRunsTableProps) {
  let body;
  if (runs == null && loading) body = <LoadingState label="Loading runs…" />;
  else if (runs == null && error) body = <ErrorState message={error} onRetry={onRetry} />;
  else if (!runs || runs.length === 0)
    body = (
      <EmptyState
        icon={FlaskConical}
        title="No evaluation runs yet"
        body="Launch a run above to measure hit rate, recall, MRR and nDCG against the golden dataset."
      />
    );
  else {
    const groups = groupRuns(runs);
    body = (
      <>
        {error && (
          <div className="mb-3">
            <ErrorState compact message={`Refresh failed: ${error}`} onRetry={onRetry} />
          </div>
        )}
        <div className="-mx-5 overflow-x-auto sm:-mx-6">
          <table className="w-full min-w-[980px] text-left text-xs">
            <thead className="text-slate-500">
              <tr className="border-b border-slate-100">
                <th className="py-2 pl-5 pr-2 font-semibold sm:pl-6">
                  <span className="sr-only">Compare</span>
                </th>
                <th className="px-2 py-2 font-semibold">Mode</th>
                <th className="px-2 py-2 text-right font-semibold">k</th>
                <th className="px-2 py-2 font-semibold">Gen</th>
                <th className="px-2 py-2 font-semibold">Status</th>
                <th className="px-2 py-2 text-right font-semibold">Hit@k</th>
                <th className="px-2 py-2 text-right font-semibold">Recall@k</th>
                <th className="px-2 py-2 text-right font-semibold">MRR</th>
                <th className="px-2 py-2 text-right font-semibold">nDCG@k</th>
                <th className="px-2 py-2 text-right font-semibold">Faithful.</th>
                <th className="px-2 py-2 text-right font-semibold">p95 latency</th>
                <th className="py-2 pl-2 pr-5 text-right font-semibold sm:pr-6">Actions</th>
              </tr>
            </thead>
            <tbody className="text-slate-700">
              {groups.map((g) => (
                <Fragment key={g.id}>
                  <tr className="border-t border-slate-100 bg-slate-50/70">
                    <th
                      colSpan={COLS}
                      scope="colgroup"
                      className="py-2 pl-5 pr-5 text-[11px] font-semibold text-slate-500 sm:pl-6"
                      title={fmtFullDateTime(g.createdAt)}
                    >
                      Batch · {g.label || 'unlabelled'} · {fmtDateTime(g.createdAt)}
                    </th>
                  </tr>
                  {g.runs.map((r) => {
                    const slot = slotById.get(r.id);
                    const selected = slot != null;
                    const active = isRunActive(r.status);
                    const busy = busyIds.has(r.id);
                    const done = r.completed_cases + r.failed_cases;
                    const pct = Math.max(0, Math.min(1, r.progress || (r.total_cases ? done / r.total_cases : 0)));
                    return (
                      <Fragment key={r.id}>
                        <tr className={`border-t border-slate-100 ${selected ? 'bg-indigo-50/30' : ''}`}>
                          <td className="py-2.5 pl-5 pr-2 sm:pl-6">
                            <label className="flex items-center gap-1.5">
                              <input
                                type="checkbox"
                                checked={selected}
                                disabled={active || (!selected && !canSelectMore)}
                                onChange={() => onToggleCompare(r.id)}
                                aria-label={`Compare ${MODE_LABEL[r.mode]} run`}
                                title={
                                  active
                                    ? 'Available once the run finishes'
                                    : !selected && !canSelectMore
                                      ? 'Up to 4 runs can be compared'
                                      : 'Compare'
                                }
                                className="h-4 w-4 cursor-pointer accent-indigo-600 disabled:cursor-not-allowed"
                              />
                              {selected && (
                                <span
                                  aria-hidden
                                  className="h-2.5 w-2.5 rounded-[3px]"
                                  style={{ backgroundColor: SERIES[slot % SERIES.length] }}
                                />
                              )}
                            </label>
                          </td>
                          <td className="whitespace-nowrap px-2 py-2.5 font-semibold text-slate-800" title={MODE_LABEL[r.mode]}>
                            {MODE_SHORT[r.mode] ?? r.mode}
                          </td>
                          <td className="px-2 py-2.5 text-right tabular-nums">{r.top_k}</td>
                          <td className="whitespace-nowrap px-2 py-2.5">
                            {r.include_generation ? (r.judge === 'auto' ? 'LLM judge' : 'Proxy') : '—'}
                          </td>
                          <td className="px-2 py-2.5">
                            {r.status === 'running' ? (
                              <div className="min-w-[120px]">
                                <div className="flex items-center justify-between gap-2">
                                  <RunStatusBadge status={r.status} />
                                  <span className="tabular-nums text-slate-500">
                                    {done}/{r.total_cases}
                                  </span>
                                </div>
                                <div
                                  className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-indigo-100"
                                  role="progressbar"
                                  aria-valuemin={0}
                                  aria-valuemax={100}
                                  aria-valuenow={Math.round(pct * 100)}
                                  aria-label="Run progress"
                                >
                                  <div className="h-full rounded-full bg-indigo-600 transition-all" style={{ width: `${pct * 100}%` }} />
                                </div>
                              </div>
                            ) : (
                              <span className="inline-flex items-center gap-2">
                                <RunStatusBadge status={r.status} />
                                {r.failed_cases > 0 && (
                                  <span className="whitespace-nowrap text-[11px] text-rose-600">
                                    {r.failed_cases} failed
                                  </span>
                                )}
                              </span>
                            )}
                          </td>
                          <td className="px-2 py-2.5 text-right tabular-nums">{fmtScore(r.metrics.hit_rate)}</td>
                          <td className="px-2 py-2.5 text-right tabular-nums">{fmtScore(r.metrics.recall)}</td>
                          <td className="px-2 py-2.5 text-right tabular-nums">{fmtScore(r.metrics.mrr)}</td>
                          <td className="px-2 py-2.5 text-right tabular-nums">{fmtScore(r.metrics.ndcg)}</td>
                          <td className="px-2 py-2.5 text-right tabular-nums">{fmtScore(r.metrics.faithfulness)}</td>
                          <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums">
                            {fmtMs(r.metrics.p95_latency_ms)}
                          </td>
                          <td className="py-2.5 pl-2 pr-5 sm:pr-6">
                            <div className="flex items-center justify-end gap-1.5">
                              <button
                                type="button"
                                onClick={() => onViewResults(r.id)}
                                className="inline-flex cursor-pointer items-center gap-1 whitespace-nowrap rounded-full border border-slate-200 bg-white px-2.5 py-1 font-semibold text-slate-600 hover:border-indigo-300 hover:text-indigo-700"
                              >
                                <Eye className="h-3.5 w-3.5" /> Results
                              </button>
                              {active ? (
                                <button
                                  type="button"
                                  onClick={() => onCancel(r.id)}
                                  disabled={busy}
                                  className="inline-flex cursor-pointer items-center gap-1 rounded-full border border-slate-200 bg-white px-2.5 py-1 font-semibold text-slate-600 hover:border-amber-300 hover:text-amber-700 disabled:opacity-50"
                                >
                                  {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Ban className="h-3.5 w-3.5" />}
                                  Cancel
                                </button>
                              ) : (
                                <button
                                  type="button"
                                  onClick={() => onDelete(r.id)}
                                  disabled={busy}
                                  aria-label="Delete run"
                                  title="Delete run"
                                  className="inline-flex cursor-pointer items-center rounded-full border border-slate-200 bg-white p-1.5 text-slate-500 hover:border-rose-300 hover:text-rose-700 disabled:opacity-50"
                                >
                                  {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                        {r.error_message && (
                          <tr>
                            <td />
                            <td colSpan={COLS - 1} className="px-2 pb-2.5 pr-5 text-[11px] text-rose-600 sm:pr-6">
                              {r.error_message}
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </>
    );
  }

  return (
    <Card
      title="Runs"
      subtitle="Tick up to 4 finished runs to compare them below. Metrics are means over cases @k."
    >
      {actionError && (
        <div className="mb-3">
          <ErrorState compact message={actionError} />
        </div>
      )}
      {body}
    </Card>
  );
}
