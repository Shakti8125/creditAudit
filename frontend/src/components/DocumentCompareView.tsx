import { useEffect, useState } from 'react';
import { FileText, GitCompareArrows, Loader2, ShieldCheck } from 'lucide-react';
import type { DocumentComparisonResult, DocumentMeta } from '@/types';
import * as api from '@/lib/api';
import { toDocumentComparison } from '@/lib/adapters';

interface DocumentCompareViewProps {
  documents: DocumentMeta[];
}

export default function DocumentCompareView({ documents }: DocumentCompareViewProps) {
  const [docAId, setDocAId] = useState<string>(() => documents[0]?.id ?? '');
  const [docBId, setDocBId] = useState<string>(
    () => documents.find((d) => d.id !== documents[0]?.id)?.id ?? '',
  );
  const [result, setResult] = useState<DocumentComparisonResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!docAId || !docBId || docAId === docBId) {
      setResult(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    api
      .compareDocuments(docAId, docBId)
      .then((dto) => {
        if (cancelled) return;
        setResult(toDocumentComparison(dto));
      })
      .catch((err) => {
        if (cancelled) return;
        setResult(null);
        setError(err instanceof Error ? err.message : 'Unable to compare documents');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [docAId, docBId]);

  const pickerClass =
    'w-full pl-3 pr-9 py-2.5 rounded-xl border border-slate-200 bg-white text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-600/20 focus:border-indigo-600 cursor-pointer';

  const options = documents.map((d) => (
    <option key={d.id} value={d.id}>
      {d.filename}
    </option>
  ));

  if (documents.length < 2) {
    return (
      <div className="flex flex-col items-center justify-center p-12 text-center bg-slate-50 border border-slate-200 rounded-2xl">
        <GitCompareArrows className="w-8 h-8 text-slate-300" />
        <p className="mt-3 text-sm font-semibold text-slate-600">Not enough documents to compare</p>
        <p className="mt-1 text-xs text-slate-400">
          Upload at least two validation documents for this model to run a differential analysis.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-bold text-slate-500 uppercase tracking-wider">
            Document A
          </label>
          <select className={pickerClass} value={docAId} onChange={(e) => setDocAId(e.target.value)}>
            {options}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-bold text-slate-500 uppercase tracking-wider">
            Document B
          </label>
          <select className={pickerClass} value={docBId} onChange={(e) => setDocBId(e.target.value)}>
            {options}
          </select>
        </div>
      </div>

      {docAId === docBId && (
        <div className="bg-slate-50 border border-slate-200 rounded-2xl p-5 flex items-center gap-3 text-sm text-slate-600">
          <GitCompareArrows className="w-5 h-5 text-indigo-600" />
          <p>Select two different documents to view a meaningful comparison.</p>
        </div>
      )}

      {error && (
        <div className="bg-rose-50 border border-rose-100 rounded-2xl p-4 text-sm text-rose-700 flex items-center gap-2">
          <ShieldCheck className="w-4 h-4" />
          {error}
        </div>
      )}

      {loading && (
        <div className="bg-slate-50 border border-slate-200 rounded-2xl p-6 flex items-center justify-center gap-2 text-sm text-slate-500">
          <Loader2 className="w-4 h-4 animate-spin text-indigo-600" />
          Comparing documents…
        </div>
      )}

      {!loading && result && docAId !== docBId && (
        <div className="space-y-5">
          <div className="bg-indigo-50/60 border border-indigo-100 rounded-2xl p-5">
            <h3 className="text-xs font-bold text-indigo-600 uppercase tracking-wider mb-2">
              Comparison Summary
            </h3>
            <p className="text-sm text-slate-800 leading-relaxed whitespace-pre-line">
              {result.summary || 'No summary returned.'}
            </p>
          </div>

          {result.differences.length > 0 ? (
            <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
              <div className="p-4 bg-slate-50 border-b border-slate-200 text-xs font-bold uppercase tracking-wider text-slate-500">
                Identified Differences ({result.differences.length})
              </div>
              <div className="divide-y divide-slate-100">
                {result.differences.map((diff, idx) => (
                  <div key={`${diff.category}-${idx}`} className="p-5 flex flex-col gap-3">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-bold px-2.5 py-0.5 rounded-full border border-indigo-200 bg-indigo-50 text-indigo-700 uppercase tracking-wider">
                        {diff.category || 'General'}
                      </span>
                    </div>
                    <p className="text-xs text-slate-600 leading-relaxed">{diff.description}</p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div className="bg-slate-50 border border-slate-200 rounded-xl p-3">
                        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1">
                          Document A
                        </span>
                        <span className="text-xs text-slate-900 font-semibold break-words">
                          {diff.docAValue || '—'}
                        </span>
                      </div>
                      <div className="bg-indigo-50/60 border border-indigo-100 rounded-xl p-3">
                        <span className="text-[10px] font-bold text-indigo-500 uppercase tracking-wider block mb-1">
                          Document B
                        </span>
                        <span className="text-xs text-slate-900 font-semibold break-words">
                          {diff.docBValue || '—'}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center p-10 text-center bg-slate-50 border border-slate-200 rounded-2xl">
              <FileText className="w-8 h-8 text-slate-300" />
              <p className="mt-3 text-sm font-semibold text-slate-600">No differences reported</p>
              <p className="mt-1 text-xs text-slate-400">
                The analyst found no material discrepancies between these two documents.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
