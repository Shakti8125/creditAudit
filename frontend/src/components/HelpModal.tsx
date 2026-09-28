import { motion } from 'motion/react';
import { BookOpen, FileText, MessageSquare, Shield, Upload, X } from 'lucide-react';

interface HelpModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const GUIDES = [
  {
    icon: Shield,
    title: 'Create an Audit',
    body: 'Click "New Audit" in the sidebar, name the model, choose its category (PD, LGD, EAD, Credit Scoring, or IFRS 9 ECL), and submit. A current model version and lineage node are created automatically.',
  },
  {
    icon: Upload,
    title: 'Upload Documents',
    body: 'Attach a PDF or DOCX validation dossier when creating an audit, or later from the Regulatory Library. Its metrics are scored against your policy thresholds, and the zero-trust privacy pipeline masks bank names, organisations, people, locations, emails, and phone numbers before any content reaches an LLM.',
  },
  {
    icon: MessageSquare,
    title: 'Run Chat',
    body: 'Ask the AI Analyst about the model open in the workspace. Answers are grounded in the latest analyzed document of its current version and the regulatory corpus, cite their sources, and are saved so you can pick the conversation up later. All outbound prompts are sanitized.',
  },
  {
    icon: FileText,
    title: 'Export Reports',
    body: 'Open "Export Report" from the workspace to download a JSON report of a model and its version history, optionally including the document audit trail and AI Analyst citations.',
  },
];

export default function HelpModal({ isOpen, onClose }: HelpModalProps) {
  if (!isOpen) return null;

  return (
    <>
      <motion.div
        onClick={onClose}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50"
      />

      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.15, ease: 'easeOut' }}
        className="sleek-card fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-lg p-7 max-h-[85vh] overflow-y-auto z-50"
      >
        <div className="flex justify-between items-center pb-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-indigo-50 border border-indigo-100 text-indigo-600 flex items-center justify-center shadow-xs">
              <BookOpen className="w-5 h-5" />
            </div>
            <div>
              <h2 className="font-display text-xl font-bold text-slate-900 tracking-tight">
                ModelAudit Guidelines
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">How to use the workspace</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-full text-slate-400 hover:text-slate-700 hover:bg-slate-100 cursor-pointer transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="py-5 space-y-4 text-sm text-slate-600">
          {GUIDES.map((guide) => {
            const Icon = guide.icon;
            return (
              <div key={guide.title} className="p-4 bg-slate-50 rounded-2xl border border-slate-200">
                <div className="flex items-center gap-2 mb-1.5">
                  <Icon className="w-4 h-4 text-indigo-600" />
                  <h3 className="text-sm font-bold text-slate-900">{guide.title}</h3>
                </div>
                <p className="text-xs text-slate-600 leading-relaxed">{guide.body}</p>
              </div>
            );
          })}
        </div>

        <div className="flex justify-end pt-3 border-t border-slate-100">
          <button
            onClick={onClose}
            className="px-5 py-2.5 bg-slate-900 text-white text-xs font-semibold rounded-xl hover:bg-slate-800 transition-colors cursor-pointer"
          >
            Got it
          </button>
        </div>
      </motion.div>
    </>
  );
}