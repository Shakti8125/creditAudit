import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Inbox,
  RefreshCw,
  Shuffle,
  Target,
  ThumbsDown,
  ThumbsUp,
  Timer,
  Zap,
} from 'lucide-react';
import { getRagDashboard, listRagTraces } from '@/lib/ragApi';
import type {
  RagDashboard,
  RagEndpointBreakdown,
  RagEndpointFilter,
  RagStageLatency,
  RagTraceList,
  RagWindow,
  TraceStatusFilter,
} from '@/lib/ragTypes';
import {
  ENDPOINT_LABEL,
  SCORE_KIND_LABEL,
  STAGE_LABEL,
  TAG_LABEL,
  fmtBucket,
  fmtBucketLong,
  fmtCompact,
  fmtFullDateTime,
  fmtMs,
  fmtPct,
  fmtRelative,
  fmtScore,
  ragLoadError,
  truncate,
} from '@/lib/ragFormat';
import { BarList, HBarPairChart, LineChart, Meter, StackedColumnChart, type HBarRow } from './charts';
import { SEQ, STAGE_P50, STAGE_P95, TREND, VOLUME } from './palette';
import KpiTile, { type KpiTone } from './KpiTile';
import TraceDetailDrawer from './TraceDetailDrawer';
import {
  Banner,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  MaskedText,
  SegmentedControl,
  TraceStatusBadge,
  selectClass,
} from './ui';

const WINDOWS: { value: RagWindow; label: string }[] = [
  { value: '24h', label: '24h' },
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
  { value: '90d', label: '90d' },
];

const PAGE_SIZE = 25;
const COMPONENT_STAGES = ['masking', 'dense', 'bm25', 'fusion', 'rerank', 'generation'] as const;
const COMPOSITE_STAGES = ['retrieval', 'ttft', 'total'] as const;

function errorTone(rate: number | null): { tone: KpiTone; label?: string } {
  if (rate == null) return { tone: 'default' };
  if (rate > 0.05) return { tone: 'critical', label: 'Critical' };
  if (rate > 0.01) return { tone: 'warning', label: 'Elevated' };
  return { tone: 'good', label: 'Healthy' };
}

export default function TelemetryPanel() {
  const [win, setWin] = useState<RagWindow>('7d');
  const [endpoint, setEndpoint] = useState<RagEndpointFilter>('all');
  const [refreshKey, setRefreshKey] = useState(0);

  const [dash, setDash] = useState<RagDashboard | null>(null);
  const [dashLoading, setDashLoading] = useState(true);
  const [dashError, setDashError] = useState<string | null>(null);
  const dashSeq = useRef(0);

  const [status, setStatus] = useState<TraceStatusFilter>('all');
  const [mine, setMine] = useState(false);
  const [offset, setOffset] = useState(0);
  const [traces, setTraces] = useState<RagTraceList | null>(null);
  const [tracesLoading, setTracesLoading] = useState(true);
  const [tracesError, setTracesError] = useState<string | null>(null);
  const traceSeq = useRef(0);

  const [openTraceId, setOpenTraceId] = useState<string | null>(null);
  const feedbackChanged = useRef(false);

  const loadDashboard = useCallback(async () => {
    const my = ++dashSeq.current;
    setDashLoading(true);
    try {
      const res = await getRagDashboard(win, endpoint);
      if (my !== dashSeq.current) return;
      setDash(res);
      setDashError(null);
    } catch (err) {
      if (my !== dashSeq.current) return;
      setDashError(ragLoadError(err, 'RAG telemetry'));
    } finally {
      if (my === dashSeq.current) setDashLoading(false);
    }
  }, [win, endpoint]);

  const loadTraces = useCallback(async () => {
    const my = ++traceSeq.current;
    setTracesLoading(true);
    try {
      const res = await listRagTraces({ window: win, endpoint, status, mine, limit: PAGE_SIZE, offset });
      if (my !== traceSeq.current) return;
      setTraces(res);
      setTracesError(null);
    } catch (err) {
      if (my !== traceSeq.current) return;
      setTracesError(ragLoadError(err, 'Traces'));
    } finally {
      if (my === traceSeq.current) setTracesLoading(false);
    }
  }, [win, endpoint, status, mine, offset]);

  useEffect(() => {
    void loadDashboard();
  }, [loadDashboard, refreshKey]);

  useEffect(() => {
    void loadTraces();
  }, [loadTraces, refreshKey]);

  // Invalidate in-flight requests on unmount.
  useEffect(
    () => () => {
      dashSeq.current += 1;
      traceSeq.current += 1;
    },
    [],
  );

  const changeWindow = (w: RagWindow) => {
    setWin(w);
    setOffset(0);
  };
  const changeEndpoint = (e: RagEndpointFilter) => {
    setEndpoint(e);
    setOffset(0);
  };

  const closeDrawer = useCallback(() => {
    setOpenTraceId(null);
    if (feedbackChanged.current) {
      feedbackChanged.current = false;
      setRefreshKey((k) => k + 1);
    }
  }, []);

  const refreshing = dashLoading && dash != null;

  return (
    <div className="space-y-6">
      {/* Filter row — scopes everything below */}
      <div className="flex flex-wrap items-center gap-3">
        <SegmentedControl
          ariaLabel="Time window"
          options={WINDOWS}
          value={win}
          onChange={changeWindow}
          size="sm"
        />
        <label className="flex items-center gap-2 text-xs font-semibold text-slate-500">
          <span className="sr-only sm:not-sr-only">Surface</span>
          <select
            value={endpoint}
            onChange={(e) => changeEndpoint(e.target.value as RagEndpointFilter)}
            className={selectClass}
            aria-label="Surface"
          >
            <option value="all">All surfaces</option>
            <option value="query">{ENDPOINT_LABEL.query}</option>
            <option value="regulatory_search">{ENDPOINT_LABEL.regulatory_search}</option>
          </select>
        </label>
        <button
          type="button"
          onClick={() => setRefreshKey((k) => k + 1)}
          disabled={dashLoading || tracesLoading}
          className="inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 transition-colors hover:border-indigo-300 hover:text-indigo-700 disabled:cursor-default disabled:opacity-70"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${dashLoading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
        {dash?.sampled && (
          <span className="text-xs font-medium text-slate-500">Showing newest 20,000 requests</span>
        )}
      </div>

      {dash == null && dashLoading && (
        <div className="sleek-card">
          <LoadingState label="Loading telemetry…" />
        </div>
      )}
      {dash == null && !dashLoading && dashError && (
        <ErrorState message={dashError} onRetry={() => setRefreshKey((k) => k + 1)} />
      )}

      {dash != null && (
        <div className={`space-y-6 transition-opacity ${refreshing ? 'opacity-60' : ''}`} aria-busy={refreshing}>
          {dashError && (
            <ErrorState compact message={`Refresh failed: ${dashError}`} onRetry={() => setRefreshKey((k) => k + 1)} />
          )}
          {dash.kpis.total_requests === 0 ? (
            <div className="sleek-card">
              <EmptyState
                icon={Inbox}
                title="No RAG traffic in this window yet"
                body="Ask the AI Analyst or Regulatory Q&A a question to generate traces."
              />
            </div>
          ) : (
            <DashboardBody dash={dash} onOpenTrace={setOpenTraceId} />
          )}
        </div>
      )}

      {/* Recent traces */}
      {dash != null && (dash.kpis.total_requests > 0 || (traces?.total ?? 0) > 0) && (
        <Card
          title="Recent traces"
          subtitle="Masked queries only — raw user text is never stored."
          bodyClassName="p-5 sm:p-6"
          action={
            <div className="flex flex-wrap items-center gap-3">
              <select
                value={status}
                onChange={(e) => {
                  setStatus(e.target.value as TraceStatusFilter);
                  setOffset(0);
                }}
                className={selectClass}
                aria-label="Status filter"
              >
                <option value="all">All statuses</option>
                <option value="ok">OK</option>
                <option value="error">Error</option>
                <option value="blocked">Blocked</option>
                <option value="cancelled">Cancelled</option>
              </select>
              <label className="flex cursor-pointer items-center gap-2 text-xs font-semibold text-slate-600">
                <input
                  type="checkbox"
                  checked={mine}
                  onChange={(e) => {
                    setMine(e.target.checked);
                    setOffset(0);
                  }}
                  className="h-4 w-4 cursor-pointer rounded accent-indigo-600"
                />
                Only mine
              </label>
            </div>
          }
        >
          <TracesTable
            traces={traces}
            loading={tracesLoading}
            error={tracesError}
            onRetry={() => void loadTraces()}
            onOpen={setOpenTraceId}
            onPage={(o) => setOffset(Math.max(0, o))}
          />
        </Card>
      )}

      <TraceDetailDrawer
        isOpen={openTraceId != null}
        traceId={openTraceId}
        onClose={closeDrawer}
        onFeedbackChange={() => {
          feedbackChanged.current = true;
        }}
      />
    </div>
  );
}

function DashboardBody({ dash, onOpenTrace }: { dash: RagDashboard; onOpenTrace: (id: string) => void }) {
  const k = dash.kpis;
  const err = errorTone(k.error_rate);
  const bucketLabels = useMemo(() => dash.timeseries.map((p) => fmtBucket(p.bucket_start, dash.bucket)), [dash]);
  const bucketLong = useMemo(() => dash.timeseries.map((p) => fmtBucketLong(p.bucket_start, dash.bucket)), [dash]);
  const hasLatency = dash.timeseries.some((p) => p.p50_total_ms != null || p.p95_total_ms != null);

  const stageRows = useMemo<HBarRow[]>(() => {
    const byName = new Map<string, RagStageLatency>(dash.stages.map((s) => [s.stage, s]));
    const toRow = (name: string, divider = false): HBarRow | null => {
      const s = byName.get(name);
      if (!s) return null;
      return {
        key: s.stage,
        label: STAGE_LABEL[s.stage] ?? s.stage,
        a: s.p50_ms,
        b: s.p95_ms,
        divider,
        details: [
          { color: STAGE_P50, value: fmtMs(s.p50_ms), label: 'p50' },
          { color: STAGE_P95, value: fmtMs(s.p95_ms), label: 'p95' },
          { value: fmtMs(s.avg_ms), label: 'average' },
          { value: fmtCompact(s.count), label: 'requests' },
        ],
        tableCells: [fmtMs(s.avg_ms), fmtCompact(s.count)],
      };
    };
    const rows: HBarRow[] = [];
    COMPONENT_STAGES.forEach((n) => {
      const r = toRow(n);
      if (r) rows.push(r);
    });
    COMPOSITE_STAGES.forEach((n, i) => {
      const r = toRow(n, i === 0);
      if (r) rows.push(r);
    });
    return rows;
  }, [dash]);
  const anyStage = stageRows.some((r) => r.a != null || r.b != null);

  const denseEmpty = (k.dense_empty_rate ?? 0) > 0.5;
  const rerankFallback = (k.rerank_fallback_rate ?? 0) > 0.2;

  return (
    <>
      {(denseEmpty || rerankFallback) && (
        <Banner tone="warning">
          {denseEmpty && (
            <p>
              Dense retrieval returned no candidates for most requests — check Pinecone/embedding configuration.
              Results are BM25-only.
            </p>
          )}
          {rerankFallback && (
            <p>Reranker fell back to fusion order in {fmtPct(k.rerank_fallback_rate)} of requests.</p>
          )}
        </Banner>
      )}

      {/* KPI row */}
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
        <KpiTile
          tone="accent"
          icon={Activity}
          label="Requests"
          value={fmtCompact(k.total_requests)}
          caption={`${fmtCompact(k.ok_count)} answered · ${fmtCompact(k.blocked_count)} blocked`}
          spark={dash.timeseries.map((p) => p.count)}
        />
        <KpiTile
          icon={Timer}
          label="p95 latency"
          value={fmtMs(k.p95_total_ms)}
          caption={`p50 ${fmtMs(k.p50_total_ms)}`}
        />
        <KpiTile
          icon={Zap}
          label="Time to first token"
          value={fmtMs(k.p50_ttft_ms)}
          caption={`p95 ${fmtMs(k.p95_ttft_ms)} · chat streaming`}
        />
        <KpiTile
          icon={AlertTriangle}
          label="Error rate"
          value={fmtPct(k.error_rate, 1)}
          caption={`${fmtCompact(k.error_count)} errors`}
          tone={err.tone}
          statusLabel={err.label}
        />
        <KpiTile
          icon={Target}
          label="Groundedness"
          value={fmtPct(k.avg_groundedness)}
          caption="Answer tokens found in retrieved context"
        />
        <KpiTile
          icon={BookOpen}
          label="Citation rate"
          value={fmtPct(k.citation_rate)}
          caption={`Answers with ≥1 inline [Source: …] · avg ${
            k.avg_citations != null ? k.avg_citations.toFixed(1) : '—'
          } retrieved`}
        />
        <KpiTile
          icon={ThumbsUp}
          label="Satisfaction"
          value={fmtPct(k.satisfaction_rate)}
          caption={`${fmtCompact(dash.feedback.thumbs_up)} of ${fmtCompact(k.feedback_count)} rated helpful`}
        />
        <KpiTile
          icon={Shuffle}
          label="LLM failover"
          value={fmtPct(k.llm_fallback_rate)}
          caption={`Rerank fallback ${fmtPct(k.rerank_fallback_rate)} · Dense empty ${fmtPct(k.dense_empty_rate)}`}
        />
      </div>

      {/* Row 2 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card title="Latency by stage" subtitle="Successful requests · component stages above the line, composites below">
          {anyStage ? (
            <HBarPairChart
              rows={stageRows}
              aLabel="p50"
              bLabel="p95"
              aColor={STAGE_P50}
              bColor={STAGE_P95}
              format={fmtMs}
              ariaLabel="Latency by stage, p50 and p95 in milliseconds"
              labelTitle="Stage"
              tableExtraColumns={['Average', 'Requests']}
            />
          ) : (
            <p className="py-8 text-center text-sm text-slate-400">No successful requests with stage timings yet.</p>
          )}
        </Card>
        <Card title="Request volume" subtitle={`Requests per ${dash.bucket} by outcome`}>
          <StackedColumnChart
            xLabels={bucketLabels}
            xTooltipLabels={bucketLong}
            xTitle={dash.bucket === 'hour' ? 'Hour' : 'Day'}
            stacks={[
              { key: 'ok', label: 'OK', color: VOLUME.ok, values: dash.timeseries.map((p) => p.ok_count) },
              { key: 'blocked', label: 'Blocked', color: VOLUME.blocked, values: dash.timeseries.map((p) => p.blocked_count) },
              { key: 'error', label: 'Error', color: VOLUME.error, values: dash.timeseries.map((p) => p.error_count) },
              {
                key: 'cancelled',
                label: 'Cancelled',
                color: VOLUME.cancelled,
                values: dash.timeseries.map((p) => p.cancelled_count),
              },
            ]}
            yFormat={(v) => fmtCompact(v)}
            ariaLabel={`Request volume per ${dash.bucket}, stacked by outcome`}
          />
        </Card>
      </div>

      {/* Row 3 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card title="Latency trend" subtitle={`End-to-end latency per ${dash.bucket}, successful requests`}>
          {hasLatency ? (
            <LineChart
              xLabels={bucketLabels}
              xTooltipLabels={bucketLong}
              xTitle={dash.bucket === 'hour' ? 'Hour' : 'Day'}
              series={[
                { key: 'p50', label: 'p50', color: TREND.p50, values: dash.timeseries.map((p) => p.p50_total_ms) },
                { key: 'p95', label: 'p95', color: TREND.p95, values: dash.timeseries.map((p) => p.p95_total_ms) },
              ]}
              yFormat={fmtMs}
              ariaLabel="End-to-end latency trend, p50 and p95"
            />
          ) : (
            <p className="py-8 text-center text-sm text-slate-400">No successful requests in this window.</p>
          )}
        </Card>
        <FeedbackCard dash={dash} onOpenTrace={onOpenTrace} />
      </div>

      {/* Row 4 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card title="By endpoint">
          {dash.by_endpoint.length === 0 ? (
            <p className="text-sm text-slate-400">No data.</p>
          ) : (
            <div className="-mx-1 overflow-x-auto">
              {/* Transposed (metrics as rows) so it fits a third-width card. */}
              <table className="w-full text-left text-xs">
                <thead className="text-slate-500">
                  <tr className="border-b border-slate-100">
                    <th scope="col" className="px-1 py-2 font-semibold">
                      Metric
                    </th>
                    {dash.by_endpoint.map((e) => (
                      <th key={e.endpoint} scope="col" className="px-1 py-2 text-right font-semibold text-slate-700">
                        {ENDPOINT_LABEL[e.endpoint] ?? e.endpoint}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 tabular-nums text-slate-700">
                  {(
                    [
                      ['Requests', (e) => fmtCompact(e.count)],
                      ['Error rate', (e) => fmtPct(e.error_rate, 1)],
                      ['p50 latency', (e) => fmtMs(e.p50_total_ms)],
                      ['p95 latency', (e) => fmtMs(e.p95_total_ms)],
                      ['Groundedness', (e) => fmtPct(e.avg_groundedness)],
                      ['Satisfaction', (e) => fmtPct(e.satisfaction_rate)],
                    ] as [string, (e: RagEndpointBreakdown) => string][]
                  ).map(([label, get]) => (
                    <tr key={label}>
                      <th scope="row" className="whitespace-nowrap px-1 py-2 font-medium text-slate-600">
                        {label}
                      </th>
                      {dash.by_endpoint.map((e) => (
                        <td key={e.endpoint} className="whitespace-nowrap px-1 py-2 text-right">
                          {get(e)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card title="Providers" subtitle="Model that served the answer">
          {dash.providers.length === 0 ? (
            <p className="text-sm text-slate-400">No generation calls recorded.</p>
          ) : (
            <ul className="space-y-3">
              {dash.providers.map((p) => (
                <li key={`${p.provider}/${p.model}`} className="text-xs">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="min-w-0">
                      <span className="font-semibold text-slate-800">{p.provider}</span>
                      <span className="block truncate text-slate-400" title={p.model}>
                        {p.model}
                      </span>
                    </span>
                    <span className="shrink-0 tabular-nums text-slate-700">
                      <strong>{fmtPct(p.share)}</strong> · {fmtCompact(p.count)}
                    </span>
                  </div>
                  <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full" style={{ backgroundColor: SEQ.s100 }}>
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${Math.max(1, p.share * 100)}%`, backgroundColor: SEQ.s450 }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Top-score by scorer">
          {dash.score_kinds.length === 0 ? (
            <p className="text-sm text-slate-400">No scored retrievals yet.</p>
          ) : (
            <div className="-mx-1 overflow-x-auto">
              <table className="w-full min-w-[280px] text-left text-xs">
                <thead className="text-slate-500">
                  <tr className="border-b border-slate-100">
                    <th className="px-1 py-2 font-semibold">Scorer</th>
                    <th className="px-1 py-2 text-right font-semibold">n</th>
                    <th className="px-1 py-2 text-right font-semibold">Avg raw</th>
                    <th className="px-1 py-2 text-right font-semibold">Avg norm.</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 tabular-nums text-slate-700">
                  {dash.score_kinds.map((s) => (
                    <tr key={s.kind}>
                      <th scope="row" className="px-1 py-2 font-semibold text-slate-800">
                        {SCORE_KIND_LABEL[s.kind] ?? s.kind}
                      </th>
                      <td className="px-1 py-2 text-right">{fmtCompact(s.count)}</td>
                      <td className="px-1 py-2 text-right">{fmtScore(s.avg_top_score)}</td>
                      <td className="px-1 py-2 text-right">{fmtScore(s.avg_top_score_norm)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="mt-3 text-[11px] leading-relaxed text-slate-400">
            NVIDIA rerank scores are logits (normalised via sigmoid); Gemini 0–10; RRF 0–1; BM25 is unbounded and not
            normalised.
          </p>
        </Card>
      </div>
    </>
  );
}

function FeedbackCard({ dash, onOpenTrace }: { dash: RagDashboard; onOpenTrace: (id: string) => void }) {
  const fb = dash.feedback;
  return (
    <Card title="Feedback" subtitle="Thumbs up / down from AI Analyst and Regulatory Q&A users">
      {fb.total === 0 ? (
        <EmptyState
          icon={ThumbsUp}
          title="No feedback in this window"
          body="Users can rate answers as helpful or not helpful under each AI response."
        />
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-1 items-end gap-4 sm:grid-cols-[1fr_auto]">
            <Meter value={fb.satisfaction_rate} label="Satisfaction" />
            <div className="flex gap-4 text-sm">
              <span className="inline-flex items-center gap-1.5 text-slate-700">
                <ThumbsUp className="h-4 w-4 text-indigo-600" aria-hidden />
                <strong className="tabular-nums">{fmtCompact(fb.thumbs_up)}</strong>
                <span className="text-xs text-slate-500">helpful</span>
              </span>
              <span className="inline-flex items-center gap-1.5 text-slate-700">
                <ThumbsDown className="h-4 w-4 text-rose-600" aria-hidden />
                <strong className="tabular-nums">{fmtCompact(fb.thumbs_down)}</strong>
                <span className="text-xs text-slate-500">not helpful</span>
              </span>
            </div>
          </div>

          {fb.tag_counts.length > 0 && (
            <div>
              <h4 className="mb-2 text-xs font-semibold text-slate-700">Reported issues</h4>
              <BarList
                ariaLabel="Feedback tags"
                rows={fb.tag_counts.map((t) => ({ key: t.tag, label: TAG_LABEL[t.tag] ?? t.tag, value: t.count }))}
              />
            </div>
          )}

          {fb.recent.length > 0 && (
            <div>
              <h4 className="mb-2 text-xs font-semibold text-slate-700">Recent</h4>
              <ul className="max-h-64 space-y-1.5 overflow-y-auto pr-1">
                {fb.recent.map((f) => (
                  <li key={f.id}>
                    <button
                      type="button"
                      onClick={() => onOpenTrace(f.trace_id)}
                      className="w-full cursor-pointer rounded-xl border border-slate-200 bg-white px-3 py-2 text-left text-xs transition-colors hover:border-indigo-300"
                    >
                      <div className="flex items-start gap-2">
                        {f.rating === 1 ? (
                          <ThumbsUp className="mt-0.5 h-3.5 w-3.5 shrink-0 text-indigo-600" aria-label="Helpful" />
                        ) : (
                          <ThumbsDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-rose-600" aria-label="Not helpful" />
                        )}
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-slate-800">
                            {f.query_masked ? <MaskedText text={truncate(f.query_masked, 90)} /> : '—'}
                          </span>
                          {f.comment && (
                            <span className="mt-0.5 block line-clamp-2 text-slate-500">“{f.comment}”</span>
                          )}
                          {f.tags.length > 0 && (
                            <span className="mt-1 flex flex-wrap gap-1">
                              {f.tags.map((t) => (
                                <span
                                  key={t}
                                  className="rounded-md border border-slate-200 bg-slate-50 px-1.5 py-px text-[10px] text-slate-600"
                                >
                                  {TAG_LABEL[t] ?? t}
                                </span>
                              ))}
                            </span>
                          )}
                        </span>
                        <span className="shrink-0 text-[11px] text-slate-400" title={fmtFullDateTime(f.created_at)}>
                          {fmtRelative(f.created_at)}
                        </span>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function TracesTable({
  traces,
  loading,
  error,
  onRetry,
  onOpen,
  onPage,
}: {
  traces: RagTraceList | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onOpen: (id: string) => void;
  onPage: (offset: number) => void;
}) {
  if (!traces && loading) return <LoadingState label="Loading traces…" />;
  if (!traces && error) return <ErrorState message={error} onRetry={onRetry} />;
  if (!traces) return null;
  if (traces.items.length === 0) {
    return (
      <EmptyState
        icon={Inbox}
        title="No traces match these filters"
        body={error ? undefined : 'Try a wider time window, another status, or clear “Only mine”.'}
      />
    );
  }
  const from = traces.offset + 1;
  const to = traces.offset + traces.items.length;

  return (
    <div className={`transition-opacity ${loading ? 'opacity-60' : ''}`}>
      {error && (
        <div className="mb-3">
          <ErrorState compact message={error} onRetry={onRetry} />
        </div>
      )}
      <div className="-mx-5 overflow-x-auto sm:-mx-6">
        <table className="w-full min-w-[1080px] text-left text-xs">
          <thead className="text-slate-500">
            <tr className="border-b border-slate-100">
              <th className="px-3 py-2 pl-5 font-semibold sm:pl-6">Time</th>
              <th className="px-3 py-2 font-semibold">Surface</th>
              <th className="px-3 py-2 font-semibold">Query</th>
              <th className="px-3 py-2 font-semibold">Status</th>
              <th className="px-3 py-2 text-right font-semibold">Total</th>
              <th className="px-3 py-2 text-right font-semibold">Retrieval</th>
              <th className="px-3 py-2 text-right font-semibold">Gen</th>
              <th className="px-3 py-2 text-right font-semibold">Citations</th>
              <th className="px-3 py-2 text-right font-semibold" title="Normalised top retrieval score">
                Top rel.
              </th>
              <th className="px-3 py-2 text-right font-semibold">Grounded</th>
              <th className="px-3 py-2 font-semibold">Provider</th>
              <th className="px-3 py-2 pr-5 text-right font-semibold sm:pr-6">Feedback</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 text-slate-700">
            {traces.items.map((t) => (
              <tr
                key={t.id}
                onClick={() => onOpen(t.id)}
                className="cursor-pointer transition-colors hover:bg-indigo-50/40"
              >
                <td className="whitespace-nowrap px-3 py-2.5 pl-5 sm:pl-6" title={fmtFullDateTime(t.created_at)}>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onOpen(t.id);
                    }}
                    className="cursor-pointer font-medium text-slate-700 underline-offset-2 hover:text-indigo-700 hover:underline"
                    aria-label={`Open trace from ${fmtFullDateTime(t.created_at)}`}
                  >
                    {fmtRelative(t.created_at)}
                  </button>
                </td>
                <td className="whitespace-nowrap px-3 py-2.5">{ENDPOINT_LABEL[t.endpoint] ?? t.endpoint}</td>
                <td className="max-w-[280px] px-3 py-2.5">
                  <span className="line-clamp-2 break-words text-slate-800" title={t.query_masked ?? undefined}>
                    {t.query_masked ? <MaskedText text={truncate(t.query_masked, 80)} /> : '—'}
                  </span>
                </td>
                <td className="px-3 py-2.5">
                  <TraceStatusBadge status={t.status} reason={t.guardrail_reason ?? t.error_stage} />
                </td>
                <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{fmtMs(t.total_ms)}</td>
                <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{fmtMs(t.retrieval_ms)}</td>
                <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{fmtMs(t.generation_ms)}</td>
                <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">
                  {t.citation_count} · {t.answer_citation_count} cited
                </td>
                <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{fmtScore(t.top_score_norm)}</td>
                <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{fmtPct(t.groundedness)}</td>
                <td className="whitespace-nowrap px-3 py-2.5">
                  <span className="inline-flex items-center gap-1" title={t.model ?? undefined}>
                    {t.provider ?? '—'}
                    {t.llm_fallback_used && (
                      <Shuffle className="h-3.5 w-3.5 text-amber-600" aria-label="Provider failover used" />
                    )}
                  </span>
                </td>
                <td className="whitespace-nowrap px-3 py-2.5 pr-5 text-right tabular-nums sm:pr-6">
                  <span className="text-slate-600" aria-label={`${t.feedback_up} helpful, ${t.feedback_down} not helpful`}>
                    ↑{t.feedback_up} ↓{t.feedback_down}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-4 flex items-center justify-between gap-3 text-xs text-slate-500">
        <span className="tabular-nums">
          {from}–{to} of {fmtCompact(traces.total)}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => onPage(traces.offset - traces.limit)}
            disabled={traces.offset === 0 || loading}
            className="inline-flex cursor-pointer items-center gap-1 rounded-full border border-slate-200 bg-white px-3 py-1 font-semibold text-slate-600 hover:border-indigo-300 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <ChevronLeft className="h-3.5 w-3.5" /> Prev
          </button>
          <button
            type="button"
            onClick={() => onPage(traces.offset + traces.limit)}
            disabled={to >= traces.total || loading}
            className="inline-flex cursor-pointer items-center gap-1 rounded-full border border-slate-200 bg-white px-3 py-1 font-semibold text-slate-600 hover:border-indigo-300 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Next <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
