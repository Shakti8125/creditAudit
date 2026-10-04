/**
 * Document aliases (`DOC-1`, `DOC-2`, ...).
 *
 * The AI Analyst never sees an uploaded document's filename: the backend labels
 * documents with these aliases in every prompt, so the model's answers cite
 * `[Source: DOC-1, Section: ...]`. The browser is not a provider, so it maps the
 * aliases back to filenames for display (the filename never leaves the tenant).
 */

// No lookbehind: older Safari versions fail to parse it. The lookahead keeps
// `DOC-1-2` and `DOC-12345` untouched.
const DOC_ALIAS = /\bDOC-\d{1,3}(?![\w-])/gi;

/**
 * Replaces the `DOC-n` aliases in an answer with display names.
 *
 * @param text Answer text as returned by the backend.
 * @param namesByAlias Display name per alias, e.g. `{ 'DOC-1': 'model_validation.pdf' }`.
 * @returns The text with every known alias replaced; unknown aliases are kept.
 */
export function expandDocAliases(text: string, namesByAlias: Record<string, string>): string {
  const upper = new Map(Object.entries(namesByAlias).map(([alias, name]) => [alias.toUpperCase(), name]));
  if (upper.size === 0) return text;
  return text.replace(DOC_ALIAS, (match) => upper.get(match.toUpperCase()) ?? match);
}
