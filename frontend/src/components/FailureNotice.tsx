/**
 * PR-03: the two notices that keep the UI honest about AI output.
 *
 * `FailureNotice` replaces a blank or "nothing found" state when an AI call failed.
 * `TruncationNotice` marks an answer that was cut off and so is incomplete.
 */
import type { ReactNode } from 'react';
import { AlertTriangle, Loader2, RefreshCw, Scissors } from 'lucide-react';
import type { FailureInfo } from '@/lib/apiFailure';

interface FailureNoticeProps {
  failure: FailureInfo;
  /** Shows a Retry button when the failure is retryable. */
  onRetry?: () => void;
  /** Disables the Retry button and shows a spinner while the retry runs. */
  retrying?: boolean;
  /** Extra line under the message, e.g. what is shown instead. */
  children?: ReactNode;
  className?: string;
}

/** Red alert for a failed AI call: what happened, what to do, and Retry when it can help. */
export function FailureNotice({ failure, onRetry, retrying = false, children, className = '' }: FailureNoticeProps) {
  const canRetry = failure.retryable && !!onRetry;
  return (
    <div
      role="alert"
      data-failure-code={failure.code ?? ''}
      className={`flex flex-wrap items-start gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-800 ${className}`}
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" aria-hidden="true" />
      <div className="min-w-0 flex-1 basis-56">
        <p className="text-sm font-bold text-rose-900">{failure.title}</p>
        <p className="mt-1 leading-relaxed">{failure.message}</p>
        {children}
        {(failure.code || failure.status) && (
          <p className="mt-1.5 break-all font-mono text-[10px] text-rose-500">
            {[failure.code, failure.status ? `HTTP ${failure.status}` : null].filter(Boolean).join(' · ')}
          </p>
        )}
      </div>
      {canRetry && (
        <button
          type="button"
          onClick={onRetry}
          disabled={retrying}
          className="flex shrink-0 cursor-pointer items-center gap-1.5 rounded-lg bg-rose-600 px-3 py-1.5 text-[11px] font-bold text-white transition-colors hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {retrying ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
          Retry
        </button>
      )}
    </div>
  );
}

interface TruncationNoticeProps {
  /** What to do about it, e.g. "Ask it to continue to get the rest." */
  children?: ReactNode;
  /** Optional button, e.g. "Continue". */
  action?: ReactNode;
  className?: string;
}

/** Orange banner under an answer the AI stopped writing early because it hit its length limit. */
export function TruncationNotice({ children, action, className = '' }: TruncationNoticeProps) {
  return (
    <div
      role="note"
      data-truncation-notice=""
      className={`flex flex-wrap items-start gap-2 rounded-xl border-2 border-orange-300 bg-orange-50 px-3 py-2 text-xs leading-relaxed text-orange-900 ${className}`}
    >
      <Scissors className="mt-0.5 h-3.5 w-3.5 shrink-0 text-orange-600" aria-hidden="true" />
      <div className="min-w-0 flex-1 basis-48">
        <strong className="font-bold">Answer cut off.</strong> The AI reached its length limit and stopped
        mid-answer, so what is shown above is incomplete.
        {children ? <> {children}</> : null}
      </div>
      {action}
    </div>
  );
}
