import { useState } from 'react';
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
  const [includeCitations, setIncludeCitations] = useState(true);
  const [includeAuditTrail, setIncludeAuditTrail] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  function handleClose() {
    setError(null);
    onClose();
  }

  async function handleDownload() {
    setDownloading(true);
    setError(null);
    try {
      const payload = await getModelExport(currentModel.id, {
        includeCitations,
        includeAuditTrail,
      });
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
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to export report data');
    } finally {
      setDownloading(false);
    }
  }

  const contents = [
    'model summary and version history',
    includeAuditTrail && 'document audit trail',
    includeCitations && 'AI Analyst citations',
  ].filter(Boolean) as string[];

  return (
    <>
      <motion.div
        onClick={handleClose}
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
            onClick={handleClose}
            className="p-2 rounded-full text-slate-400 hover:text-slate-700 hover:bg-slate-100 cursor-pointer transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="py-5 space-y-4 text-sm">
          <div className="space-y-2.5">
            <label className="flex items-start gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                checked={includeAuditTrail}
                onChange={(e) => setIncludeAuditTrail(e.target.checked)}
                className="rounded accent-indigo-600 w-4 h-4 cursor-pointer mt-0.5"
              />
              <span className="text-xs text-slate-800">
                Include audit trail
                <span className="block text-[11px] text-slate-400">
                  Every document uploaded for this model, with upload time and processing status.
                </span>
              </span>
            </label>

            <label className="flex items-start gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                checked={includeCitations}
                onChange={(e) => setIncludeCitations(e.target.checked)}
                className="rounded accent-indigo-600 w-4 h-4 cursor-pointer mt-0.5"
              />
              <span className="text-xs text-slate-800">
                Include citations
                <span className="block text-[11px] text-slate-400">
                  Sources cited by AI Analyst answers about this model.
                </span>
              </span>
            </label>
          </div>

          <div className="p-4 bg-slate-50 rounded-2xl border border-slate-200 text-xs text-slate-700 space-y-1.5">
            <div className="flex items-center gap-2 font-bold text-slate-900">
              <FileText className="w-4 h-4 text-indigo-600" />
              <span>JSON report</span>
            </div>
            <p className="text-[11px] text-slate-500">Contains the {contents.join(', ')}.</p>
          </div>

          {error && (
            <div className="p-4 text-xs text-red-600 bg-red-50 border border-red-100 rounded-xl">
              {error}
            </div>
          )}

          <div className="flex items-center gap-2 text-[11px] text-slate-400">
            <Lock className="w-3.5 h-3.5" />
            <span>Report data is fetched from the audit server when you download.</span>
          </div>
        </div>

        <div className="flex justify-end gap-3 pt-3 border-t border-slate-100">
          <button
            onClick={handleClose}
            className="px-4 py-2 text-xs font-semibold text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-xl transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <button
            onClick={handleDownload}
            disabled={downloading}
            className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed text-white text-xs font-semibold rounded-xl shadow-md shadow-indigo-200 transition-all flex items-center gap-2 cursor-pointer active:scale-[0.98]"
          >
            {downloading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Download className="w-4 h-4" />
            )}
            <span>{downloading ? 'Preparing…' : 'Download JSON'}</span>
          </button>
        </div>
      </motion.div>
    </>
  );
}
