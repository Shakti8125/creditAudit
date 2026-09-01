export type NavItem = 'overview' | 'workspace' | 'compare' | 'library' | 'settings';

export type ModelStatus = 'PASS' | 'WARNING' | 'BREACH';
export type NotificationType = 'PASS' | 'WARNING' | 'BREACH' | 'INFO';

export interface MetricSet {
  gini: number;
  giniThreshold: number;
  auc: number;
  aucBenchmark: number;
  ks: number;
  ksBenchmark: number;
  psi: number;
  psiThreshold: number;
}

export type GapStatus = ModelStatus | 'BREACH / GAP';

export interface GapRequirement {
  id: string;
  title: string;
  icon: string;
  status: GapStatus;
  details: string;
}

export interface ModelSummary {
  id: string;
  name: string;
  type: string;
  lastAnalyzed: string;
  status: ModelStatus;
  version: string;
  portfolio: string;
  algorithm: string;
  description: string;
  metrics: MetricSet;
  gapAnalysis: {
    overallCompliance: number;
    requirements: GapRequirement[];
  };
}

export interface RedactedEntity {
  id: string;
  rawString: string;
  maskedPayload: string;
  entityType: 'BANK' | 'PERSON' | 'LOCATION' | 'IDENTIFIER' | 'ORG';
  timestamp: string;
}

export interface ChatSource {
  title: string;
  ref: string;
}

export interface ChatMessage {
  id: string;
  sender: 'ai' | 'user';
  timestamp: string;
  content: string;
  sources?: ChatSource[];
  suggestedActions?: string[];
  isHighlighted?: boolean;
}

export interface ComparisonDiff {
  type: 'added' | 'changed' | 'removed';
  text: string;
  oldVal?: string;
  newVal?: string;
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
  dataConfig: string;
  dataConfigDiff?: ComparisonDiff;
  metrics: ComparisonMetric[];
  findings: {
    label: string;
    openCount: number;
    resolvedCount?: number;
    diffNote?: string;
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
  minObservationMonths: number;
  autoMaskBank: boolean;
  autoMaskBorrower: boolean;
  autoMaskLocation: boolean;
  strictZeroTrust: boolean;
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
  securityClearance?: string;
  role: string;
  isActive: boolean;
}

export interface SearchResult {
  id: string;
  type: 'model' | 'regulatory_standard';
  title: string;
  description?: string;
}

export interface RocPoint {
  fpr: number;
  tpr: number;
}

export interface DocumentMeta {
  id: string;
  filename: string;
  fileType: string;
  uploadTime: string;
  status: string;
  chunkCount: number;
}