import type {
  ComparisonModel,
  DashboardMetrics,
  GapRequirement,
  GapStatus,
  MetricSet,
  ModelSummary,
  NotificationItem,
  RedactedEntity,
  RegulatoryClause,
  RegulatoryStandard,
  TenantSettings,
  UserProfile,
} from '@/types';

const GINI_TARGET = 50;
const AUC_BENCHMARK = 0.75;
const KS_BENCHMARK = 35;

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

function getMetricValue(m: any, k: string, expectedScale?: 'pct' | 'decimal'): number {
  const item = m?.[k];
  if (!item) return 0;
  const v = typeof item.value === 'number' ? item.value : Number(item.value);
  if (!Number.isFinite(v)) return 0;

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

function num(m: any, k: string): number {
  return getMetricValue(m, k);
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

function mapGapStatus(s: any): GapStatus {
  if (s === 'BREACH' || s === 'WARNING' || s === 'PASS') return s;
  return 'WARNING';
}

export function relativeTime(iso: string): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';

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

export function toModelSummary(dto: any, settings?: TenantSettings): ModelSummary {
  const rawMetrics = dto.current_version?.metrics;
  const metrics: MetricSet = {
    gini: getMetricValue(rawMetrics, 'gini', 'pct'),
    giniThreshold: GINI_TARGET,
    auc: getMetricValue(rawMetrics, 'auc', 'decimal'),
    aucBenchmark: AUC_BENCHMARK,
    ks: getMetricValue(rawMetrics, 'ks', 'pct'),
    ksBenchmark: KS_BENCHMARK,
    psi: getMetricValue(rawMetrics, 'psi', 'decimal'),
    psiThreshold: settings?.psiWarningThreshold ?? 0.1,
  };

  const results: any[] = (dto.current_version?.gap_analysis?.results ?? []) as any[];
  const requirements: GapRequirement[] = results.map((r, i) => ({
    id: `req-${i}`,
    title: humanize(r.metric_name ?? ''),
    icon: iconFor(r.metric_name ?? ''),
    status: mapGapStatus(r.status),
    details: r.rule_basis ?? '',
  }));

  let pass = 0;
  let warning = 0;
  for (const r of results) {
    if (r.status === 'PASS') pass += 1;
    else if (r.status === 'WARNING') warning += 1;
  }
  const overallCompliance = results.length
    ? Math.round(((pass + 0.5 * warning) / results.length) * 100)
    : 0;

  const rawVersion = dto.current_version?.version ?? '1.0';
  const version = dto.current_version?.is_current
    ? `Version ${rawVersion} • Production`
    : `Version ${rawVersion}`;

  return {
    id: dto.id,
    name: dto.name,
    type: dto.type,
    description: dto.description ?? '',
    portfolio: dto.portfolio ?? '—',
    algorithm: dto.algorithm ?? '—',
    status: (dto.status ?? 'PASS') as ModelSummary['status'],
    version,
    lastAnalyzed: relativeTime(dto.current_version?.created_at ?? dto.created_at),
    metrics,
    gapAnalysis: { overallCompliance, requirements },
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
    fullName: dto.full_name,
    title: dto.title,
    division: dto.division,
    securityClearance: dto.security_clearance,
    role: dto.role,
    isActive: !!dto.is_active,
  };
}

export function toDashboardMetrics(dto: any): DashboardMetrics {
  return {
    activeModels: dto.active_models ?? 0,
    documentsAnalyzed: dto.documents_analyzed ?? 0,
    complianceIssues: dto.compliance_issues ?? 0,
    aiReviews: 0,
  };
}

export function toSettings(dto: any): TenantSettings {
  return {
    giniTolerance: dto.gini_tolerance ?? 0.05,
    psiWarningThreshold: dto.psi_warning_threshold ?? 0.1,
    psiBreachThreshold: dto.psi_breach_threshold ?? 0.25,
    minObservationMonths: dto.min_observation_months ?? 24,
    autoMaskBank: !!dto.auto_mask_bank,
    autoMaskBorrower: !!dto.auto_mask_borrower,
    autoMaskLocation: !!dto.auto_mask_location,
    strictZeroTrust: !!dto.strict_zero_trust,
  };
}

function entityTypeFromToken(token: string): RedactedEntity['entityType'] {
  if (token.startsWith('[BANK')) return 'BANK';
  if (token.startsWith('[PERSON')) return 'PERSON';
  if (token.startsWith('[LOC') || token.startsWith('[LOCATION')) return 'LOCATION';
  if (token.startsWith('[ORG')) return 'ORG';
  return 'IDENTIFIER';
}

export function redactionsToEntities(
  redactions: Record<string, string>,
): RedactedEntity[] {
  const timestamp = new Date().toLocaleTimeString();
  return Object.entries(redactions ?? {}).map(([raw, masked]) => ({
    id: masked,
    rawString: raw,
    maskedPayload: masked,
    entityType: entityTypeFromToken(masked),
    timestamp,
  }));
}

export function toComparisonModel(dto: any): ComparisonModel {
  return {
    title: dto.title,
    role: dto.role,
    version: dto.version,
    methodology: dto.methodology ?? '',
    dataConfig: dto.data_config ?? '',
    methodologyDiff: dto.methodology_diff
      ? { type: dto.methodology_diff.type, text: dto.methodology_diff.text }
      : undefined,
    dataConfigDiff: dto.data_config_diff
      ? {
          type: dto.data_config_diff.type,
          text: dto.data_config_diff.text,
          oldVal: dto.data_config_diff.old_val,
          newVal: dto.data_config_diff.new_val,
        }
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
      resolvedCount: dto.findings?.resolved_count,
      diffNote: dto.findings?.diff_note,
    },
  };
}