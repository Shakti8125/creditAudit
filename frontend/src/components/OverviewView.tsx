import { useState } from 'react';
import type { DashboardMetrics, ModelStatus, ModelSummary } from '@/types';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle,
  FileText,
  Plus,
  Search,
  TrendingUp,
  Zap,
} from 'lucide-react';

interface OverviewViewProps {
  models: ModelSummary[];
  metrics: DashboardMetrics;
  onSelectModel: (m: ModelSummary) => void;
  onNavigateToWorkspace: () => void;
  onOpenNewAudit: () => void;
}

type StatusFilter = 'ALL' | ModelStatus;

const STATUS_BADGE: Record<ModelStatus, string> = {
  PASS: 'bg-emerald-50 text-emerald-600 border-emerald-200',
  WARNING: 'bg-amber-50 text-amber-600 border-amber-200',
  BREACH: 'bg-rose-50 text-rose-600 border-rose-200',
};

function StatusBadge({ status }: { status: ModelStatus }) {
  return (
    <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-bold border ${STATUS_BADGE[status]}`}>
      {status}
    </span>
  );
}

export default function OverviewView({
  models,
  metrics,
  onSelectModel,
  onNavigateToWorkspace,
  onOpenNewAudit,
}: OverviewViewProps) {
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('ALL');

  const filteredModels = models.filter((m) => {
    const q = searchTerm.trim().toLowerCase();
    const matchesSearch =
      !q ||
      m.name.toLowerCase().includes(q) ||
      m.type.toLowerCase().includes(q) ||
      m.description.toLowerCase().includes(q);
    const matchesStatus = statusFilter === 'ALL' || m.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const aiReviewsLabel = metrics.aiReviews || '—';

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xs font-bold text-indigo-600 uppercase tracking-wider mb-1">
            Auditing Intelligence System
          </h2>
          <h1 className="font-display text-3xl md:text-4xl font-bold text-slate-900 tracking-tight">
            Institutional Model Overview
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Real-time validation tracking, regulatory benchmarking, and privacy-shielded intelligence.
          </p>
        </div>

        <button
          onClick={onOpenNewAudit}
          className="self-start md:self-auto flex items-center gap-2 bg-slate-900 hover:bg-slate-800 text-white rounded-xl py-2.5 px-5 text-sm font-semibold transition-all shadow-md active:scale-95 cursor-pointer"
        >
          <Plus className="w-4 h-4" />
          <span>New Audit</span>
        </button>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <div className="bg-indigo-600 rounded-3xl p-7 text-white flex flex-col justify-between relative overflow-hidden min-h-[160px] group">
          <div className="absolute -top-12 -right-12 w-36 h-36 bg-white/15 rounded-full blur-2xl pointer-events-none group-hover:scale-125 transition-transform" />
          <div className="flex justify-between items-start z-10">
            <span className="text-xs font-bold uppercase tracking-wider text-indigo-100">
              Active Models
            </span>
            <div className="w-8 h-8 rounded-full bg-white/20 flex items-center justify-center text-white">
              <Zap className="w-4 h-4" />
            </div>
          </div>
          <div className="z-10 mt-4">
            <div className="text-4xl font-bold tracking-tight text-white">
              {metrics.activeModels}
            </div>
            <div className="flex items-center gap-1 text-xs text-indigo-100 font-medium mt-1">
              <TrendingUp className="w-3.5 h-3.5" />
              <span>100% compliant baseline</span>
            </div>
          </div>
        </div>

        <div className="sleek-card rounded-3xl p-7 flex flex-col justify-between min-h-[160px] hover:border-slate-300 transition-all">
          <div className="flex justify-between items-start">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
              Documents Analyzed
            </span>
            <div className="w-8 h-8 rounded-full bg-slate-100 flex items-center justify-center text-slate-600">
              <FileText className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-4xl font-bold tracking-tight text-slate-900">
              {metrics.documentsAnalyzed}
            </div>
            <p className="text-xs text-slate-400 font-medium mt-1">
              Validation dossiers & stress manuals
            </p>
          </div>
        </div>

        <div className="sleek-card rounded-3xl p-7 flex flex-col justify-between min-h-[160px] hover:border-slate-300 transition-all">
          <div className="flex justify-between items-start">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
              Compliance Issues
            </span>
            <div className="w-8 h-8 rounded-full bg-amber-50 flex items-center justify-center text-amber-600">
              <AlertTriangle className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-4xl font-bold tracking-tight text-amber-500">
              {metrics.complianceIssues}
            </div>
            <p className="text-xs text-amber-600 font-medium mt-1">
              Flags requiring review
            </p>
          </div>
        </div>

        <div className="sleek-card rounded-3xl p-7 flex flex-col justify-between min-h-[160px] hover:border-slate-300 transition-all">
          <div className="flex justify-between items-start">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
              AI Reviews Completed
            </span>
            <div className="w-8 h-8 rounded-full bg-emerald-50 flex items-center justify-center text-emerald-600">
              <CheckCircle className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-4xl font-bold tracking-tight text-slate-900">
              {aiReviewsLabel}
            </div>
            <p className="text-xs text-emerald-600 font-medium mt-1">
              Zero PII leaks detected
            </p>
          </div>
        </div>
      </div>

      {/* Models section */}
      <div className="sleek-card overflow-hidden">
        <div className="p-6 md:p-8 border-b border-slate-100 flex flex-col lg:flex-row justify-between lg:items-center gap-4">
          <div>
            <h3 className="font-display font-bold text-xl text-slate-900">
              Validated Models
            </h3>
            <p className="text-xs text-slate-500 mt-1">
              Select a model to open deep-dive analytics and chat audit assistants.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex space-x-1 bg-slate-50 p-1 rounded-full border border-slate-200">
              {(['ALL', 'PASS', 'WARNING', 'BREACH'] as const).map((st) => (
                <button
                  key={st}
                  onClick={() => setStatusFilter(st)}
                  className={`px-3 py-1 rounded-full text-xs font-bold transition-all cursor-pointer ${
                    statusFilter === st
                      ? 'bg-indigo-600 text-white shadow-sm shadow-indigo-200'
                      : 'text-slate-500 hover:text-slate-900 hover:bg-slate-100'
                  }`}
                >
                  {st}
                </button>
              ))}
            </div>

            <div className="relative">
              <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Filter models..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-8 pr-3 py-1.5 bg-slate-100 border border-slate-200 rounded-full text-xs font-medium text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-600/30 w-36 sm:w-56"
              />
            </div>
          </div>
        </div>

        <div className="p-6 md:p-8">
          {models.length === 0 ? (
            <div className="py-16 text-center flex flex-col items-center gap-4">
              <div className="w-14 h-14 rounded-2xl bg-slate-100 flex items-center justify-center text-slate-400">
                <Zap className="w-6 h-6" />
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-700">
                  No models on record yet
                </p>
                <p className="text-xs text-slate-400 mt-1">
                  Initiate your first audit to establish an institutional model registry.
                </p>
              </div>
              <button
                onClick={onOpenNewAudit}
                className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl py-2.5 px-5 text-sm font-semibold transition-all shadow-md cursor-pointer"
              >
                <Plus className="w-4 h-4" />
                <span>New Audit</span>
              </button>
            </div>
          ) : filteredModels.length === 0 ? (
            <div className="py-16 text-center text-sm text-slate-400 font-medium">
              No models found matching your search criteria.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
              {filteredModels.map((model) => (
                <button
                  key={model.id}
                  onClick={() => {
                    onSelectModel(model);
                    onNavigateToWorkspace();
                  }}
                  className="group text-left rounded-2xl border border-slate-200 p-5 hover:border-indigo-300 hover:shadow-md transition-all cursor-pointer bg-white flex flex-col gap-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-semibold text-sm text-slate-900 truncate group-hover:text-indigo-600 transition-colors">
                        {model.name}
                      </p>
                      <p className="text-[11px] text-slate-400 mt-0.5 truncate">
                        {model.version}
                      </p>
                    </div>
                    <StatusBadge status={model.status} />
                  </div>

                  <div className="flex flex-wrap gap-1.5">
                    <span className="px-2 py-0.5 rounded-md bg-slate-100 text-slate-600 text-[11px] font-medium">
                      {model.type}
                    </span>
                    <span className="px-2 py-0.5 rounded-md bg-indigo-50 text-indigo-600 text-[11px] font-medium">
                      {model.algorithm}
                    </span>
                  </div>

                  <p className="text-xs text-slate-500 line-clamp-2">
                    {model.description || 'No description provided.'}
                  </p>

                  <div className="flex items-center justify-between text-[11px] text-slate-400 border-t border-slate-100 pt-3 mt-auto">
                    <span className="truncate">{model.portfolio}</span>
                    <span className="font-mono text-indigo-600 whitespace-nowrap">
                      Gini {model.metrics.gini} · AUC {model.metrics.auc.toFixed(2)}
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-[11px] text-slate-400">
                    <span>Last analyzed {model.lastAnalyzed}</span>
                    <span className="flex items-center gap-1 text-indigo-600 font-semibold opacity-0 group-hover:opacity-100 transition-opacity">
                      Open
                      <ArrowRight className="w-3.5 h-3.5" />
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}