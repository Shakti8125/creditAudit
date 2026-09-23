import type {
  ChatMessage,
  ChatSessionSummary,
  ChatSource,
  ComparisonModel,
  DashboardMetrics,
  DocumentComparisonResult,
  DocumentDetail,
  DocumentMeta,
  LlmGapAnalysis,
  MetricSet,
  ModelStatus,
  ModelSummary,
  NotificationItem,
  PolicyResult,
  PolicyStatus,
  RedactedEntity,
  RegulatoryClause,
  RegulatoryStandard,
  SearchResult,
  TenantSettings,
  UserProfile,
} from '@/types';

// Backend PolicyChecker defaults, used only if tenant settings failed to load.
const DEFAULT_PSI_WARNING = 0.1;
const DEFAULT_PSI_BREACH = 0.25;

const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
];

/**
 * Reads a metric from a ModelValidationProfile dump, normalised like the
 * backend PolicyChecker. Returns null when the metric was not reported.
 */
export function getMetricValue(
  m: any,
  k: string,
  expectedScale?: 'pct' | 'decimal',
): number | null {
  const item = m?.[k];
  if (!item) return null;
  const v = typeof item.value === 'number' ? item.value : Number(item.value);
  if (!Number.isFinite(v)) return null;

  if (expectedScale === 'pct') {
    // If unit is absolute and v <= 1.0 (e.g. KS = 0.41019), convert to percentage (41.019%)
    if (item.unit === 'absolute' && v <= 1.0) return v * 100.0;
    return v;
  }
  if (expectedScale === 'decimal') {
    // If unit is % or v > 1.0 (e.g. PSI = 5.5%), convert to decimal (0.055)
    if (item.unit === '%' || v > 1.0) return v / 100.0;
    return v;
  }
  return v;
}

function humanize(metric: string): string {
  const m = metric.trim().toLowerCase();
  if (m === 'gini') return 'Gini Coefficient';
  if (m === 'auc' || m === 'auc_roc') return 'AUC';
  if (m === 'ks' || m === 'ks_statistic') return 'KS Statistic';
  if (m === 'psi') return 'Population Stability';
  return metric
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function iconFor(metric: string): string {
  const m = metric.toLowerCase();
  if (m.includes('auc') || m.includes('ks')) return 'model_training';
  if (m.includes('psi') || m.includes('stability')) return 'timeline';
  if (m.includes('gini')) return 'model_training';
  if (m.includes('data')) return 'database';
  if (m.includes('document') || m.includes('doc')) return 'description';
  return 'description';
}

function toPolicyStatus(s: any): PolicyStatus | null {
  return s === 'BREACH' || s === 'WARNING' || s === 'PASS' ? s : null;
}

/**
 * Parses a backend timestamp. The API returns naive UTC ISO strings (no "Z"),
 * which `Date` would otherwise read as local time. Returns NaN when invalid.
 */
export function parseTimestamp(iso: string): number {
  if (!iso) return Number.NaN;
  const hasZone = /(Z|[+-]\d\d:?\d\d)$/i.test(iso);
  return Date.parse(hasZone ? iso : `${iso}Z`);
}

export function relativeTime(iso: string): string {
  const time = parseTimestamp(iso);
  if (Number.isNaN(time)) return '—';
  const date = new Date(time);

  const diffMs = Date.now() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHr = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);

  if (diffSec < 60) return '< 1 min ago';
  if (diffMin < 60) return `${diffMin} min${diffMin === 1 ? '' : 's'} ago`;
  if (diffHr < 24) return `${diffHr} hr${diffHr === 1 ? '' : 's'} ago`;
  if (diffDay === 1) return 'Yesterday';
  if (diffDay < 30) return `${diffDay} days ago`;
  return `${MONTHS[date.getMonth()]} ${date.getDate()}, ${date.getFullYear()}`;
}

function toPolicyResults(gapAnalysis: any): PolicyResult[] {
  const raw: any[] = Array.isArray(gapAnalysis?.results) ? gapAnalysis.results : [];
  const results: PolicyResult[] = [];
  raw.forEach((r, i) => {
    const status = toPolicyStatus(r?.status);
    const value = Number(r?.value);
    if (!status || !Number.isFinite(value)) return;
    const metricName = String(r.metric_name ?? '');
    results.push({
      id: `policy-${i}`,
      metricName,
      title: humanize(metricName),
      icon: iconFor(metricName),
      value,
      threshold: String(r.threshold ?? ''),
      status,
      ruleBasis: r.rule_basis ?? '',
    });
  });
  return results;
}

export function toModelSummary(dto: any, settings?: TenantSettings): ModelSummary {
  const rawMetrics = dto.current_version?.metrics;
  const metrics: MetricSet = {
    gini: getMetricValue(rawMetrics, 'gini', 'pct'),
    auc: getMetricValue(rawMetrics, 'auc', 'decimal'),
    ks: getMetricValue(rawMetrics, 'ks', 'pct'),
    psi: getMetricValue(rawMetrics, 'psi', 'decimal'),
    psiWarningThreshold: settings?.psiWarningThreshold ?? DEFAULT_PSI_WARNING,
    psiBreachThreshold: settings?.psiBreachThreshold ?? DEFAULT_PSI_BREACH,
  };

  const policyResults = toPolicyResults(dto.current_version?.gap_analysis);
  let pass = 0;
  let warning = 0;
  for (const r of policyResults) {
    if (r.status === 'PASS') pass += 1;
    else if (r.status === 'WARNING') warning += 1;
  }
  const overallCompliance = policyResults.length
    ? Math.round(((pass + 0.5 * warning) / policyResults.length) * 100)
    : null;

  const rawVersion = dto.current_version?.version ?? '1.0';
  const version = dto.current_version?.is_current
    ? `Version ${rawVersion} (current)`
    : `Version ${rawVersion}`;

  const status: ModelStatus = toPolicyStatus(dto.status) ?? 'PENDING';

  return {
    id: dto.id,
    name: dto.name,
    type: dto.type,
    currentVersionId: dto.current_version?.id,
    description: dto.description ?? '',
    portfolio: dto.portfolio ?? '—',
    algorithm: dto.algorithm ?? '—',
    status,
    version,
    lastAnalyzed: dto.last_analyzed_at ? relativeTime(dto.last_analyzed_at) : null,
    metrics,
    policyResults,
    overallCompliance,
  };
}

export function toRegulatoryStandard(dto: any): RegulatoryStandard {
  const relevantClauses: RegulatoryClause[] = (dto.clauses_json ?? [] as any[]).map(
    (c: any) => ({
      clause: c.clause ?? '',
      topic: c.topic ?? '',
      requirement: c.requirement ?? '',
      threshold: c.threshold,
    }),
  );

  return {
    id: dto.id,
    code: dto.code ?? '',
    title: dto.title ?? '',
    authority: dto.authority ?? '',
    jurisdiction: dto.jurisdiction ?? '',
    effectiveDate: dto.effective_date ?? '',
    category: dto.category ?? '',
    description: dto.description ?? '',
    relevantClauses,
  };
}

export function toNotification(dto: any): NotificationItem {
  return {
    id: dto.id,
    title: dto.title,
    description: dto.description,
    type: dto.type,
    isRead: !!dto.is_read,
    time: relativeTime(dto.created_at),
    modelId: dto.model_id ?? undefined,
  };
}

export function toProfile(dto: any): UserProfile {
  return {
    id: dto.id,
    email: dto.email,
    fullName: dto.full_name ?? undefined,
    title: dto.title ?? undefined,
    division: dto.division ?? undefined,
    role: dto.role,
    isActive: !!dto.is_active,
  };
}

export function toDashboardMetrics(dto: any): DashboardMetrics {
  return {
    activeModels: dto.active_models ?? 0,
    documentsAnalyzed: dto.documents_analyzed ?? 0,
    complianceIssues: dto.compliance_issues ?? 0,
    aiReviews: dto.ai_reviews ?? 0,
  };
}

export function toSettings(dto: any): TenantSettings {
  return {
    giniTolerance: dto.gini_tolerance ?? 0.05,
    psiWarningThreshold: dto.psi_warning_threshold ?? DEFAULT_PSI_WARNING,
    psiBreachThreshold: dto.psi_breach_threshold ?? DEFAULT_PSI_BREACH,
  };
}

export function toSearchResult(dto: any): SearchResult | null {
  const type = dto?.type;
  if (type !== 'model' && type !== 'regulatory_standard' && type !== 'document') return null;
  return {
    id: String(dto.id),
    type,
    title: dto.title ?? '',
    description: dto.description ?? undefined,
    modelId: dto.model_id ?? (type === 'model' ? String(dto.id) : undefined),
  };
}

function entityTypeFromToken(token: string): RedactedEntity['entityType'] {
  if (token.startsWith('[BANK')) return 'BANK';
  if (token.startsWith('[PERSON')) return 'PERSON';
  if (token.startsWith('[LOC') || token.startsWith('[GPE')) return 'LOCATION';
  if (token.startsWith('[ORG')) return 'ORG';
  return 'IDENTIFIER';
}

export function redactionsToEntities(
  redactions: Record<string, string>,
): RedactedEntity[] {
  const timestamp = new Date().toLocaleTimeString();
  return Object.entries(redactions ?? {}).map(([raw, masked]) => ({
    rawString: raw,
    maskedPayload: masked,
    entityType: entityTypeFromToken(masked),
    timestamp,
  }));
}

export function toChatSource(dto: any): ChatSource {
  return {
    title: dto?.source ?? '',
    ref: dto?.section ?? '',
    text: dto?.text ?? '',
    score: typeof dto?.score === 'number' ? dto.score : undefined,
  };
}

export function toChatMessage(dto: any): ChatMessage {
  const sources: any[] = Array.isArray(dto.sources_json) ? dto.sources_json : [];
  return {
    id: String(dto.id),
    sender: dto.role === 'user' ? 'user' : 'ai',
    timestamp: relativeTime(dto.created_at),
    content: dto.content ?? '',
    sources: sources.map(toChatSource),
  };
}

export function toChatSessionSummary(dto: any): ChatSessionSummary {
  return {
    id: String(dto.id),
    modelVersionId: dto.model_version_id ?? undefined,
    createdAt: dto.created_at ?? '',
    messageCount: dto.message_count ?? 0,
    lastMessagePreview: dto.last_message_preview ?? undefined,
  };
}

export function toDocumentMeta(dto: any): DocumentMeta {
  return {
    id: dto.id,
    filename: dto.filename ?? '',
    fileType: dto.file_type ?? '',
    uploadTime: dto.upload_time ?? '',
    status: dto.status ?? '',
    chunkCount: dto.chunk_count ?? 0,
    modelVersionId: dto.model_version_id ?? undefined,
  };
}

/** Parses a GapAnalysisResponse ({gaps, coverage_score}); null if absent. */
export function toLlmGapAnalysis(dto: any): LlmGapAnalysis | null {
  if (!dto || typeof dto !== 'object' || !Array.isArray(dto.gaps)) return null;
  const rawScore = Number(dto.coverage_score);
  // The LLM may report coverage as a fraction or a percentage.
  const coverageScore = Number.isFinite(rawScore)
    ? Math.round(rawScore <= 1 ? rawScore * 100 : rawScore)
    : 0;
  return {
    coverageScore: Math.max(0, Math.min(100, coverageScore)),
    gaps: dto.gaps.map((g: any) => ({
      requirement: g?.requirement ?? '',
      status: g?.status ?? '',
      description: g?.description ?? '',
      recommendation: g?.recommendation ?? '',
    })),
  };
}

export function toDocumentDetail(dto: any): DocumentDetail {
  const metricsSummary = (dto.metrics_summary ?? {}) as Record<string, unknown>;
  return {
    id: dto.id,
    filename: dto.filename ?? '',
    status: dto.status ?? '',
    metricsSummary,
    llmGapAnalysis: toLlmGapAnalysis(metricsSummary.llm_gap_analysis),
    chunks: (dto.chunks ?? []).map((c: any) => ({
      index: c.index ?? 0,
      text: c.text ?? '',
    })),
  };
}

export function toDocumentComparison(dto: any): DocumentComparisonResult {
  return {
    summary: dto.summary ?? '',
    differences: (dto.differences ?? []).map((d: any) => ({
      category: d.category ?? '',
      description: d.description ?? '',
      docAValue: d.doc_a_value ?? '',
      docBValue: d.doc_b_value ?? '',
    })),
  };
}

export function toComparisonModel(dto: any): ComparisonModel {
  return {
    title: dto.title,
    role: dto.role,
    version: dto.version,
    methodology: dto.methodology ?? '',
    methodologyDiff: dto.methodology_diff
      ? { type: dto.methodology_diff.type, text: dto.methodology_diff.text }
      : undefined,
    metrics: (dto.metrics ?? []).map((m: any) => ({
      name: m.name,
      value: m.value,
      oldValue: m.old_value,
      newValue: m.new_value,
      isDiff: !!m.is_diff,
    })),
    findings: {
      label: dto.findings?.label ?? 'Open Findings',
      openCount: dto.findings?.open_count ?? 0,
      fewerThanBaseline: dto.findings?.resolved_count ?? undefined,
    },
  };
}
