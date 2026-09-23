import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { cancelEvalRun, deleteEvalRun, listEvalCases, listEvalRuns } from '@/lib/ragApi';
import type { EvalCase, EvalRunSummary } from '@/lib/ragTypes';
import { MODE_ORDER, errorMessage, isRunActive, ragLoadError } from '@/lib/ragFormat';
import EvalRunLauncher from './EvalRunLauncher';
import EvalRunsTable from './EvalRunsTable';
import EvalRunComparison, { type SelectedRun } from './EvalRunComparison';
import EvalRunResultsDrawer from './EvalRunResultsDrawer';
import EvalDatasetPanel from './EvalDatasetPanel';
import { SegmentedControl } from './ui';

type SubTab = 'runs' | 'dataset';

const POLL_MS = 2000;
const MAX_COMPARE = 4;
const RUN_LIST_LIMIT = 50;

interface Selection {
  id: string;
  slot: number;
}

/** Latest batch whose runs have all finished (and at least one completed): its completed runs. */
function defaultSelectionIds(runs: EvalRunSummary[]): string[] {
  const groups = new Map<string, EvalRunSummary[]>();
  for (const r of runs) {
    const g = groups.get(r.group_id);
    if (g) g.push(r);
    else groups.set(r.group_id, [r]);
  }
  for (const group of groups.values()) {
    if (group.some((r) => isRunActive(r.status))) continue;
    const done = group.filter((r) => r.status === 'completed');
    if (done.length === 0) continue;
    return done
      .sort((a, b) => MODE_ORDER.indexOf(a.mode) - MODE_ORDER.indexOf(b.mode))
      .slice(0, MAX_COMPARE)
      .map((r) => r.id);
  }
  return [];
}

export default function EvaluationPanel() {
  const [sub, setSub] = useState<SubTab>('runs');

  // ---- golden dataset (lifted: the launcher needs counts and the selection)
  const [cases, setCases] = useState<EvalCase[] | null>(null);
  const [casesLoading, setCasesLoading] = useState(true);
  const [casesError, setCasesError] = useState<string | null>(null);
  const [selectedCaseIds, setSelectedCaseIds] = useState<Set<string>>(() => new Set());

  // ---- runs
  const [runs, setRuns] = useState<EvalRunSummary[] | null>(null);
  const [runsLoading, setRunsLoading] = useState(true);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyRunIds, setBusyRunIds] = useState<Set<string>>(() => new Set());

  // ---- comparison selection: slots are assigned at selection time and stay stable
  const [selection, setSelection] = useState<Selection[]>([]);
  const [touched, setTouched] = useState(false);

  const [drawer, setDrawer] = useState<{ runId: string; caseId?: string } | null>(null);

  const mounted = useRef(true);
  const runsInFlight = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const loadCases = useCallback(async () => {
    setCasesLoading(true);
    try {
      const res = await listEvalCases(true);
      if (!mounted.current) return;
      setCases(res.cases);
      setCasesError(null);
    } catch (err) {
      if (!mounted.current) return;
      setCasesError(ragLoadError(err, 'Golden dataset'));
    } finally {
      if (mounted.current) setCasesLoading(false);
    }
  }, []);

  const loadRuns = useCallback(async () => {
    if (runsInFlight.current) return;
    runsInFlight.current = true;
    try {
      const res = await listEvalRuns(RUN_LIST_LIMIT, 0);
      if (!mounted.current) return;
      setRuns(res.runs);
      setRunsError(null);
    } catch (err) {
      if (!mounted.current) return;
      setRunsError(ragLoadError(err, 'Evaluation runs'));
    } finally {
      runsInFlight.current = false;
      if (mounted.current) setRunsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCases();
    void loadRuns();
  }, [loadCases, loadRuns]);

  // Poll while any run is pending/running; stops on completion or unmount.
  const anyActive = useMemo(() => (runs ?? []).some((r) => isRunActive(r.status)), [runs]);
  useEffect(() => {
    if (!anyActive) return;
    const id = window.setInterval(() => void loadRuns(), POLL_MS);
    return () => window.clearInterval(id);
  }, [anyActive, loadRuns]);

  // Keep selection valid; apply the default selection until the user edits it.
  useEffect(() => {
    if (!runs) return;
    const byId = new Set(runs.map((r) => r.id));
    setSelection((prev) => {
      if (!touched) {
        const ids = defaultSelectionIds(runs);
        const same = ids.length === prev.length && ids.every((id, i) => prev[i]?.id === id);
        return same ? prev : ids.map((id, slot) => ({ id, slot }));
      }
      const kept = prev.filter((s) => byId.has(s.id));
      return kept.length === prev.length ? prev : kept;
    });
  }, [runs, touched]);

  // Drop selected case ids that no longer exist.
  useEffect(() => {
    if (!cases) return;
    const ids = new Set(cases.map((c) => c.id));
    setSelectedCaseIds((prev) => {
      const next = new Set([...prev].filter((id) => ids.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [cases]);

  const toggleCompare = (id: string) => {
    setTouched(true);
    setSelection((prev) => {
      if (prev.some((s) => s.id === id)) return prev.filter((s) => s.id !== id);
      if (prev.length >= MAX_COMPARE) return prev;
      const used = new Set(prev.map((s) => s.slot));
      let slot = 0;
      while (used.has(slot)) slot += 1;
      return [...prev, { id, slot }];
    });
  };

  const withBusy = async (id: string, fn: () => Promise<unknown>) => {
    setBusyRunIds((prev) => new Set(prev).add(id));
    setActionError(null);
    try {
      await fn();
    } catch (err) {
      if (mounted.current) setActionError(errorMessage(err, 'Action failed'));
    } finally {
      if (mounted.current) {
        setBusyRunIds((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
        void loadRuns();
      }
    }
  };

  const handleCancel = (id: string) => void withBusy(id, () => cancelEvalRun(id));
  const handleDelete = (id: string) => {
    if (!window.confirm('Delete this evaluation run and its per-case results? This cannot be undone.')) return;
    void withBusy(id, () => deleteEvalRun(id));
  };

  const activeCases = useMemo(() => (cases ?? []).filter((c) => c.is_active), [cases]);
  const selectedActiveIds = useMemo(
    () => activeCases.filter((c) => selectedCaseIds.has(c.id)).map((c) => c.id),
    [activeCases, selectedCaseIds],
  );

  const runById = useMemo(() => new Map((runs ?? []).map((r) => [r.id, r])), [runs]);
  const selectedRuns: SelectedRun[] = selection
    .map((s) => {
      const run = runById.get(s.id);
      return run ? { run, slot: s.slot } : null;
    })
    .filter((x): x is SelectedRun => x != null);
  const slotById = new Map(selection.map((s) => [s.id, s.slot]));

  return (
    <div className="space-y-6">
      <SegmentedControl
        ariaLabel="Evaluation section"
        size="sm"
        options={[
          { value: 'runs', label: 'Runs' },
          { value: 'dataset', label: `Golden dataset${cases ? ` (${cases.length})` : ''}` },
        ]}
        value={sub}
        onChange={setSub}
      />

      <div hidden={sub !== 'runs'} className="space-y-6">
        <EvalRunLauncher
          activeCaseCount={activeCases.length}
          selectedActiveCaseIds={selectedActiveIds}
          selectedInactiveCount={selectedCaseIds.size - selectedActiveIds.length}
          casesLoading={casesLoading && cases == null}
          casesError={cases == null ? casesError : null}
          runActive={anyActive}
          onGoToDataset={() => setSub('dataset')}
          onLaunched={() => {
            setTouched(false);
            void loadRuns();
          }}
        />

        <EvalRunsTable
          runs={runs}
          loading={runsLoading}
          error={runsError}
          actionError={actionError}
          onRetry={() => {
            setRunsLoading(true);
            void loadRuns();
          }}
          slotById={slotById}
          canSelectMore={selection.length < MAX_COMPARE}
          onToggleCompare={toggleCompare}
          onViewResults={(runId) => setDrawer({ runId })}
          onCancel={handleCancel}
          onDelete={handleDelete}
          busyIds={busyRunIds}
        />

        <EvalRunComparison
          selected={selectedRuns}
          hasAnyRuns={(runs?.length ?? 0) > 0}
          onRemove={(id) => toggleCompare(id)}
          onOpenCase={(runId, caseId) => setDrawer({ runId, caseId })}
        />
      </div>

      <div hidden={sub !== 'dataset'}>
        <EvalDatasetPanel
          cases={cases}
          loading={casesLoading}
          error={casesError}
          onReload={() => void loadCases()}
          onCaseSaved={(c) =>
            setCases((prev) => {
              if (!prev) return [c];
              const i = prev.findIndex((x) => x.id === c.id);
              if (i === -1) return [...prev, c];
              const next = prev.slice();
              next[i] = c;
              return next;
            })
          }
          onCaseDeleted={(id) => setCases((prev) => (prev ? prev.filter((c) => c.id !== id) : prev))}
          selectedIds={selectedCaseIds}
          onSelectedChange={setSelectedCaseIds}
        />
      </div>

      <EvalRunResultsDrawer
        isOpen={drawer != null}
        run={drawer ? runById.get(drawer.runId) ?? null : null}
        focusCaseId={drawer?.caseId}
        onClose={() => setDrawer(null)}
      />
    </div>
  );
}
