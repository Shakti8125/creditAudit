import { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { GitBranch, GitCommit, GitFork, Loader2, X } from 'lucide-react';
import { getModelVersions } from '@/lib/api';
import type { ModelSummary } from '@/types';

interface ModelLineageModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentModel: ModelSummary;
}

interface VersionNode {
  id: string;
  version: string;
  isCurrent: boolean;
  gini: string;
  status: 'PASS' | 'WARNING' | 'BREACH' | null;
}

function giniLabel(metrics: any): string {
  const value = Number(metrics?.gini?.value);
  return Number.isFinite(value) && value !== 0 ? `${value}%` : '—';
}

function deriveStatus(gapAnalysis: any): VersionNode['status'] {
  const results: any[] = gapAnalysis?.results ?? [];
  if (!Array.isArray(results) || results.length === 0) return null;
  let breach = 0;
  let warning = 0;
  let pass = 0;
  for (const r of results) {
    const s = r?.status;
    if (s === 'BREACH') breach += 1;
    else if (s === 'WARNING') warning += 1;
    else if (s === 'PASS') pass += 1;
  }
  if (breach > 0) return 'BREACH';
  if (warning > 0) return 'WARNING';
  if (pass > 0) return 'PASS';
  return null;
}

const STATUS_BADGE: Record<'PASS' | 'WARNING' | 'BREACH', string> = {
  PASS: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  WARNING: 'bg-amber-50 text-amber-700 border-amber-200',
  BREACH: 'bg-rose-50 text-rose-700 border-rose-200',
};

export default function ModelLineageModal({
  isOpen,
  onClose,
  currentModel,
}: ModelLineageModalProps) {
  const [nodes, setNodes] = useState<VersionNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await getModelVersions(currentModel.id);
        if (cancelled) return;
        const data: any[] = Array.isArray(res) ? res : (res as any)?.items ?? [];
        setNodes(
          data.map((v: any) => ({
            id: String(v.id ?? v.version),
            version: v.version ?? '—',
            isCurrent: !!v.is_current,
            gini: giniLabel(v.metrics),
            status: deriveStatus(v.gap_analysis),
          })),
        );
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unable to load lineage');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [isOpen, currentModel.id]);

  if (!isOpen) return null;

  return (
    <>
      <motion.div
        onClick={onClose}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50"
      />

      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.15, ease: 'easeOut' }}
        className="sleek-card fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-xl p-7 max-h-[85vh] overflow-y-auto z-50"
      >
        <div className="flex justify-between items-center pb-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-indigo-50 border border-indigo-100 text-indigo-600 flex items-center justify-center shadow-xs">
              <GitFork className="w-5 h-5" />
            </div>
            <div>
              <h2 className="font-display text-xl font-bold text-slate-900 tracking-tight">
                Model Lineage & Genealogy
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                {currentModel.name} — Version History & Iterations
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-full text-slate-400 hover:text-slate-700 hover:bg-slate-100 cursor-pointer transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="py-6">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-slate-400">
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
          ) : error ? (
            <div className="p-4 text-xs text-red-600 bg-red-50 border border-red-100 rounded-xl">
              {error}
            </div>
          ) : nodes.length === 0 ? (
            <div className="p-8 text-center text-xs text-slate-400">
              No version history available for this model.
            </div>
          ) : (
            <div className="space-y-6">
              {nodes.map((node, index) => (
                <div key={node.id} className="relative flex items-start gap-4">
                  {index < nodes.length - 1 && (
                    <div className="absolute left-[17px] top-9 bottom-[-24px] w-[2px] bg-slate-200" />
                  )}

                  <div
                    className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 z-10 ${
                      node.isCurrent
                        ? 'bg-indigo-600 text-white shadow-md shadow-indigo-200 ring-4 ring-indigo-50'
                        : 'bg-slate-100 text-slate-500 border border-slate-200'
                    }`}
                  >
                    {node.isCurrent ? (
                      <GitCommit className="w-4 h-4" />
                    ) : (
                      <GitBranch className="w-4 h-4" />
                    )}
                  </div>

                  <div
                    className={`flex-1 p-4 rounded-2xl border transition-all ${
                      node.isCurrent
                        ? 'bg-white border-indigo-200 shadow-sm ring-1 ring-indigo-100'
                        : 'bg-slate-50 border-slate-200'
                    }`}
                  >
                    <div className="flex justify-between items-start">
                      <div>
                        <span className="font-mono text-xs font-bold text-slate-400 block mb-0.5">
                          {node.version}
                        </span>
                        <h4 className="text-sm font-bold text-slate-900">
                          {node.isCurrent ? 'Current Version' : `Version ${node.version}`}
                        </h4>
                      </div>
                      <span
                        className={`text-[10px] font-bold px-2.5 py-0.5 rounded-full uppercase tracking-wider ${
                          node.isCurrent
                            ? 'bg-amber-50 text-amber-700 border border-amber-200'
                            : 'bg-slate-200/70 text-slate-600'
                        }`}
                      >
                        {node.isCurrent ? 'Current' : 'Archived'}
                      </span>
                    </div>

                    <div className="mt-2.5 pt-2 border-t border-slate-100 flex justify-between items-center text-xs text-slate-500">
                      <span>
                        Status:{' '}
                        <strong className="text-slate-700 font-medium">
                          {node.status ? (
                            <span
                              className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-bold uppercase tracking-wider ${STATUS_BADGE[node.status]}`}
                            >
                              {node.status}
                            </span>
                          ) : (
                            '—'
                          )}
                        </strong>
                      </span>
                      <span className="font-mono font-bold text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded-md">
                        Gini: {node.gini}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="flex justify-end pt-3 border-t border-slate-100">
          <button
            onClick={onClose}
            className="px-5 py-2.5 bg-slate-900 text-white text-xs font-semibold rounded-xl hover:bg-slate-800 transition-colors cursor-pointer"
          >
            Done
          </button>
        </div>
      </motion.div>
    </>
  );
}