/**
 * NEW-02 interim: renders the "illustrative sample, not official text" label.
 * The label text and the rules for when it applies live in `lib/illustrativeSample.ts`;
 * remove both together when the real regulatory corpus is live.
 */
import type { ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';
import { ILLUSTRATIVE_LABEL } from '@/lib/illustrativeSample';

/** Amber pill carrying the label; sits next to a citation, standard or rule basis. */
export function IllustrativeBadge({ className = '' }: { className?: string }) {
  return (
    <span
      data-illustrative-label=""
      className={`inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[10px] font-bold leading-tight text-amber-800 ${className}`}
    >
      <AlertTriangle className="h-3 w-3 shrink-0" aria-hidden="true" />
      {ILLUSTRATIVE_LABEL}
    </span>
  );
}

interface IllustrativeNoticeProps {
  /** Lead-in that ends just before the label, e.g. "These sources are an". */
  children?: ReactNode;
  /** Optional sentence(s) after the label. */
  after?: ReactNode;
  className?: string;
}

/** Amber note for a block of content (an answer, a list, a page). */
export function IllustrativeNotice({ children, after, className = '' }: IllustrativeNoticeProps) {
  return (
    <div
      role="note"
      data-illustrative-notice=""
      className={`flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900 ${className}`}
    >
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" aria-hidden="true" />
      <div className="min-w-0">
        {children}
        {children ? ' ' : null}
        <strong className="font-bold">{ILLUSTRATIVE_LABEL}.</strong>
        {after ? ' ' : null}
        {after}
      </div>
    </div>
  );
}
