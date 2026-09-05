import { useEffect, useState } from 'react';
import { FileText, Loader2, Lock, ShieldCheck } from 'lucide-react';
import type { DocumentDetail, DocumentMeta } from '@/types';
import * as api from '@/lib/api';
import { relativeTime, toDocumentDetail, toDocumentMeta } from '@/lib/adapters';
import DocumentCompareView from '@/components/DocumentCompareView';

interface DocumentViewerProps {
  /** Active version of the model currently open in the workspace. */
  modelVersionId?: string;
  /** Document to preselect — set right after an upload. */
  initialDocumentId?: string | null;
}

type DocumentsMode = 'browse' | 'compare';

export default function DocumentViewer({
  modelVersionId,
  initialDocumentId,
}: DocumentViewerProps) {
  const [mode, setMode] = useState<DocumentsMode>('browse');
  const [documents, setDocuments] = useState<DocumentMeta[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(initialDocumentId ?? null);
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setListLoading(true);
    setListError(null);

    api
      .listDocuments()
      .then((dto) => {
        if (cancelled) return;
        const raw = Array.isArray(dto) ? dto : (dto?.documents ?? []);
        const all: DocumentMeta[] = raw.map(toDocumentMeta);
        // The list endpoint is tenant-scoped, so narrow to the model version
        // currently open in the workspace client-side.
        const scoped = modelVersionId
          ? all.filter((d) => d.modelVersionId === modelVersionId)
          : all;
        setDocuments(scoped);
        setSelectedId((prev) => {
          // A freshly uploaded document wins, then the existing selection.
          if (initialDocumentId && scoped.some((d) => d.id === initialDocumentId)) {
            return initialDocumentId;
          }
          if (prev && scoped.some((d) => d.id === prev)) return prev;
          return scoped[0]?.id ?? null;
        });
      })
      .catch((err) => {
        if (cancelled) return;
        setListError(err instanceof Error ? err.message : 'Unable to load documents');
      })
      .finally(() => {
        if (!cancelled) setListLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [modelVersionId, initialDocumentId]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }

    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);

    api
      .getDocument(selectedId)
      .then((dto) => {
        if (cancelled) return;
        setDetail(toDocumentDetail(dto));
      })
      .catch((err) => {
        if (cancelled) return;
        setDetail(null);
        setDetailError(err instanceof Error ? err.message : 'Unable to load document');
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const modeButton = (key: DocumentsMode, label: string) => (
    <button
      key={key}
      type="button"
      onClick={() => setMode(key)}
      className={`px-3.5 py-1.5 rounded-full text-xs font-bold transition-colors cursor-pointer border ${
        mode === key
          ? 'bg-indigo-600 border-indigo-600 text-white shadow-sm'
          : 'bg-white border-slate-200 text-slate-600 hover:border-indigo-300 hover:text-indigo-700'
      }`}
    >
      {label}
    </button>
  );

  if (listLoading) {
    return (
      <div className="flex items-center justify-center gap-2 p-12 text-sm text-slate-500">
        <Loader2 className="w-4 h-4 animate-spin text-indigo-600" />
        Loading documents…
      </div>
    );
  }

  if (listError) {
    return (
      <div className="bg-rose-50 border border-rose-100 rounded-2xl p-4 text-sm text-rose-700 flex items-center gap-2">
        <ShieldCheck className="w-4 h-4" />
        {listError}
      </div>
    );
  }

  if (documents.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center p-12 text-center bg-slate-50 border border-slate-200 rounded-2xl">
        <FileText className="w-8 h-8 text-slate-300" />
        <p className="mt-3 text-sm font-semibold text-slate-600">No documents for this model yet</p>
        <p className="mt-1 text-xs text-slate-400">
          Upload a validation dossier from the Regulatory Library to see its masked content here.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {modeButton('browse', 'Browse')}
          {modeButton('compare', 'Compare')}
        </div>
        <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-3 py-1">
          <Lock className="w-3 h-3" />
          Showing privacy-masked content only
        </span>
      </div>

      {mode === 'compare' ? (
        <DocumentCompareView documents={documents} />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-5">
          {/* List */}
          <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm h-fit">
            <div className="p-4 bg-slate-50 border-b border-slate-200 text-xs font-bold uppercase tracking-wider text-slate-500">
              Documents ({documents.length})
            </div>
            <div className="divide-y divide-slate-100 max-h-[520px] overflow-y-auto">
              {documents.map((doc) => (
                <button
                  key={doc.id}
                  type="button"
                  onClick={() => setSelectedId(doc.id)}
                  className={`w-full text-left p-4 flex items-start gap-3 transition-colors cursor-pointer ${
                    selectedId === doc.id ? 'bg-indigo-50/60' : 'hover:bg-slate-50'
                  }`}
                >
                  <FileText
                    className={`w-4 h-4 shrink-0 mt-0.5 ${
                      selectedId === doc.id ? 'text-indigo-600' : 'text-slate-400'
                    }`}
                  />
                  <div className="min-w-0">
                    <span className="block text-xs font-bold text-slate-900 truncate">
                      {doc.filename}
                    </span>
                    <span className="block text-[11px] text-slate-400 font-medium mt-0.5">
                      {doc.chunkCount} chunks · {relativeTime(doc.uploadTime)}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Detail */}
          <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
            {detailLoading ? (
              <div className="flex items-center justify-center gap-2 p-12 text-sm text-slate-500">
                <Loader2 className="w-4 h-4 animate-spin text-indigo-600" />
                Loading document…
              </div>
            ) : detailError ? (
              <div className="m-4 bg-rose-50 border border-rose-100 rounded-xl p-4 text-sm text-rose-700 flex items-center gap-2">
                <ShieldCheck className="w-4 h-4" />
                {detailError}
              </div>
            ) : detail ? (
              <>
                <div className="p-4 bg-slate-50 border-b border-slate-200 flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-bold text-slate-900 truncate">
                    {detail.filename}
                  </span>
                  <span className="text-[10px] font-bold px-2.5 py-0.5 rounded-full border border-slate-200 bg-white text-slate-600 uppercase tracking-wider">
                    {detail.status}
                  </span>
                </div>

                {detail.chunks.length > 0 ? (
                  <div className="divide-y divide-slate-100 max-h-[520px] overflow-y-auto">
                    {detail.chunks.map((chunk) => (
                      <div key={chunk.index} className="p-5 flex gap-4">
                        <span className="text-[10px] font-bold text-slate-300 font-mono shrink-0 pt-0.5">
                          #{chunk.index}
                        </span>
                        <p className="text-xs text-slate-700 leading-relaxed whitespace-pre-line break-words">
                          {chunk.text}
                        </p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center p-12 text-center">
                    <FileText className="w-8 h-8 text-slate-300" />
                    <p className="mt-3 text-sm font-semibold text-slate-600">
                      This document has no extracted chunks
                    </p>
                    <p className="mt-1 text-xs text-slate-400">
                      It may still be processing, or extraction may have failed.
                    </p>
                  </div>
                )}
              </>
            ) : (
              <div className="flex flex-col items-center justify-center p-12 text-center">
                <FileText className="w-8 h-8 text-slate-300" />
                <p className="mt-3 text-sm font-semibold text-slate-600">Select a document</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
