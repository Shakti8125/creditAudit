import { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { Download, FileText, Loader2, Lock, X } from 'lucide-react';
import { getModelExport } from '@/lib/api';
import type { ModelSummary } from '@/types';

interface ExportReportModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentModel: ModelSummary;
}

export default function ExportReportModal({
  isOpen,
  onClose,
  currentModel,
}: ExportReportModalProps) {
  const [exportData, setExportData] = useState<unknown>(null);
  const [includeCitations, setIncludeCitations] = useState(true);
  const [includeAuditTrail, setIncludeAuditTrail] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await getModelExport(currentModel.id);
        if (!cancelled) setExportData(res);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unable to load export data');
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

  function handleDownload() {
    if (exportData == null) return;
    const payload = {
      ...(exportData as Record<string, unknown>),
      export_options: {
        include_citations: includeCitations,
        include_audit_trail: includeAuditTrail,
      },
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${currentModel.name.replace(/\s+/g, '_')}_Validation_Report.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

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
        className="sleek-card fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-md p-7 z-50"
      >
        <div className="flex justify-between items-center pb-4 border-b border-slate-100">
          <div>
            <h2 className="font-display text-xl font-bold text-slate-900 tracking-tight">
              Export Validation Report
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">{currentModel.name}</p>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-full text-slate-400 hover:text-slate-700 hover:bg-slate-100 cursor-pointer transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="py-5 space-y-4 text-sm">
          <div>
            <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-2">
              Export Format
            </label>
            <div className="grid grid-cols-3 gap-2.5">
              <button
                type="button"
                disabled
                className="py-2.5 px-3 rounded-xl border text-xs font-bold uppercase transition-all bg-slate-50 text-slate-400 border-slate-200 cursor-not-allowed"
                title="Not yet available"
              >
                PDF
              </button>
              <button
                type="button"
                disabled
                className="py-2.5 px-3 rounded-xl border text-xs font-bold uppercase transition-all bg-slate-50 text-slate-400 border-slate-200 cursor-not-allowed"
                title="Not yet available"
              >
                DOCX
              </button>
              <button
                type="button"
                className="py-2.5 px-3 rounded-xl border text-xs font-bold uppercase transition-all cursor-pointer bg-indigo-600 text-white border-indigo-600 shadow-md shadow-indigo-100"
              >
                JSON
              </button>
            </div>
            <p className="mt-1.5 text-[11px] text-slate-400">
              PDF and DOCX report generation is not yet available.
            </p>
          </div>

          <div className="space-y-2.5 pt-2">
            <label className="flex items-center gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                checked={includeCitations}
                onChange={(e) => setIncludeCitations(e.target.checked)}
                className="rounded accent-indigo-600 w-4 h-4 cursor-pointer"
              />
              <span className="text-xs text-slate-800">Include citations</span>
            </label>

            <label className="flex items-center gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                checked={includeAuditTrail}
                onChange={(e) => setIncludeAuditTrail(e.target.checked)}
                className="rounded accent-indigo-600 w-4 h-4 cursor-pointer"
              />
              <span className="text-xs text-slate-800">Include audit trail</span>
            </label>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-6 text-slate-400">
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
          ) : error ? (
            <div className="p-4 text-xs text-red-600 bg-red-50 border border-red-100 rounded-xl">
              {error}
            </div>
          ) : (
            exportData != null && (
              <div className="p-4 bg-slate-50 rounded-2xl border border-slate-200 text-xs text-slate-700 space-y-1.5">
                <div className="flex items-center gap-2 font-bold text-slate-900">
                  <FileText className="w-4 h-4 text-indigo-600" />
                  <span>Export payload ready</span>
                </div>
                <p className="text-[11px] text-slate-500">
                  JSON includes the model summary, lineage history, and your selected options.
                </p>
              </div>
            )
          )}

          <div className="flex items-center gap-2 text-[11px] text-slate-400">
            <Lock className="w-3.5 h-3.5" />
            <span>Export is generated client-side from the current model&apos;s data.</span>
          </div>
        </div>

        <div className="flex justify-end gap-3 pt-3 border-t border-slate-100">
          <button
            onClick={onClose}
            className="px-4 py-2 text-xs font-semibold text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-xl transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <button
            onClick={handleDownload}
            disabled={loading || exportData == null}
            className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed text-white text-xs font-semibold rounded-xl shadow-md shadow-indigo-200 transition-all flex items-center gap-2 cursor-pointer active:scale-[0.98]"
          >
            <Download className="w-4 h-4" />
            <span>Download JSON</span>
          </button>
        </div>
      </motion.div>
    </>
  );
}