/**
 * Links shown on the offline front door. Set at build time in the Vercel project
 * (`VITE_DEMO_VIDEO_URL`, `VITE_REPO_URL`, `VITE_CONTACT_URL`); none is a secret.
 */

const DEFAULT_REPO_URL = 'https://github.com/Shakti8125/creditAudit';

/** Accepts http(s) and, for the contact link only, mailto; anything else is dropped. */
function safeUrl(value: unknown, allowMailto = false): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  try {
    const { protocol } = new URL(trimmed);
    if (protocol === 'https:' || protocol === 'http:') return trimmed;
    if (allowMailto && protocol === 'mailto:') return trimmed;
  } catch {
    // Not a URL.
  }
  return null;
}

const env = (import.meta as any).env as Record<string, string | undefined>;

const repoUrl = (safeUrl(env.VITE_REPO_URL) ?? DEFAULT_REPO_URL).replace(/\/+$/, '');

export const demoLinks = {
  videoUrl: safeUrl(env.VITE_DEMO_VIDEO_URL),
  repoUrl,
  localRunUrl: `${repoUrl}/blob/main/docs/LOCAL_DEMO.md`,
  contactUrl: safeUrl(env.VITE_CONTACT_URL, true),
};
