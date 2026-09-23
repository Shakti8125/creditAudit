import { Component, lazy, Suspense, type ErrorInfo, type ReactNode } from 'react';
import { Loader2, XCircle } from 'lucide-react';

/**
 * RAG Performance route. The page (charts, tables, drawers) is code-split so it does not
 * grow the main bundle; this wrapper only handles the loading and load-failure states.
 */
const RagPerformancePage = lazy(() => import('@/components/rag/RagPerformancePage'));

class LoadBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('RAG Performance failed to render', error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div
        role="alert"
        className="flex flex-wrap items-center gap-3 rounded-2xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-700"
      >
        <XCircle className="h-4 w-4 shrink-0" />
        <span className="min-w-0 flex-1">RAG Performance failed to load.</span>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="cursor-pointer rounded-full border border-rose-200 bg-white px-3 py-1 text-xs font-semibold hover:bg-rose-100"
        >
          Reload
        </button>
      </div>
    );
  }
}

export default function RagPerformanceView() {
  return (
    <LoadBoundary>
      <Suspense
        fallback={
          <div role="status" className="flex items-center gap-2 py-10 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin text-indigo-600" />
            Loading RAG Performance…
          </div>
        }
      >
        <RagPerformancePage />
      </Suspense>
    </LoadBoundary>
  );
}
