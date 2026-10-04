/**
 * NEW-02 interim: the "illustrative sample" label.
 *
 * The app's built-in regulatory text (the 10 hardcoded paragraphs cited as
 * `CBUAE-MMG-2022`, the sample standards catalogue and the `CBUAE MMG` rule basis of the
 * policy checks) was written as illustrative sample content. It is NOT official CBUAE,
 * Basel or IFRS text, and its thresholds are not published requirements. Until the real
 * regulatory corpus replaces it (corpus plan C3/C4, tracker item NEW-02), every place that
 * shows one of these identifiers carries the label below.
 *
 * Single source of truth: `illustrativeSample.json` (next to this file). It lists the
 * exact identifiers that are illustrative. Anything else, such as a citation from the real
 * corpus, never gets the label. The label is applied in the adapters (`lib/adapters.ts`),
 * so live answers, saved conversations and stored policy results are all covered, and the
 * components only render it (`components/IllustrativeBadge.tsx`).
 *
 * To remove it when the real corpus is live: empty the three lists in the JSON (every label
 * disappears), then delete this file, the JSON, the badge component and their imports.
 * `backend/tests/test_illustrative_sample_registry.py` keeps the JSON in step with the
 * backend sample data, and goes away with it.
 */
import registry from '@/lib/illustrativeSample.json';

/** The label shown next to every illustrative citation, standard and rule basis. */
export const ILLUSTRATIVE_LABEL: string = registry.label;

function normalise(value: string): string {
  return value.trim().toLowerCase();
}

const CITATION_SOURCES = new Set(registry.citationSources.map(normalise));
const STANDARD_CODES = new Set(registry.standardCodes.map(normalise));
const RULE_BASES = new Set(registry.ruleBases.map(normalise));

function listed(set: Set<string>, value: string | null | undefined): boolean {
  return typeof value === 'string' && set.has(normalise(value));
}

/** True while any built-in sample content is still in use (drives the static notices). */
export function illustrativeSampleActive(): boolean {
  return CITATION_SOURCES.size + STANDARD_CODES.size + RULE_BASES.size > 0;
}

/** A retrieval citation `source` (e.g. `CBUAE-MMG-2022`) that comes from the sample corpus. */
export function isIllustrativeSource(source: string | null | undefined): boolean {
  return listed(CITATION_SOURCES, source);
}

/** A regulatory standard `code` (catalogue row) that comes from the sample seed. */
export function isIllustrativeStandardCode(code: string | null | undefined): boolean {
  return listed(STANDARD_CODES, code);
}

/** A policy-check `rule_basis` that presents a sample threshold as an official source. */
export function isIllustrativeRuleBasis(ruleBasis: string | null | undefined): boolean {
  return listed(RULE_BASES, ruleBasis);
}

/**
 * Note to put at the top of an exported report when it contains any illustrative
 * identifier (the export is a backend JSON that leaves the app), else null.
 */
export function illustrativeExportNotice(payload: unknown): string | null {
  if (!illustrativeSampleActive()) return null;
  const text = JSON.stringify(payload ?? null);
  const quoted = [
    ...registry.citationSources,
    ...registry.standardCodes,
    ...registry.ruleBases,
  ].some((id) => text.includes(JSON.stringify(id)));
  if (!quoted) return null;
  const names = registry.citationSources
    .concat(registry.ruleBases)
    .map((s) => `"${s}"`)
    .join(' or ');
  return `Regulatory references named ${names} in this report are an ${registry.label}. They are not CBUAE requirements.`;
}
