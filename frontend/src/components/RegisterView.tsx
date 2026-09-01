import { useState, type FormEvent } from 'react';
import { motion } from 'motion/react';
import { ArrowRight, Building2, Loader2, Lock, Mail, Shield } from 'lucide-react';
import useAuth from '@/hooks/useAuth';

interface RegisterViewProps {
  onSwitch?: () => void;
}

export default function RegisterView({ onSwitch }: RegisterViewProps) {
  const { register } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [tenantName, setTenantName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      await register(email, password, tenantName);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create account');
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center px-4 py-12">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: 'easeOut' }}
        className="w-full max-w-md"
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

          <h2 className="font-display font-bold text-xl text-slate-900">Create an account</h2>
          <p className="mt-1 text-sm text-slate-500">Provision a new audit workspace.</p>

          <form onSubmit={handleSubmit} className="mt-6 space-y-4">
            <div>
              <label htmlFor="register-email" className="block text-sm font-semibold text-slate-700 mb-1.5">
                Work email
              </label>
              <div className="relative">
                <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  id="register-email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@bank.com"
                  className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-slate-200 bg-white text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-600/20 focus:border-indigo-600"
                />
              </div>
            </div>

            <div>
              <label htmlFor="register-tenant" className="block text-sm font-semibold text-slate-700 mb-1.5">
                Organization
              </label>
              <div className="relative">
                <Building2 className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  id="register-tenant"
                  type="text"
                  autoComplete="organization"
                  required
                  value={tenantName}
                  onChange={(e) => setTenantName(e.target.value)}
                  placeholder="Acme National Bank"
                  className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-slate-200 bg-white text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-600/20 focus:border-indigo-600"
                />
              </div>
            </div>

            <div>
              <label htmlFor="register-password" className="block text-sm font-semibold text-slate-700 mb-1.5">
                Password
              </label>
              <div className="relative">
                <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  id="register-password"
                  type="password"
                  autoComplete="new-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-slate-200 bg-white text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-600/20 focus:border-indigo-600"
                />
              </div>
            </div>

            {error && (
              <p className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={pending}
              className="w-full flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed text-white font-semibold text-sm py-2.5 rounded-xl transition-colors cursor-pointer"
            >
              {pending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Creating account…
                </>
              ) : (
                <>
                  Create account
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>

          <p className="mt-6 text-sm text-center text-slate-500">
            Already have an account?{' '}
            <button
              type="button"
              onClick={onSwitch}
              className="text-indigo-600 font-semibold hover:text-indigo-700 cursor-pointer"
            >
              Sign in
            </button>
          </p>
        </div>
      </motion.div>
    </div>
  );
}