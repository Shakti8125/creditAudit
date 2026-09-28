import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type {
  ChatMessage,
  ChatSource,
  DocumentMeta,
  LlmGapAnalysis,
  ModelSummary,
  PopulationDecile,
  WorkspaceTab,
} from '@/types';
import {
  AlertTriangle,
  BookOpen,
  Download,
  FileText,
  GitCompareArrows,
  Loader2,
  MessageSquarePlus,
  RefreshCw,
  Send,
  Sparkles,
} from 'lucide-react';
import {
  getChatMessages,
  getDocument,
  getPopulationDeciles,
  listChatSessions,
  listDocuments,
  runGapAnalysis,
} from '@/lib/api';
import {
  parseTimestamp,
  toChatMessage,
  toChatSessionSummary,
  toChatSource,
  toDocumentDetail,
  toDocumentMeta,
  toLlmGapAnalysis,
} from '@/lib/adapters';
import { streamQuery } from '@/lib/sse';
import DocumentViewer from '@/components/DocumentViewer';
import FeedbackControl from '@/components/rag/FeedbackControl';

interface WorkspaceViewProps {
  currentModel: ModelSummary;
  tab: WorkspaceTab;
  onTabChange: (tab: WorkspaceTab) => void;
  /**
   * Document to preselect in the Documents tab (just uploaded, or opened from a
   * citation / search result). The AI Analyst is scoped to it when it belongs to
   * the current version.
   */
  activeDocumentId?: string | null;
  onExportReport: () => void;
  onNavigateToCompare: () => void;
  /** Opens the Regulatory Library focused on a citation source / standard code. */
  onOpenRegulatoryStandard: (query: string) => void;
  onOpenDocument: (documentId: string) => void;
  /** Reports the AI Analyst session in use (for the Privacy Inspector). */
  onSessionIdChange: (sessionId: string | null) => void;
  /** Called after a document of this model was deleted. */
  onDocumentsChanged: () => void;
}

const TABS: { key: WorkspaceTab; label: string }[] = [
  { key: 'metrics', label: 'Metrics' },
  { key: 'gap', label: 'Gap Analysis' },
  { key: 'documents', label: 'Documents' },
  { key: 'analyst', label: 'AI Analyst' },
  { key: 'citations', label: 'Citations' },
];

type MetricKey = 'gini' | 'auc' | 'ks' | 'psi';

/** Headline metric cards; `policyName` is the backend PolicyChecker metric_name. */
const METRIC_CARDS: {
  key: MetricKey;
  label: string;
  policyName: string;
  format: (value: number) => string;
}[] = [
  { key: 'gini', label: 'Gini Coefficient', policyName: 'Gini Coefficient', format: (v) => `${fmt(v, 1)}%` },
  { key: 'auc', label: 'AUC', policyName: 'AUC', format: (v) => fmt(v, 3) },
  { key: 'ks', label: 'KS Statistic', policyName: 'KS Statistic', format: (v) => `${fmt(v, 1)}%` },
  { key: 'psi', label: 'Population Stability', policyName: 'PSI', format: (v) => fmt(v, 3) },
];

function fmt(value: number, decimals: number): string {
  return value.toFixed(decimals).replace(/\.?0+$/, '');
}

function prettyThreshold(threshold: string): string {
  return threshold.replace('>=', '≥').replace('<=', '≤');
}

/** Formats a policy result value; percentage-scaled metrics carry a % threshold. */
function formatPolicyValue(value: number, threshold: string): string {
  return threshold.includes('%') ? `${fmt(value, 1)}%` : fmt(value, 3);
}

function statusPill(status: string): string {
  if (status === 'PASS') return 'bg-emerald-50 border-emerald-200 text-emerald-700';
  if (status === 'WARNING') return 'bg-amber-50 border-amber-200 text-amber-700';
  if (status === 'PENDING' || status === 'N/A') return 'bg-slate-100 border-slate-200 text-slate-500';
  return 'bg-rose-50 border-rose-200 text-rose-700';
}

function statusFill(status?: string): string {
  if (status === 'PASS') return 'bg-emerald-500';
  if (status === 'WARNING') return 'bg-amber-500';
  if (status === 'BREACH') return 'bg-rose-500';
  return 'bg-slate-400';
}

function statusText(status?: string): string {
  if (status === 'PASS') return 'text-emerald-600';
  if (status === 'WARNING') return 'text-amber-600';
  if (status === 'BREACH') return 'text-rose-600';
  return 'text-slate-600';
}

interface ChatMessageBubbleProps {
  message: ChatMessage;
  sourceLabel: (source: ChatSource) => string;
  onOpenSource: (source: ChatSource) => void;
}

/** Renders one chat message; all assistant-message UI lives here. */
function ChatMessageBubble({ message, sourceLabel, onOpenSource }: ChatMessageBubbleProps) {
  const isUser = message.sender === 'user';
  return (
    <div className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div className="w-8 h-8 rounded-xl bg-indigo-600 text-white flex items-center justify-center shrink-0 shadow-sm shadow-indigo-200 mt-1">
          <Sparkles className="w-4 h-4 text-white" />
        </div>
      )}

      <div className="max-w-[85%] space-y-1">
        <div
          className={`p-4 rounded-2xl shadow-xs text-xs leading-relaxed ${
            isUser
              ? 'bg-indigo-600 text-white rounded-tr-xs shadow-md shadow-indigo-100'
              : message.isHighlighted
                ? 'bg-indigo-50/60 border border-indigo-100 text-slate-900 rounded-tl-xs'
                : 'bg-slate-50 border border-slate-200 text-slate-900 rounded-tl-xs'
          }`}
        >
          {message.content ? (
            <div className="whitespace-pre-line">{message.content}</div>
          ) : (
            <div className="flex items-center gap-2 text-slate-400">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              <span>Analyzing model &amp; regulatory context…</span>
            </div>
          )}

          {message.sources && message.sources.length > 0 && (
            <div className="mt-3 pt-3 border-t border-slate-200/60 flex flex-wrap items-center gap-2">
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mr-1 block w-full">
                Sources &amp; Rules:
              </span>
              {message.sources.map((source, idx) => (
                <button
                  key={`${source.title}-${idx}`}
                  type="button"
                  onClick={() => onOpenSource(source)}
                  className="flex items-center space-x-1 px-2.5 py-1 rounded-full bg-white border border-slate-200 text-xs font-bold text-slate-800 hover:border-indigo-300 transition-colors cursor-pointer shadow-xs"
                >
                  <BookOpen className="w-3 h-3 text-indigo-600" />
                  <span>
                    {sourceLabel(source)}
                    {source.ref ? ` — ${source.ref}` : ''}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
        {message.timestamp && (
          <p className={`text-[10px] text-slate-400 ${isUser ? 'text-right pr-1' : 'pl-1'}`}>
            {message.timestamp}
          </p>
        )}
        {!isUser && message.traceId && message.timestamp && !message.isError && (
          <div className="pl-1">
            <FeedbackControl traceId={message.traceId} compact />
          </div>
        )}
      </div>
    </div>
  );
}

export default function WorkspaceView({
  currentModel,
  tab,
  onTabChange,
  activeDocumentId,
  onExportReport,
  onNavigateToCompare,
  onOpenRegulatoryStandard,
  onOpenDocument,
  onSessionIdChange,
  onDocumentsChanged,
}: WorkspaceViewProps) {
  const versionId = currentModel.currentVersionId;

  const [deciles, setDeciles] = useState<PopulationDecile[] | null>(null);
  const [decilesLoading, setDecilesLoading] = useState(true);
  const [decilesFailed, setDecilesFailed] = useState(false);

  // Documents of the current version (latest analyzed document drives gap analysis & chat scope).
  const [versionDocs, setVersionDocs] = useState<DocumentMeta[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [docsError, setDocsError] = useState<string | null>(null);
  const [docsReloadKey, setDocsReloadKey] = useState(0);

  // AI gap analysis of the latest document.
  const [llmGap, setLlmGap] = useState<LlmGapAnalysis | null>(null);
  const [llmGapDocId, setLlmGapDocId] = useState<string | null>(null);
  const [llmGapLoading, setLlmGapLoading] = useState(false);
  const [llmGapLoadError, setLlmGapLoadError] = useState<string | null>(null);
  const [llmGapRunning, setLlmGapRunning] = useState(false);
  const [llmGapRunError, setLlmGapRunError] = useState<string | null>(null);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
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
    if (!versionId) {
      setVersionDocs([]);
      setDocsLoading(false);
      return;
    }
    let cancelled = false;
    setDocsLoading(true);
    setDocsError(null);
    listDocuments()
      .then((dto) => {
        if (cancelled) return;
        const raw = Array.isArray(dto) ? dto : (dto?.documents ?? []);
        setVersionDocs(
          (raw as unknown[]).map(toDocumentMeta).filter((d) => d.modelVersionId === versionId),
        );
      })
      .catch((err) => {
        if (cancelled) return;
        setVersionDocs([]);
        setDocsError(err instanceof Error ? err.message : 'Unable to load documents');
      })
      .finally(() => {
        if (!cancelled) setDocsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [versionId, docsReloadKey]);

  // Resume the most recent AI Analyst conversation for this model version.
  useEffect(() => {
    if (!versionId) {
      setHistoryLoading(false);
      return;
    }
    let cancelled = false;
    setHistoryLoading(true);
    setHistoryError(null);
    (async () => {
      try {
        const sessions = await listChatSessions(versionId);
        const latest = Array.isArray(sessions) && sessions.length > 0
          ? toChatSessionSummary(sessions[0])
          : null;
        if (!latest || cancelled) return;
        const raw = await getChatMessages(latest.id);
        if (cancelled) return;
        setMessages((Array.isArray(raw) ? raw : []).map(toChatMessage));
        setSessionId(latest.id);
      } catch (err) {
        if (!cancelled) {
          setHistoryError(
            err instanceof Error ? err.message : 'Unable to load the previous conversation',
          );
        }
      } finally {
        if (!cancelled) setHistoryLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [versionId]);

  useEffect(() => {
    onSessionIdChange(sessionId);
  }, [sessionId, onSessionIdChange]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, streaming]);

  const latestDoc = useMemo(() => {
    const ready = versionDocs.filter((d) => d.status === 'READY');
    ready.sort((a, b) => parseTimestamp(b.uploadTime) - parseTimestamp(a.uploadTime));
    return ready[0] ?? null;
  }, [versionDocs]);
  const latestDocId = latestDoc?.id ?? null;

  // The document the AI Analyst answers from: an explicitly opened document of this
  // version, else the backend falls back to the latest analyzed one.
  const activeVersionDoc =
    versionDocs.find((d) => d.id === activeDocumentId && d.status === 'READY') ?? null;
  const chatDocument = activeVersionDoc ?? latestDoc;

  // Load the persisted AI gap analysis of the latest document when the Gap tab is opened.
  useEffect(() => {
    if (tab !== 'gap' || !latestDocId || llmGapRunning || llmGapDocId === latestDocId) return;
    let cancelled = false;
    setLlmGapLoading(true);
    setLlmGapLoadError(null);
    getDocument(latestDocId)
      .then((dto) => {
        if (cancelled) return;
        setLlmGap(toDocumentDetail(dto).llmGapAnalysis);
        setLlmGapDocId(latestDocId);
      })
      .catch((err) => {
        if (!cancelled) {
          setLlmGapLoadError(err instanceof Error ? err.message : 'Unable to load gap analysis');
        }
      })
      .finally(() => {
        if (!cancelled) setLlmGapLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tab, latestDocId, llmGapRunning, llmGapDocId]);

  const currentLlmGap = latestDocId && llmGapDocId === latestDocId ? llmGap : null;

  const handleRunGapAnalysis = async () => {
    if (!latestDocId || llmGapRunning) return;
    onTabChange('gap');
    setLlmGapRunning(true);
    setLlmGapRunError(null);
    // A run supersedes an in-flight load of the persisted analysis (whose effect is
    // cancelled and would otherwise leave the loading spinner on forever).
    setLlmGapLoading(false);
    setLlmGapLoadError(null);
    try {
      const dto = await runGapAnalysis(latestDocId);
      setLlmGap(toLlmGapAnalysis(dto));
      setLlmGapDocId(latestDocId);
    } catch (err) {
      setLlmGapRunError(err instanceof Error ? err.message : 'Unable to run gap analysis');
    } finally {
      setLlmGapRunning(false);
    }
  };

  const resolveSourceDocumentId = useCallback(
    (source: ChatSource): string | null => {
      if (source.title.startsWith('doc-')) return source.title.slice(4);
      return versionDocs.find((d) => d.filename === source.title)?.id ?? null;
    },
    [versionDocs],
  );

  const sourceLabel = (source: ChatSource): string => {
    const docId = resolveSourceDocumentId(source);
    if (!docId) return source.title;
    return versionDocs.find((d) => d.id === docId)?.filename ?? source.title;
  };

  const openSource = (source: ChatSource) => {
    const docId = resolveSourceDocumentId(source);
    if (docId) {
      onOpenDocument(docId);
    } else {
      onOpenRegulatoryStandard(source.ref ? `${source.title} (${source.ref})` : source.title);
    }
  };

  const latestCitationMessage = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const msg = messages[i];
      if (msg.sender === 'ai' && msg.sources && msg.sources.length > 0) {
        return msg;
      }
    }
    return null;
  }, [messages]);

  const policyByName = new Map(currentModel.policyResults.map((r) => [r.metricName, r]));
  const psiResult = policyByName.get('PSI');

  const handleSend = async (textOverride?: string) => {
    const text = (textOverride ?? input).trim();
    if (!text || streaming || historyLoading) return;
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

    let pendingSources: ChatSource[] = [];
    let pendingTraceId: string | undefined;

    const pushError = (message: string) => {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === aiId
            ? {
                ...m,
                content: m.content
                  ? `${m.content}\n\n[Response interrupted: ${message}]`
                  : `Unable to complete analysis: ${message}`,
                timestamp: 'Just now',
                traceId: m.traceId ?? pendingTraceId,
                isError: true,
              }
            : m,
        ),
      );
    };

    try {
      await streamQuery(
        {
          question: text,
          documentId: activeVersionDoc?.id,
          modelVersionId: versionId,
          sessionId: sessionId ?? undefined,
        },
        {
          onSessionId: (id) => {
            if (id) setSessionId(id);
          },
          onTrace: (id) => {
            pendingTraceId = id;
          },
          onCitations: (citations) => {
            pendingSources = (citations ?? []).map(toChatSource);
          },
          onToken: (token) => {
            setMessages((prev) =>
              prev.map((m) => (m.id === aiId ? { ...m, content: m.content + token } : m)),
            );
          },
          onDone: () => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === aiId
                  ? {
                      ...m,
                      content: m.content || 'No answer was generated. Please try rephrasing the question.',
                      timestamp: 'Just now',
                      sources: pendingSources,
                      isHighlighted: true,
                      traceId: pendingTraceId,
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

  const startNewConversation = () => {
    setMessages([]);
    setSessionId(null);
    setHistoryError(null);
  };

  const { psi, psiWarningThreshold, psiBreachThreshold } = currentModel.metrics;
  const decileMax = deciles
    ? Math.max(1, ...deciles.flatMap((d) => [d.expected, d.actual]))
    : 1;
  const psiDomain = Math.max(psiBreachThreshold * 1.5, psi ?? 0);
  const psiPct = psi != null ? Math.min(100, (psi / psiDomain) * 100) : 0;
  const warnPct = (psiWarningThreshold / psiDomain) * 100;
  const breachPct = (psiBreachThreshold / psiDomain) * 100;

  const quickActionClass =
    'px-3 py-1 rounded-full bg-slate-100 hover:bg-indigo-50 hover:text-indigo-700 hover:border-indigo-200 border border-slate-200 text-xs font-semibold text-slate-700 transition-colors shadow-xs cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed';

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
                className={`inline-flex items-center px-2.5 py-0.5 rounded-full border text-[10px] font-bold uppercase tracking-wider ${statusPill(currentModel.status)}`}
              >
                {currentModel.status}
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
                  Last Analyzed Document
                </dt>
                <dd className="text-sm font-bold text-slate-900 mt-0.5">
                  {currentModel.lastAnalyzed ?? 'None yet'}
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
              onClick={() => onTabChange(t.key)}
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
              {/* Metric cards: value, status and threshold come from the backend policy check */}
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
                {METRIC_CARDS.map((card) => {
                  const result = policyByName.get(card.policyName);
                  const value = result?.value ?? currentModel.metrics[card.key];
                  const tone = result?.status ?? (value == null ? 'N/A' : null);
                  return (
                    <div
                      key={card.key}
                      className="bg-slate-50/70 border border-slate-200 rounded-2xl p-5 hover:border-indigo-300 transition-all shadow-xs"
                    >
                      <div className="flex justify-between items-start mb-2">
                        <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                          {card.label}
                        </span>
                        {tone && (
                          <span
                            className={`text-[10px] font-bold px-2 py-0.5 rounded-full border uppercase tracking-wider ${statusPill(tone)}`}
                          >
                            {tone}
                          </span>
                        )}
                      </div>
                      {value == null ? (
                        <div className="text-lg font-bold text-slate-400 tracking-tight py-1.5">
                          Not reported
                        </div>
                      ) : (
                        <div className="text-3xl font-bold text-slate-900 tracking-tight">
                          {card.format(value)}
                        </div>
                      )}
                      <div className="text-xs text-slate-500 font-medium mt-1">
                        {result
                          ? `Threshold ${prettyThreshold(result.threshold)}`
                          : value == null
                            ? 'Not found in analyzed documents'
                            : 'Not scored by policy check'}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Population stability */}
              <div className="bg-slate-50/70 border border-slate-200 rounded-2xl p-6 flex flex-col shadow-xs">
                <div className="flex justify-between items-center mb-4">
                  <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wider">
                    Population Distribution (Expected vs Actual)
                  </h3>
                  <span className="text-xs text-slate-500 font-bold">
                    {psi != null ? `${fmt(psi, 3)} PSI` : 'PSI not reported'}
                  </span>
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
                ) : psi == null ? (
                  <div className="flex-1 flex items-center gap-2 min-h-[120px] p-3 rounded-xl bg-slate-100 border border-slate-200 text-xs text-slate-600">
                    <AlertTriangle className="w-4 h-4 text-slate-400 shrink-0" />
                    <span>
                      No population stability data yet
                      {decilesFailed ? ' (could not load population deciles)' : ''}. Upload a
                      validation document that reports PSI or a decile distribution.
                    </span>
                  </div>
                ) : (
                  <div className="flex-1 flex flex-col justify-center min-h-[160px]">
                    <div className="flex justify-between text-xs font-semibold mb-2">
                      <span className="text-slate-500">Population Stability Index (PSI)</span>
                      <span className={`font-bold ${statusText(psiResult?.status)}`}>
                        {fmt(psi, 3)}
                      </span>
                    </div>

                    <div className="relative h-3 bg-slate-100 rounded-full overflow-hidden">
                      <div
                        className={`absolute inset-y-0 left-0 rounded-full ${statusFill(psiResult?.status)}`}
                        style={{ width: `${psiPct}%` }}
                      />
                      <div
                        className="absolute top-0 bottom-0 w-0.5 bg-amber-500"
                        style={{ left: `${warnPct}%` }}
                        title={`Warning threshold ${fmt(psiWarningThreshold, 3)}`}
                      />
                      <div
                        className="absolute top-0 bottom-0 w-0.5 bg-rose-500"
                        style={{ left: `${breachPct}%` }}
                        title={`Breach threshold ${fmt(psiBreachThreshold, 3)}`}
                      />
                    </div>

                    <div className="flex justify-between text-[11px] text-slate-400 mt-1.5">
                      <span>0</span>
                      <span>
                        Warning ≥ {fmt(psiWarningThreshold, 3)} · Breach &gt;{' '}
                        {fmt(psiBreachThreshold, 3)}
                      </span>
                    </div>

                    <div className="mt-4 flex items-start gap-2 p-3 rounded-xl bg-slate-100 border border-slate-200 text-xs text-slate-600 leading-relaxed">
                      <AlertTriangle className="w-4 h-4 text-slate-400 shrink-0 mt-0.5" />
                      <span>
                        Decile distribution unavailable
                        {decilesFailed ? ' (could not load population deciles).' : '.'} Showing
                        the PSI value against your configured thresholds.
                      </span>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {tab === 'gap' && (
            <div className="flex flex-col gap-8 w-full items-center">
              {/* Policy threshold checks */}
              <div className="flex flex-col items-center">
                <div className="relative w-44 h-44 rounded-full bg-slate-100 flex items-center justify-center">
                  <div
                    className="absolute inset-0 rounded-full"
                    style={{
                      background: `conic-gradient(#4f46e5 ${(currentModel.overallCompliance ?? 0) * 3.6}deg, #e2e8f0 0deg)`,
                    }}
                  />
                  <div className="relative w-36 h-36 bg-white rounded-full flex flex-col items-center justify-center shadow-md z-10">
                    <span className="text-4xl font-bold text-slate-900">
                      {currentModel.overallCompliance != null
                        ? `${currentModel.overallCompliance}%`
                        : '—'}
                    </span>
                    <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider text-center mt-1 leading-tight">
                      Policy
                      <br />
                      Compliance
                    </span>
                  </div>
                </div>
              </div>

              {currentModel.policyResults.length > 0 ? (
                <div className="w-full max-w-2xl bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
                  <div className="p-4 bg-slate-50 border-b border-slate-200 text-xs font-bold uppercase tracking-wider text-slate-500">
                    Policy Threshold Checks
                  </div>
                  <div className="divide-y divide-slate-100">
                    {currentModel.policyResults.map((res) => (
                      <div key={res.id} className="p-5 hover:bg-slate-50/70 transition-colors flex flex-col gap-2">
                        <div className="flex justify-between items-center gap-3">
                          <div className="flex items-center space-x-3">
                            <span className="material-symbols-outlined text-indigo-600 text-xl">
                              {res.icon}
                            </span>
                            <span className="text-sm font-bold text-slate-900">{res.title}</span>
                          </div>
                          <span
                            className={`text-[10px] font-bold px-3 py-0.5 rounded-full border uppercase tracking-wider shrink-0 ${statusPill(res.status)}`}
                          >
                            {res.status}
                          </span>
                        </div>
                        <p className="text-xs text-slate-600 pl-8 leading-relaxed">
                          Value{' '}
                          <span className="font-mono font-bold text-slate-900">
                            {formatPolicyValue(res.value, res.threshold)}
                          </span>{' '}
                          · Threshold{' '}
                          <span className="font-mono font-bold text-slate-900">
                            {prettyThreshold(res.threshold)}
                          </span>
                          {res.ruleBasis && ` · ${res.ruleBasis}`}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="w-full max-w-2xl flex flex-col items-center justify-center p-10 text-center bg-slate-50 border border-slate-200 rounded-2xl">
                  <FileText className="w-8 h-8 text-slate-300" />
                  <p className="mt-3 text-sm font-semibold text-slate-600">No policy checks yet</p>
                  <p className="mt-1 text-xs text-slate-400">
                    Upload and analyze a validation document to score its metrics against your
                    policy thresholds.
                  </p>
                </div>
              )}

              {/* LLM gap analysis of the latest document */}
              <div className="w-full max-w-2xl bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
                <div className="p-4 bg-slate-50 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-500 block">
                      AI Gap Analysis (CBUAE MMG checklist)
                    </span>
                    {latestDoc && (
                      <span className="text-[11px] text-slate-400 truncate block">
                        Latest document: {latestDoc.filename}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {currentLlmGap && (
                      <span className="text-[11px] font-bold text-indigo-700 bg-indigo-50 border border-indigo-100 rounded-full px-2.5 py-0.5">
                        Coverage {currentLlmGap.coverageScore}%
                      </span>
                    )}
                    {latestDoc && (
                      <button
                        type="button"
                        onClick={handleRunGapAnalysis}
                        disabled={llmGapRunning}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed text-white text-[11px] font-bold transition-colors cursor-pointer"
                      >
                        {llmGapRunning ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <RefreshCw className="w-3 h-3" />
                        )}
                        {currentLlmGap ? 'Re-run' : 'Run analysis'}
                      </button>
                    )}
                  </div>
                </div>

                <div className="p-5">
                  {docsLoading ? (
                    <div className="flex items-center justify-center gap-2 py-6 text-xs text-slate-400">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Loading documents…
                    </div>
                  ) : docsError ? (
                    <p className="text-xs text-rose-700 bg-rose-50 border border-rose-100 rounded-xl px-3 py-2">
                      {docsError}
                    </p>
                  ) : !latestDoc ? (
                    <p className="text-xs text-slate-500 text-center py-4">
                      Upload and analyze a validation document for this version to run an AI gap
                      analysis.
                    </p>
                  ) : (
                    <div className="space-y-4">
                      {llmGapRunError && (
                        <p className="text-xs text-rose-700 bg-rose-50 border border-rose-100 rounded-xl px-3 py-2">
                          Gap analysis failed: {llmGapRunError}
                        </p>
                      )}
                      {llmGapLoadError && !llmGapRunning && (
                        <p className="text-xs text-rose-700 bg-rose-50 border border-rose-100 rounded-xl px-3 py-2">
                          {llmGapLoadError}
                        </p>
                      )}

                      {llmGapRunning ? (
                        <div className="flex items-center justify-center gap-2 py-6 text-xs text-slate-500">
                          <Loader2 className="w-4 h-4 animate-spin text-indigo-600" />
                          Running AI gap analysis… this can take up to a minute.
                        </div>
                      ) : llmGapLoading ? (
                        <div className="flex items-center justify-center gap-2 py-6 text-xs text-slate-400">
                          <Loader2 className="w-4 h-4 animate-spin" />
                          Loading gap analysis…
                        </div>
                      ) : currentLlmGap ? (
                        currentLlmGap.gaps.length > 0 ? (
                          <div className="divide-y divide-slate-100 -my-2">
                            {currentLlmGap.gaps.map((gap, idx) => (
                              <div key={`${gap.requirement}-${idx}`} className="py-4 flex flex-col gap-1.5">
                                <div className="flex justify-between items-start gap-3">
                                  <span className="text-sm font-bold text-slate-900">
                                    {gap.requirement}
                                  </span>
                                  <span
                                    className={`text-[10px] font-bold px-3 py-0.5 rounded-full border uppercase tracking-wider shrink-0 ${statusPill(gap.status)}`}
                                  >
                                    {gap.status || '—'}
                                  </span>
                                </div>
                                {gap.description && (
                                  <p className="text-xs text-slate-600 leading-relaxed">
                                    {gap.description}
                                  </p>
                                )}
                                {gap.recommendation && (
                                  <p className="text-xs text-indigo-700 leading-relaxed">
                                    <span className="font-bold">Recommendation:</span>{' '}
                                    {gap.recommendation}
                                  </p>
                                )}
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-xs text-slate-500 text-center py-4">
                            The analysis reported no gaps for this document.
                          </p>
                        )
                      ) : (
                        !llmGapLoadError && (
                          <p className="text-xs text-slate-500 text-center py-4">
                            No AI gap analysis has been run for this document yet.
                          </p>
                        )
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {tab === 'documents' && (
            <DocumentViewer
              modelVersionId={versionId}
              initialDocumentId={activeDocumentId}
              onDocumentDeleted={() => {
                setDocsReloadKey((k) => k + 1);
                onDocumentsChanged();
              }}
            />
          )}

          {tab === 'analyst' && (
            <div className="flex flex-col h-[520px]">
              <div className="flex items-center justify-between gap-3 pb-3 mb-3 border-b border-slate-100 text-[11px] text-slate-500">
                <span className="flex items-center gap-1.5 min-w-0">
                  <FileText className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                  <span className="truncate">
                    {docsLoading
                      ? 'Loading document context…'
                      : chatDocument
                        ? `Grounded in ${chatDocument.filename} and the regulatory corpus`
                        : 'No analyzed document for this version yet: answers use the regulatory corpus only'}
                  </span>
                </span>
                {messages.length > 0 && (
                  <button
                    type="button"
                    onClick={startNewConversation}
                    disabled={streaming}
                    className="flex items-center gap-1 shrink-0 font-bold text-indigo-600 hover:text-indigo-700 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <MessageSquarePlus className="w-3.5 h-3.5" />
                    New conversation
                  </button>
                )}
              </div>

              <div className="flex-1 overflow-y-auto space-y-4 pr-2">
                {historyLoading ? (
                  <div className="flex items-center justify-center gap-2 py-8 text-xs text-slate-400">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Loading previous conversation…
                  </div>
                ) : (
                  <>
                    {historyError && (
                      <p className="text-xs text-rose-700 bg-rose-50 border border-rose-100 rounded-xl px-3 py-2">
                        Could not load the previous conversation: {historyError}
                      </p>
                    )}

                    {messages.length === 0 && (
                      <div className="flex flex-col items-center justify-center text-center py-8">
                        <div className="w-12 h-12 rounded-2xl bg-indigo-600 text-white flex items-center justify-center shadow-md shadow-indigo-200 mb-4">
                          <Sparkles className="w-6 h-6" />
                        </div>
                        <h3 className="text-sm font-bold text-slate-900">AI Analyst</h3>
                        <p className="mt-1 text-xs text-slate-500 max-w-md leading-relaxed">
                          Ask questions about {currentModel.name}. Answers stream from its latest
                          analyzed document and the regulatory corpus, cite their sources, and are
                          saved for this model version.
                        </p>
                      </div>
                    )}

                    {messages.map((msg) => (
                      <ChatMessageBubble
                        key={msg.id}
                        message={msg}
                        sourceLabel={sourceLabel}
                        onOpenSource={openSource}
                      />
                    ))}
                  </>
                )}

                <div ref={chatEndRef} />
              </div>

              <div className="pt-4 border-t border-slate-100 shrink-0 space-y-3">
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={handleRunGapAnalysis}
                    disabled={!latestDoc || llmGapRunning}
                    title={latestDoc ? undefined : 'Upload and analyze a document first'}
                    className={quickActionClass}
                  >
                    Run Gap Analysis
                  </button>
                  <button
                    type="button"
                    onClick={() => handleSend('Extract key performance metrics')}
                    disabled={streaming || historyLoading}
                    className={quickActionClass}
                  >
                    Extract Metrics
                  </button>
                  <button
                    type="button"
                    onClick={() => handleSend('Summarize methodology and sample observation')}
                    disabled={streaming || historyLoading}
                    className={quickActionClass}
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
                    disabled={!input.trim() || streaming || historyLoading}
                    className={`w-8 h-8 rounded-full flex items-center justify-center transition-colors cursor-pointer ${
                      input.trim() && !streaming && !historyLoading
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
                      onClick={() => openSource(source)}
                      className="w-full flex items-start gap-3 p-4 bg-slate-50 border border-slate-200 rounded-2xl hover:border-indigo-300 transition-colors text-left cursor-pointer"
                    >
                      <div className="w-8 h-8 rounded-lg bg-indigo-50 border border-indigo-100 flex items-center justify-center shrink-0">
                        <BookOpen className="w-4 h-4 text-indigo-600" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-start justify-between gap-3">
                          <span className="text-sm font-bold text-slate-900 block min-w-0 truncate">
                            {sourceLabel(source)}
                          </span>
                          {source.score != null && (
                            <span className="text-[10px] font-mono font-bold text-slate-400 shrink-0">
                              score {source.score.toFixed(3)}
                            </span>
                          )}
                        </div>
                        {source.ref && (
                          <span className="text-xs text-slate-500 font-medium">{source.ref}</span>
                        )}
                        {source.text && (
                          <p className="mt-2 text-xs text-slate-600 leading-relaxed line-clamp-3 whitespace-pre-line">
                            {source.text}
                          </p>
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
