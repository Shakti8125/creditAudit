import { useState } from 'react';
import TelemetryPanel from './TelemetryPanel';
import EvaluationPanel from './EvaluationPanel';
import { SegmentedControl } from './ui';

type RagTab = 'telemetry' | 'evaluation';

/**
 * RAG Performance page body: live telemetry from every retrieval-augmented answer plus
 * offline evaluation against a golden dataset. Panels are mounted on first visit and kept
 * alive so filters, selections and in-flight polling survive tab switches.
 * Loaded lazily by components/RagPerformanceView.tsx.
 */
export default function RagPerformancePage() {
  const [tab, setTab] = useState<RagTab>('telemetry');
  const [visited, setVisited] = useState<Record<RagTab, boolean>>({ telemetry: true, evaluation: false });

  const select = (t: RagTab) => {
    setTab(t);
    setVisited((prev) => (prev[t] ? prev : { ...prev, [t]: true }));
  };

  return (
    <div className="min-w-0 space-y-8">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div className="min-w-0">
          <h2 className="mb-1 text-xs font-bold uppercase tracking-wider text-indigo-600">Retrieval quality</h2>
          <h1 className="font-display text-3xl font-bold tracking-tight text-slate-900 md:text-4xl">RAG Performance</h1>
          <p className="mt-1 text-sm text-slate-500">
            Live telemetry from every retrieval-augmented answer, plus offline evaluation against a golden dataset.
          </p>
        </div>
        <div className="shrink-0">
          <SegmentedControl
            ariaLabel="RAG performance view"
            options={[
              { value: 'telemetry', label: 'Live telemetry' },
              { value: 'evaluation', label: 'Offline evaluation' },
            ]}
            value={tab}
            onChange={select}
          />
        </div>
      </div>

      {visited.telemetry && (
        <div hidden={tab !== 'telemetry'}>
          <TelemetryPanel />
        </div>
      )}
      {visited.evaluation && (
        <div hidden={tab !== 'evaluation'}>
          <EvaluationPanel />
        </div>
      )}
    </div>
  );
}
