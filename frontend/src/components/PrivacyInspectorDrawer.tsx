import { useState } from 'react';
import { motion } from 'motion/react';
import {
  ArrowRight,
  Bot,
  Check,
  CheckCircle2,
  Copy,
  FileText,
  Loader2,
  Radar,
  Shield,
  Sparkles,
  X,
} from 'lucide-react';
import { maskText } from '@/lib/api';
import { redactionsToEntities } from '@/lib/adapters';
import type { RedactedEntity } from '@/types';

interface PrivacyInspectorDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  redactedEntities: RedactedEntity[];
}

const TYPE_STYLES: Record<RedactedEntity['entityType'], string> = {
  BANK: 'bg-indigo-50 text-indigo-700 border-indigo-200',
  PERSON: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  LOCATION: 'bg-amber-50 text-amber-700 border-amber-200',
  IDENTIFIER: 'bg-slate-100 text-slate-600 border-slate-200',
  ORG: 'bg-rose-50 text-rose-700 border-rose-200',
};

export default function PrivacyInspectorDrawer({
  isOpen,
  onClose,
  redactedEntities,
}: PrivacyInspectorDrawerProps) {
  const [testInput, setTestInput] = useState(
    'Emirates NBD approved the retail revolving facility reviewed by John Smith in Dubai with Gini = 63.4%.',
  );
  const [maskedPreview, setMaskedPreview] = useState<string | null>(null);
  const [extraEntities, setExtraEntities] = useState<RedactedEntity[]>([]);
  const [masking, setMasking] = useState(false);
  const [maskError, setMaskError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  if (!isOpen) return null;

  const entities = [...redactedEntities, ...extraEntities];

  async function handleMask() {
    if (!testInput.trim() || masking) return;
    setMasking(true);
    setMaskError(null);
    try {
      const res = await maskText(testInput);
      setMaskedPreview(res.masked_text ?? null);
      const built = redactionsToEntities(res.redactions);
      setExtraEntities((prev) => [...prev, ...built]);
    } catch (err) {
      setMaskError(err instanceof Error ? err.message : 'Unable to mask text');
    } finally {
      setMasking(false);
    }
  }

  async function handleCopy(text: string, id: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 1500);
    } catch {
      // Clipboard unavailable.
    }
  }

  return (
    <>
      <motion.div
        onClick={onClose}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50"
      />

      <motion.aside
        initial={{ x: '100%' }}
        animate={{ x: 0 }}
        transition={{ type: 'tween', duration: 0.25, ease: 'easeOut' }}
        className="glass-drawer fixed top-0 right-0 bottom-0 w-full sm:w-[540px] z-50 flex flex-col overflow-hidden"
      >
        <div className="p-6 border-b border-slate-100 flex justify-between items-start bg-slate-50/50">
          <div>
            <h2 className="font-display text-xl font-bold text-slate-900 tracking-tight mb-1">
              Privacy Inspector
            </h2>
            <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-emerald-50 border border-emerald-200 rounded-full">
              <div className="relative w-2 h-2">
                <div className="absolute inset-0 bg-emerald-500 rounded-full" />
                <div className="animate-ping absolute inset-0 bg-emerald-400 rounded-full opacity-75" />
              </div>
              <span className="text-[10px] font-bold text-emerald-700 uppercase tracking-wider">
                Zero-Trust Data Pipeline: Protected
              </span>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-slate-800 hover:bg-slate-100 rounded-full transition-all cursor-pointer"
            aria-label="Close Drawer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          <section>
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3">
              Pipeline Masking Trace
            </h3>
            <div className="relative flex items-center justify-between p-5 bg-slate-50 border border-slate-200 rounded-2xl">
              <div className="relative z-10 flex flex-col items-center gap-1.5">
                <div className="w-10 h-10 rounded-full bg-white border border-slate-200 flex items-center justify-center shadow-xs">
                  <FileText className="w-4 h-4 text-slate-700" />
                </div>
                <span className="text-[11px] text-slate-600 font-medium">Raw Doc</span>
              </div>
              <div className="relative z-10 flex flex-col items-center gap-1.5">
                <div className="w-10 h-10 rounded-full bg-white border border-slate-200 flex items-center justify-center shadow-xs">
                  <Radar className="w-4 h-4 text-slate-700" />
                </div>
                <span className="text-[11px] text-slate-600 font-medium">Detect</span>
              </div>
              <div className="relative z-10 flex flex-col items-center gap-1.5">
                <div className="w-10 h-10 rounded-full bg-indigo-600 text-white flex items-center justify-center shadow-md shadow-indigo-200 relative">
                  <Shield className="w-4 h-4 text-white" />
                  <div className="absolute -top-0.5 -right-0.5 w-3 h-3 bg-emerald-500 rounded-full border-2 border-white" />
                </div>
                <span className="text-[11px] font-bold text-indigo-600">Masking</span>
              </div>
              <div className="relative z-10 flex flex-col items-center gap-1.5">
                <div className="w-10 h-10 rounded-full bg-white border border-slate-200 flex items-center justify-center shadow-xs">
                  <Bot className="w-4 h-4 text-slate-700" />
                </div>
                <span className="text-[11px] text-slate-600 font-medium">Secure LLM</span>
              </div>
            </div>
          </section>

          <section>
            <div className="flex justify-between items-end mb-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                Entity Redaction Log
              </h3>
              <span className="text-xs text-slate-500 font-mono">{entities.length} entities</span>
            </div>

            {entities.length === 0 ? (
              <div className="p-6 text-center text-xs text-slate-400 bg-white border border-slate-200 rounded-2xl">
                No entities masked yet. Use the simulator below.
              </div>
            ) : (
              <div className="bg-white border border-slate-200 rounded-2xl shadow-xs overflow-hidden">
                <div className="grid grid-cols-[1fr_auto] gap-4 px-4 py-3 bg-slate-50 border-b border-slate-100 text-xs font-semibold text-slate-500">
                  <span>Detected String (Raw)</span>
                  <span>Masked Payload (LLM)</span>
                </div>
                <div className="divide-y divide-slate-100 text-sm">
                  {entities.map((item) => (
                    <div
                      key={item.id}
                      className="px-4 py-3 hover:bg-slate-50/70 transition-colors group"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-slate-800 line-through decoration-rose-400 decoration-2 font-medium text-xs min-w-0 truncate">
                          {item.rawString}
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
                          <span className="inline-flex items-center px-2 py-0.5 rounded-lg border border-indigo-200 bg-indigo-50 text-indigo-700 font-mono text-xs font-bold">
                            {item.maskedPayload}
                          </span>
                          <button
                            onClick={() => handleCopy(item.maskedPayload, item.id)}
                            className="opacity-0 group-hover:opacity-100 p-1.5 text-slate-400 hover:text-indigo-600 transition-all rounded-lg hover:bg-slate-100 cursor-pointer"
                            title="Copy Masked Token"
                          >
                            {copiedId === item.id ? (
                              <Check className="w-3.5 h-3.5 text-emerald-600" />
                            ) : (
                              <Copy className="w-3.5 h-3.5" />
                            )}
                          </button>
                        </div>
                      </div>
                      <div className="mt-1.5 flex items-center gap-2">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-bold uppercase tracking-wider ${TYPE_STYLES[item.entityType]}`}
                        >
                          {item.entityType}
                        </span>
                        <span className="text-[10px] text-slate-400 font-medium">
                          {item.timestamp}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>

          <section className="bg-slate-50 border border-slate-200 rounded-2xl p-5 shadow-xs">
            <div className="flex items-center gap-2 mb-1.5">
              <Sparkles className="w-4 h-4 text-indigo-600" />
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-900">
                Live Redaction Simulator
              </h4>
            </div>
            <p className="text-xs text-slate-500 mb-3">
              Type custom institutional text to verify zero-trust regex & NER tokenization:
            </p>

            <textarea
              value={testInput}
              onChange={(e) => setTestInput(e.target.value)}
              rows={2}
              className="w-full text-xs bg-white border border-slate-200 rounded-xl p-3 text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 resize-none mb-3 transition-all"
              placeholder="Enter institutional names, borrowers, or locations..."
            />

            {maskedPreview && (
              <div className="p-3 rounded-xl bg-white border border-slate-200 text-xs leading-relaxed text-slate-900 mb-3">
                <span className="text-[10px] font-bold uppercase text-slate-400 block mb-1">
                  Outbound Prompt to AI Model:
                </span>
                <div className="break-words font-mono text-xs text-slate-700">
                  {maskedPreview}
                </div>
              </div>
            )}

            {maskError && (
              <p className="mb-3 text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                {maskError}
              </p>
            )}

            <button
              type="button"
              onClick={handleMask}
              disabled={masking || !testInput.trim()}
              className="px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed text-white text-xs font-semibold rounded-xl shadow-md shadow-indigo-200 transition-all flex items-center gap-2 cursor-pointer active:scale-[0.98]"
            >
              {masking ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Masking…</span>
                </>
              ) : (
                <>
                  <Shield className="w-3.5 h-3.5" />
                  <span>Mask</span>
                </>
              )}
            </button>
          </section>

          <section>
            <div className="p-5 bg-emerald-50/50 border border-emerald-200 rounded-2xl flex gap-3.5 items-start">
              <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
              <div>
                <h4 className="text-sm font-bold text-slate-900 mb-1">
                  Audit Metrics Intact
                </h4>
                <p className="text-xs text-slate-600 leading-relaxed">
                  Financial and statistical numbers are verified to bypass masking so that model
                  performance statistics remain unaltered for LLM interpretation.
                </p>
              </div>
            </div>
          </section>
        </div>
      </motion.aside>
    </>
  );
}