import { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import {
  AlertTriangle,
  ArrowRight,
  Bell,
  CheckCircle2,
  Info,
  Loader2,
  X,
} from 'lucide-react';
import { listNotifications, markNotificationRead } from '@/lib/api';
import { toNotification } from '@/lib/adapters';
import type { NotificationItem, NotificationType } from '@/types';

interface NotificationsDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectModel: (modelId: string) => void;
}

const TYPE_ICON: Record<NotificationType, typeof Info> = {
  PASS: CheckCircle2,
  WARNING: AlertTriangle,
  BREACH: AlertTriangle,
  INFO: Info,
};

const TYPE_ICON_COLOR: Record<NotificationType, string> = {
  PASS: 'text-emerald-600',
  WARNING: 'text-amber-500',
  BREACH: 'text-rose-500',
  INFO: 'text-sky-500',
};

const TYPE_BADGE: Record<NotificationType, string> = {
  PASS: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  WARNING: 'bg-amber-50 text-amber-700 border-amber-200',
  BREACH: 'bg-rose-50 text-rose-700 border-rose-200',
  INFO: 'bg-sky-50 text-sky-700 border-sky-200',
};

export default function NotificationsDrawer({
  isOpen,
  onClose,
  onSelectModel,
}: NotificationsDrawerProps) {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await listNotifications();
        if (cancelled) return;
        const data = Array.isArray(res) ? res : (res as any)?.items ?? [];
        setItems(data.map((n: any) => toNotification(n)));
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unable to load notifications');
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

  async function handleClick(item: NotificationItem) {
    if (!item.isRead) {
      setItems((prev) =>
        prev.map((n) => (n.id === item.id ? { ...n, isRead: true } : n)),
      );
      try {
        await markNotificationRead(item.id);
      } catch {
        // Ignore read-marking failure; navigation still proceeds.
      }
    }
    if (item.modelId) {
      onSelectModel(item.modelId);
      onClose();
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
        className="glass-drawer fixed top-0 right-0 bottom-0 w-full sm:w-[440px] z-50 flex flex-col overflow-hidden"
      >
        <div className="p-6 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-indigo-50 border border-indigo-100 text-indigo-600 flex items-center justify-center shadow-xs">
              <Bell className="w-5 h-5" />
            </div>
            <div>
              <h2 className="font-display text-xl font-bold text-slate-900 tracking-tight">
                Audit Notifications
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">Model alerts & regulatory updates</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-full text-slate-400 hover:text-slate-700 hover:bg-slate-100 cursor-pointer transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-3.5">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-slate-400">
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
          ) : error ? (
            <div className="p-4 text-xs text-red-600 bg-red-50 border border-red-100 rounded-xl">
              {error}
            </div>
          ) : items.length === 0 ? (
            <div className="p-6 text-center text-xs text-slate-400">No notifications yet.</div>
          ) : (
            items.map((n) => {
              const Icon = TYPE_ICON[n.type];
              return (
                <div
                  key={n.id}
                  onClick={() => handleClick(n)}
                  className={`p-4 rounded-2xl border transition-all cursor-pointer group ${
                    n.isRead
                      ? 'bg-white border-slate-200 hover:border-indigo-200 hover:shadow-xs'
                      : 'bg-indigo-50/40 border-indigo-200 hover:bg-indigo-50/60 hover:shadow-xs'
                  }`}
                >
                  <div className="flex justify-between items-start mb-1.5">
                    <div className="flex items-center gap-2 text-xs font-bold text-slate-900">
                      <Icon className={`w-4 h-4 shrink-0 ${TYPE_ICON_COLOR[n.type]}`} />
                      <span>{n.title}</span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-bold uppercase tracking-wider ${TYPE_BADGE[n.type]}`}
                      >
                        {n.type}
                      </span>
                      {!n.isRead && (
                        <span className="w-2 h-2 bg-indigo-500 rounded-full" title="Unread" />
                      )}
                    </div>
                  </div>

                  {n.description && (
                    <p className="text-xs text-slate-600 leading-relaxed">{n.description}</p>
                  )}

                  <div className="mt-3 pt-2.5 border-t border-slate-200/60 flex items-center justify-between text-xs text-indigo-600 font-semibold opacity-90 group-hover:opacity-100">
                    <span>{n.time}</span>
                    {n.modelId && (
                      <span className="inline-flex items-center gap-1">
                        Inspect in Workspace
                        <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-1 transition-transform" />
                      </span>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </motion.aside>
    </>
  );
}