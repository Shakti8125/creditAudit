export type NavItem = 'overview' | 'workspace' | 'compare' | 'library' | 'settings';

export type WorkspaceTab = 'metrics' | 'gap' | 'documents' | 'analyst' | 'citations';

/** Outcome of a backend policy check. */
export type PolicyStatus = 'PASS' | 'WARNING' | 'BREACH';
/** Model status; PENDING until a document has been analyzed for the model. */
export type ModelStatus = PolicyStatus | 'PENDING';
export type NotificationType = 'PASS' | 'WARNING' | 'BREACH' | 'INFO';

/**
 * Headline metrics of the current version, normalised to display scale
 * (Gini and KS in %, AUC and PSI as decimals). `null` = not reported.
 */
export interface MetricSet {
  gini: number | null;
  auc: number | null;
  ks: number | null;
  psi: number | null;
  /** Tenant PSI thresholds the backend scores against (Settings). */
  psiWarningThreshold: number;
  psiBreachThreshold: number;
}

/** One row of the backend BreachReport (`current_version.gap_analysis.results`). */
export interface PolicyResult {
  id: string;
  /** Exact backend metric_name, e.g. "Gini Coefficient", "AUC", "KS Statistic", "PSI". */
  metricName: string;
  /** Display label. */
  title: string;
  /** Material Symbols icon name. */
  icon: string;
  /** Value as scored by the backend (Gini/KS in %, AUC/PSI as decimals). */
  value: number;
  /** Threshold expression as reported by the backend, e.g. ">= 40.0%". */
  threshold: string;
  status: PolicyStatus;
  ruleBasis: string;
}

export interface ModelSummary {
  id: string;
  name: string;
  type: string;
  /** Relative time of the latest analyzed document on the current version; null if none. */
  lastAnalyzed: string | null;
  status: ModelStatus;
  version: string;
  /** Id of the model's active version — used to scope documents to this model. */
  currentVersionId?: string;
  portfolio: string;
  algorithm: string;
  description: string;
  metrics: MetricSet;
  policyResults: PolicyResult[];
  /** Share of passed policy checks (warnings count half); null when nothing was scored. */
  overallCompliance: number | null;
}

export interface RedactedEntity {
  rawString: string;
  maskedPayload: string;
  entityType: 'BANK' | 'PERSON' | 'LOCATION' | 'IDENTIFIER' | 'ORG';
  timestamp: string;
}

export interface ChatSource {
  /** Citation source: a regulatory corpus id, `doc-<document id>`, or a document filename. */
  title: string;
  /** Section within the source. */
  ref: string;
  /** Retrieved passage (privacy-masked). */
  text: string;
  score?: number;
}

export interface ChatMessage {
  id: string;
  sender: 'ai' | 'user';
  timestamp: string;
  content: string;
  sources?: ChatSource[];
  isHighlighted?: boolean;
}

/** Summary of a persisted AI Analyst conversation (GET /query/sessions). */
export interface ChatSessionSummary {
  id: string;
  modelVersionId?: string;
  createdAt: string;
  messageCount: number;
  lastMessagePreview?: string;
}

export interface ComparisonDiff {
  type: 'added' | 'changed' | 'removed';
  text: string;
}

export interface ComparisonMetric {
  name: string;
  value: string;
  oldValue?: string;
  newValue?: string;
  isDiff?: boolean;
}

export interface ComparisonModel {
  title: string;
  role: 'baseline' | 'challenger';
  version: string;
  methodology: string;
  methodologyDiff?: ComparisonDiff;
  metrics: ComparisonMetric[];
  findings: {
    label: string;
    openCount: number;
    /** Challenger only: how many fewer open findings than the baseline. */
    fewerThanBaseline?: number;
  };
}

export interface RegulatoryClause {
  clause: string;
  topic: string;
  requirement: string;
  threshold?: string;
}

export interface RegulatoryStandard {
  id: string;
  code: string;
  title: string;
  authority: string;
  jurisdiction: string;
  effectiveDate: string;
  category: string;
  description: string;
  relevantClauses: RegulatoryClause[];
}

export interface PopulationDecile {
  decile: string;
  expected: number;
  actual: number;
}

export interface DashboardMetrics {
  activeModels: number;
  documentsAnalyzed: number;
  complianceIssues: number;
  aiReviews: number;
}

export interface TenantSettings {
  giniTolerance: number;
  psiWarningThreshold: number;
  psiBreachThreshold: number;
}

export interface NotificationItem {
  id: string;
  title: string;
  description?: string;
  type: NotificationType;
  isRead: boolean;
  time: string;
  modelId?: string;
}

export interface UserProfile {
  id: string;
  email: string;
  fullName?: string;
  title?: string;
  division?: string;
  role: string;
  isActive: boolean;
}

export interface SearchResult {
  id: string;
  type: 'model' | 'regulatory_standard' | 'document';
  title: string;
  /** Standards: the standard code. Documents: "Document". Models: the description. */
  description?: string;
  /** Owning model for models and documents. */
  modelId?: string;
}

export interface DocumentMeta {
  id: string;
  filename: string;
  fileType: string;
  uploadTime: string;
  status: string;
  chunkCount: number;
  modelVersionId?: string;
}

export interface DocumentChunk {
  index: number;
  text: string;
}

export interface ComplianceGap {
  requirement: string;
  /** PASS | WARNING | BREACH | MISSING (LLM-assessed). */
  status: string;
  description: string;
  recommendation: string;
}

/** LLM gap analysis of a document (POST /gap-analysis; persisted in metrics_summary). */
export interface LlmGapAnalysis {
  gaps: ComplianceGap[];
  /** 0–100. */
  coverageScore: number;
}

export interface DocumentDetail {
  id: string;
  filename: string;
  status: string;
  metricsSummary: Record<string, unknown>;
  llmGapAnalysis: LlmGapAnalysis | null;
  chunks: DocumentChunk[];
}

export interface DocumentDifference {
  category: string;
  description: string;
  docAValue: string;
  docBValue: string;
}

export interface DocumentComparisonResult {
  differences: DocumentDifference[];
  summary: string;
}