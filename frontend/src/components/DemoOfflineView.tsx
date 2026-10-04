import type { ReactNode } from 'react';
import { motion } from 'motion/react';
import { GitBranch, Loader2, Mail, PlayCircle, RefreshCw, ServerOff, Shield, Terminal } from 'lucide-react';
import { demoLinks } from '@/lib/demoLinks';

interface DemoOfflineViewProps {
  retrying: boolean;
  onRetry: () => void;
}

function LinkButton({
  href,
  icon,
  children,
  primary = false,
}: {
  href: string;
  icon: ReactNode;
  children: ReactNode;
  primary?: boolean;
}) {
  const tone = primary
    ? 'bg-indigo-600 hover:bg-indigo-700 text-white'
    : 'bg-white hover:bg-slate-50 text-slate-700 border border-slate-200';
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={`flex items-center justify-center gap-2 font-semibold text-sm py-2.5 px-4 rounded-xl transition-colors ${tone}`}
    >
      {icon}
      {children}
    </a>
  );
}

/**
 * Front door shown when no backend answers. It says plainly that the backend is
 * offline by design; it shows no mock data and does not pretend the app is live.
 */
export default function DemoOfflineView({ retrying, onRetry }: DemoOfflineViewProps) {
  const { videoUrl, repoUrl, localRunUrl, contactUrl } = demoLinks;

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center px-4 py-12">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: 'easeOut' }}
        className="w-full max-w-xl"
      >
        <div className="sleek-card p-8">
          <div className="flex items-center gap-2.5 mb-8">
            <div className="w-10 h-10 rounded-xl bg-indigo-600 text-white flex items-center justify-center shadow-md shadow-indigo-200">
              <Shield className="w-5 h-5" />
            </div>
            <div>
              <h1 className="font-display font-bold text-slate-900 tracking-tight leading-tight">
                ModelAudit AI
              </h1>
              <p className="text-[11px] text-slate-400 font-medium tracking-wide">
                Institutional Intelligence
              </p>
            </div>
          </div>

          <p className="text-sm text-slate-600 leading-relaxed">
            ModelAudit AI reviews credit-risk model validation documents against regulatory
            standards. It finds gaps, compares model versions and answers questions with citations,
            masking personal and bank-identifying text before anything reaches an LLM provider.
          </p>

          <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 flex gap-3">
            <ServerOff className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
            <div className="text-sm text-amber-900">
              <p className="font-semibold">The backend is offline by design.</p>
              <p className="mt-1 text-amber-800 leading-relaxed">
                It runs on the author&apos;s machine for live demos, so there is nothing to sign in
                to on this page. The AWS deployment from September 2026 was retired to keep the
                project free of cost.
              </p>
            </div>
          </div>

          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            {videoUrl && (
              <LinkButton primary href={videoUrl} icon={<PlayCircle className="w-4 h-4" />}>
                Watch the demo
              </LinkButton>
            )}
            <LinkButton
              primary={!videoUrl}
              href={repoUrl}
              icon={<GitBranch className="w-4 h-4" />}
            >
              Source on GitHub
            </LinkButton>
            <LinkButton href={localRunUrl} icon={<Terminal className="w-4 h-4" />}>
              Run it locally
            </LinkButton>
            {contactUrl && (
              <LinkButton href={contactUrl} icon={<Mail className="w-4 h-4" />}>
                Ask for a live walkthrough
              </LinkButton>
            )}
          </div>

          <div className="mt-6 pt-5 border-t border-slate-100 flex items-center justify-between gap-3">
            <p role="status" className="text-xs text-slate-400">
              {retrying ? 'Checking the backend…' : 'Checking again every 30 seconds.'}
            </p>
            <button
              type="button"
              onClick={onRetry}
              disabled={retrying}
              className="flex items-center gap-1.5 shrink-0 whitespace-nowrap text-xs font-semibold text-indigo-600 hover:text-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed cursor-pointer"
            >
              {retrying ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <RefreshCw className="w-3.5 h-3.5" />
              )}
              Check now
            </button>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
