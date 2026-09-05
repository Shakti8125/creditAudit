import { useEffect, useMemo, useRef, useState } from 'react';
import type {
  ChatMessage,
  ChatSource,
  ModelStatus,
  ModelSummary,
  PopulationDecile,
} from '@/types';
import {
  AlertTriangle,
  BookOpen,
  Download,
  FileText,
  GitCompareArrows,
  Loader2,
  Send,
  Sparkles,
} from 'lucide-react';
import { getPopulationDeciles } from '@/lib/api';
import { aucToRoc } from '@/lib/roc';
import { streamQuery } from '@/lib/sse';
import DocumentViewer from '@/components/DocumentViewer';

interface WorkspaceViewProps {
  currentModel: ModelSummary;
  onExportReport: () => void;
  onNavigateToCompare: () => void;
  onOpenRegulatoryStandard: (code: string) => void;
  /** Document uploaded in this session — preselected in the Documents tab. */
  activeDocumentId?: string | null;
}

type WorkspaceTab = 'metrics' | 'gap' | 'documents' | 'analyst' | 'citations';

const TABS: { key: WorkspaceTab; label: string }[] = [
  { key: 'metrics', label: 'Metrics' },
  { key: 'gap', label: 'Gap Analysis' },
  { key: 'documents', label: 'Documents' },
  { key: 'analyst', label: 'AI Analyst' },
  { key: 'citations', label: 'Citations' },
];

function fmt(value: number, decimals: number): string {
  return value.toFixed(decimals).replace(/\.?0+$/, '');
}

function metricTone(
  direction: 'higher' | 'lower',
  value: number,
  threshold: number,
): ModelStatus {
  if (direction === 'higher') {
    if (value >= threshold) return 'PASS';
    if (value >= threshold * 0.8) return 'WARNING';
    return 'BREACH';
  }
  if (value <= threshold) return 'PASS';
  if (value <= threshold * 2) return 'WARNING';
  return 'BREACH';
}

function statusPill(status: string): string {
  if (status === 'PASS') return 'bg-emerald-50 border-emerald-200 text-emerald-700';
  if (status === 'WARNING') return 'bg-amber-50 border-amber-200 text-amber-700';
  return 'bg-rose-50 border-rose-200 text-rose-700';
}

function toneFill(status: string): string {
  if (status === 'PASS') return '#10b981';
  if (status === 'WARNING') return '#f59e0b';
  return '#f43f5e';
}

export default function WorkspaceView({
  currentModel,
  onExportReport,
  onNavigateToCompare,
  onOpenRegulatoryStandard,
  activeDocumentId,
}: WorkspaceViewProps) {
  const [tab, setTab] = useState<WorkspaceTab>('metrics');

  const [deciles, setDeciles] = useState<PopulationDecile[] | null>(null);
  const [decilesLoading, setDecilesLoading] = useState(true);
  const [decilesFailed, setDecilesFailed] = useState(false);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let active = true;
    setDecilesLoading(true);
    getPopulationDeciles(currentModel.id)
      .then((data) => {
        if (!active) return;
        const list = Array.isArray(data?.deciles) ? (data.deciles as PopulationDecile[]) : [];
        setDeciles(list.length > 0 ? list : null);
        setDecilesFailed(false);
      })
      .catch(() => {
        if (!active) return;
        setDeciles(null);
        setDecilesFailed(true);
      })
      .finally(() => {
        if (active) setDecilesLoading(false);
      });
    return () => {
      active = false;
    };
  }, [currentModel.id]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, streaming]);

  const rocPoints = useMemo(
    () => aucToRoc(currentModel.metrics.auc),
    [currentModel.metrics.auc],
  );

  const latestCitationMessage = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const msg = messages[i];
      if (msg.sender === 'ai' && msg.sources && msg.sources.length > 0) {
        return msg;
      }
    }
    return null;
  }, [messages]);

  const isEadOrLgd = currentModel.type === 'EAD' || currentModel.type === 'LGD';
  const hasGini = currentModel.metrics.gini > 0;
  const hasAuc = currentModel.metrics.auc > 0;

  const metricCards = [
    {
      key: 'gini',
      label: 'Gini Coefficient',
      display: hasGini ? `${fmt(currentModel.metrics.gini, 1)}%` : isEadOrLgd ? 'N/A' : `${fmt(currentModel.metrics.gini, 1)}%`,
      note: isEadOrLgd && !hasGini ? `Not applicable for ${currentModel.type}` : `Threshold ≥ ${fmt(currentModel.metrics.giniThreshold, 1)}%`,
      tone: isEadOrLgd && !hasGini ? ('PASS' as ModelStatus) : metricTone('higher', currentModel.metrics.gini, currentModel.metrics.giniThreshold),
    },
    {
      key: 'auc',
      label: 'AUC',
      display: hasAuc ? fmt(currentModel.metrics.auc, 3) : isEadOrLgd ? 'N/A' : fmt(currentModel.metrics.auc, 3),
      note: isEadOrLgd && !hasAuc ? `Not applicable for ${currentModel.type}` : `Benchmark ≥ ${fmt(currentModel.metrics.aucBenchmark, 3)}`,
      tone: isEadOrLgd && !hasAuc ? ('PASS' as ModelStatus) : metricTone('higher', currentModel.metrics.auc, currentModel.metrics.aucBenchmark),
    },
    {
      key: 'ks',
      label: 'KS Statistic',
      display: `${fmt(currentModel.metrics.ks, 1)}%`,
      note: `Benchmark ≥ ${fmt(currentModel.metrics.ksBenchmark, 1)}%`,
      tone: metricTone('higher', currentModel.metrics.ks, currentModel.metrics.ksBenchmark),
    },
    {
      key: 'psi',
      label: 'Population Stability',
      display: fmt(currentModel.metrics.psi, 3),
      note: `Threshold < ${fmt(currentModel.metrics.psiThreshold, 3)}`,
      tone: metricTone('lower', currentModel.metrics.psi, currentModel.metrics.psiThreshold),
    },
  ];

  const handleSend = async (textOverride?: string) => {
    const text = (textOverride ?? input).trim();
    if (!text || streaming) return;
    setInput('');

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      sender: 'user',
      timestamp: 'Just now',
      content: text,
    };
    const aiId = `ai-${Date.now()}`;
    const aiMsg: ChatMessage = {
      id: aiId,
      sender: 'ai',
      timestamp: '',
      content: '',
    };

    setMessages((prev) => [...prev, userMsg, aiMsg]);
    setStreaming(true);

    const pendingSources: ChatSource[] = [];
    const pendingActions: string[] = [];

    const pushError = (message: string) => {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === aiId
            ? {
                ...m,
                content: m.content || `Unable to complete analysis: ${message}`,
                timestamp: 'Just now',
              }
            : m,
        ),
      );
    };

    try {
      await streamQuery(
        { question: text, documentId: undefined, sessionId: sessionId ?? undefined },
        {
          onSessionId: (id) => {
            if (id) setSessionId(id);
          },
          onCitations: (citations) => {
            pendingSources.length = 0;
            for (const c of citations ?? []) {
              pendingSources.push({ title: c?.source ?? '', ref: c?.section ?? '' });
            }
          },
          onToken: (token) => {
            setMessages((prev) =>
              prev.map((m) => (m.id === aiId ? { ...m, content: m.content + token } : m)),
            );
          },
          onSuggestedActions: (actions) => {
            pendingActions.length = 0;
            pendingActions.push(...(actions ?? []));
          },
          onDone: () => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === aiId
                  ? {
                      ...m,
                      timestamp: 'Just now',
                      sources: pendingSources,
                      suggestedActions: pendingActions,
                      isHighlighted: true,
                    }
                  : m,
              ),
            );
          },
          onError: (message) => pushError(message),
        },
      );
    } catch (err) {
      pushError(err instanceof Error ? err.message : 'Unable to reach the AI analyst.');
    } finally {
      setStreaming(false);
    }
  };

  const PLOT = { w: 320, h: 240, pad: 36 };
  const sx = (fpr: number) => PLOT.pad + fpr * (PLOT.w - 2 * PLOT.pad);
  const sy = (tpr: number) => PLOT.pad + (1 - tpr) * (PLOT.h - 2 * PLOT.pad);
  const rocLine = rocPoints
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${sx(p.fpr).toFixed(2)} ${sy(p.tpr).toFixed(2)}`)
    .join(' ');
  const rocArea = `${rocLine} L ${sx(1).toFixed(2)} ${sy(0).toFixed(2)} L ${sx(0).toFixed(2)} ${sy(0).toFixed(2)} Z`;
  const gridFractions = [0.25, 0.5, 0.75, 1];

  const psiStatus = metricTone('lower', currentModel.metrics.psi, currentModel.metrics.psiThreshold);
  const decileMax = deciles
    ? Math.max(1, ...deciles.flatMap((d) => [d.expected, d.actual]))
    : 1;
  const psiDomain = Math.max(currentModel.metrics.psiThreshold * 2, currentModel.metrics.psi);
  const psiPct = Math.min(100, (currentModel.metrics.psi / psiDomain) * 100);
  const thresholdPct = (currentModel.metrics.psiThreshold / psiDomain) * 100;

  const headerStatus = currentModel.status;

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <header className="sleek-card p-6 md:p-8">
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-3 flex-wrap">
              <span className="inline-flex items-center gap-1.5 text-[11px] font-bold text-indigo-600 uppercase tracking-wider">
                <Sparkles className="w-3.5 h-3.5" />
                Active Audit Dossier
              </span>
              <span
                className={`inline-flex items-center px-2.5 py-0.5 rounded-full border text-[10px] font-bold uppercase tracking-wider ${statusPill(headerStatus)}`}
              >
                {headerStatus}
              </span>
            </div>

            <h1 className="font-display text-2xl md:text-3xl font-bold text-slate-900 tracking-tight mt-2">
              {currentModel.name}
            </h1>
            <p className="text-sm text-slate-500 font-medium mt-1">{currentModel.version}</p>

            <dl className="mt-5 grid grid-cols-1 sm:grid-cols-3 gap-x-8 gap-y-3 max-w-2xl">
              <div>
                <dt className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                  Model Type & Algorithm
                </dt>
                <dd className="text-sm font-bold text-slate-900 mt-0.5">
                  {currentModel.type} · {currentModel.algorithm}
                </dd>
              </div>
              <div>
                <dt className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                  Target Portfolio
                </dt>
                <dd className="text-sm font-bold text-slate-900 mt-0.5">{currentModel.portfolio}</dd>
              </div>
              <div>
                <dt className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                  Last Audit Run
                </dt>
                <dd className="text-sm font-bold text-slate-900 mt-0.5">
                  {currentModel.lastAnalyzed}
                </dd>
              </div>
            </dl>

            {currentModel.description && (
              <p className="mt-5 text-sm text-slate-600 leading-relaxed max-w-3xl">
                {currentModel.description}
              </p>
            )}
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={onNavigateToCompare}
              className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl border border-slate-200 bg-white text-xs font-bold text-slate-700 hover:text-indigo-700 hover:border-indigo-300 transition-colors cursor-pointer"
            >
              <GitCompareArrows className="w-3.5 h-3.5" />
              Compare
            </button>
            <button
              type="button"
              onClick={onExportReport}
              className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold shadow-sm shadow-indigo-200 transition-colors cursor-pointer active:scale-95"
            >
              <Download className="w-3.5 h-3.5" />
              Export Report
            </button>
          </div>
        </div>
      </header>

      {/* Tabs + content */}
      <div className="sleek-card overflow-hidden flex flex-col">
        <div className="flex items-center border-b border-slate-100 px-4 bg-slate-50/50 overflow-x-auto">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={`py-3.5 px-4 text-xs font-bold whitespace-nowrap transition-colors cursor-pointer border-b-2 ${
                tab === t.key
                  ? 'text-indigo-600 border-indigo-600'
                  : 'text-slate-500 hover:text-slate-900 border-transparent'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="flex-1 p-6 md:p-8">
          {tab === 'metrics' && (
            <div className="flex flex-col gap-6">
              {/* Metric cards */}
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
                {metricCards.map((metric) => (
                  <div
                    key={metric.key}
                    className="bg-slate-50/70 border border-slate-200 rounded-2xl p-5 hover:border-indigo-300 transition-all shadow-xs"
                  >
                    <div className="flex justify-between items-start mb-2">
                      <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                        {metric.label}
                      </span>
                      <span
                        className={`text-[10px] font-bold px-2 py-0.5 rounded-full border uppercase tracking-wider ${statusPill(metric.tone)}`}
                      >
                        {metric.tone}
                      </span>
                    </div>
                    <div className="text-3xl font-bold text-slate-900 tracking-tight">
                      {metric.display}
                    </div>
                    <div className="text-xs text-slate-500 font-medium mt-1">{metric.note}</div>
                  </div>
                ))}
              </div>

              {/* Charts */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* ROC */}
                <div className="bg-slate-50/70 border border-slate-200 rounded-2xl p-6 flex flex-col shadow-xs">
                  <div className="flex justify-between items-center mb-4">
                    <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wider">
                      Discriminatory Power (ROC Curve)
                    </h3>
                    <span className="text-xs text-indigo-600 font-bold font-mono bg-indigo-50 px-2 py-0.5 rounded-md">
                      AUC = {fmt(currentModel.metrics.auc, 3)}
                    </span>
                  </div>

                  <div className="flex-1 flex items-center justify-center">
                    <svg
                      viewBox={`0 0 ${PLOT.w} ${PLOT.h}`}
                      className="w-full h-56"
                      role="img"
                      aria-label="ROC curve reconstructed from AUC"
                    >
                      {gridFractions.map((f) => (
                        <g key={f}>
                          <line
                            x1={sx(0)}
                            y1={sy(f)}
                            x2={sx(1)}
                            y2={sy(f)}
                            stroke="#e2e8f0"
                            strokeDasharray="3 3"
                          />
                          <line
                            x1={sx(f)}
                            y1={sy(0)}
                            x2={sx(f)}
                            y2={sy(1)}
                            stroke="#e2e8f0"
                            strokeDasharray="3 3"
                          />
                        </g>
                      ))}

                      <line x1={sx(0)} y1={sy(0)} x2={sx(1)} y2={sy(0)} stroke="#94a3b8" strokeWidth="1.5" />
                      <line x1={sx(0)} y1={sy(0)} x2={sx(0)} y2={sy(1)} stroke="#94a3b8" strokeWidth="1.5" />

                      <line
                        x1={sx(0)}
                        y1={sy(0)}
                        x2={sx(1)}
                        y2={sy(1)}
                        stroke="#cbd5e1"
                        strokeWidth="1.5"
                        strokeDasharray="4 4"
                      />

                      <path d={rocArea} fill="rgba(79, 70, 229, 0.08)" />
                      <path
                        d={rocLine}
                        fill="none"
                        stroke="#4f46e5"
                        strokeWidth="2.5"
                        strokeLinejoin="round"
                        strokeLinecap="round"
                      />
                    </svg>
                  </div>

                  <div className="flex justify-between items-center text-[11px] text-slate-400 mt-2 pt-2 border-t border-slate-200">
                    <span>False Positive Rate</span>
                    <span className="font-medium">reconstructed from AUC (binormal)</span>
                    <span>True Positive Rate</span>
                  </div>
                </div>

                {/* PSI panel */}
                <div className="bg-slate-50/70 border border-slate-200 rounded-2xl p-6 flex flex-col shadow-xs">
                  <div className="flex justify-between items-center mb-4">
                    <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wider">
                      Population Distribution (Expected vs Actual)
                    </h3>
                    <span className="text-xs text-slate-500 font-bold">{fmt(currentModel.metrics.psi, 3)} PSI</span>
                  </div>

                  {decilesLoading ? (
                    <div className="flex-1 flex items-center justify-center min-h-[200px] text-slate-400">
                      <Loader2 className="w-5 h-5 animate-spin" />
                      <span className="ml-2 text-xs font-semibold">Loading decile distribution…</span>
                    </div>
                  ) : deciles && deciles.length > 0 ? (
                    <>
                      <div className="flex items-center gap-4 text-[11px] font-medium mb-4">
                        <div className="flex items-center space-x-1.5">
                          <span className="w-2.5 h-2.5 rounded-sm bg-slate-300" />
                          <span className="text-slate-500">Expected</span>
                        </div>
                        <div className="flex items-center space-x-1.5">
                          <span className="w-2.5 h-2.5 rounded-sm bg-indigo-600" />
                          <span className="text-slate-700 font-semibold">Actual</span>
                        </div>
                      </div>

                      <div className="flex items-end justify-between gap-2 flex-1 min-h-[180px]">
                        {deciles.map((d) => (
                          <div key={d.decile} className="flex-1 flex flex-col items-center gap-1.5">
                            <div className="w-full h-36 flex items-end justify-center gap-1">
                              <div
                                style={{ height: `${(d.expected / decileMax) * 100}%` }}
                                className="w-2.5 rounded-t-sm bg-slate-300"
                                title={`Expected: ${fmt(d.expected, 2)}%`}
                              />
                              <div
                                style={{ height: `${(d.actual / decileMax) * 100}%` }}
                                className="w-2.5 rounded-t-sm bg-indigo-600"
                                title={`Actual: ${fmt(d.actual, 2)}%`}
                              />
                            </div>
                            <span className="text-[10px] text-slate-500 font-bold whitespace-nowrap">
                              {d.decile}
                            </span>
                          </div>
                        ))}
                      </div>

                      <div className="mt-4 overflow-x-auto border-t border-slate-200 pt-3">
                        <table className="w-full text-left text-xs">
                          <thead>
                            <tr className="text-slate-400 uppercase tracking-wider text-[10px]">
                              <th className="py-1 pr-4 font-bold">Decile</th>
                              <th className="py-1 pr-4 font-bold">Expected (%)</th>
                              <th className="py-1 font-bold">Actual (%)</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-100">
                            {deciles.map((d) => (
                              <tr key={d.decile}>
                                <td className="py-1.5 pr-4 text-slate-700 font-semibold">{d.decile}</td>
                                <td className="py-1.5 pr-4 text-slate-600">{fmt(d.expected, 2)}</td>
                                <td className="py-1.5 text-slate-600">{fmt(d.actual, 2)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </>
                  ) : (
                    <div className="flex-1 flex flex-col justify-center min-h-[200px]">
                      <div className="flex justify-between text-xs font-semibold mb-2">
                        <span className="text-slate-500">Population Stability Index (PSI)</span>
                        <span className={`font-bold ${
                          toneFill(psiStatus) === '#10b981'
                            ? 'text-emerald-600'
                            : toneFill(psiStatus) === '#f59e0b'
                              ? 'text-amber-600'
                              : 'text-rose-600'
                        }`}>
                          {fmt(currentModel.metrics.psi, 3)}
                        </span>
                      </div>

                      <div className="relative h-3 bg-slate-100 rounded-full overflow-hidden">
                        <div
                          className="absolute inset-y-0 left-0 rounded-full"
                          style={{ width: `${psiPct}%`, backgroundColor: toneFill(psiStatus) }}
                        />
                        <div
                          className="absolute top-0 bottom-0 w-0.5 bg-slate-400"
                          style={{ left: `${thresholdPct}%` }}
                          title={`Threshold ${fmt(currentModel.metrics.psiThreshold, 3)}`}
                        />
                      </div>

                      <div className="flex justify-between text-[11px] text-slate-400 mt-1.5">
                        <span>0</span>
                        <span>Breach threshold &lt; {fmt(currentModel.metrics.psiThreshold, 3)}</span>
                      </div>

                      <div className="mt-4 flex items-start gap-2 p-3 rounded-xl bg-slate-100 border border-slate-200 text-xs text-slate-600 leading-relaxed">
                        <AlertTriangle className="w-4 h-4 text-slate-400 shrink-0 mt-0.5" />
                        <span>
                          Decile distribution unavailable
                          {decilesFailed ? ' (could not load population deciles).' : '.'} Showing PSI
                          scalar against your configured threshold.
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {tab === 'gap' && (
            <div className="flex flex-col gap-8 w-full items-center">
              <div className="flex flex-col items-center">
                <div className="relative w-44 h-44 rounded-full bg-slate-100 flex items-center justify-center">
                  <div
                    className="absolute inset-0 rounded-full"
                    style={{
                      background: `conic-gradient(#4f46e5 ${currentModel.gapAnalysis.overallCompliance * 3.6}deg, #e2e8f0 0deg)`,
                    }}
                  />
                  <div className="relative w-36 h-36 bg-white rounded-full flex flex-col items-center justify-center shadow-md z-10">
                    <span className="text-4xl font-bold text-slate-900">
                      {currentModel.gapAnalysis.overallCompliance}%
                    </span>
                    <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider text-center mt-1 leading-tight">
                      Overall
                      <br />
                      Compliance
                    </span>
                  </div>
                </div>

                <div className="w-64 mt-6">
                  <div className="h-3 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-indigo-600 rounded-full transition-all"
                      style={{ width: `${currentModel.gapAnalysis.overallCompliance}%` }}
                    />
                  </div>
                </div>
              </div>

              {currentModel.gapAnalysis.requirements.length > 0 ? (
                <div className="w-full max-w-2xl bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
                  <div className="p-4 bg-slate-50 border-b border-slate-200 text-xs font-bold uppercase tracking-wider text-slate-500">
                    Institutional Audit Requirements Matrix
                  </div>
                  <div className="divide-y divide-slate-100">
                    {currentModel.gapAnalysis.requirements.map((req) => (
                      <div key={req.id} className="p-5 hover:bg-slate-50/70 transition-colors flex flex-col gap-2">
                        <div className="flex justify-between items-center gap-3">
                          <div className="flex items-center space-x-3">
                            <span className="material-symbols-outlined text-indigo-600 text-xl">
                              {req.icon}
                            </span>
                            <span className="text-sm font-bold text-slate-900">{req.title}</span>
                          </div>
                          <span
                            className={`text-[10px] font-bold px-3 py-0.5 rounded-full border uppercase tracking-wider shrink-0 ${statusPill(req.status)}`}
                          >
                            {req.status}
                          </span>
                        </div>
                        <p className="text-xs text-slate-600 pl-8 leading-relaxed">{req.details}</p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="w-full max-w-2xl flex flex-col items-center justify-center p-10 text-center bg-slate-50 border border-slate-200 rounded-2xl">
                  <FileText className="w-8 h-8 text-slate-300" />
                  <p className="mt-3 text-sm font-semibold text-slate-600">No gap-analysis requirements yet</p>
                  <p className="mt-1 text-xs text-slate-400">
                    Upload and analyze a validation document to populate the requirements matrix.
                  </p>
                </div>
              )}
            </div>
          )}

          {tab === 'documents' && (
            <DocumentViewer
              modelVersionId={currentModel.currentVersionId}
              initialDocumentId={activeDocumentId}
            />
          )}

          {tab === 'analyst' && (
            <div className="flex flex-col h-[520px]">
              <div className="flex-1 overflow-y-auto space-y-4 pr-2">
                {messages.length === 0 && (
                  <div className="flex flex-col items-center justify-center text-center py-8">
                    <div className="w-12 h-12 rounded-2xl bg-indigo-600 text-white flex items-center justify-center shadow-md shadow-indigo-200 mb-4">
                      <Sparkles className="w-6 h-6" />
                    </div>
                    <h3 className="text-sm font-bold text-slate-900">AI Analyst</h3>
                    <p className="mt-1 text-xs text-slate-500 max-w-md leading-relaxed">
                      Ask questions about {currentModel.name}. Responses stream from the institutional
                      document and regulatory corpus, with sources and recommended actions.
                    </p>
                  </div>
                )}

                {messages.map((msg) => (
                  <div
                    key={msg.id}
                    className={`flex gap-3 ${msg.sender === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    {msg.sender === 'ai' && (
                      <div className="w-8 h-8 rounded-xl bg-indigo-600 text-white flex items-center justify-center shrink-0 shadow-sm shadow-indigo-200 mt-1">
                        <Sparkles className="w-4 h-4 text-white" />
                      </div>
                    )}

                    <div className="max-w-[85%] space-y-2">
                      <div
                        className={`p-4 rounded-2xl shadow-xs text-xs leading-relaxed ${
                          msg.sender === 'user'
                            ? 'bg-indigo-600 text-white rounded-tr-xs shadow-md shadow-indigo-100'
                            : msg.isHighlighted
                              ? 'bg-indigo-50/60 border border-indigo-100 text-slate-900 rounded-tl-xs'
                              : 'bg-slate-50 border border-slate-200 text-slate-900 rounded-tl-xs'
                        }`}
                      >
                        {msg.content ? (
                          <div className="whitespace-pre-line">{msg.content}</div>
                        ) : (
                          <div className="flex items-center gap-2 text-slate-400">
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            <span>Analyzing model &amp; regulatory context…</span>
                          </div>
                        )}

                        {msg.sources && msg.sources.length > 0 && (
                          <div className="mt-3 pt-3 border-t border-slate-200/60 flex flex-wrap items-center gap-2">
                            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mr-1 block w-full">
                              Sources &amp; Rules:
                            </span>
                            {msg.sources.map((source, idx) => (
                              <button
                                key={`${source.title}-${idx}`}
                                type="button"
                                onClick={() => onOpenRegulatoryStandard(source.title)}
                                className="flex items-center space-x-1 px-2.5 py-1 rounded-full bg-white border border-slate-200 text-xs font-bold text-slate-800 hover:border-indigo-300 transition-colors cursor-pointer shadow-xs"
                              >
                                <BookOpen className="w-3 h-3 text-indigo-600" />
                                <span>
                                  {source.title}
                                  {source.ref ? ` — ${source.ref}` : ''}
                                </span>
                              </button>
                            ))}
                          </div>
                        )}
                      </div>

                      {msg.suggestedActions && msg.suggestedActions.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 pt-1">
                          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider w-full pl-1">
                            Recommended Actions:
                          </span>
                          {msg.suggestedActions.map((action, idx) => (
                            <button
                              key={`${action}-${idx}`}
                              type="button"
                              onClick={() => handleSend(action)}
                              disabled={streaming}
                              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-full bg-white border border-slate-200 hover:border-indigo-300 hover:bg-indigo-50 text-xs font-semibold text-slate-700 transition-all shadow-xs cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              <Sparkles className="w-3 h-3 text-indigo-600" />
                              <span>{action}</span>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))}

                <div ref={chatEndRef} />
              </div>

              <div className="pt-4 border-t border-slate-100 shrink-0 space-y-3">
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => handleSend('Run gap analysis on this model')}
                    disabled={streaming}
                    className="px-3 py-1 rounded-full bg-slate-100 hover:bg-indigo-50 hover:text-indigo-700 hover:border-indigo-200 border border-slate-200 text-xs font-semibold text-slate-700 transition-colors shadow-xs cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Run Gap Analysis
                  </button>
                  <button
                    type="button"
                    onClick={() => handleSend('Extract key performance metrics')}
                    disabled={streaming}
                    className="px-3 py-1 rounded-full bg-slate-100 hover:bg-indigo-50 hover:text-indigo-700 hover:border-indigo-200 border border-slate-200 text-xs font-semibold text-slate-700 transition-colors shadow-xs cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Extract Metrics
                  </button>
                  <button
                    type="button"
                    onClick={() => handleSend('Summarize methodology and sample observation')}
                    disabled={streaming}
                    className="px-3 py-1 rounded-full bg-slate-100 hover:bg-indigo-50 hover:text-indigo-700 hover:border-indigo-200 border border-slate-200 text-xs font-semibold text-slate-700 transition-colors shadow-xs cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Summarize Methodology
                  </button>
                </div>

                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    handleSend();
                  }}
                  className="relative flex items-center bg-slate-100 rounded-full border border-slate-200 px-3 py-1.5 focus-within:ring-2 focus-within:ring-indigo-600/30 transition-all"
                >
                  <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="Ask about this model or request an analysis..."
                    className="flex-1 bg-transparent border-none outline-none px-2 text-xs text-slate-900 placeholder:text-slate-400"
                  />
                  <button
                    type="submit"
                    disabled={!input.trim() || streaming}
                    className={`w-8 h-8 rounded-full flex items-center justify-center transition-colors cursor-pointer ${
                      input.trim() && !streaming
                        ? 'bg-indigo-600 text-white shadow-sm'
                        : 'bg-slate-200 text-slate-400 cursor-not-allowed'
                    }`}
                    title="Send message"
                  >
                    <Send className="w-3.5 h-3.5" />
                  </button>
                </form>
              </div>
            </div>
          )}

          {tab === 'citations' && (
            <div className="space-y-3">
              {latestCitationMessage?.sources && latestCitationMessage.sources.length > 0 ? (
                <>
                  <p className="text-xs text-slate-400 font-medium">
                    Sources &amp; rules cited by the most recent AI Analyst response.
                  </p>
                  {latestCitationMessage.sources.map((source, idx) => (
                    <button
                      key={`${source.title}-${idx}`}
                      type="button"
                      onClick={() => onOpenRegulatoryStandard(source.title)}
                      className="w-full flex items-start gap-3 p-4 bg-slate-50 border border-slate-200 rounded-2xl hover:border-indigo-300 transition-colors text-left cursor-pointer"
                    >
                      <div className="w-8 h-8 rounded-lg bg-indigo-50 border border-indigo-100 flex items-center justify-center shrink-0">
                        <BookOpen className="w-4 h-4 text-indigo-600" />
                      </div>
                      <div className="min-w-0">
                        <span className="text-sm font-bold text-slate-900 block">{source.title}</span>
                        {source.ref && (
                          <span className="text-xs text-slate-500 font-medium">{source.ref}</span>
                        )}
                      </div>
                    </button>
                  ))}
                </>
              ) : (
                <div className="flex flex-col items-center justify-center p-12 text-center bg-slate-50 border border-slate-200 rounded-2xl">
                  <FileText className="w-8 h-8 text-slate-300" />
                  <p className="mt-3 text-sm font-semibold text-slate-600">No citations yet</p>
                  <p className="mt-1 text-xs text-slate-400">
                    Ask the AI Analyst a question to surface cited sources and regulatory rules here.
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}