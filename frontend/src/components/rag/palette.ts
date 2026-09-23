/**
 * Chart colour roles for the RAG Performance page (light theme).
 *
 * SERIES is the validated reference categorical palette; slots 1–4 are assigned in this
 * fixed order and never cycled (adjacent-pair CVD-safe: worst adjacent ΔE 9.1 protan,
 * normal-vision 22.9 on #ffffff). Slots 3 and 4 sit below 3:1 contrast on white, so every
 * chart ships a legend plus a data-table view (relief rule).
 *
 * Text never takes a series colour; labels and values use slate text classes / INK / AXIS.
 */

export const SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100'] as const;

/** Sequential blue ramp (one hue, light → dark). */
export const SEQ = {
  s100: '#cde2fb',
  s250: '#86b6ef',
  s350: '#5598e7',
  s450: '#2a78d6',
  s500: '#256abf',
  s600: '#184f95',
} as const;

/** Reserved status colours — always paired with an icon and a label, never colour alone. */
export const STATUS = {
  good: '#0ca30c',
  warning: '#fab219',
  serious: '#ec835a',
  critical: '#d03b3b',
} as const;

export const NEUTRAL = '#94a3b8';
export const GRID = '#e2e8f0';
export const AXIS = '#64748b';
export const INK = '#0f172a';
/** Chart surface (the sleek-card background) — used for the 2px surface gap and marker rings. */
export const SURFACE = '#ffffff';

/** Stage latency: p50 darker, p95 lighter step of the same hue (ordinal). */
export const STAGE_P50 = SEQ.s450;
export const STAGE_P95 = SEQ.s250;

/** Request-volume stack colours. */
export const VOLUME = {
  ok: SERIES[0],
  blocked: STATUS.warning,
  error: STATUS.critical,
  cancelled: NEUTRAL,
} as const;

/** Latency trend lines. */
export const TREND = { p50: SERIES[0], p95: SERIES[1] } as const;

/** Trace waterfall segments: retrieval stages step through the sequential ramp. */
export const WATERFALL = {
  dense: SEQ.s600,
  bm25: SEQ.s500,
  fusion: SEQ.s350,
  rerank: SEQ.s250,
  retrievalOther: SEQ.s100,
  masking: NEUTRAL,
  generation: SERIES[1],
  other: GRID,
} as const;
