import { useEffect, useState } from 'react';
import { AlertTriangle, Check, Loader2, Lock, Save, ShieldCheck, Sliders } from 'lucide-react';
import type { TenantSettings } from '@/types';
import * as api from '@/lib/api';
import { toSettings } from '@/lib/adapters';

// Fixed Gini floor applied by the backend policy checker (CBUAE MMG).
const GINI_FLOOR_PCT = 40;

interface SettingsViewProps {
  /** Called after thresholds are saved (the backend has re-scored every model). */
  onSaved: () => void;
}

interface SliderFieldProps {
  label: string;
  display: string;
  description: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}

function SliderField({
  label,
  display,
  description,
  value,
  min,
  max,
  step,
  onChange,
}: SliderFieldProps) {
  return (
    <div className="flex flex-col gap-2.5 bg-slate-50 p-5 rounded-2xl border border-slate-200">
      <div className="flex justify-between items-center">
        <span className="font-semibold text-slate-800">{label}</span>
        <span className="font-mono font-bold text-indigo-700 bg-indigo-50 border border-indigo-100 px-2.5 py-0.5 rounded-lg text-xs">
          {display}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="accent-indigo-600 cursor-pointer"
      />
      <p className="text-xs text-slate-500">{description}</p>
    </div>
  );
}

const ENFORCED_MASKING: { label: string; token: string }[] = [
  { label: 'Bank & financial institution names', token: '[BANK_1]' },
  { label: 'Organisations', token: '[ORG_1]' },
  { label: 'People (borrowers, personnel)', token: '[PERSON_1]' },
  { label: 'Locations', token: '[GPE_1]' },
  { label: 'Email addresses', token: '[EMAIL_1]' },
  { label: 'Phone numbers', token: '[PHONE_1]' },
];

export default function SettingsView({ onSaved }: SettingsViewProps) {
  const [settings, setSettings] = useState<TenantSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveNote, setSaveNote] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getSettings()
      .then((dto) => {
        if (cancelled) return;
        setSettings(toSettings(dto));
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err instanceof Error ? err.message : 'Unable to load settings');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const psiOrderInvalid =
    !!settings && settings.psiWarningThreshold >= settings.psiBreachThreshold;

  async function handleSave() {
    if (!settings || psiOrderInvalid) return;
    setSaving(true);
    setSaveNote(null);
    try {
      await api.updateSettings({
        gini_tolerance: settings.giniTolerance,
        psi_warning_threshold: settings.psiWarningThreshold,
        psi_breach_threshold: settings.psiBreachThreshold,
      });
      setSaveNote('Settings saved. All models were re-scored against the new thresholds.');
      onSaved();
    } catch (err) {
      setSaveNote(`Save failed: ${err instanceof Error ? err.message : 'unknown error'}`);
    } finally {
      setSaving(false);
    }
  }

  function update(patch: Partial<TenantSettings>) {
    setSettings((prev) => (prev ? { ...prev, ...patch } : prev));
  }

  const giniWarnCeiling = settings
    ? Number((GINI_FLOOR_PCT + settings.giniTolerance * 100).toFixed(1))
    : GINI_FLOOR_PCT;

  return (
    <div className="space-y-8 max-w-4xl">
      {/* Header */}
      <div>
        <h2 className="text-xs font-bold text-indigo-600 uppercase tracking-wider mb-1">
          System Configuration
        </h2>
        <h1 className="font-display text-3xl font-bold text-slate-900 tracking-tight">
          Audit Rules & Privacy Thresholds
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Configure the policy thresholds used to score model validation metrics. Privacy masking
          is always enforced.
        </p>
      </div>

      {loading && (
        <div className="sleek-card p-6 flex items-center justify-center gap-2 text-sm text-slate-500">
          <Loader2 className="w-4 h-4 animate-spin text-indigo-600" />
          Loading settings…
        </div>
      )}

      {!loading && loadError && (
        <div className="bg-rose-50 border border-rose-100 rounded-2xl p-4 text-sm text-rose-700 flex items-center gap-2">
          <ShieldCheck className="w-4 h-4" />
          {loadError}
        </div>
      )}

      {!loading && !loadError && settings && (
        <div className="space-y-6">
          {/* Section 1: Quantitative Audit Thresholds */}
          <section className="sleek-card p-7 space-y-6">
            <div className="flex items-center gap-2.5 border-b border-slate-100 pb-4">
              <Sliders className="w-5 h-5 text-indigo-600" />
              <div>
                <h3 className="text-base font-bold text-slate-900">Policy Scoring Thresholds</h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  Saving re-scores the current version of every model against these thresholds.
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-5 text-sm">
              <div className="md:col-span-2">
                <SliderField
                  label="Gini Warning Band"
                  display={`${GINI_FLOOR_PCT}–${giniWarnCeiling}%`}
                  description={`Gini below ${GINI_FLOOR_PCT}% is a breach (CBUAE MMG). Gini from ${GINI_FLOOR_PCT}% up to ${giniWarnCeiling}% is flagged as a warning; above that it passes.`}
                  value={settings.giniTolerance}
                  min={0.01}
                  max={0.3}
                  step={0.01}
                  onChange={(v) => update({ giniTolerance: v })}
                />
              </div>

              <SliderField
                label="Population Stability (PSI) Warning"
                display={settings.psiWarningThreshold.toFixed(2)}
                description={`PSI from ${settings.psiWarningThreshold.toFixed(
                  2,
                )} up to ${settings.psiBreachThreshold.toFixed(2)} is flagged as a warning (moderate population shift).`}
                value={settings.psiWarningThreshold}
                min={0.05}
                max={0.2}
                step={0.01}
                onChange={(v) => update({ psiWarningThreshold: v })}
              />

              <SliderField
                label="Population Stability (PSI) Breach"
                display={settings.psiBreachThreshold.toFixed(2)}
                description="PSI above this level is scored as a stability breach."
                value={settings.psiBreachThreshold}
                min={0.15}
                max={0.5}
                step={0.01}
                onChange={(v) => update({ psiBreachThreshold: v })}
              />

              {psiOrderInvalid && (
                <p className="md:col-span-2 flex items-center gap-2 text-xs font-semibold text-rose-700 bg-rose-50 border border-rose-100 rounded-xl px-3 py-2">
                  <AlertTriangle className="w-4 h-4 shrink-0" />
                  The PSI warning threshold must be lower than the breach threshold.
                </p>
              )}
            </div>
          </section>

          {/* Section 2: Zero-Trust Data Masking (not configurable) */}
          <section className="sleek-card p-7 space-y-5">
            <div className="flex items-center justify-between gap-3 border-b border-slate-100 pb-4">
              <div className="flex items-center gap-2.5">
                <ShieldCheck className="w-5 h-5 text-emerald-600" />
                <h3 className="text-base font-bold text-slate-900">
                  Zero-Trust Privacy & PII Scrubbing
                </h3>
              </div>
              <span className="inline-flex items-center gap-1.5 text-[11px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-3 py-1">
                <Lock className="w-3 h-3" />
                Always enforced
              </span>
            </div>

            <p className="text-xs text-slate-500">
              Before any text reaches an LLM, these entities are replaced with tokens. Masking
              cannot be disabled.
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 text-sm">
              {ENFORCED_MASKING.map((item) => (
                <div
                  key={item.token}
                  className="flex items-center justify-between gap-3 p-3.5 bg-slate-50 rounded-xl border border-slate-200"
                >
                  <span className="text-xs font-semibold text-slate-800">{item.label}</span>
                  <code className="font-mono text-[11px] font-bold text-indigo-600">{item.token}</code>
                </div>
              ))}
            </div>

            <div className="flex items-start gap-2.5 p-3.5 bg-emerald-50/60 border border-emerald-200 rounded-xl text-xs text-emerald-800">
              <Check className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
              <span>
                Egress validation: every outbound prompt is re-checked and hard-blocked if an
                unmasked entity remains.
              </span>
            </div>
          </section>

          {/* Save Bar */}
          <div className="flex justify-end items-center gap-3 pt-2">
            {saveNote && (
              <span
                className={`text-xs font-bold flex items-center gap-1.5 ${
                  saveNote.startsWith('Save failed')
                    ? 'text-rose-600'
                    : 'text-emerald-600'
                }`}
              >
                {saveNote.startsWith('Save failed') ? <ShieldCheck className="w-4 h-4" /> : <Check className="w-4 h-4" />}
                {saveNote}
              </span>
            )}

            <button
              type="button"
              onClick={handleSave}
              disabled={saving || psiOrderInvalid}
              className="flex items-center gap-2 px-6 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed text-white rounded-xl text-sm font-semibold active:scale-[0.98] transition-all shadow-md shadow-indigo-200 cursor-pointer"
            >
              {saving ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Save className="w-4 h-4" />
              )}
              <span>{saving ? 'Saving…' : 'Save Configuration'}</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
