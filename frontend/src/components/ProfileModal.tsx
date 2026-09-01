import { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { BadgeCheck, Building, Loader2, Mail, Shield, User, X } from 'lucide-react';
import { getUserProfile } from '@/lib/api';
import { toProfile } from '@/lib/adapters';
import type { UserProfile } from '@/types';

interface ProfileModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function ProfileModal({ isOpen, onClose }: ProfileModalProps) {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
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
          ) : profile ? (
            <div className="space-y-4">
              <div className="flex items-center gap-4 p-4 bg-slate-50 rounded-2xl border border-slate-200">
                <div className="w-13 h-13 rounded-2xl bg-indigo-50 border border-indigo-100 text-indigo-600 flex items-center justify-center shrink-0">
                  <User className="w-6 h-6" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-slate-900">
                    {profile.fullName || profile.email}
                  </h3>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {profile.title ?? 'Risk Management'}
                    {profile.division ? ` · ${profile.division}` : ''}
                  </p>
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
                    <Shield className="w-4 h-4 text-emerald-600" />
                    Security Clearance:
                  </span>
                  <span className="font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-2.5 py-0.5 rounded-full">
                    {profile.securityClearance ?? '—'}
                  </span>
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

        <div className="flex justify-end pt-3 border-t border-slate-100">
          <button
            onClick={onClose}
            className="px-5 py-2.5 bg-slate-900 text-white text-xs font-semibold rounded-xl hover:bg-slate-800 transition-colors cursor-pointer"
          >
            Close
          </button>
        </div>
      </motion.div>
    </>
  );
}