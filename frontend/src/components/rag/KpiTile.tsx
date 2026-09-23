import { AlertTriangle, CheckCircle2, XCircle, type LucideIcon } from 'lucide-react';
import { Sparkline } from './charts';
import { SEQ } from './palette';

export type KpiTone = 'default' | 'accent' | 'good' | 'warning' | 'critical';

interface KpiTileProps {
  label: string;
  value: string;
  caption?: string;
  tone?: KpiTone;
  icon: LucideIcon;
  spark?: number[];
  /** Label for status tones (status is never conveyed by colour alone). */
  statusLabel?: string;
}

const STATUS_META: Record<'good' | 'warning' | 'critical', { icon: LucideIcon; cls: string; label: string }> = {
  good: { icon: CheckCircle2, cls: 'bg-emerald-50 text-emerald-700 border-emerald-200', label: 'Healthy' },
  warning: { icon: AlertTriangle, cls: 'bg-amber-50 text-amber-800 border-amber-200', label: 'Elevated' },
  critical: { icon: XCircle, cls: 'bg-rose-50 text-rose-700 border-rose-200', label: 'Critical' },
};

/** Stat tile: sentence-case label, proportional-figure value, caption, optional sparkline. */
export default function KpiTile({
  label,
  value,
  caption,
  tone = 'default',
  icon: Icon,
  spark,
  statusLabel,
}: KpiTileProps) {
  const accent = tone === 'accent';
  const status = tone === 'good' || tone === 'warning' || tone === 'critical' ? STATUS_META[tone] : null;
  const StatusIcon = status?.icon;

  return (
    <div
      className={`relative flex min-h-[148px] min-w-0 flex-col justify-between overflow-hidden rounded-3xl p-6 ${
        accent ? 'bg-indigo-600 text-white' : 'sleek-card'
      }`}
    >
      {accent && (
        <div className="pointer-events-none absolute -right-12 -top-12 h-36 w-36 rounded-full bg-white/15 blur-2xl" />
      )}
      <div className="z-10 flex items-start justify-between gap-3">
        <span className={`text-xs font-semibold ${accent ? 'text-indigo-100' : 'text-slate-500'}`}>
          {label}
        </span>
        <div
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
            accent ? 'bg-white/20 text-white' : 'bg-slate-100 text-slate-600'
          }`}
        >
          <Icon className="h-4 w-4" aria-hidden />
        </div>
      </div>

      <div className="z-10 mt-3 min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`text-3xl font-bold tracking-tight ${accent ? 'text-white' : 'text-slate-900'}`}>
            {value}
          </span>
          {status && StatusIcon && (
            <span
              className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-bold ${status.cls}`}
            >
              <StatusIcon className="h-3 w-3" aria-hidden />
              {statusLabel ?? status.label}
            </span>
          )}
        </div>
        {caption && (
          <p className={`mt-1 text-xs font-medium ${accent ? 'text-indigo-100' : 'text-slate-500'}`}>
            {caption}
          </p>
        )}
        {spark && spark.length > 1 && (
          <div className="mt-2">
            <Sparkline
              values={spark}
              color={accent ? '#ffffff' : SEQ.s450}
              ringColor={accent ? '#4f46e5' : '#ffffff'}
              height={32}
              ariaLabel={`${label} trend`}
            />
          </div>
        )}
      </div>
    </div>
  );
}
