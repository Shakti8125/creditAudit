import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Loader2 } from 'lucide-react';
import { isBackendOnline } from '@/lib/health';
import DemoOfflineView from '@/components/DemoOfflineView';

const RETRY_INTERVAL_MS = 30_000;

type GateStatus = 'checking' | 'online' | 'offline';

/**
 * Shows the app only when the backend answers. Otherwise it shows the offline
 * front door instead of a sign-in form that cannot work.
 *
 * Once the backend has answered, the gate stays out of the way: it does not poll
 * again, so a later outage cannot unmount a session in progress.
 */
export default function BackendGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<GateStatus>('checking');
  const [retrying, setRetrying] = useState(false);
  const mounted = useRef(true);

  const probe = useCallback(async () => {
    const online = await isBackendOnline();
    if (mounted.current) setStatus(online ? 'online' : 'offline');
  }, []);

  useEffect(() => {
    mounted.current = true;
    void probe();
    return () => {
      mounted.current = false;
    };
  }, [probe]);

  useEffect(() => {
    if (status !== 'offline') return;
    const timer = window.setInterval(() => {
      if (!document.hidden) void probe();
    }, RETRY_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [status, probe]);

  const retry = useCallback(async () => {
    setRetrying(true);
    await probe();
    if (mounted.current) setRetrying(false);
  }, [probe]);

  if (status === 'online') return <>{children}</>;

  if (status === 'checking') {
    return (
      <div
        role="status"
        className="min-h-screen bg-slate-50 flex items-center justify-center gap-2 text-sm text-slate-500"
      >
        <Loader2 className="w-4 h-4 animate-spin" />
        Connecting to the backend…
      </div>
    );
  }

  return <DemoOfflineView retrying={retrying} onRetry={retry} />;
}
