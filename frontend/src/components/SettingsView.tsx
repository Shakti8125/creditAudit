import { useEffect, useState } from 'react';
import { Check, Loader2, Save, ShieldCheck, Sliders } from 'lucide-react';
import type { TenantSettings } from '@/types';
import * as api from '@/lib/api';
import { toSettings } from '@/lib/adapters';

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

interface ToggleRowProps {
  title: string;
  example: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}

function ToggleRow({ title, example, checked, onChange }: ToggleRowProps) {
  return (
    <label className="flex items-center justify-between p-4 bg-slate-50 rounded-2xl border border-slate-200 cursor-pointer hover:bg-slate-100/70 transition-colors">
      <div>
        <span className="font-semibold text-slate-900 block">{title}</span>
        <span className="text-xs text-slate-500">
          Replaces identifiers with{' '}
          <code className="font-mono font-bold text-indigo-600">{example}</code> before LLM
          transmission.
        </span>
      </div>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="w-4 h-4 accent-indigo-600 rounded cursor-pointer"
      />
    </label>
  );
}

export default function SettingsView() {
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

  async function handleSave() {
    if (!settings) return;
    setSaving(true);
    setSaveNote(null);
    try {
      await api.updateSettings({
        gini_tolerance: settings.giniTolerance,
        psi_warning_threshold: settings.psiWarningThreshold,
        psi_breach_threshold: settings.psiBreachThreshold,
        min_observation_months: settings.minObservationMonths,
        auto_mask_bank: settings.autoMaskBank,
        auto_mask_borrower: settings.autoMaskBorrower,
        auto_mask_location: settings.autoMaskLocation,
        strict_zero_trust: settings.strictZeroTrust,
      });
      setSaveNote('Settings saved successfully!');
    } catch (err) {
      setSaveNote(`Save failed: ${err instanceof Error ? err.message : 'unknown error'}`);
    } finally {
      setSaving(false);
    }
  }

  function update(patch: Partial<TenantSettings>) {
    setSettings((prev) => (prev ? { ...prev, ...patch } : prev));
  }

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
          Configure validation tolerance boundaries, zero-trust tokenization algorithms, and
          reporting formats.
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
              <h3 className="text-base font-bold text-slate-900">
                Model Performance Degradation Tolerances
              </h3>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-5 text-sm">
              <SliderField
                label="Max Gini Degradation Tolerance"
                display={`${(settings.giniTolerance * 100).toFixed(0)}%`}
                description={`Flags a warning if out-of-time Gini drops by more than ${(
                  settings.giniTolerance * 100
                ).toFixed(0)}% (CBUAE §4.2 standard).`}
                value={settings.giniTolerance}
                min={0.01}
                max={0.3}
                step={0.01}
                onChange={(v) => update({ giniTolerance: v })}
              />

              <SliderField
                label="Population Stability (PSI) Warning"
                display={settings.psiWarningThreshold.toFixed(2)}
                description={`PSI between ${settings.psiWarningThreshold.toFixed(
                  2,
                )} and ${settings.psiBreachThreshold.toFixed(2)} indicates moderate population shift.`}
                value={settings.psiWarningThreshold}
                min={0.05}
                max={0.2}
                step={0.01}
                onChange={(v) => update({ psiWarningThreshold: v })}
              />

              <SliderField
                label="Population Stability (PSI) Breach"
                display={settings.psiBreachThreshold.toFixed(2)}
                description="PSI above this level is treated as a stability breach and flagged in early-warning alerts."
                value={settings.psiBreachThreshold}
                min={0.15}
                max={0.5}
                step={0.01}
                onChange={(v) => update({ psiBreachThreshold: v })}
              />

              <div className="md:col-span-2">
                <SliderField
                  label="Minimum Historical Sample Window (Basel III/IV)"
                  display={`${settings.minObservationMonths} Months (${(
                    settings.minObservationMonths / 12
                  ).toFixed(1)} Years)`}
                  description="Basel CRE guidelines mandate a 5-year (60 months) default history spanning economic cycle downturns."
                  value={settings.minObservationMonths}
                  min={24}
                  max={120}
                  step={6}
                  onChange={(v) => update({ minObservationMonths: v })}
                />
              </div>
            </div>
          </section>

          {/* Section 2: Zero-Trust Data Masking Rules */}
          <section className="sleek-card p-7 space-y-6">
            <div className="flex items-center gap-2.5 border-b border-slate-100 pb-4">
              <ShieldCheck className="w-5 h-5 text-emerald-600" />
              <h3 className="text-base font-bold text-slate-900">
                Zero-Trust Privacy & PII Scrubbing Rules
              </h3>
            </div>

            <div className="space-y-3.5 text-sm">
              <ToggleRow
                title="Automatic Institutional Entity Masking (e.g., Bank Names)"
                example="[BANK_1]"
                checked={settings.autoMaskBank}
                onChange={(v) => update({ autoMaskBank: v })}
              />
              <ToggleRow
                title="Personnel & Borrower PII Tokenization"
                example="[PERSON_N]"
                checked={settings.autoMaskBorrower}
                onChange={(v) => update({ autoMaskBorrower: v })}
              />
              <ToggleRow
                title="Geographic Location Masking"
                example="[LOCATION_N]"
                checked={settings.autoMaskLocation}
                onChange={(v) => update({ autoMaskLocation: v })}
              />
              <ToggleRow
                title="Strict Zero-Trust Egress Validation"
                example="[IDENTIFIER_N]"
                checked={settings.strictZeroTrust}
                onChange={(v) => update({ strictZeroTrust: v })}
              />
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
              disabled={saving}
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