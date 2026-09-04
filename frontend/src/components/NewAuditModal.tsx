import { useState, type FormEvent } from 'react';
import { motion } from 'motion/react';
import { FileText, Loader2, Plus, ShieldCheck, UploadCloud, X } from 'lucide-react';
import { createModel, getModel, uploadDocument } from '@/lib/api';
import { toModelSummary } from '@/lib/adapters';
import type { ModelSummary } from '@/types';

interface NewAuditModalProps {
  isOpen: boolean;
  onClose: () => void;
  onAuditCreated: (model: ModelSummary) => void;
}

const MODEL_TYPES = [
  { value: 'PD', label: 'PD — Probability of Default' },
  { value: 'LGD', label: 'LGD — Loss Given Default' },
  { value: 'EAD', label: 'EAD — Exposure at Default' },
  { value: 'Credit Scoring', label: 'Credit Scoring / Application' },
  { value: 'IFRS 9 ECL', label: 'IFRS 9 ECL Provisioning' },
] as const;

export default function NewAuditModal({
  isOpen,
  onClose,
  onAuditCreated,
}: NewAuditModalProps) {
  const [name, setName] = useState('');
  const [type, setType] = useState<string>('PD');
  const [algorithm, setAlgorithm] = useState('');
  const [portfolio, setPortfolio] = useState('');
  const [description, setDescription] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);

  if (!isOpen) return null;

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!name.trim()) {
      setNameError('Model name is required.');
      return;
    }
    setNameError(null);
    setError(null);
    setSubmitting(true);
    try {
      const res = await createModel({
        name: name.trim(),
        type,
        description: description.trim() || undefined,
        portfolio: portfolio.trim() || undefined,
        algorithm: algorithm.trim() || undefined,
      });
      let finalModel = res;
      if (file && res?.current_version?.id) {
        await uploadDocument(res.current_version.id, file);
        if (res.id) {
          finalModel = await getModel(res.id);
        }
      }
      onAuditCreated(toModelSummary(finalModel));
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create audit');
    } finally {
      setSubmitting(false);
    }
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
        className="sleek-card fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-lg p-7 max-h-[90vh] overflow-y-auto z-50"
      >
        <div className="flex justify-between items-center pb-4 border-b border-slate-100">
          <div>
            <h2 className="font-display text-xl font-bold text-slate-900 tracking-tight">
              Initiate New Model Audit
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Upload documentation and configure audit scope with zero-trust PII masking.
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-full text-slate-400 hover:text-slate-700 hover:bg-slate-100 cursor-pointer transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 pt-5 text-sm">
          <div>
            <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
              Model Name *
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Commercial Real Estate PD Model"
              className="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all"
            />
            {nameError && <p className="mt-1 text-xs text-red-600">{nameError}</p>}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                Model Category
              </label>
              <select
                value={type}
                onChange={(e) => setType(e.target.value)}
                className="w-full px-3 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all"
              >
                {MODEL_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                Algorithm
              </label>
              <input
                type="text"
                value={algorithm}
                onChange={(e) => setAlgorithm(e.target.value)}
                placeholder="e.g. Logistic Regression"
                className="w-full px-3 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
              Target Lending Portfolio
            </label>
            <input
              type="text"
              value={portfolio}
              onChange={(e) => setPortfolio(e.target.value)}
              placeholder="e.g. Prime Residential Mortgages"
              className="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all"
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder="Brief description of the model, methodology, and validation scope."
              className="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 resize-none transition-all"
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
              Validation Document (PDF / DOCX)
            </label>
            <input
              id="new-audit-file"
              type="file"
              accept=".pdf,.docx"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="hidden"
            />
            <label
              htmlFor="new-audit-file"
              className="p-4 border-2 border-dashed border-slate-200 rounded-2xl bg-slate-50 hover:bg-indigo-50/30 hover:border-indigo-300 transition-all flex items-center justify-center gap-2.5 text-xs text-slate-600 cursor-pointer"
            >
              {file ? (
                <FileText className="w-4 h-4 text-indigo-600" />
              ) : (
                <UploadCloud className="w-4 h-4 text-indigo-600" />
              )}
              <span>{file ? file.name : 'Click to select a validation dossier (optional)'}</span>
            </label>
          </div>

          <div className="p-3.5 bg-emerald-50 border border-emerald-200 rounded-2xl flex items-center gap-2.5 text-xs text-emerald-800 font-medium">
            <ShieldCheck className="w-4 h-4 text-emerald-600 shrink-0" />
            <span>Zero-trust privacy pipeline enabled: PII & bank identities will be auto-masked.</span>
          </div>

          {error && (
            <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <div className="flex justify-end gap-3 pt-3">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-xs font-semibold text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-xl transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed text-white text-xs font-semibold rounded-xl shadow-md shadow-indigo-200 transition-all flex items-center gap-2 cursor-pointer active:scale-[0.98]"
            >
              {submitting ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Processing Audit…</span>
                </>
              ) : (
                <>
                  <Plus className="w-3.5 h-3.5" />
                  <span>Create Audit</span>
                </>
              )}
            </button>
          </div>
        </form>
      </motion.div>
    </>
  );
}