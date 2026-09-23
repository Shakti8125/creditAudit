/**
 * Inline-SVG chart primitives for the RAG Performance page (no chart library).
 *
 * Conventions (dataviz method):
 * - Each chart measures its container and renders an SVG whose viewBox equals its pixel
 *   size, so text stays 10–11px on phones instead of being scaled down.
 * - Bars ≤24px thick with a 4px rounded data end and a square baseline; 2px surface gap
 *   between stacked segments / adjacent bars; 2px lines with round caps; r=4 end markers
 *   with a 2px surface ring; 1px solid gridlines; at most one y-axis.
 * - Hover and keyboard focus show the same tooltip (roving tabindex over x bands / rows:
 *   Tab into the chart, then arrow keys). Tooltips enhance, never gate: every chart has a
 *   "View data table" twin.
 * - All labels are rendered as React text nodes (never innerHTML): series names, sections
 *   and masked queries are untrusted.
 */
import {
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type RefObject,
} from 'react';
import { AXIS, GRID, SEQ, SURFACE } from './palette';

// ---------------------------------------------------------------------------
// Geometry & scale helpers
// ---------------------------------------------------------------------------

const r2 = (n: number) => Math.round(n * 100) / 100;

/** Vertical column: rounded top (data end), square baseline. `y` is the top edge. */
export function columnPath(x: number, y: number, w: number, h: number, r = 4): string {
  if (!(w > 0) || !(h > 0)) return '';
  const rr = Math.max(0, Math.min(r, w / 2, h));
  return (
    `M${r2(x)},${r2(y + h)}V${r2(y + rr)}` +
    `A${r2(rr)},${r2(rr)} 0 0 1 ${r2(x + rr)},${r2(y)}` +
    `H${r2(x + w - rr)}` +
    `A${r2(rr)},${r2(rr)} 0 0 1 ${r2(x + w)},${r2(y + rr)}` +
    `V${r2(y + h)}Z`
  );
}

/** Horizontal bar: square baseline on the left, rounded right (data) end. */
export function hbarPath(x: number, y: number, w: number, h: number, r = 4): string {
  if (!(w > 0) || !(h > 0)) return '';
  const rr = Math.max(0, Math.min(r, h / 2, w));
  return (
    `M${r2(x)},${r2(y)}H${r2(x + w - rr)}` +
    `A${r2(rr)},${r2(rr)} 0 0 1 ${r2(x + w)},${r2(y + rr)}` +
    `V${r2(y + h - rr)}` +
    `A${r2(rr)},${r2(rr)} 0 0 1 ${r2(x + w - rr)},${r2(y + h)}` +
    `H${r2(x)}Z`
  );
}

/** Plain rectangle path (interior stacked segments have no rounded end). */
function rectPath(x: number, y: number, w: number, h: number): string {
  if (!(w > 0) || !(h > 0)) return '';
  return `M${r2(x)},${r2(y)}H${r2(x + w)}V${r2(y + h)}H${r2(x)}Z`;
}

/** Clean ticks from 0 to ≥max: steps of 1/2/2.5/5 × 10ⁿ (integers only when asked). */
export function niceTicks(
  maxValue: number,
  opts: { target?: number; integer?: boolean } = {},
): number[] {
  const target = opts.target ?? 4;
  const max =
    Number.isFinite(maxValue) && maxValue > 0 ? maxValue : opts.integer ? target : 1;
  const raw = max / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const steps = opts.integer ? [1, 2, 5, 10] : [1, 2, 2.5, 5, 10];
  let step = (steps.find((s) => norm <= s) ?? 10) * mag;
  if (opts.integer) step = Math.max(1, Math.round(step));
  const top = Math.ceil(max / step - 1e-9) * step;
  const ticks: number[] = [];
  for (let i = 0; i * step <= top + step * 1e-6; i += 1) {
    ticks.push(Number((i * step).toFixed(10)));
  }
  return ticks;
}

/** Rough text width for layout decisions (system sans, ~0.58em per glyph). */
export function textWidth(s: string, px = 10): number {
  return s.length * px * 0.58;
}

function fitText(s: string, maxPx: number, px = 11): string {
  const maxChars = Math.max(3, Math.floor(maxPx / (px * 0.58)));
  return s.length > maxChars ? `${s.slice(0, maxChars - 1).trimEnd()}…` : s;
}

function finite(v: number | null | undefined): v is number {
  return v != null && Number.isFinite(v);
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/** Tracks an element's content width with ResizeObserver. */
export function useElementWidth<T extends HTMLElement>(
  fallback = 600,
): [RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const w = Math.floor(el.getBoundingClientRect().width);
      if (w > 0) setWidth(w);
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

/**
 * Roving-tabindex keyboard access over a chart's hit bands: one Tab stop per chart,
 * arrow keys / Home / End move between bands, focus shows the same tooltip as hover.
 */
function useBandFocus(count: number, onFocusBand: (i: number) => void, onBlur: () => void) {
  const refs = useRef<(SVGRectElement | null)[]>([]);
  const [active, setActive] = useState(0);
  const current = Math.min(active, Math.max(0, count - 1));
  return (i: number) => ({
    ref: (el: SVGRectElement | null) => {
      refs.current[i] = el;
    },
    tabIndex: i === current ? 0 : -1,
    style: { outline: 'none' },
    onFocus: () => {
      setActive(i);
      onFocusBand(i);
    },
    onBlur,
    onKeyDown: (e: KeyboardEvent<SVGRectElement>) => {
      let next = -1;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = Math.min(count - 1, i + 1);
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = Math.max(0, i - 1);
      else if (e.key === 'Home') next = 0;
      else if (e.key === 'End') next = count - 1;
      if (next >= 0) {
        e.preventDefault();
        refs.current[next]?.focus();
      }
    },
  });
}

// ---------------------------------------------------------------------------
// Tooltip, legend, table view
// ---------------------------------------------------------------------------

export interface TipRow {
  /** Series colour — drawn as a short line key beside the (text-coloured) value. */
  color?: string;
  value: string;
  label: string;
  note?: string | null;
}

interface TipData {
  x: number;
  y: number;
  title: string;
  rows: TipRow[];
  footer?: string;
}

function ChartTooltip({ tip, width, height }: { tip: TipData | null; width: number; height: number }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ w: 180, h: 60 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    setSize((prev) => (prev.w === w && prev.h === h ? prev : { w, h }));
  }, [tip]);
  if (!tip) return null;
  let left = tip.x + 14;
  if (left + size.w > width) left = tip.x - 14 - size.w;
  if (left < 0) left = Math.max(0, Math.min(width - size.w, tip.x - size.w / 2));
  const top = Math.max(0, Math.min(tip.y - 12, height - Math.min(size.h, height)));
  return (
    <div
      ref={ref}
      className="pointer-events-none absolute z-20 max-w-[260px] rounded-xl border border-slate-200 bg-white/95 px-3 py-2 text-xs shadow-lg shadow-slate-200/60"
      style={{ left, top }}
    >
      <div className="mb-1 font-semibold text-slate-700">{tip.title}</div>
      {tip.rows.map((row, i) => (
        <div key={i} className="py-0.5">
          <div className="flex items-center gap-2">
            {row.color && (
              <span
                aria-hidden
                className="inline-block h-0.5 w-3 shrink-0 rounded-full"
                style={{ backgroundColor: row.color }}
              />
            )}
            <span className="font-bold tabular-nums text-slate-900">{row.value}</span>
            <span className="min-w-0 truncate text-slate-500">{row.label}</span>
          </div>
          {row.note && <div className="pl-5 text-[11px] text-slate-400">{row.note}</div>}
        </div>
      ))}
      {tip.footer && (
        <div className="mt-1 border-t border-slate-100 pt-1 text-slate-500">{tip.footer}</div>
      )}
    </div>
  );
}

export interface LegendItem {
  label: string;
  color: string;
}

export function Legend({ items, mark }: { items: LegendItem[]; mark: 'rect' | 'line' }) {
  if (items.length < 2) return null;
  return (
    <ul className="mb-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-slate-600">
      {items.map((item) => (
        <li key={item.label} className="flex min-w-0 items-center gap-1.5">
          {mark === 'rect' ? (
            <span
              aria-hidden
              className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
              style={{ backgroundColor: item.color }}
            />
          ) : (
            <span
              aria-hidden
              className="h-0.5 w-3.5 shrink-0 rounded-full"
              style={{ backgroundColor: item.color }}
            />
          )}
          <span className="min-w-0 break-words">{item.label}</span>
        </li>
      ))}
    </ul>
  );
}

/** Accessible table twin of a chart, collapsed behind a disclosure. */
export function DataTable({
  caption,
  columns,
  rows,
}: {
  caption: string;
  columns: string[];
  rows: string[][];
}) {
  return (
    <details className="mt-3">
      <summary className="w-fit cursor-pointer select-none text-xs font-semibold text-slate-500 hover:text-slate-800">
        View data table
      </summary>
      <div className="mt-2 max-h-72 overflow-auto rounded-xl border border-slate-100">
        <table className="w-full text-left text-xs">
          <caption className="sr-only">{caption}</caption>
          <thead className="sticky top-0 bg-slate-50 text-slate-500">
            <tr>
              {columns.map((c, i) => (
                <th
                  key={`${c}-${i}`}
                  scope="col"
                  className={`whitespace-nowrap px-3 py-2 font-semibold ${i > 0 ? 'text-right' : ''}`}
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 tabular-nums text-slate-700">
            {rows.map((row, ri) => (
              <tr key={ri}>
                {row.map((cell, ci) =>
                  ci === 0 ? (
                    <th key={ci} scope="row" className="whitespace-nowrap px-3 py-1.5 font-medium">
                      {cell}
                    </th>
                  ) : (
                    <td key={ci} className="whitespace-nowrap px-3 py-1.5 text-right">
                      {cell}
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function ChartFrame({
  frameRef,
  children,
  tip,
  width,
  height,
  legend,
  table,
}: {
  frameRef: RefObject<HTMLDivElement | null>;
  children: ReactNode;
  tip: TipData | null;
  width: number;
  height: number;
  legend?: ReactNode;
  table: ReactNode;
}) {
  return (
    <figure className="m-0 min-w-0">
      {legend}
      <div ref={frameRef} className="relative w-full">
        {children}
        <ChartTooltip tip={tip} width={width} height={height} />
      </div>
      {table}
    </figure>
  );
}

function pointerY(frame: HTMLDivElement | null, e: ReactPointerEvent<Element>): number {
  if (!frame) return 0;
  return e.clientY - frame.getBoundingClientRect().top;
}

function thinStep(n: number, plotWidth: number, maxLabels: number, minGap = 56): number {
  const fit = Math.max(2, Math.min(maxLabels, Math.floor(plotWidth / minGap)));
  return Math.max(1, Math.ceil(n / fit));
}

function YAxis({
  ticks,
  yAt,
  left,
  right,
  format,
}: {
  ticks: number[];
  yAt: (v: number) => number;
  left: number;
  right: number;
  format: (v: number) => string;
}) {
  return (
    <g aria-hidden>
      {ticks.map((t) => (
        <g key={t}>
          <line
            x1={left}
            x2={right}
            y1={r2(yAt(t))}
            y2={r2(yAt(t))}
            stroke={t === 0 ? '#cbd5e1' : GRID}
            strokeWidth={1}
            shapeRendering="crispEdges"
          />
          <text
            x={left - 6}
            y={yAt(t)}
            dy="0.32em"
            textAnchor="end"
            fontSize={10}
            fill={AXIS}
            style={{ fontVariantNumeric: 'tabular-nums' }}
          >
            {format(t)}
          </text>
        </g>
      ))}
    </g>
  );
}

function XLabels({
  labels,
  xAt,
  y,
  step,
}: {
  labels: string[];
  xAt: (i: number) => number;
  y: number;
  step: number;
}) {
  const n = labels.length;
  return (
    <g aria-hidden>
      {labels.map((label, i) => {
        if (i % step !== 0) return null;
        const anchor = n > 1 && i === 0 ? 'start' : n > 1 && i === n - 1 ? 'end' : 'middle';
        const dx = anchor === 'start' ? -4 : anchor === 'end' ? 4 : 0;
        return (
          <text key={i} x={xAt(i) + dx} y={y} textAnchor={anchor} fontSize={10} fill={AXIS}>
            {label}
          </text>
        );
      })}
    </g>
  );
}

// ---------------------------------------------------------------------------
// Sparkline & Meter (figures)
// ---------------------------------------------------------------------------

export function Sparkline({
  values,
  color = SEQ.s450,
  ringColor = SURFACE,
  height = 36,
  ariaLabel = 'Trend',
}: {
  values: number[];
  color?: string;
  ringColor?: string;
  height?: number;
  ariaLabel?: string;
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>(160);
  const pts = values.filter(Number.isFinite);
  if (pts.length < 2) return <div ref={ref} style={{ height }} />;
  const max = Math.max(...pts);
  const min = Math.min(0, ...pts);
  const pad = 5;
  const span = max - min || 1;
  const x = (i: number) => pad + (i * (width - pad * 2)) / (pts.length - 1);
  const y = (v: number) => pad + (1 - (v - min) / span) * (height - pad * 2);
  const d = pts.map((v, i) => `${i === 0 ? 'M' : 'L'}${r2(x(i))},${r2(y(v))}`).join('');
  const last = pts.length - 1;
  return (
    <div ref={ref} className="w-full">
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={ariaLabel}
      >
        <path
          d={d}
          fill="none"
          stroke={color}
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx={x(last)} cy={y(pts[last])} r={3.5} fill={color} stroke={ringColor} strokeWidth={2} />
      </svg>
    </div>
  );
}

export function Meter({ value, label }: { value: number | null; label: string }) {
  const pct = finite(value) ? Math.max(0, Math.min(1, value)) * 100 : 0;
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <span className="text-xs font-semibold text-slate-500">{label}</span>
        <span className="text-2xl font-bold text-slate-900">
          {finite(value) ? `${Math.round(pct)}%` : '—'}
        </span>
      </div>
      <div
        className="h-2.5 w-full overflow-hidden rounded-full"
        style={{ backgroundColor: SEQ.s100 }}
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={finite(value) ? Math.round(pct) : undefined}
        aria-valuetext={finite(value) ? `${Math.round(pct)}%` : 'No data'}
      >
        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: SEQ.s450 }} />
      </div>
    </div>
  );
}

/** Single-hue horizontal bars with values at the tips (every bar labelled, so no hover). */
export function BarList({
  rows,
  color = SEQ.s450,
  format = (v: number) => String(v),
  ariaLabel,
}: {
  rows: { key: string; label: string; value: number }[];
  color?: string;
  format?: (v: number) => string;
  ariaLabel: string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="space-y-2" aria-label={ariaLabel}>
      {rows.map((row) => (
        <li key={row.key} className="grid grid-cols-[minmax(0,7.5rem)_1fr] items-center gap-3 text-xs">
          <span className="truncate text-slate-600" title={row.label}>
            {row.label}
          </span>
          <span className="flex min-w-0 items-center gap-2">
            <span
              aria-hidden
              className="h-2.5 rounded-r-[4px]"
              style={{
                width: `${Math.max(2, (row.value / max) * 100)}%`,
                maxWidth: 'calc(100% - 2.5rem)',
                backgroundColor: color,
              }}
            />
            <span className="font-semibold tabular-nums text-slate-700">{format(row.value)}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// LineChart
// ---------------------------------------------------------------------------

export interface LineSeries {
  key: string;
  label: string;
  color: string;
  values: (number | null)[];
}

export function LineChart({
  xLabels,
  xTooltipLabels,
  series,
  yMax,
  yFormat,
  height = 220,
  ariaLabel,
  xTitle = 'x',
  directLabels = true,
  maxXLabels = 8,
}: {
  xLabels: string[];
  xTooltipLabels?: string[];
  series: LineSeries[];
  yMax?: number;
  yFormat: (v: number) => string;
  height?: number;
  ariaLabel: string;
  xTitle?: string;
  directLabels?: boolean;
  maxXLabels?: number;
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const [tip, setTip] = useState<TipData | null>(null);
  const n = xLabels.length;
  const tipLabels = xTooltipLabels ?? xLabels;

  const all = series.flatMap((s) => s.values.filter(finite));
  const ticks = niceTicks(yMax ?? (all.length ? Math.max(...all) : 0));
  const top = yMax ?? ticks[ticks.length - 1] ?? 1;
  const tickText = ticks.map(yFormat);
  const ml = Math.ceil(Math.max(0, ...tickText.map((t) => textWidth(t)))) + 10;
  const mt = 10;
  const mb = 26;
  const ph = Math.max(20, height - mt - mb);
  const yAt = (v: number) => mt + ph - (Math.max(0, Math.min(v, top)) / (top || 1)) * ph;

  // Direct end labels: only when there is room and they do not collide (else legend + tooltip).
  const ends = series.map((s) => {
    for (let i = s.values.length - 1; i >= 0; i -= 1) {
      const v = s.values[i];
      if (finite(v)) return { i, v };
    }
    return null;
  });
  const endTexts = series.map((s, k) => {
    const end = ends[k];
    return end ? `${s.label} ${yFormat(end.v)}` : '';
  });
  let showDirect = directLabels && width >= 440 && ends.some(Boolean);
  if (showDirect) {
    const ys = ends.filter((e): e is { i: number; v: number } => e != null).map((e) => yAt(e.v));
    ys.sort((a, b) => a - b);
    for (let k = 1; k < ys.length; k += 1) if (ys[k] - ys[k - 1] < 13) showDirect = false;
  }
  const mr = showDirect
    ? Math.min(150, Math.ceil(Math.max(...endTexts.map((t) => textWidth(t, 10.5)))) + 16)
    : 12;
  const pw = Math.max(10, width - ml - mr);
  const xAt = (i: number) => ml + (n <= 1 ? pw / 2 : (i * pw) / (n - 1));
  const step = thinStep(n, pw, maxXLabels);

  const show = (i: number, y: number) => {
    setHover(i);
    setTip({
      x: xAt(i),
      y,
      title: tipLabels[i] ?? '',
      rows: series.map((s) => {
        const v = s.values[i];
        return { color: s.color, value: finite(v) ? yFormat(v) : '—', label: s.label };
      }),
    });
  };
  const hide = () => {
    setHover(null);
    setTip(null);
  };
  const bandProps = useBandFocus(n, (i) => show(i, mt + 8), hide);

  return (
    <ChartFrame
      frameRef={ref}
      tip={tip}
      width={width}
      height={height}
      legend={<Legend items={series.map((s) => ({ label: s.label, color: s.color }))} mark="line" />}
      table={
        <DataTable
          caption={ariaLabel}
          columns={[xTitle, ...series.map((s) => s.label)]}
          rows={xLabels.map((_, i) => [
            tipLabels[i] ?? '',
            ...series.map((s) => {
              const v = s.values[i];
              return finite(v) ? yFormat(v) : '—';
            }),
          ])}
        />
      }
    >
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={ariaLabel}
        onPointerLeave={hide}
        className="block select-none"
      >
        <YAxis ticks={ticks} yAt={yAt} left={ml} right={ml + pw} format={yFormat} />
        <XLabels labels={xLabels} xAt={xAt} y={height - 8} step={step} />

        {hover != null && (
          <line
            x1={r2(xAt(hover))}
            x2={r2(xAt(hover))}
            y1={mt}
            y2={mt + ph}
            stroke={AXIS}
            strokeOpacity={0.45}
            strokeWidth={1}
            shapeRendering="crispEdges"
          />
        )}

        {series.map((s) => {
          let d = '';
          let pen = false;
          const isolated: number[] = [];
          s.values.forEach((v, i) => {
            if (!finite(v)) {
              pen = false;
              return;
            }
            d += `${pen ? 'L' : 'M'}${r2(xAt(i))},${r2(yAt(v))}`;
            const prev = s.values[i - 1];
            const next = s.values[i + 1];
            if (!finite(prev) && !finite(next)) isolated.push(i);
            pen = true;
          });
          return (
            <g key={s.key}>
              <path
                d={d}
                fill="none"
                stroke={s.color}
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              {isolated.map((i) => (
                <circle key={i} cx={xAt(i)} cy={yAt(s.values[i] as number)} r={3} fill={s.color} />
              ))}
            </g>
          );
        })}

        {/* End markers (and direct labels when they fit) */}
        {series.map((s, k) => {
          const end = ends[k];
          if (!end) return null;
          return (
            <g key={`end-${s.key}`}>
              <circle
                cx={xAt(end.i)}
                cy={yAt(end.v)}
                r={4}
                fill={s.color}
                stroke={SURFACE}
                strokeWidth={2}
              />
              {showDirect && (
                <text
                  x={xAt(end.i) + 9}
                  y={yAt(end.v)}
                  dy="0.32em"
                  fontSize={10.5}
                  fill="#334155"
                  aria-hidden
                >
                  {endTexts[k]}
                </text>
              )}
            </g>
          );
        })}

        {hover != null &&
          series.map((s) => {
            const v = s.values[hover];
            if (!finite(v)) return null;
            return (
              <circle
                key={`hover-${s.key}`}
                cx={xAt(hover)}
                cy={yAt(v)}
                r={4}
                fill={s.color}
                stroke={SURFACE}
                strokeWidth={2}
              />
            );
          })}

        {/* Hit bands: full-height, snap to nearest x */}
        {xLabels.map((label, i) => {
          const left = n <= 1 ? ml : i === 0 ? ml : (xAt(i - 1) + xAt(i)) / 2;
          const right = n <= 1 ? ml + pw : i === n - 1 ? ml + pw : (xAt(i) + xAt(i + 1)) / 2;
          return (
            <rect
              key={i}
              {...bandProps(i)}
              x={i === 0 ? left - 6 : left}
              y={mt}
              width={Math.max(1, right - left + (i === 0 ? 6 : 0) + (i === n - 1 ? 6 : 0))}
              height={ph}
              fill="transparent"
              aria-label={`${tipLabels[i] ?? label}: ${series
                .map((s) => {
                  const v = s.values[i];
                  return `${s.label} ${finite(v) ? yFormat(v) : 'no data'}`;
                })
                .join(', ')}`}
              onPointerEnter={(e) => show(i, pointerY(ref.current, e))}
              onPointerMove={(e) => show(i, pointerY(ref.current, e))}
            />
          );
        })}
      </svg>
    </ChartFrame>
  );
}

// ---------------------------------------------------------------------------
// StackedColumnChart
// ---------------------------------------------------------------------------

export interface StackSeries {
  key: string;
  label: string;
  color: string;
  values: number[];
}

export function StackedColumnChart({
  xLabels,
  xTooltipLabels,
  stacks,
  yFormat,
  height = 220,
  ariaLabel,
  xTitle = 'x',
  maxXLabels = 8,
}: {
  xLabels: string[];
  xTooltipLabels?: string[];
  stacks: StackSeries[];
  yFormat: (v: number) => string;
  height?: number;
  ariaLabel: string;
  xTitle?: string;
  maxXLabels?: number;
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const [tip, setTip] = useState<TipData | null>(null);
  const n = xLabels.length;
  const tipLabels = xTooltipLabels ?? xLabels;
  const totals = xLabels.map((_, i) => stacks.reduce((sum, s) => sum + (s.values[i] ?? 0), 0));

  const ticks = niceTicks(Math.max(0, ...totals), { integer: true });
  const top = ticks[ticks.length - 1] || 1;
  const ml = Math.ceil(Math.max(0, ...ticks.map((t) => textWidth(yFormat(t))))) + 10;
  const mr = 8;
  const mt = 10;
  const mb = 26;
  const pw = Math.max(10, width - ml - mr);
  const ph = Math.max(20, height - mt - mb);
  const band = pw / Math.max(1, n);
  const colW = Math.max(1, Math.min(24, band - 2));
  const yAt = (v: number) => mt + ph - (Math.min(v, top) / top) * ph;
  const xCenter = (i: number) => ml + band * i + band / 2;
  const step = thinStep(n, pw, maxXLabels);

  const show = (i: number, y: number) => {
    setHover(i);
    setTip({
      x: xCenter(i),
      y,
      title: tipLabels[i] ?? '',
      rows: stacks.map((s) => ({ color: s.color, value: yFormat(s.values[i] ?? 0), label: s.label })),
      footer: `Total ${yFormat(totals[i] ?? 0)}`,
    });
  };
  const hide = () => {
    setHover(null);
    setTip(null);
  };
  const bandProps = useBandFocus(n, (i) => show(i, mt + 8), hide);

  return (
    <ChartFrame
      frameRef={ref}
      tip={tip}
      width={width}
      height={height}
      legend={<Legend items={stacks.map((s) => ({ label: s.label, color: s.color }))} mark="rect" />}
      table={
        <DataTable
          caption={ariaLabel}
          columns={[xTitle, ...stacks.map((s) => s.label), 'Total']}
          rows={xLabels.map((_, i) => [
            tipLabels[i] ?? '',
            ...stacks.map((s) => yFormat(s.values[i] ?? 0)),
            yFormat(totals[i] ?? 0),
          ])}
        />
      }
    >
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={ariaLabel}
        onPointerLeave={hide}
        className="block select-none"
      >
        <YAxis ticks={ticks} yAt={yAt} left={ml} right={ml + pw} format={yFormat} />
        <XLabels labels={xLabels} xAt={xCenter} y={height - 8} step={step} />

        {xLabels.map((_, i) => {
          const x = xCenter(i) - colW / 2;
          const topIdx = stacks.reduce((acc, s, k) => ((s.values[i] ?? 0) > 0 ? k : acc), -1);
          let cum = 0;
          const segs: ReactNode[] = [];
          stacks.forEach((s, k) => {
            const v = s.values[i] ?? 0;
            if (v <= 0) return;
            const y1 = yAt(cum + v);
            const y0 = yAt(cum);
            const gapBelow = cum > 0 ? 2 : 0;
            const h = Math.max(1, y0 - y1 - gapBelow);
            cum += v;
            segs.push(
              <path
                key={s.key}
                d={k === topIdx ? columnPath(x, y1, colW, h, 4) : rectPath(x, y1, colW, h)}
                fill={s.color}
              />,
            );
          });
          return (
            <g key={i} opacity={hover === i ? 0.72 : 1}>
              {segs}
            </g>
          );
        })}

        {xLabels.map((label, i) => (
          <rect
            key={`hit-${i}`}
            {...bandProps(i)}
            x={ml + band * i}
            y={mt}
            width={Math.max(1, band)}
            height={ph}
            fill="transparent"
            aria-label={`${tipLabels[i] ?? label}: ${stacks
              .map((s) => `${s.label} ${yFormat(s.values[i] ?? 0)}`)
              .join(', ')}`}
            onPointerEnter={(e) => show(i, pointerY(ref.current, e))}
            onPointerMove={(e) => show(i, pointerY(ref.current, e))}
          />
        ))}
      </svg>
    </ChartFrame>
  );
}

// ---------------------------------------------------------------------------
// GroupedBarChart
// ---------------------------------------------------------------------------

export interface BarSeries {
  key: string;
  label: string;
  color: string;
  values: (number | null)[];
  /** Optional secondary line per category shown in the tooltip (e.g. judge breakdown). */
  notes?: (string | null)[];
}

export function GroupedBarChart({
  categories,
  series,
  yMax = 1,
  yFormat,
  valueFormat,
  height = 240,
  ariaLabel,
  xTitle = 'Metric',
  directLabels = true,
}: {
  categories: string[];
  series: BarSeries[];
  yMax?: number;
  yFormat: (v: number) => string;
  valueFormat?: (v: number) => string;
  height?: number;
  ariaLabel: string;
  xTitle?: string;
  directLabels?: boolean;
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const [tip, setTip] = useState<TipData | null>(null);
  const fmtValue = valueFormat ?? yFormat;
  const nCat = categories.length;
  const m = Math.max(1, series.length);

  const ticks = niceTicks(yMax);
  const top = yMax || ticks[ticks.length - 1] || 1;
  const ml = Math.ceil(Math.max(0, ...ticks.map((t) => textWidth(yFormat(t))))) + 10;
  const mr = 8;
  const mt = 18;
  const mb = 24;
  const pw = Math.max(10, width - ml - mr);
  const ph = Math.max(20, height - mt - mb);
  const band = pw / Math.max(1, nCat);
  const barW = Math.max(2, Math.min(24, (band * 0.82 - (m - 1) * 2) / m));
  const groupW = m * barW + (m - 1) * 2;
  const yAt = (v: number) => mt + ph - (Math.max(0, Math.min(v, top)) / top) * ph;
  const xCenter = (i: number) => ml + band * i + band / 2;
  const barX = (i: number, j: number) => xCenter(i) - groupW / 2 + j * (barW + 2);
  const labelsFit =
    directLabels &&
    m <= 4 &&
    series.every((s) => s.values.every((v) => !finite(v) || textWidth(fmtValue(v), 9.5) <= barW + 2));

  const show = (i: number, y: number) => {
    setHover(i);
    setTip({
      x: xCenter(i),
      y,
      title: categories[i] ?? '',
      rows: series.map((s) => {
        const v = s.values[i];
        return {
          color: s.color,
          value: finite(v) ? fmtValue(v) : '—',
          label: s.label,
          note: s.notes?.[i] ?? null,
        };
      }),
    });
  };
  const hide = () => {
    setHover(null);
    setTip(null);
  };
  const bandProps = useBandFocus(nCat, (i) => show(i, mt + 8), hide);

  return (
    <ChartFrame
      frameRef={ref}
      tip={tip}
      width={width}
      height={height}
      legend={<Legend items={series.map((s) => ({ label: s.label, color: s.color }))} mark="rect" />}
      table={
        <DataTable
          caption={ariaLabel}
          columns={[xTitle, ...series.map((s) => s.label)]}
          rows={categories.map((c, i) => [
            c,
            ...series.map((s) => {
              const v = s.values[i];
              return finite(v) ? fmtValue(v) : '—';
            }),
          ])}
        />
      }
    >
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={ariaLabel}
        onPointerLeave={hide}
        className="block select-none"
      >
        <YAxis ticks={ticks} yAt={yAt} left={ml} right={ml + pw} format={yFormat} />
        <XLabels labels={categories.map((c) => fitText(c, band - 4, 10))} xAt={xCenter} y={height - 7} step={1} />

        {categories.map((_, i) => (
          <g key={i} opacity={hover === i ? 0.72 : 1}>
            {series.map((s, j) => {
              const v = s.values[i];
              if (!finite(v)) return null;
              const y = yAt(v);
              const h = mt + ph - y;
              const x = barX(i, j);
              return (
                <g key={s.key}>
                  {h > 0 ? (
                    <path d={columnPath(x, y, barW, h, 4)} fill={s.color} />
                  ) : (
                    <line x1={x} x2={x + barW} y1={mt + ph - 0.5} y2={mt + ph - 0.5} stroke={s.color} strokeWidth={1} />
                  )}
                  {labelsFit && (
                    <text
                      x={x + barW / 2}
                      y={y - 4}
                      textAnchor="middle"
                      fontSize={9.5}
                      fill="#475569"
                      aria-hidden
                      style={{ fontVariantNumeric: 'tabular-nums' }}
                    >
                      {fmtValue(v)}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        ))}

        {categories.map((c, i) => (
          <rect
            key={`hit-${i}`}
            {...bandProps(i)}
            x={ml + band * i}
            y={0}
            width={Math.max(1, band)}
            height={mt + ph}
            fill="transparent"
            aria-label={`${c}: ${series
              .map((s) => {
                const v = s.values[i];
                return `${s.label} ${finite(v) ? fmtValue(v) : 'no data'}`;
              })
              .join(', ')}`}
            onPointerEnter={(e) => show(i, pointerY(ref.current, e))}
            onPointerMove={(e) => show(i, pointerY(ref.current, e))}
          />
        ))}
      </svg>
    </ChartFrame>
  );
}

// ---------------------------------------------------------------------------
// HBarPairChart (two ordinal measures per row, e.g. p50 / p95)
// ---------------------------------------------------------------------------

export interface HBarRow {
  key: string;
  label: string;
  a: number | null;
  b: number | null;
  /** Draw a hairline divider above this row (e.g. component vs composite stages). */
  divider?: boolean;
  /** Optional identity dot (e.g. the run's categorical slot colour). */
  swatch?: string;
  /** Custom tooltip rows (defaults to a / b). */
  details?: TipRow[];
  /** Extra cells for the table view, matching `tableExtraColumns`. */
  tableCells?: string[];
}

export function HBarPairChart({
  rows,
  aLabel,
  bLabel,
  aColor,
  bColor,
  format,
  ariaLabel,
  labelTitle = 'Row',
  tableExtraColumns = [],
}: {
  rows: HBarRow[];
  aLabel: string;
  bLabel: string;
  aColor: string;
  bColor: string;
  format: (v: number) => string;
  ariaLabel: string;
  labelTitle?: string;
  tableExtraColumns?: string[];
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const [tip, setTip] = useState<TipData | null>(null);

  const BAR = 10;
  const GAP = 2;
  const DIVIDER_H = 11;
  const AXIS_H = 20;
  const swatchSpace = rows.some((r) => r.swatch) ? 14 : 0;
  // Labels sit left of the bars when they fit; otherwise (phones, long run names) they
  // move onto their own line above the bars so nothing is truncated.
  const inlineLabelW = Math.max(84, Math.min(180, Math.round(width * 0.34)));
  const longestLabel = Math.max(0, ...rows.map((r) => textWidth(r.label, 11))) + swatchSpace + 10;
  const stacked = width < 440 || longestLabel > inlineLabelW;
  const labelW = stacked ? 0 : inlineLabelW;
  const LABEL_H = stacked ? 16 : 0;
  const ROW_H = LABEL_H + BAR * 2 + GAP + 12;
  const BAR_TOP = LABEL_H + 6;
  const valueW = 50;
  const px = labelW + (stacked ? 1 : 0);
  const pw = Math.max(10, width - px - valueW);

  const vals = rows.flatMap((r) => [r.a, r.b]).filter(finite);
  const ticks = niceTicks(vals.length ? Math.max(...vals) : 0, {
    target: Math.max(2, Math.min(5, Math.floor(pw / 70))),
  });
  const top = ticks[ticks.length - 1] || 1;
  const xAt = (v: number) => px + (Math.max(0, Math.min(v, top)) / top) * pw;

  const tops: number[] = [];
  let yCursor = 4;
  rows.forEach((row, i) => {
    if (row.divider && i > 0) yCursor += DIVIDER_H;
    tops.push(yCursor);
    yCursor += ROW_H;
  });
  const plotBottom = yCursor;
  const height = plotBottom + AXIS_H;

  const detailRows = (row: HBarRow): TipRow[] =>
    row.details ?? [
      { color: aColor, value: finite(row.a) ? format(row.a) : '—', label: aLabel },
      { color: bColor, value: finite(row.b) ? format(row.b) : '—', label: bLabel },
    ];

  const show = (i: number, y: number) => {
    const row = rows[i];
    if (!row) return;
    setHover(i);
    const tipX = xAt(Math.max(finite(row.a) ? row.a : 0, finite(row.b) ? row.b : 0));
    setTip({ x: Math.min(tipX, px + pw), y, title: row.label, rows: detailRows(row) });
  };
  const hide = () => {
    setHover(null);
    setTip(null);
  };
  const bandProps = useBandFocus(rows.length, (i) => show(i, (tops[i] ?? 0) + ROW_H), hide);

  return (
    <ChartFrame
      frameRef={ref}
      tip={tip}
      width={width}
      height={height}
      legend={
        <Legend
          items={[
            { label: aLabel, color: aColor },
            { label: bLabel, color: bColor },
          ]}
          mark="rect"
        />
      }
      table={
        <DataTable
          caption={ariaLabel}
          columns={[labelTitle, aLabel, bLabel, ...tableExtraColumns]}
          rows={rows.map((r) => [
            r.label,
            finite(r.a) ? format(r.a) : '—',
            finite(r.b) ? format(r.b) : '—',
            ...(r.tableCells ?? []),
          ])}
        />
      }
    >
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={ariaLabel}
        onPointerLeave={hide}
        className="block select-none"
      >
        {/* vertical gridlines + bottom axis */}
        <g aria-hidden>
          {ticks.map((t, k) => (
            <g key={t}>
              <line
                x1={r2(xAt(t))}
                x2={r2(xAt(t))}
                y1={0}
                y2={plotBottom}
                stroke={t === 0 ? '#cbd5e1' : GRID}
                strokeWidth={1}
                shapeRendering="crispEdges"
              />
              <text
                x={xAt(t)}
                y={plotBottom + 13}
                textAnchor={k === 0 ? 'start' : k === ticks.length - 1 ? 'end' : 'middle'}
                fontSize={10}
                fill={AXIS}
                style={{ fontVariantNumeric: 'tabular-nums' }}
              >
                {format(t)}
              </text>
            </g>
          ))}
        </g>

        {rows.map((row, i) => {
          const y0 = tops[i] ?? 0;
          const cy = stacked ? y0 + LABEL_H / 2 + 2 : y0 + ROW_H / 2;
          const tipValue = finite(row.b) ? row.b : finite(row.a) ? row.a : null;
          const tipEnd = finite(row.b)
            ? xAt(row.b)
            : finite(row.a)
              ? xAt(row.a)
              : px;
          return (
            <g key={row.key}>
              {row.divider && i > 0 && (
                <line
                  x1={0}
                  x2={width}
                  y1={y0 - DIVIDER_H / 2}
                  y2={y0 - DIVIDER_H / 2}
                  stroke={GRID}
                  strokeWidth={1}
                  shapeRendering="crispEdges"
                />
              )}
              {row.swatch && <circle cx={5} cy={cy} r={4} fill={row.swatch} />}
              <text x={swatchSpace} y={cy} dy="0.32em" fontSize={11} fill="#334155">
                {fitText(row.label, (stacked ? width : labelW - 10) - swatchSpace, 11)}
              </text>
              <g opacity={hover === i ? 0.72 : 1}>
                {finite(row.a) && (
                  <path d={hbarPath(px, y0 + BAR_TOP, Math.max(1, xAt(row.a) - px), BAR, 4)} fill={aColor} />
                )}
                {finite(row.b) && (
                  <path
                    d={hbarPath(px, y0 + BAR_TOP + BAR + GAP, Math.max(1, xAt(row.b) - px), BAR, 4)}
                    fill={bColor}
                  />
                )}
              </g>
              {tipValue != null ? (
                <text
                  x={tipEnd + 5}
                  y={finite(row.b) ? y0 + BAR_TOP + BAR + GAP + BAR / 2 : y0 + BAR_TOP + BAR / 2}
                  dy="0.32em"
                  fontSize={10}
                  fill="#475569"
                  style={{ fontVariantNumeric: 'tabular-nums' }}
                  aria-hidden
                >
                  {format(tipValue)}
                </text>
              ) : (
                <text
                  x={px + 5}
                  y={y0 + BAR_TOP + BAR}
                  dy="0.32em"
                  fontSize={10}
                  fill={AXIS}
                  fontStyle="italic"
                  aria-hidden
                >
                  no data
                </text>
              )}
            </g>
          );
        })}

        {rows.map((row, i) => (
          <rect
            key={`hit-${row.key}`}
            {...bandProps(i)}
            x={0}
            y={tops[i] ?? 0}
            width={width}
            height={ROW_H}
            fill="transparent"
            aria-label={`${row.label}: ${detailRows(row)
              .map((d) => `${d.label} ${d.value}`)
              .join(', ')}`}
            onPointerEnter={(e) => show(i, pointerY(ref.current, e))}
            onPointerMove={(e) => show(i, pointerY(ref.current, e))}
          />
        ))}
      </svg>
    </ChartFrame>
  );
}

