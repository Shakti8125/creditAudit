import { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { Loader2, Plus, Save, Trash2, X } from 'lucide-react';
import { createEvalCase, listEvalDocuments, updateEvalCase, type EvalDocumentOption } from '@/lib/ragApi';
import type { EvalCase, EvalCaseInput, EvalExpectedRef } from '@/lib/ragTypes';
import { errorMessage } from '@/lib/ragFormat';
import { buttonPrimary, inputClass, useEscape } from './ui';

interface EvalCaseEditorModalProps {
  isOpen: boolean;
  initial: EvalCase | null;
  onClose: () => void;
  onSaved: (c: EvalCase) => void;
}

interface TargetDraft {
  uid: number;
  source: string;
  section: string;
  keywords: string;
  minHits: string;
  chunkIndex: string;
}

const MAX_TARGETS = 10;
const MAX_KEYWORDS = 12;
let uidCounter = 0;

function blankTarget(): TargetDraft {
  uidCounter += 1;
  return { uid: uidCounter, source: '', section: '', keywords: '', minHits: '', chunkIndex: '' };
}

function fromRef(ref: EvalExpectedRef): TargetDraft {
  return {
    ...blankTarget(),
    source: ref.source ?? '',
    section: ref.section ?? '',
    keywords: ref.keywords.join(', '),
    minHits: ref.min_keyword_hits != null ? String(ref.min_keyword_hits) : '',
    chunkIndex: ref.chunk_index != null ? String(ref.chunk_index) : '',
  };
}

function parseKeywords(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of text.split(',')) {
    const kw = raw.trim();
    if (!kw || seen.has(kw.toLowerCase())) continue;
    seen.add(kw.toLowerCase());
    out.push(kw);
  }
  return out;
}

/** Validates a draft and returns the API payload, or the list of problems. */
function buildRefs(
  targets: TargetDraft[],
  hasDocument: boolean,
): { refs: Array<Partial<EvalExpectedRef>>; problems: string[] } {
  const problems: string[] = [];
  const refs: Array<Partial<EvalExpectedRef>> = [];
  targets.forEach((t, i) => {
    const n = `Target #${i + 1}`;
    const keywords = parseKeywords(t.keywords);
    const source = t.source.trim();
    const section = t.section.trim();
    const minHits = t.minHits.trim() ? Number(t.minHits) : null;
    const chunk = hasDocument && t.chunkIndex.trim() ? Number(t.chunkIndex) : null;
    if (!source && !section && keywords.length === 0 && chunk == null) {
      problems.push(`${n} needs a source, section, keywords or chunk index.`);
    }
    if (source.length > 200) problems.push(`${n}: source must be at most 200 characters.`);
    if (section.length > 300) problems.push(`${n}: section must be at most 300 characters.`);
    if (keywords.length > MAX_KEYWORDS) problems.push(`${n}: at most ${MAX_KEYWORDS} keywords.`);
    if (keywords.some((k) => k.length > 80)) problems.push(`${n}: each keyword must be at most 80 characters.`);
    if (minHits != null) {
      if (!Number.isInteger(minHits) || minHits < 1) problems.push(`${n}: min hits must be a whole number ≥ 1.`);
      else if (keywords.length === 0) problems.push(`${n}: min hits requires keywords.`);
      else if (minHits > keywords.length) problems.push(`${n}: min hits cannot exceed the number of keywords.`);
    }
    if (chunk != null && (!Number.isInteger(chunk) || chunk < 0)) {
      problems.push(`${n}: chunk index must be a whole number ≥ 0.`);
    }
    refs.push({
      source: source || null,
      section: section || null,
      keywords,
      min_keyword_hits: minHits,
      chunk_index: chunk,
    });
  });
  return { refs, problems };
}

export default function EvalCaseEditorModal({ isOpen, initial, onClose, onSaved }: EvalCaseEditorModalProps) {
  const [question, setQuestion] = useState('');
  const [documentId, setDocumentId] = useState<string>('');
  const [targets, setTargets] = useState<TargetDraft[]>([blankTarget()]);
  const [referenceAnswer, setReferenceAnswer] = useState('');
  const [isActive, setIsActive] = useState(true);
  const [docs, setDocs] = useState<EvalDocumentOption[] | null>(null);
  const [docsError, setDocsError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [serverError, setServerError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setQuestion(initial?.question ?? '');
    setDocumentId(initial?.document_id ?? '');
    setTargets(initial && initial.expected_refs.length > 0 ? initial.expected_refs.map(fromRef) : [blankTarget()]);
    setReferenceAnswer(initial?.reference_answer ?? '');
    setIsActive(initial?.is_active ?? true);
    setProblems([]);
    setServerError(null);
  }, [isOpen, initial]);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    setDocsError(null);
    listEvalDocuments()
      .then((all) => {
        if (!cancelled) setDocs(all.filter((d) => d.status.toUpperCase() === 'READY'));
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setDocs([]);
          setDocsError(errorMessage(err, 'Could not load documents'));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  useEscape(isOpen && !saving, onClose);

  if (!isOpen) return null;

  const hasDocument = documentId !== '';
  const docOptions = docs ?? [];
  const currentDocMissing = hasDocument && docs != null && !docOptions.some((d) => d.id === documentId);

  const updateTarget = (uid: number, patch: Partial<TargetDraft>) =>
    setTargets((prev) => prev.map((t) => (t.uid === uid ? { ...t, ...patch } : t)));

  async function submit() {
    const q = question.trim();
    const found: string[] = [];
    if (q.length < 5 || q.length > 1000) found.push('Question must be 5–1000 characters.');
    if (targets.length === 0) found.push('Add at least one relevance target.');
    if (targets.length > MAX_TARGETS) found.push(`At most ${MAX_TARGETS} targets.`);
    if (referenceAnswer.trim().length > 4000) found.push('Reference answer must be at most 4000 characters.');
    const { refs, problems: refProblems } = buildRefs(targets, hasDocument);
    found.push(...refProblems);
    setProblems(found);
    setServerError(null);
    if (found.length > 0) return;

    const payload: EvalCaseInput = {
      question: q,
      reference_answer: referenceAnswer.trim() ? referenceAnswer.trim() : null,
      document_id: hasDocument ? documentId : null,
      expected_refs: refs,
      is_active: isActive,
    };
    setSaving(true);
    try {
      const saved = initial ? await updateEvalCase(initial.id, payload) : await createEvalCase(payload);
      onSaved(saved);
    } catch (err) {
      setServerError(errorMessage(err, 'Could not save the case'));
    } finally {
      setSaving(false);
    }
  }

  const labelCls = 'mb-1.5 block text-xs font-bold uppercase tracking-wider text-slate-500';

  return (
    <>
      <motion.div
        onClick={() => !saving && onClose()}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-sm"
      />
      <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6">
        <motion.div
          initial={{ opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.15, ease: 'easeOut' }}
          role="dialog"
          aria-modal="true"
          aria-labelledby="eval-case-editor-title"
          className="sleek-card pointer-events-auto flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden"
        >
          <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4 sm:px-7">
            <h2 id="eval-case-editor-title" className="font-display text-xl font-bold tracking-tight text-slate-900">
              {initial ? 'Edit evaluation case' : 'Add evaluation case'}
            </h2>
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              aria-label="Close"
              className="cursor-pointer rounded-full p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <form
            className="flex-1 space-y-5 overflow-y-auto px-5 py-5 text-sm sm:px-7"
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <label className="block">
              <span className={labelCls}>Question</span>
              <textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                rows={3}
                maxLength={1000}
                placeholder="e.g. What minimum Gini must a retail PD model maintain on out-of-time data?"
                className={`${inputClass} resize-y`}
              />
              <span className="mt-1 block text-right text-[11px] tabular-nums text-slate-400">{question.trim().length}/1000</span>
            </label>

            <label className="block">
              <span className={labelCls}>Scope</span>
              <select
                value={documentId}
                onChange={(e) => {
                  setDocumentId(e.target.value);
                  if (!e.target.value) setTargets((prev) => prev.map((t) => ({ ...t, chunkIndex: '' })));
                }}
                className={`${inputClass} cursor-pointer`}
              >
                <option value="">Regulatory corpus (no document)</option>
                {currentDocMissing && (
                  <option value={documentId}>{initial?.document_filename ?? 'Current document (unavailable)'}</option>
                )}
                {docOptions.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.filename}
                  </option>
                ))}
              </select>
              {docs == null && <span className="mt-1 block text-xs text-slate-400">Loading documents…</span>}
              {docsError && <span className="mt-1 block text-xs text-rose-600">{docsError}</span>}
            </label>

            <fieldset>
              <legend className={labelCls}>Relevance targets</legend>
              <p className="-mt-0.5 mb-3 text-xs text-slate-500">
                A retrieved passage is relevant when it matches a target by source/section, by enough keywords, or by
                chunk. Each target needs at least one field.
              </p>
              <ol className="space-y-3">
                {targets.map((t, i) => {
                  const kws = parseKeywords(t.keywords);
                  return (
                    <li key={t.uid} className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
                      <div className="mb-2 flex items-center justify-between">
                        <span className="text-xs font-bold text-slate-600">Target #{i + 1}</span>
                        <button
                          type="button"
                          onClick={() => setTargets((prev) => prev.filter((x) => x.uid !== t.uid))}
                          disabled={targets.length <= 1}
                          aria-label={`Remove target ${i + 1}`}
                          className="cursor-pointer rounded-full p-1.5 text-slate-400 hover:bg-white hover:text-rose-600 disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                        <label className="block">
                          <span className="mb-1 block text-[11px] font-semibold text-slate-500">Source (optional)</span>
                          <input
                            value={t.source}
                            maxLength={200}
                            onChange={(e) => updateTarget(t.uid, { source: e.target.value })}
                            placeholder="CBUAE-MMG-2022"
                            className={inputClass}
                          />
                        </label>
                        <label className="block">
                          <span className="mb-1 block text-[11px] font-semibold text-slate-500">Section (optional)</span>
                          <input
                            value={t.section}
                            maxLength={300}
                            onChange={(e) => updateTarget(t.uid, { section: e.target.value })}
                            placeholder="Section 4 - Quantitative Validation…"
                            className={inputClass}
                          />
                        </label>
                        <label className="block sm:col-span-2">
                          <span className="mb-1 block text-[11px] font-semibold text-slate-500">
                            Keywords (comma-separated)
                          </span>
                          <input
                            value={t.keywords}
                            onChange={(e) => updateTarget(t.uid, { keywords: e.target.value })}
                            placeholder="gini, out-of-time, 0.40"
                            className={inputClass}
                          />
                          {kws.length > 0 && (
                            <span className="mt-1.5 flex flex-wrap gap-1">
                              {kws.map((k) => (
                                <span
                                  key={k}
                                  className="rounded-md border border-indigo-100 bg-indigo-50 px-1.5 py-0.5 text-[11px] font-medium text-indigo-700"
                                >
                                  {k}
                                </span>
                              ))}
                            </span>
                          )}
                        </label>
                        <label className="block">
                          <span className="mb-1 block text-[11px] font-semibold text-slate-500">Min keyword hits</span>
                          <input
                            type="number"
                            min={1}
                            max={MAX_KEYWORDS}
                            value={t.minHits}
                            onChange={(e) => updateTarget(t.uid, { minHits: e.target.value })}
                            placeholder={kws.length ? `default ${Math.max(1, Math.ceil(0.6 * kws.length))}` : '—'}
                            className={inputClass}
                          />
                        </label>
                        <label className="block">
                          <span className="mb-1 block text-[11px] font-semibold text-slate-500">Chunk index</span>
                          <input
                            type="number"
                            min={0}
                            value={t.chunkIndex}
                            disabled={!hasDocument}
                            onChange={(e) => updateTarget(t.uid, { chunkIndex: e.target.value })}
                            placeholder={hasDocument ? 'e.g. 12' : 'Needs a document scope'}
                            className={`${inputClass} disabled:cursor-not-allowed disabled:bg-slate-100`}
                          />
                          <span className="mt-1 block text-[11px] text-slate-400">
                            0-based chunk number from the Documents tab
                          </span>
                        </label>
                      </div>
                    </li>
                  );
                })}
              </ol>
              <button
                type="button"
                onClick={() => setTargets((prev) => [...prev, blankTarget()])}
                disabled={targets.length >= MAX_TARGETS}
                className="mt-3 inline-flex cursor-pointer items-center gap-1.5 text-xs font-semibold text-indigo-600 hover:text-indigo-800 disabled:cursor-not-allowed disabled:text-slate-400"
              >
                <Plus className="h-3.5 w-3.5" /> Add target{targets.length >= MAX_TARGETS ? ' (max 10)' : ''}
              </button>
            </fieldset>

            <label className="block">
              <span className={labelCls}>Reference answer (optional)</span>
              <textarea
                value={referenceAnswer}
                onChange={(e) => setReferenceAnswer(e.target.value)}
                rows={3}
                maxLength={4000}
                placeholder="Used to score answer correctness when generation is evaluated."
                className={`${inputClass} resize-y`}
              />
            </label>

            <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
                className="h-4 w-4 cursor-pointer accent-indigo-600"
              />
              Active (included in “All active cases” runs)
            </label>

            {(problems.length > 0 || serverError) && (
              <div role="alert" className="space-y-1 rounded-xl border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">
                {problems.map((p) => (
                  <p key={p}>{p}</p>
                ))}
                {serverError && <p>{serverError}</p>}
              </div>
            )}

            <div className="flex justify-end gap-2 border-t border-slate-100 pt-4">
              <button
                type="button"
                onClick={onClose}
                disabled={saving}
                className="cursor-pointer rounded-xl px-4 py-2.5 text-sm font-semibold text-slate-600 hover:bg-slate-100"
              >
                Cancel
              </button>
              <button type="submit" disabled={saving} className={buttonPrimary}>
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                {initial ? 'Save changes' : 'Add case'}
              </button>
            </div>
          </form>
        </motion.div>
      </div>
    </>
  );
}
