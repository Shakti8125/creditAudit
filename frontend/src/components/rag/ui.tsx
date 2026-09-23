/** Small shared UI pieces for the RAG Performance page (cards, states, badges). */
import { useEffect, type ReactNode } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Loader2,
  MinusCircle,
  RotateCcw,
  ShieldAlert,
  XCircle,
  type LucideIcon,
} from 'lucide-react';
import type { EvalRunStatus, TraceStatus } from '@/lib/ragTypes';
import { RUN_STATUS_LABEL, TRACE_STATUS_LABEL } from '@/lib/ragFormat';

const PLACEHOLDER = /(\[[A-Z][A-Z_]*_\d+\])/g;
const IS_PLACEHOLDER = /^\[[A-Z][A-Z_]*_\d+\]$/;

/** Masked text with privacy placeholders such as [BANK_1] set in monospace. */
export function MaskedText({ text }: { text: string }) {
  return (
    <>
      {text.split(PLACEHOLDER).map((part, i) =>
        IS_PLACEHOLDER.test(part) ? (
          <span key={i} className="font-mono text-[0.92em] text-indigo-700">
            {part}
          </span>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

export function Card({
  title,
  subtitle,
  action,
  children,
  className = '',
  bodyClassName = 'p-5 sm:p-6',
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`sleek-card min-w-0 ${className}`}>
      <div className={bodyClassName}>
        {(title || action) && (
          <div className="mb-4 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
            <div className="min-w-0">
              {title && <h3 className="text-base font-bold text-slate-900">{title}</h3>}
              {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
            </div>
            {action}
          </div>
        )}
        {children}
      </div>
    </section>
  );
}

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  size = 'md',
}: {
  options: SegmentOption<T>[];
  value: T;
  onChange: (v: T) => void;
  ariaLabel: string;
  size?: 'sm' | 'md';
}) {
  const pad = size === 'sm' ? 'px-3 py-1 text-xs' : 'px-4 py-1.5 text-sm';
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className="inline-flex max-w-full flex-wrap gap-1 rounded-full border border-slate-200 bg-white p-1"
    >
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(opt.value)}
            className={`${pad} cursor-pointer whitespace-nowrap rounded-full font-semibold transition-colors ${
              active ? 'bg-indigo-50 text-indigo-700' : 'text-slate-600 hover:bg-slate-100'
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

export function LoadingState({ label = 'Loading…', className = '' }: { label?: string; className?: string }) {
  return (
    <div
      role="status"
      className={`flex items-center justify-center gap-2 py-10 text-sm text-slate-500 ${className}`}
    >
      <Loader2 className="h-4 w-4 animate-spin text-indigo-600" />
      {label}
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
  compact = false,
}: {
  message: string;
  onRetry?: () => void;
  compact?: boolean;
}) {
  return (
    <div
      role="alert"
      className={`flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border border-rose-100 bg-rose-50 text-sm text-rose-700 ${
        compact ? 'px-3 py-2' : 'px-4 py-3'
      }`}
    >
      <XCircle className="h-4 w-4 shrink-0" />
      <span className="min-w-0 flex-1 break-words">{message}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-rose-200 bg-white px-3 py-1 text-xs font-semibold text-rose-700 hover:bg-rose-100"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  body,
  action,
}: {
  icon: LucideIcon;
  title: string;
  body?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 px-4 py-10 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100 text-slate-400">
        <Icon className="h-6 w-6" />
      </div>
      <div>
        <p className="text-sm font-semibold text-slate-700">{title}</p>
        {body && <p className="mx-auto mt-1 max-w-md text-xs text-slate-500">{body}</p>}
      </div>
      {action}
    </div>
  );
}

export function Banner({
  tone,
  children,
}: {
  tone: 'warning' | 'info';
  children: ReactNode;
}) {
  const cls =
    tone === 'warning'
      ? 'border-amber-200 bg-amber-50 text-amber-800'
      : 'border-indigo-100 bg-indigo-50 text-indigo-800';
  return (
    <div role="status" className={`flex items-start gap-2.5 rounded-2xl border px-4 py-3 text-sm ${cls}`}>
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 space-y-1">{children}</div>
    </div>
  );
}

const TRACE_STATUS_STYLE: Record<TraceStatus, { cls: string; icon: LucideIcon }> = {
  ok: { cls: 'bg-emerald-50 text-emerald-700 border-emerald-200', icon: CheckCircle2 },
  error: { cls: 'bg-rose-50 text-rose-700 border-rose-200', icon: XCircle },
  blocked: { cls: 'bg-amber-50 text-amber-700 border-amber-200', icon: ShieldAlert },
  cancelled: { cls: 'bg-slate-100 text-slate-600 border-slate-200', icon: MinusCircle },
};

export function TraceStatusBadge({ status, reason }: { status: TraceStatus; reason?: string | null }) {
  const { cls, icon: Icon } = TRACE_STATUS_STYLE[status] ?? TRACE_STATUS_STYLE.error;
  return (
    <span
      title={reason ? `${TRACE_STATUS_LABEL[status]}: ${reason}` : TRACE_STATUS_LABEL[status]}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-bold ${cls}`}
    >
      <Icon className="h-3 w-3" />
      {TRACE_STATUS_LABEL[status] ?? status}
    </span>
  );
}

const RUN_STATUS_STYLE: Record<EvalRunStatus, { cls: string; icon: LucideIcon }> = {
  pending: { cls: 'bg-slate-100 text-slate-600 border-slate-200', icon: Clock },
  running: { cls: 'bg-indigo-50 text-indigo-700 border-indigo-200', icon: Loader2 },
  completed: { cls: 'bg-emerald-50 text-emerald-700 border-emerald-200', icon: CheckCircle2 },
  failed: { cls: 'bg-rose-50 text-rose-700 border-rose-200', icon: XCircle },
  cancelled: { cls: 'bg-slate-100 text-slate-600 border-slate-200', icon: MinusCircle },
};

export function RunStatusBadge({ status }: { status: EvalRunStatus }) {
  const { cls, icon: Icon } = RUN_STATUS_STYLE[status] ?? RUN_STATUS_STYLE.failed;
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-bold ${cls}`}
    >
      <Icon className={`h-3 w-3 ${status === 'running' ? 'animate-spin' : ''}`} />
      {RUN_STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function Chip({
  children,
  tone = 'slate',
  title,
}: {
  children: ReactNode;
  tone?: 'slate' | 'indigo' | 'amber' | 'rose' | 'emerald';
  title?: string;
}) {
  const cls = {
    slate: 'bg-slate-100 text-slate-600 border-slate-200',
    indigo: 'bg-indigo-50 text-indigo-700 border-indigo-100',
    amber: 'bg-amber-50 text-amber-800 border-amber-200',
    rose: 'bg-rose-50 text-rose-700 border-rose-200',
    emerald: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  }[tone];
  return (
    <span
      title={title}
      className={`inline-flex max-w-full items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${cls}`}
    >
      <span className="truncate">{children}</span>
    </span>
  );
}

/** Closes a drawer/modal on Escape while it is open. */
export function useEscape(active: boolean, onClose: () => void) {
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [active, onClose]);
}

export const inputClass =
  'w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:border-indigo-300 focus:outline-none focus:ring-2 focus:ring-indigo-600/20';

export const selectClass =
  'rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-600/20 cursor-pointer';

export const buttonGhost =
  'inline-flex cursor-pointer items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition-colors hover:border-indigo-300 hover:text-indigo-700 disabled:cursor-not-allowed disabled:opacity-50';

export const buttonPrimary =
  'inline-flex cursor-pointer items-center justify-center gap-2 rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-md shadow-indigo-200 transition-all hover:bg-indigo-700 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60';
