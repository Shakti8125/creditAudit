import { useEffect, useState } from 'react';
import {
  ArrowRight,
  GitCompareArrows,
  Loader2,
  Plus,
  ShieldCheck,
  TrendingDown,
} from 'lucide-react';
import type { ComparisonDiff, ComparisonModel, ModelSummary } from '@/types';
import * as api from '@/lib/api';
import { toComparisonModel } from '@/lib/adapters';

interface CompareModelsViewProps {
  models: ModelSummary[];
  currentModel: ModelSummary;
  onSelectModel: (m: ModelSummary) => void;
}

interface ComparisonResult {
  baseline: ComparisonModel;
  challenger: ComparisonModel;
}

function diffClassFor(type?: ComparisonDiff['type']): string {
  if (type === 'added') return 'diff-added';
  if (type === 'changed') return 'diff-changed';
  if (type === 'removed') return 'diff-removed';
  return '';
}

function ModelCard({ model }: { model: ComparisonModel }) {
  const isChallenger = model.role === 'challenger';

  return (
    <section
      className={`bg-white rounded-3xl p-7 flex flex-col gap-6 shadow-sm ${
        isChallenger
          ? 'border-2 border-indigo-200 shadow-md shadow-indigo-50/50'
          : 'border border-slate-200'
      }`}
    >
      <div className="border-b border-slate-100 pb-4 flex justify-between items-end">
        <div>
          <span
            className={`text-[11px] font-bold uppercase tracking-wider block mb-0.5 ${
              isChallenger ? 'text-indigo-600' : 'text-slate-400'
            }`}
          >
            {isChallenger ? 'Challenger Candidate' : 'Baseline Model'}
          </span>
          <h3 className="text-xl font-bold text-slate-900">{model.title}</h3>
        </div>
        <span
          className={`text-xs font-bold px-3 py-1 rounded-full shadow-xs ${
            isChallenger
              ? 'bg-indigo-600 text-white'
              : 'bg-slate-100 text-slate-600'
          }`}
        >
          {model.version}
        </span>
      </div>

      {/* Methodology */}
      <div className="flex flex-col gap-2">
        <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">Methodology</h4>
        <div className="bg-slate-50 border border-slate-200 rounded-2xl p-4 text-xs text-slate-800 leading-relaxed">
          <p>{model.methodology}</p>
          {model.methodologyDiff && (
            <div
              className={`mt-2.5 px-3 py-1.5 rounded-lg inline-flex items-center gap-1.5 text-xs font-semibold ${diffClassFor(
                model.methodologyDiff.type,
              )}`}
            >
              {model.methodologyDiff.type === 'added' && <Plus className="w-3.5 h-3.5" />}
              {model.methodologyDiff.type === 'removed' && (
                <TrendingDown className="w-3.5 h-3.5" />
              )}
              <span>{model.methodologyDiff.text}</span>
            </div>
          )}
        </div>
      </div>

      {/* Data Configuration */}
      <div className="flex flex-col gap-2">
        <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
          Data Configuration
        </h4>
        <div className="bg-slate-50 border border-slate-200 rounded-2xl p-4 text-xs text-slate-800 leading-relaxed space-y-2.5">
          <p>{model.dataConfig}</p>
          {model.dataConfigDiff && (
            <div
              className={`px-3 py-2 rounded-xl inline-flex flex-wrap items-center gap-1 text-xs font-medium ${diffClassFor(
                model.dataConfigDiff.type,
              )}`}
            >
              <span>{model.dataConfigDiff.text ?? 'Observation window changed'}</span>
              {model.dataConfigDiff.oldVal && model.dataConfigDiff.newVal && (
                <>
                  <span>from</span>
                  <del className="opacity-50 mx-0.5">{model.dataConfigDiff.oldVal}</del>
                  <span>to</span>
                  <span className="font-bold font-mono">{model.dataConfigDiff.newVal}</span>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Performance Metrics */}
      <div className="flex flex-col gap-2">
        <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
          Performance Metrics
        </h4>
        <div className="space-y-2">
          {model.metrics.map((m, i) => (
            <div
              key={i}
              className={`rounded-xl p-3.5 text-xs text-slate-800 flex justify-between items-center border ${
                m.isDiff
                  ? m.oldValue
                    ? 'diff-changed'
                    : 'diff-added'
                  : 'bg-slate-50 border-slate-200'
              }`}
            >
              <span className="text-slate-600 font-medium">{m.name}</span>
              <div className="flex items-center gap-2 font-mono text-xs font-bold">
                {m.oldValue && (
                  <del className="opacity-40 text-slate-400">{m.oldValue}</del>
                )}
                {m.isDiff && <ArrowRight className="w-3.5 h-3.5 text-indigo-600" />}
                <span className="text-slate-900 text-sm">{m.value}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Validation Findings */}
      <div className="flex flex-col gap-2">
        <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
          Validation Findings
        </h4>
        <div
          className={`rounded-xl p-3.5 text-xs text-slate-800 flex items-center justify-between border ${
            isChallenger && model.findings.diffNote
              ? 'bg-emerald-50/50 border-emerald-200'
              : 'bg-slate-50 border-slate-200'
          }`}
        >
          <span className="text-slate-700 font-semibold">
            {model.findings.label}
            {model.findings.resolvedCount !== undefined &&
              ` · ${model.findings.resolvedCount} resolved`}
          </span>
          <div className="flex items-center gap-2">
            {model.findings.diffNote && (
              <span className="text-emerald-700 font-bold">{model.findings.diffNote}</span>
            )}
            <span
              className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                model.findings.diffNote
                  ? 'bg-emerald-100 text-emerald-700'
                  : 'bg-amber-100 text-amber-700'
              }`}
            >
              {model.findings.openCount}
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}

export default function CompareModelsView({
  models,
  currentModel,
  onSelectModel,
}: CompareModelsViewProps) {
  const [baselineId, setBaselineId] = useState<string>(currentModel.id);
  const [challengerId, setChallengerId] = useState<string>(
    () => models.find((m) => m.id !== currentModel.id)?.id ?? currentModel.id,
  );
  const [result, setResult] = useState<ComparisonResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    api
      .compareModels(baselineId, challengerId)
      .then((dto) => {
        if (cancelled) return;
        setResult({
          baseline: toComparisonModel(dto.baseline),
          challenger: toComparisonModel(dto.challenger),
        });
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Unable to compare models');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [baselineId, challengerId]);

  const selectOptions = models.map((m) => (
    <option key={m.id} value={m.id}>
      {m.name} — {m.version}
    </option>
  ));

  const pickerClass =
    'w-full pl-3 pr-9 py-2.5 rounded-xl border border-slate-200 bg-white text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-600/20 focus:border-indigo-600 cursor-pointer';

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h2 className="text-xs font-bold text-indigo-600 uppercase tracking-wider mb-1">
          Architectural Differential Analysis
        </h2>
        <h1 className="font-display text-3xl font-bold text-slate-900 tracking-tight flex flex-wrap items-center gap-3">
          <span>{currentModel.name}</span>
          <span className="text-slate-400 font-normal">— Baseline vs Challenger</span>
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Side-by-side architectural diff comparing baseline production model against challenger
          validation runs.
        </p>
      </div>

      {/* Pickers */}
      <div className="sleek-card p-6 grid grid-cols-1 md:grid-cols-2 gap-5">
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-bold text-slate-500 uppercase tracking-wider">
            Baseline Model
          </label>
          <select
            className={pickerClass}
            value={baselineId}
            onChange={(e) => {
              const id = e.target.value;
              setBaselineId(id);
              const model = models.find((m) => m.id === id);
              if (model) onSelectModel(model);
            }}
          >
            {selectOptions}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-bold text-slate-500 uppercase tracking-wider">
            Challenger Model
          </label>
          <select
            className={pickerClass}
            value={challengerId}
            onChange={(e) => setChallengerId(e.target.value)}
          >
            {selectOptions}
          </select>
        </div>
      </div>

      {baselineId === challengerId && (
        <div className="sleek-card p-5 flex items-center gap-3 text-sm text-slate-600">
          <GitCompareArrows className="w-5 h-5 text-indigo-600" />
          <p>
            Baseline and challenger are the same model. Select a different challenger to view a
            meaningful comparison.
          </p>
        </div>
      )}

      {error && (
        <div className="bg-rose-50 border border-rose-100 rounded-2xl p-4 text-sm text-rose-700 flex items-center gap-2">
          <ShieldCheck className="w-4 h-4" />
          {error}
        </div>
      )}

      {loading && (
        <div className="sleek-card p-6 flex items-center justify-center gap-2 text-sm text-slate-500">
          <Loader2 className="w-4 h-4 animate-spin text-indigo-600" />
          Retrieving comparison…
        </div>
      )}

      {!loading && result && baselineId !== challengerId && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 relative">
          <div className="hidden lg:flex absolute left-1/2 top-0 bottom-0 -translate-x-1/2 w-px bg-slate-200 items-start pt-10 z-10">
            <div className="bg-slate-900 text-white rounded-full w-9 h-9 flex items-center justify-center text-xs font-bold absolute left-1/2 -translate-x-1/2 shadow-md">
              VS
            </div>
          </div>
          <ModelCard model={result.baseline} />
          <ModelCard model={result.challenger} />
        </div>
      )}
    </div>
  );
}