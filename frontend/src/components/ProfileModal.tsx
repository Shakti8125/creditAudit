import { useEffect, useState, type FormEvent } from 'react';
import { motion } from 'motion/react';
import { BadgeCheck, Building, Loader2, Mail, Pencil, Save, User, X } from 'lucide-react';
import { getUserProfile, updateUserProfile } from '@/lib/api';
import { toProfile } from '@/lib/adapters';
import type { UserProfile } from '@/types';

interface ProfileModalProps {
  isOpen: boolean;
  onClose: () => void;
}

// Backend limit for each editable profile field.
const MAX_FIELD_LENGTH = 120;

interface ProfileDraft {
  fullName: string;
  title: string;
  division: string;
}

function draftFrom(profile: UserProfile): ProfileDraft {
  return {
    fullName: profile.fullName ?? '',
    title: profile.title ?? '',
    division: profile.division ?? '',
  };
}

export default function ProfileModal({ isOpen, onClose }: ProfileModalProps) {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [draft, setDraft] = useState<ProfileDraft | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    setDraft(null);
    setSaveError(null);
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await getUserProfile();
        if (!cancelled) setProfile(toProfile(res));
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unable to load profile');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  if (!isOpen) return null;

  async function handleSave(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!draft) return;
    setSaving(true);
    setSaveError(null);
    try {
      const res = await updateUserProfile({
        fullName: draft.fullName.trim() || null,
        title: draft.title.trim() || null,
        division: draft.division.trim() || null,
      });
      setProfile(toProfile(res));
      setDraft(null);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Unable to save profile');
    } finally {
      setSaving(false);
    }
  }

  const inputClass =
    'w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all';

  const field = (key: keyof ProfileDraft, label: string, placeholder: string) => (
    <div>
      <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
        {label}
      </label>
      <input
        type="text"
        value={draft?.[key] ?? ''}
        maxLength={MAX_FIELD_LENGTH}
        onChange={(e) => setDraft((prev) => (prev ? { ...prev, [key]: e.target.value } : prev))}
        placeholder={placeholder}
        className={inputClass}
      />
    </div>
  );

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
        className="sleek-card fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-md p-7 z-50"
      >
        <div className="flex justify-between items-center pb-4 border-b border-slate-100">
          <h2 className="font-display text-xl font-bold text-slate-900 tracking-tight">
            Validator Credentials
          </h2>
          <button
            onClick={onClose}
            className="p-2 rounded-full text-slate-400 hover:text-slate-700 hover:bg-slate-100 cursor-pointer transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="py-5">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-slate-400">
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
          ) : error ? (
            <div className="p-4 text-xs text-red-600 bg-red-50 border border-red-100 rounded-xl">
              {error}
            </div>
          ) : profile && draft ? (
            <form id="profile-edit-form" onSubmit={handleSave} className="space-y-4 text-sm">
              {field('fullName', 'Full Name', 'e.g. Jane Doe')}
              {field('title', 'Title', 'e.g. Senior Model Validator')}
              {field('division', 'Division', 'e.g. Model Risk Management')}
              {saveError && (
                <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                  {saveError}
                </p>
              )}
            </form>
          ) : profile ? (
            <div className="space-y-4">
              <div className="flex items-center gap-4 p-4 bg-slate-50 rounded-2xl border border-slate-200">
                <div className="w-13 h-13 rounded-2xl bg-indigo-50 border border-indigo-100 text-indigo-600 flex items-center justify-center shrink-0">
                  <User className="w-6 h-6" />
                </div>
                <div className="min-w-0">
                  <h3 className="text-sm font-bold text-slate-900 truncate">
                    {profile.fullName || profile.email}
                  </h3>
                  {(profile.title || profile.division) && (
                    <p className="text-xs text-slate-500 mt-0.5">
                      {[profile.title, profile.division].filter(Boolean).join(' · ')}
                    </p>
                  )}
                </div>
              </div>

              <div className="space-y-2.5 text-xs text-slate-700">
                <div className="flex items-center justify-between p-3 bg-slate-50 rounded-xl border border-slate-200">
                  <span className="flex items-center gap-2 text-slate-500">
                    <Mail className="w-4 h-4 text-slate-400" />
                    Email:
                  </span>
                  <span className="font-bold text-slate-900">{profile.email}</span>
                </div>

                <div className="flex items-center justify-between p-3 bg-slate-50 rounded-xl border border-slate-200">
                  <span className="flex items-center gap-2 text-slate-500">
                    <Building className="w-4 h-4 text-slate-400" />
                    Division:
                  </span>
                  <span className="font-bold text-slate-900">{profile.division ?? '—'}</span>
                </div>

                <div className="flex items-center justify-between p-3 bg-slate-50 rounded-xl border border-slate-200">
                  <span className="flex items-center gap-2 text-slate-500">
                    <BadgeCheck className="w-4 h-4 text-indigo-500" />
                    Role:
                  </span>
                  <span className="font-bold text-indigo-700 bg-indigo-50 border border-indigo-200 px-2.5 py-0.5 rounded-full">
                    {profile.role}
                  </span>
                </div>

                <div className="flex items-center justify-between p-3 bg-slate-50 rounded-xl border border-slate-200">
                  <span className="text-slate-500">Status:</span>
                  <span
                    className={`font-bold px-2.5 py-0.5 rounded-full border ${
                      profile.isActive
                        ? 'text-emerald-700 bg-emerald-50 border-emerald-200'
                        : 'text-rose-700 bg-rose-50 border-rose-200'
                    }`}
                  >
                    {profile.isActive ? 'Active' : 'Inactive'}
                  </span>
                </div>
              </div>
            </div>
          ) : null}
        </div>

        <div className="flex justify-end gap-3 pt-3 border-t border-slate-100">
          {draft ? (
            <>
              <button
                type="button"
                onClick={() => {
                  setDraft(null);
                  setSaveError(null);
                }}
                disabled={saving}
                className="px-4 py-2 text-xs font-semibold text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-xl transition-colors cursor-pointer disabled:opacity-60"
              >
                Cancel
              </button>
              <button
                type="submit"
                form="profile-edit-form"
                disabled={saving}
                className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed text-white text-xs font-semibold rounded-xl shadow-md shadow-indigo-200 transition-all flex items-center gap-2 cursor-pointer"
              >
                {saving ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Save className="w-3.5 h-3.5" />
                )}
                <span>{saving ? 'Saving…' : 'Save'}</span>
              </button>
            </>
          ) : (
            <>
              {profile && !loading && !error && (
                <button
                  type="button"
                  onClick={() => setDraft(draftFrom(profile))}
                  className="px-4 py-2.5 text-xs font-semibold text-indigo-700 bg-indigo-50 border border-indigo-100 hover:bg-indigo-100 rounded-xl transition-colors cursor-pointer flex items-center gap-2"
                >
                  <Pencil className="w-3.5 h-3.5" />
                  Edit profile
                </button>
              )}
              <button
                onClick={onClose}
                className="px-5 py-2.5 bg-slate-900 text-white text-xs font-semibold rounded-xl hover:bg-slate-800 transition-colors cursor-pointer"
              >
                Close
              </button>
            </>
          )}
        </div>
      </motion.div>
    </>
  );
}
