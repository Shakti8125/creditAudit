import { useEffect, useMemo, useState } from 'react';
import { Check, Database, Loader2, Pencil, Plus, RotateCcw, Search, Trash2 } from 'lucide-react';
import { deleteEvalCase, restoreDefaultEvalCases, updateEvalCase } from '@/lib/ragApi';
import type { EvalCase, EvalExpectedRef } from '@/lib/ragTypes';
import { errorMessage, truncate } from '@/lib/ragFormat';
import EvalCaseEditorModal from './EvalCaseEditorModal';
import { Card, EmptyState, ErrorState, LoadingState, SegmentedControl, buttonGhost } from './ui';

type ActiveFilter = 'all' | 'active' | 'inactive';

interface EvalDatasetPanelProps {
  cases: EvalCase[] | null;
  loading: boolean;
  error: string | null;
  onReload: () => void;
  onCaseSaved: (c: EvalCase) => void;
  onCaseDeleted: (id: string) => void;
  selectedIds: Set<string>;
  onSelectedChange: (ids: Set<string>) => void;
}

/** Compact chip text for a relevance target. */
export function refLabel(ref: EvalExpectedRef): string {
  const parts: string[] = [];
  if (ref.section) parts.push(ref.section);
  else if (ref.source) parts.push(ref.source);
  if (ref.keywords.length > 0) parts.push(`kw: ${ref.keywords.join(', ')}`);
  if (ref.chunk_index != null) parts.push(`chunk #${ref.chunk_index}`);
  return parts.join(' · ') || '—';
}

export default function EvalDatasetPanel({
  cases,
  loading,
  error,
  onReload,
  onCaseSaved,
  onCaseDeleted,
  selectedIds,
  onSelectedChange,
}: EvalDatasetPanelProps) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<ActiveFilter>('all');
  const [editor, setEditor] = useState<{ open: boolean; initial: EvalCase | null }>({ open: false, initial: null });
  const [busy, setBusy] = useState<Set<string>>(() => new Set());
  const [restoring, setRestoring] = useState(false);
  const [toast, setToast] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 4000);
    return () => window.clearTimeout(id);
  }, [toast]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (cases ?? []).filter(
      (c) =>
        (filter === 'all' || (filter === 'active' ? c.is_active : !c.is_active)) &&
        (!q || c.question.toLowerCase().includes(q)),
    );
  }, [cases, query, filter]);

  const allFilteredSelected = filtered.length > 0 && filtered.every((c) => selectedIds.has(c.id));
  const toggleAll = () => {
    const next = new Set(selectedIds);
    if (allFilteredSelected) filtered.forEach((c) => next.delete(c.id));
    else filtered.forEach((c) => next.add(c.id));
    onSelectedChange(next);
  };
  const toggleOne = (id: string) => {
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onSelectedChange(next);
  };

  const setBusyFor = (id: string, on: boolean) =>
    setBusy((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  async function toggleActive(c: EvalCase) {
    setBusyFor(c.id, true);
    onCaseSaved({ ...c, is_active: !c.is_active }); // optimistic
    try {
      const saved = await updateEvalCase(c.id, { is_active: !c.is_active });
      onCaseSaved(saved);
    } catch (err) {
      onCaseSaved(c); // rollback
      setToast({ tone: 'error', text: errorMessage(err, 'Could not update the case') });
    } finally {
      setBusyFor(c.id, false);
    }
  }

  async function remove(c: EvalCase) {
    if (!window.confirm(`Delete this case?\n\n“${truncate(c.question, 120)}”\n\nHistorical run results are kept.`)) return;
    setBusyFor(c.id, true);
    try {
      await deleteEvalCase(c.id);
      onCaseDeleted(c.id);
    } catch (err) {
      setToast({ tone: 'error', text: errorMessage(err, 'Could not delete the case') });
    } finally {
      setBusyFor(c.id, false);
    }
  }

  async function restore() {
    setRestoring(true);
    try {
      const res = await restoreDefaultEvalCases();
      setToast({
        tone: 'ok',
        text: `${res.inserted} default case${res.inserted === 1 ? '' : 's'} restored`,
      });
      onReload();
    } catch (err) {
      setToast({ tone: 'error', text: errorMessage(err, 'Could not restore defaults') });
    } finally {
      setRestoring(false);
    }
  }

  let body;
  if (cases == null && loading) body = <LoadingState label="Loading golden dataset…" />;
  else if (cases == null && error) body = <ErrorState message={error} onRetry={onReload} />;
  else if (!cases || cases.length === 0)
    body = (
      <EmptyState
        icon={Database}
        title="The golden dataset is empty"
        body="Restore the 22 default CBUAE cases or add your own question with relevance targets."
      />
    );
  else if (filtered.length === 0)
    body = <p className="py-10 text-center text-sm text-slate-400">No cases match your search.</p>;
  else
    body = (
      <div className="-mx-5 overflow-x-auto sm:-mx-6">
        <table className="w-full min-w-[860px] text-left text-xs">
          <thead className="text-slate-500">
            <tr className="border-b border-slate-100">
              <th className="py-2 pl-5 pr-2 sm:pl-6">
                <input
                  type="checkbox"
                  checked={allFilteredSelected}
                  onChange={toggleAll}
                  aria-label="Select all visible cases"
                  className="h-4 w-4 cursor-pointer accent-indigo-600"
                />
              </th>
              <th className="px-2 py-2 font-semibold">Question</th>
              <th className="px-2 py-2 font-semibold">Scope</th>
              <th className="px-2 py-2 font-semibold">Targets</th>
              <th className="px-2 py-2 text-center font-semibold">Ref answer</th>
              <th className="px-2 py-2 font-semibold">Origin</th>
              <th className="px-2 py-2 font-semibold">Active</th>
              <th className="py-2 pl-2 pr-5 text-right font-semibold sm:pr-6">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 text-slate-700">
            {filtered.map((c) => {
              const isBusy = busy.has(c.id);
              return (
                <tr key={c.id} className={`${c.is_active ? '' : 'text-slate-400'} ${selectedIds.has(c.id) ? 'bg-indigo-50/30' : ''}`}>
                  <td className="py-2.5 pl-5 pr-2 align-top sm:pl-6">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(c.id)}
                      onChange={() => toggleOne(c.id)}
                      aria-label="Select case for a run"
                      className="h-4 w-4 cursor-pointer accent-indigo-600"
                    />
                  </td>
                  <td className="max-w-[320px] px-2 py-2.5 align-top">
                    <span className={`line-clamp-3 break-words ${c.is_active ? 'text-slate-800' : ''}`} title={c.question}>
                      {c.question}
                    </span>
                  </td>
                  <td className="max-w-[160px] px-2 py-2.5 align-top">
                    <span className="block truncate" title={c.document_filename ?? undefined}>
                      {c.document_id ? c.document_filename ?? 'Document (unavailable)' : 'Regulatory corpus'}
                    </span>
                  </td>
                  <td className="max-w-[260px] px-2 py-2.5 align-top">
                    <div className="flex flex-wrap gap-1">
                      {c.expected_refs.map((ref, i) => (
                        <span
                          key={i}
                          title={refLabel(ref)}
                          className="inline-block max-w-full truncate rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-600"
                        >
                          {truncate(refLabel(ref), 48)}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-2 py-2.5 text-center align-top">
                    {c.reference_answer ? (
                      <Check className="mx-auto h-4 w-4 text-emerald-600" aria-label="Has reference answer" />
                    ) : (
                      <span aria-label="No reference answer">—</span>
                    )}
                  </td>
                  <td className="px-2 py-2.5 align-top">
                    <span
                      className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-bold ${
                        c.origin === 'default'
                          ? 'border-slate-200 bg-slate-100 text-slate-600'
                          : 'border-indigo-200 bg-indigo-50 text-indigo-700'
                      }`}
                    >
                      {c.origin === 'default' ? 'Default' : 'Custom'}
                    </span>
                  </td>
                  <td className="px-2 py-2.5 align-top">
                    <button
                      type="button"
                      role="switch"
                      aria-checked={c.is_active}
                      aria-label={c.is_active ? 'Deactivate case' : 'Activate case'}
                      onClick={() => void toggleActive(c)}
                      disabled={isBusy}
                      className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors disabled:opacity-60 ${
                        c.is_active ? 'bg-indigo-600' : 'bg-slate-300'
                      }`}
                    >
                      <span
                        className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${
                          c.is_active ? 'translate-x-4.5' : 'translate-x-0.5'
                        }`}
                      />
                    </button>
                  </td>
                  <td className="py-2.5 pl-2 pr-5 align-top sm:pr-6">
                    <div className="flex justify-end gap-1.5">
                      <button
                        type="button"
                        onClick={() => setEditor({ open: true, initial: c })}
                        disabled={isBusy}
                        aria-label="Edit case"
                        title="Edit case"
                        className="cursor-pointer rounded-full border border-slate-200 bg-white p-1.5 text-slate-500 hover:border-indigo-300 hover:text-indigo-700 disabled:opacity-50"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => void remove(c)}
                        disabled={isBusy}
                        aria-label="Delete case"
                        title="Delete case"
                        className="cursor-pointer rounded-full border border-slate-200 bg-white p-1.5 text-slate-500 hover:border-rose-300 hover:text-rose-700 disabled:opacity-50"
                      >
                        {isBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );

  return (
    <Card
      title="Golden dataset"
      subtitle="Questions with known relevant passages. Retrieval is judged by section, keywords or chunk targets."
    >
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative min-w-0 flex-1 basis-48">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search questions…"
            aria-label="Search questions"
            className="w-full rounded-full border border-slate-200 bg-slate-50 py-1.5 pl-8 pr-3 text-xs font-medium text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-600/30"
          />
        </div>
        <SegmentedControl
          ariaLabel="Active filter"
          size="sm"
          options={[
            { value: 'all', label: 'All' },
            { value: 'active', label: 'Active' },
            { value: 'inactive', label: 'Inactive' },
          ]}
          value={filter}
          onChange={setFilter}
        />
        <div className="flex gap-2">
          <button type="button" onClick={() => setEditor({ open: true, initial: null })} className={buttonGhost}>
            <Plus className="h-3.5 w-3.5" /> Add case
          </button>
          <button type="button" onClick={() => void restore()} disabled={restoring} className={buttonGhost}>
            {restoring ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
            Restore defaults
          </button>
        </div>
      </div>

      {toast && (
        <p
          role="status"
          className={`mb-3 rounded-xl border px-3 py-2 text-xs font-medium ${
            toast.tone === 'ok'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
              : 'border-rose-100 bg-rose-50 text-rose-700'
          }`}
        >
          {toast.text}
        </p>
      )}

      {cases != null && error && (
        <div className="mb-3">
          <ErrorState compact message={`Refresh failed: ${error}`} onRetry={onReload} />
        </div>
      )}

      {cases != null && cases.length > 0 && (
        <p className="mb-2 text-xs text-slate-500">
          {cases.filter((c) => c.is_active).length} active of {cases.length} · {selectedIds.size} selected for a run
          {selectedIds.size > 0 && (
            <button
              type="button"
              onClick={() => onSelectedChange(new Set())}
              className="ml-2 cursor-pointer font-semibold text-indigo-600 hover:underline"
            >
              Clear selection
            </button>
          )}
        </p>
      )}

      {body}

      <EvalCaseEditorModal
        isOpen={editor.open}
        initial={editor.initial}
        onClose={() => setEditor({ open: false, initial: null })}
        onSaved={(c) => {
          onCaseSaved(c);
          setEditor({ open: false, initial: null });
          setToast({ tone: 'ok', text: editor.initial ? 'Case updated' : 'Case added' });
        }}
      />
    </Card>
  );
}
