import { useEffect, useRef, useState, type FormEvent } from 'react';
import {
  BookOpen,
  CheckCircle2,
  ChevronDown,
  FileText,
  Loader2,
  Search,
  ShieldCheck,
  UploadCloud,
} from 'lucide-react';
import type { ModelSummary, RegulatoryStandard } from '@/types';
import * as api from '@/lib/api';
import { toRegulatoryStandard } from '@/lib/adapters';

interface RegulatoryLibraryViewProps {
  models: ModelSummary[];
  onAnalyzeDocument: (docName: string) => void;
}

interface SearchCitation {
  source: string;
  section: string;
}

interface SearchResult {
  answer: string;
  citations: SearchCitation[];
}

function statusBadge(status: string): string {
  if (status.startsWith('error') || status.startsWith('failed') || status.startsWith('Unable')) {
    return 'text-rose-600';
  }
  return 'text-indigo-600';
}

export default function RegulatoryLibraryView({
  models,
  onAnalyzeDocument,
}: RegulatoryLibraryViewProps) {
  const [standards, setStandards] = useState<RegulatoryStandard[]>([]);
  const [standardsLoading, setStandardsLoading] = useState(true);
  const [standardsError, setStandardsError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const [question, setQuestion] = useState('');
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchResult, setSearchResult] = useState<SearchResult | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);

  const [selectedModelId, setSelectedModelId] = useState<string>(models[0]?.id ?? '');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .listRegulatoryStandards()
      .then((dto) => {
        if (cancelled) return;
        const items = Array.isArray(dto) ? dto : dto?.standards ?? [];
        setStandards(items.map(toRegulatoryStandard));
      })
      .catch((err) => {
        if (cancelled) return;
        setStandardsError(
          err instanceof Error ? err.message : 'Unable to load regulatory standards',
        );
      })
      .finally(() => {
        if (!cancelled) setStandardsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSearch(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!question.trim()) return;
    setSearchLoading(true);
    setSearchError(null);
    setSearchResult(null);
    try {
      const dto = await api.regulatorySearch(question.trim());
      const citations = Array.isArray(dto.citations)
        ? dto.citations.map((c: any) => ({
            source: c.source ?? c.title ?? '',
            section: c.section ?? c.clause ?? '',
          }))
        : [];
      setSearchResult({ answer: dto.answer ?? '', citations });
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : 'Unable to search regulations');
    } finally {
      setSearchLoading(false);
    }
  }

  async function handleAnalyze(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!selectedModelId || !selectedFile) return;
    setUploading(true);
    setStatus('Uploading document…');
    setUploadError(null);
    try {
      const model = await api.getModel(selectedModelId);
      const versionId = model?.current_version?.id;
      if (!versionId) {
        throw new Error('The selected model has no active version to attach the document to.');
      }
      const upload = await api.uploadDocument(versionId, selectedFile);
      const documentId = upload?.document_id ?? upload?.id;
      if (!documentId) {
        throw new Error('Upload succeeded but no document id was returned.');
      }
      setStatus('Running gap analysis…');
      await api.runGapAnalysis(documentId);
      setStatus('Analysis complete.');
      onAnalyzeDocument(selectedFile.name);
    } catch (err) {
      setStatus(null);
      setUploadError(err instanceof Error ? err.message : 'Unable to analyze document');
    } finally {
      setUploading(false);
    }
  }

  const inputClass =
    'w-full px-3.5 py-2.5 rounded-xl border border-slate-200 bg-white text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-600/20 focus:border-indigo-600';

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h2 className="text-xs font-bold text-indigo-600 uppercase tracking-wider mb-1">
          Regulatory Compliance & Knowledge Library
        </h2>
        <h1 className="font-display text-3xl font-bold text-slate-900 tracking-tight">
          Audit Guidelines & Document Analyzer
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Benchmark model performance and conceptual soundness against Central Bank & Basel
          governance frameworks.
        </p>
      </div>

      {/* Document Upload & Analyze */}
      <section className="sleek-card p-6">
        <div className="flex items-center gap-2.5 mb-4">
          <UploadCloud className="w-5 h-5 text-indigo-600" />
          <div>
            <h3 className="text-base font-bold text-slate-900">Analyze a Model Document</h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Attach a PDF or DOCX model development document, then extract, sanitize, and run gap
              analysis against active standards.
            </p>
          </div>
        </div>

        {models.length === 0 ? (
          <div className="bg-slate-50 border border-slate-200 rounded-2xl p-5 text-sm text-slate-500 flex items-center gap-2">
            <BookOpen className="w-4 h-4 text-slate-400" />
            Create a model first, then attach validation documents to it for analysis.
          </div>
        ) : (
          <form onSubmit={handleAnalyze} className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold text-slate-500 uppercase tracking-wider">
                Target Model
              </label>
              <select
                className={inputClass}
                value={selectedModelId}
                onChange={(e) => setSelectedModelId(e.target.value)}
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name} — {m.version}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold text-slate-500 uppercase tracking-wider">
                Document (PDF / DOCX)
              </label>
              <div className="flex items-center gap-2">
                <input
                  ref={fileRef}
                  type="file"
                  accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  className="hidden"
                  onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
                />
                <button
                  type="button"
                  onClick={() => fileRef.current?.click()}
                  className="flex-1 flex items-center gap-2 px-3.5 py-2.5 rounded-xl border border-dashed border-slate-300 hover:border-indigo-400 hover:bg-slate-50 text-sm text-slate-500 cursor-pointer transition-colors"
                >
                  <FileText className="w-4 h-4 text-indigo-600" />
                  {selectedFile ? selectedFile.name : 'Choose file…'}
                </button>
              </div>
            </div>

            <div className="md:col-span-2 flex items-center gap-3">
              <button
                type="submit"
                disabled={uploading || !selectedFile}
                className="flex items-center gap-2 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed text-white rounded-xl text-sm font-semibold cursor-pointer transition-colors"
              >
                {uploading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Analyzing…
                  </>
                ) : (
                  <>
                    <ShieldCheck className="w-4 h-4" />
                    Upload & Analyze
                  </>
                )}
              </button>
              {status && (
                <span className={`text-xs font-semibold ${statusBadge(status)}`}>{status}</span>
              )}
            </div>

            {uploadError && (
              <p className="md:col-span-2 text-sm text-rose-600 bg-rose-50 border border-rose-100 rounded-lg px-3 py-2">
                {uploadError}
              </p>
            )}
          </form>
        )}
      </section>

      {/* Q&A Search */}
      <section className="sleek-card p-6">
        <div className="flex items-center gap-2.5 mb-4">
          <Search className="w-5 h-5 text-indigo-600" />
          <div>
            <h3 className="text-base font-bold text-slate-900">Regulatory Q&A</h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Ask a question about regulatory requirements and get grounded answers with citations.
            </p>
          </div>
        </div>

        <form onSubmit={handleSearch} className="flex flex-col sm:flex-row gap-2">
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="e.g. What is the minimum observation window for PD models under Basel?"
            className={`${inputClass} flex-1`}
          />
          <button
            type="submit"
            disabled={searchLoading || !question.trim()}
            className="flex items-center justify-center gap-2 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed text-white rounded-xl text-sm font-semibold cursor-pointer transition-colors"
          >
            {searchLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            Ask
          </button>
        </form>

        {searchError && (
          <p className="mt-3 text-sm text-rose-600 bg-rose-50 border border-rose-100 rounded-lg px-3 py-2">
            {searchError}
          </p>
        )}

        {searchResult && (
          <div className="mt-4 space-y-3">
            <div className="bg-slate-50 border border-slate-200 rounded-2xl p-4 text-sm text-slate-800 leading-relaxed">
              {searchResult.answer}
            </div>
            {searchResult.citations.length > 0 && (
              <div className="space-y-1.5">
                <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400 block">
                  Citations
                </span>
                {searchResult.citations.map((c, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-2 text-xs text-slate-700 bg-white border border-slate-200 rounded-xl px-3 py-2"
                  >
                    <BookOpen className="w-3.5 h-3.5 text-indigo-600" />
                    <span className="font-semibold">{c.source}</span>
                    {c.section && <span className="text-slate-400">• {c.section}</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      {/* Catalog */}
      <section className="sleek-card overflow-hidden">
        <div className="p-6 border-b border-slate-100 bg-slate-50/50">
          <h3 className="text-base font-bold text-slate-900">Regulatory Guidelines Catalog</h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Active supervisory standards used by ModelAudit AI to perform gap analysis and threshold
            checking.
          </p>
        </div>

        {standardsLoading && (
          <div className="p-6 flex items-center justify-center gap-2 text-sm text-slate-500">
            <Loader2 className="w-4 h-4 animate-spin text-indigo-600" />
            Loading standards…
          </div>
        )}

        {!standardsLoading && standardsError && (
          <div className="p-6 text-sm text-rose-600 bg-rose-50 border border-rose-100 flex items-center gap-2">
            <ShieldCheck className="w-4 h-4" />
            {standardsError}
          </div>
        )}

        {!standardsLoading && !standardsError && standards.length === 0 && (
          <div className="p-6 text-sm text-slate-500">No regulatory standards available.</div>
        )}

        {!standardsLoading && !standardsError && (
          <div className="divide-y divide-slate-100">
            {standards.map((std) => {
              const expanded = expandedId === std.id;
              return (
                <div key={std.id} className="p-6 hover:bg-slate-50/50 transition-all flex flex-col gap-4">
                  <div className="flex flex-col md:flex-row justify-between md:items-start gap-2">
                    <div>
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className="font-mono text-xs font-bold text-indigo-700 bg-indigo-50 border border-indigo-100 px-2 py-0.5 rounded-md">
                          {std.code}
                        </span>
                        <span className="text-xs text-slate-500">
                          {std.authority} • {std.jurisdiction}
                        </span>
                      </div>
                      <h4 className="text-lg font-bold text-slate-900">{std.title}</h4>
                      <p className="text-[11px] text-slate-400 mt-0.5">
                        {std.category && `${std.category} · `}Effective {std.effectiveDate}
                      </p>
                    </div>
                    <span className="text-[11px] font-bold text-emerald-700 bg-emerald-50 px-3 py-1 rounded-full border border-emerald-200 self-start">
                      Active Framework
                    </span>
                  </div>

                  <p className="text-sm text-slate-600 leading-relaxed">{std.description}</p>

                  <button
                    type="button"
                    onClick={() => setExpandedId(expanded ? null : std.id)}
                    className="self-start flex items-center gap-1.5 text-xs font-semibold text-indigo-600 hover:text-indigo-700 cursor-pointer"
                  >
                    {expanded ? 'Hide' : 'View'} relevant clauses (
                    {std.relevantClauses.length})
                    <ChevronDown
                      className={`w-3.5 h-3.5 transition-transform ${expanded ? 'rotate-180' : ''}`}
                    />
                  </button>

                  {expanded && (
                    <div className="bg-slate-50 border border-slate-200 rounded-2xl p-4 space-y-3">
                      <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400 block">
                        Key Quantitative Clauses & Audited Metrics:
                      </span>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                        {std.relevantClauses.map((clause, cIdx) => (
                          <div
                            key={cIdx}
                            className="bg-white p-3.5 rounded-xl border border-slate-200 text-xs space-y-1.5 shadow-xs"
                          >
                            <div className="flex justify-between items-center font-bold text-slate-900">
                              <span>{clause.clause}</span>
                              {clause.threshold && (
                                <span className="font-mono text-[10px] text-amber-700 bg-amber-50 border border-amber-200 px-1.5 py-0.5 rounded-md">
                                  {clause.threshold}
                                </span>
                              )}
                            </div>
                            <div className="font-semibold text-slate-800">{clause.topic}</div>
                            <p className="text-slate-500 text-[11px] leading-snug">{clause.requirement}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {expanded && std.relevantClauses.length === 0 && (
                    <div className="bg-slate-50 border border-slate-200 rounded-2xl p-4 text-sm text-slate-500 flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                      No structured clauses recorded for this standard.
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}