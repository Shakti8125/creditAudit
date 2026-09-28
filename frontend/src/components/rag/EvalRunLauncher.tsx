import { useState } from 'react';
import { FlaskConical, Loader2, Play } from 'lucide-react';
import { ApiError } from '@/lib/http';
import { createEvalRuns } from '@/lib/ragApi';
import type { EvalRunCreateResponse, JudgeMode, RetrievalMode } from '@/lib/ragTypes';
import { JUDGE_LABEL, MODE_LABEL, MODE_ORDER, errorMessage, estimateLlmCalls, fmtCompact } from '@/lib/ragFormat';
import { Card, ErrorState, buttonPrimary, inputClass } from './ui';

interface EvalRunLauncherProps {
  activeCaseCount: number;
  selectedActiveCaseIds: string[];
  selectedInactiveCount: number;
  casesLoading: boolean;
  casesError: string | null;
  runActive: boolean;
  onGoToDataset: () => void;
  onLaunched: (res: EvalRunCreateResponse) => void;
}

type Scope = 'all' | 'selected';

export default function EvalRunLauncher({
  activeCaseCount,
  selectedActiveCaseIds,
  selectedInactiveCount,
  casesLoading,
  casesError,
  runActive,
  onGoToDataset,
  onLaunched,
}: EvalRunLauncherProps) {
  const [modes, setModes] = useState<RetrievalMode[]>(['hybrid_rerank']);
  const [topK, setTopK] = useState('5');
  const [includeGen, setIncludeGen] = useState(false);
  const [judge, setJudge] = useState<JudgeMode>('auto');
  const [label, setLabel] = useState('');
  const [scope, setScope] = useState<Scope>('all');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const k = Number(topK);
  const kValid = Number.isInteger(k) && k >= 1 && k <= 20;
  const effectiveScope: Scope = scope === 'selected' && selectedActiveCaseIds.length > 0 ? 'selected' : 'all';
  const caseCount = effectiveScope === 'selected' ? selectedActiveCaseIds.length : activeCaseCount;
  const estimate = estimateLlmCalls(modes, caseCount, includeGen, judge);
  const orderedModes = MODE_ORDER.filter((m) => modes.includes(m));
  const callKinds = [
    modes.some((m) => m !== 'bm25') && 'embed',
    modes.includes('hybrid_rerank') && 'rerank',
    includeGen && 'generation',
    includeGen && judge === 'auto' && 'judge',
  ].filter((x): x is string => Boolean(x));

  const blockers: string[] = [];
  if (modes.length === 0) blockers.push('Select at least one retrieval mode.');
  if (!kValid) blockers.push('top_k must be a whole number from 1 to 20.');
  if (!casesLoading && caseCount === 0) blockers.push('There are no active cases to evaluate.');
  if (caseCount > 200) blockers.push('At most 200 cases can be evaluated per run.');

  const toggleMode = (m: RetrievalMode) =>
    setModes((prev) => (prev.includes(m) ? prev.filter((x) => x !== m) : [...prev, m]));

  async function launch() {
    if (blockers.length > 0 || submitting || runActive) return;
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const res = await createEvalRuns({
        modes: orderedModes,
        top_k: k,
        include_generation: includeGen,
        judge,
        case_ids: effectiveScope === 'selected' ? selectedActiveCaseIds : null,
        label: label.trim() ? label.trim() : null,
      });
      setNotice(
        `Started ${res.runs.length} run${res.runs.length === 1 ? '' : 's'} · ≈ ${fmtCompact(
          res.estimated_llm_calls,
        )} LLM calls.`,
      );
      onLaunched(res);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('Another evaluation is already running.');
      } else {
        setError(errorMessage(err, 'Could not start the evaluation'));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card
      title={
        <span className="inline-flex items-center gap-2">
          <FlaskConical className="h-4.5 w-4.5 text-indigo-600" />
          Run an offline evaluation
        </span>
      }
      subtitle="Replays the golden dataset through the retrieval pipeline and scores relevance (and optionally the generated answers)."
    >
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="space-y-5">
          <fieldset>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <legend className="text-xs font-bold uppercase tracking-wider text-slate-500">Retrieval modes</legend>
              <button
                type="button"
                onClick={() => setModes([...MODE_ORDER])}
                className="cursor-pointer text-xs font-semibold text-indigo-600 hover:text-indigo-800"
              >
                Compare all modes
              </button>
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {MODE_ORDER.map((m) => (
                <label
                  key={m}
                  className={`flex cursor-pointer items-center gap-2.5 rounded-xl border px-3 py-2 text-sm transition-colors ${
                    modes.includes(m)
                      ? 'border-indigo-200 bg-indigo-50/60 text-indigo-800'
                      : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={modes.includes(m)}
                    onChange={() => toggleMode(m)}
                    className="h-4 w-4 cursor-pointer accent-indigo-600"
                  />
                  <span className="min-w-0">{MODE_LABEL[m]}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-[8rem_1fr]">
            <label className="block">
              <span className="mb-1.5 block text-xs font-bold uppercase tracking-wider text-slate-500">top_k</span>
              <input
                type="number"
                min={1}
                max={20}
                step={1}
                value={topK}
                onChange={(e) => setTopK(e.target.value)}
                className={inputClass}
                aria-invalid={!kValid}
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-xs font-bold uppercase tracking-wider text-slate-500">
                Label (optional)
              </span>
              <input
                type="text"
                maxLength={120}
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="e.g. Baseline Sept"
                className={inputClass}
              />
            </label>
          </div>

          <div className="space-y-2.5">
            <label className="flex cursor-pointer items-center gap-2.5 text-sm font-medium text-slate-700">
              <input
                type="checkbox"
                role="switch"
                checked={includeGen}
                onChange={(e) => setIncludeGen(e.target.checked)}
                className="h-4 w-4 cursor-pointer accent-indigo-600"
              />
              Also evaluate generated answers
            </label>
            {includeGen && (
              <fieldset className="ml-6 space-y-1.5">
                <legend className="sr-only">Judge</legend>
                {(['auto', 'deterministic'] as JudgeMode[]).map((j) => (
                  <label key={j} className="flex cursor-pointer items-center gap-2 text-sm text-slate-600">
                    <input
                      type="radio"
                      name="eval-judge"
                      checked={judge === j}
                      onChange={() => setJudge(j)}
                      className="h-4 w-4 cursor-pointer accent-indigo-600"
                    />
                    {JUDGE_LABEL[j]}
                  </label>
                ))}
              </fieldset>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <fieldset className="space-y-2">
            <legend className="mb-1 text-xs font-bold uppercase tracking-wider text-slate-500">Case scope</legend>
            <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-700">
              <input
                type="radio"
                name="eval-scope"
                checked={effectiveScope === 'all'}
                onChange={() => setScope('all')}
                className="h-4 w-4 cursor-pointer accent-indigo-600"
              />
              All active cases ({casesLoading ? '…' : activeCaseCount})
            </label>
            <label
              className={`flex items-center gap-2 text-sm ${
                selectedActiveCaseIds.length === 0 ? 'cursor-not-allowed text-slate-400' : 'cursor-pointer text-slate-700'
              }`}
            >
              <input
                type="radio"
                name="eval-scope"
                checked={effectiveScope === 'selected'}
                disabled={selectedActiveCaseIds.length === 0}
                onChange={() => setScope('selected')}
                className="h-4 w-4 cursor-pointer accent-indigo-600 disabled:cursor-not-allowed"
              />
              Selected cases ({selectedActiveCaseIds.length})
            </label>
            {selectedActiveCaseIds.length === 0 && (
              <p className="pl-6 text-xs text-slate-500">
                Pick cases in the{' '}
                <button
                  type="button"
                  onClick={onGoToDataset}
                  className="cursor-pointer font-semibold text-indigo-600 hover:underline"
                >
                  Golden dataset
                </button>{' '}
                tab to run a subset.
              </p>
            )}
            {effectiveScope === 'selected' && selectedInactiveCount > 0 && (
              <p className="pl-6 text-xs text-amber-700">
                {selectedInactiveCount} selected inactive case{selectedInactiveCount === 1 ? '' : 's'} will be skipped.
              </p>
            )}
            {casesError && <p className="text-xs text-rose-600">{casesError}</p>}
          </fieldset>

          <div className="border-t border-slate-200 pt-3">
            <p className="text-sm text-slate-600">
              <span className="text-2xl font-bold text-slate-900">≈ {fmtCompact(estimate)}</span> LLM calls
            </p>
            <p className="mt-0.5 text-xs text-slate-500">
              {orderedModes.length} mode{orderedModes.length === 1 ? '' : 's'} × {caseCount} case
              {caseCount === 1 ? '' : 's'}
              {callKinds.length > 0 ? ` · ${callKinds.join(', ')}` : ' · BM25 needs no LLM calls'}
            </p>
          </div>

          <button
            type="button"
            onClick={() => void launch()}
            disabled={blockers.length > 0 || submitting || runActive || casesLoading}
            className={buttonPrimary}
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            Run evaluation
          </button>
          {runActive && !submitting && (
            <p className="text-xs text-slate-500">An evaluation is in progress; wait for it to finish or cancel it.</p>
          )}
          {blockers.length > 0 && !casesLoading && (
            <ul className="space-y-0.5 text-xs text-amber-700">
              {blockers.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          )}
          {error && <ErrorState compact message={error} />}
          {notice && !error && (
            <p className="text-xs font-medium text-emerald-700" role="status">
              {notice}
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}
