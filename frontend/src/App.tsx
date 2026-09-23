import { useCallback, useEffect, useRef, useState } from 'react';
import { X, Shield, AlertTriangle } from 'lucide-react';

import type {
  NavItem,
  ModelSummary,
  DashboardMetrics,
  TenantSettings,
  WorkspaceTab,
} from '@/types';
import {
  listModels,
  getModel,
  getSettings,
  getDashboardMetrics,
  listNotifications,
} from '@/lib/api';
import {
  toModelSummary,
  toSettings,
  toDashboardMetrics,
  toNotification,
} from '@/lib/adapters';
import useAuth from '@/hooks/useAuth';

import SideNav from '@/components/SideNav';
import TopNav from '@/components/TopNav';
import OverviewView from '@/components/OverviewView';
import WorkspaceView from '@/components/WorkspaceView';
import CompareModelsView from '@/components/CompareModelsView';
import RegulatoryLibraryView from '@/components/RegulatoryLibraryView';
import SettingsView from '@/components/SettingsView';
import LoginView from '@/components/LoginView';
import RegisterView from '@/components/RegisterView';
import PrivacyInspectorDrawer from '@/components/PrivacyInspectorDrawer';
import NotificationsDrawer from '@/components/NotificationsDrawer';
import NewAuditModal from '@/components/NewAuditModal';
import ModelLineageModal from '@/components/ModelLineageModal';
import ExportReportModal from '@/components/ExportReportModal';
import ProfileModal from '@/components/ProfileModal';
import HelpModal from '@/components/HelpModal';

const NAV_LABELS: Record<NavItem, string> = {
  overview: 'Overview',
  workspace: 'Workspace',
  compare: 'Compare Models',
  library: 'Regulatory Library',
  settings: 'Settings',
};

const EMPTY_METRICS: DashboardMetrics = {
  activeModels: 0,
  documentsAnalyzed: 0,
  complianceIssues: 0,
  aiReviews: 0,
};

function countUnread(dto: unknown): number {
  const raw: any[] = Array.isArray(dto) ? dto : ((dto as any)?.items ?? []);
  return raw.map(toNotification).filter((n) => !n.isRead).length;
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export default function App() {
  const { user, ready, logout } = useAuth();
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');

  const [activeNav, setActiveNav] = useState<NavItem>('overview');
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>('metrics');
  const [models, setModels] = useState<ModelSummary[]>([]);
  const [currentModel, setCurrentModel] = useState<ModelSummary | null>(null);
  const [metrics, setMetrics] = useState<DashboardMetrics>(EMPTY_METRICS);
  const [settings, setSettings] = useState<TenantSettings | undefined>(undefined);
  const settingsRef = useRef<TenantSettings | undefined>(undefined);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [appError, setAppError] = useState<string | null>(null);
  // Document to focus in the workspace: just uploaded, or opened from a citation / search result.
  const [activeDocumentId, setActiveDocumentId] = useState<string | null>(null);
  // AI Analyst session in use, for the Privacy Inspector's redaction log.
  const [chatSessionId, setChatSessionId] = useState<string | null>(null);
  // Standard code / citation source the Regulatory Library should focus on.
  const [libraryFocus, setLibraryFocus] = useState<string | null>(null);

  // Modals & drawers
  const [isPrivacyInspectorOpen, setIsPrivacyInspectorOpen] = useState(false);
  const [isNewAuditOpen, setIsNewAuditOpen] = useState(false);
  const [isLineageOpen, setIsLineageOpen] = useState(false);
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false);
  const [isExportOpen, setIsExportOpen] = useState(false);
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const [isHelpOpen, setIsHelpOpen] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  /**
   * Reloads settings, models, dashboard KPIs and the unread-notification count.
   * Keeps the selected model (or switches to `selectModelId`).
   */
  const reload = useCallback(async (selectModelId?: string) => {
    const [settingsRes, modelsRes, metricsRes, notificationsRes] = await Promise.allSettled([
      getSettings(),
      listModels(),
      getDashboardMetrics(),
      listNotifications(),
    ]);

    const s =
      settingsRes.status === 'fulfilled' ? toSettings(settingsRes.value) : settingsRef.current;
    settingsRef.current = s;
    setSettings(s);

    if (modelsRes.status === 'fulfilled') {
      const raw: unknown[] = Array.isArray(modelsRes.value) ? modelsRes.value : [];
      const adapted = raw.map((d) => toModelSummary(d, s));
      setModels(adapted);
      setCurrentModel((prev) => {
        const wanted = selectModelId ?? prev?.id;
        return adapted.find((m) => m.id === wanted) ?? adapted[0] ?? null;
      });
      setAppError(null);
    } else {
      setAppError(errorMessage(modelsRes.reason, 'Unable to load models.'));
    }
    if (metricsRes.status === 'fulfilled') setMetrics(toDashboardMetrics(metricsRes.value));
    if (notificationsRes.status === 'fulfilled') {
      setUnreadCount(countUnread(notificationsRes.value));
    }
  }, []);

  useEffect(() => {
    if (!user) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    void reload().finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [user, reload]);

  const handleLogout = () => {
    setModels([]);
    setCurrentModel(null);
    setActiveDocumentId(null);
    setChatSessionId(null);
    setLibraryFocus(null);
    setActiveNav('overview');
    logout();
  };

  const selectNav = (item: NavItem) => {
    setLibraryFocus(null);
    setActiveNav(item);
  };

  /** Opens a model in the workspace, fetching it if it is not in the local list. */
  const openModelById = async (modelId: string): Promise<boolean> => {
    let found = models.find((m) => m.id === modelId);
    if (!found) {
      try {
        found = toModelSummary(await getModel(modelId), settings);
      } catch (err) {
        setAppError(errorMessage(err, 'Unable to open the model.'));
        return false;
      }
      const fetched = found;
      setModels((prev) => (prev.some((m) => m.id === fetched.id) ? prev : [fetched, ...prev]));
    }
    setCurrentModel(found);
    setActiveNav('workspace');
    return true;
  };

  const openDocument = async (documentId: string, modelId?: string) => {
    if (modelId && modelId !== currentModel?.id && !(await openModelById(modelId))) return;
    setActiveDocumentId(documentId);
    setWorkspaceTab('documents');
    setActiveNav('workspace');
  };

  const openStandard = (query: string) => {
    setLibraryFocus(query);
    setActiveNav('library');
  };

  const handleAuditCreated = (newModel: ModelSummary, documentId?: string) => {
    setModels((prev) => [newModel, ...prev.filter((m) => m.id !== newModel.id)]);
    setCurrentModel(newModel);
    setActiveDocumentId(documentId ?? null);
    setWorkspaceTab('metrics');
    setActiveNav('workspace');
    void reload(newModel.id);
  };

  const handleDocumentAnalyzed = (model: ModelSummary, documentId: string) => {
    setModels((prev) => prev.map((m) => (m.id === model.id ? model : m)));
    setCurrentModel(model);
    setActiveDocumentId(documentId);
    setWorkspaceTab('gap');
    setActiveNav('workspace');
    void reload(model.id);
  };

  if (!ready) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center text-slate-500">
        <span className="animate-pulse">Loading…</span>
      </div>
    );
  }

  if (!user) {
    return authMode === 'login' ? (
      <LoginView onSwitch={() => setAuthMode('register')} />
    ) : (
      <RegisterView onSwitch={() => setAuthMode('login')} />
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 relative selection:bg-indigo-600 selection:text-white">
      <SideNav
        activeNav={activeNav}
        onSelectNav={selectNav}
        onOpenNewAudit={() => setIsNewAuditOpen(true)}
        onOpenProfile={() => setIsProfileOpen(true)}
        onOpenHelp={() => setIsHelpOpen(true)}
        onLogout={handleLogout}
      />

      {isMobileMenuOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div
            onClick={() => setIsMobileMenuOpen(false)}
            className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs"
          />
          <div className="fixed top-0 left-0 bottom-0 w-72 bg-white p-6 flex flex-col shadow-2xl z-50">
            <div className="flex justify-between items-center mb-6">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-xl bg-indigo-600 text-white flex items-center justify-center shadow-md shadow-indigo-200">
                  <Shield className="w-4 h-4" />
                </div>
                <h2 className="font-display font-bold text-slate-900 tracking-tight">ModelAudit AI</h2>
              </div>
              <button
                onClick={() => setIsMobileMenuOpen(false)}
                className="p-1.5 rounded-full text-slate-400 hover:text-slate-700 hover:bg-slate-100 cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <nav className="space-y-1.5 flex-1">
              {(Object.keys(NAV_LABELS) as NavItem[]).map((item) => (
                <button
                  key={item}
                  onClick={() => {
                    selectNav(item);
                    setIsMobileMenuOpen(false);
                  }}
                  className={`w-full text-left px-3.5 py-2.5 rounded-xl text-sm font-semibold transition-all cursor-pointer ${
                    activeNav === item
                      ? 'bg-indigo-50 text-indigo-700 font-bold'
                      : 'text-slate-600 hover:bg-slate-100'
                  }`}
                >
                  {NAV_LABELS[item]}
                </button>
              ))}
            </nav>

            <button
              onClick={() => {
                setIsMobileMenuOpen(false);
                setIsNewAuditOpen(true);
              }}
              className="w-full bg-indigo-600 text-white py-3 rounded-xl text-sm font-bold shadow-md shadow-indigo-200 hover:bg-indigo-700 transition-all cursor-pointer mt-4"
            >
              + New Audit
            </button>
          </div>
        </div>
      )}

      <TopNav
        currentModel={currentModel}
        models={models}
        unreadCount={unreadCount}
        onSelectModel={(m) => setCurrentModel(m)}
        onOpenModel={(id) => void openModelById(id)}
        onOpenStandard={openStandard}
        onOpenDocument={(docId, modelId) => void openDocument(docId, modelId)}
        onOpenPrivacyInspector={() => setIsPrivacyInspectorOpen(true)}
        onOpenLineage={() => setIsLineageOpen(true)}
        onOpenNotifications={() => setIsNotificationsOpen(true)}
        onToggleMobileMenu={() => setIsMobileMenuOpen(true)}
      />

      <main className="md:ml-[304px] pt-28 px-6 pb-12 transition-all">
        {appError && (
          <div className="mb-6 bg-rose-50 border border-rose-100 rounded-2xl p-4 text-sm text-rose-700 flex flex-wrap items-center gap-3">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span className="flex-1 min-w-0">{appError}</span>
            <button
              type="button"
              onClick={() => void reload()}
              className="text-xs font-bold text-rose-700 hover:text-rose-900 cursor-pointer"
            >
              Retry
            </button>
            <button
              type="button"
              onClick={() => setAppError(null)}
              className="p-1 rounded-full text-rose-400 hover:text-rose-700 hover:bg-rose-100 cursor-pointer"
              aria-label="Dismiss"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {loading && <div className="text-slate-400">Loading workspace…</div>}

        {!loading && activeNav === 'overview' && (
          <OverviewView
            models={models}
            metrics={metrics}
            onSelectModel={(m) => setCurrentModel(m)}
            onNavigateToWorkspace={() => setActiveNav('workspace')}
            onOpenNewAudit={() => setIsNewAuditOpen(true)}
          />
        )}

        {!loading && activeNav === 'workspace' &&
          (currentModel ? (
            <WorkspaceView
              key={`${currentModel.id}:${currentModel.currentVersionId ?? ''}`}
              currentModel={currentModel}
              tab={workspaceTab}
              onTabChange={setWorkspaceTab}
              activeDocumentId={activeDocumentId}
              onExportReport={() => setIsExportOpen(true)}
              onNavigateToCompare={() => setActiveNav('compare')}
              onOpenRegulatoryStandard={openStandard}
              onOpenDocument={(docId) => void openDocument(docId)}
              onSessionIdChange={setChatSessionId}
              onDocumentsChanged={() => void reload()}
            />
          ) : (
            <div className="sleek-card p-8 text-slate-500">No model selected yet.</div>
          ))}

        {!loading && activeNav === 'compare' &&
          (currentModel ? (
            <CompareModelsView
              models={models}
              currentModel={currentModel}
              onSelectModel={(m) => setCurrentModel(m)}
            />
          ) : (
            <div className="sleek-card p-8 text-slate-500">No model to compare yet.</div>
          ))}

        {!loading && activeNav === 'library' && (
          <RegulatoryLibraryView
            models={models}
            settings={settings}
            focusQuery={libraryFocus}
            onAnalyzeDocument={handleDocumentAnalyzed}
            onUploadFailed={() => void reload()}
          />
        )}

        {!loading && activeNav === 'settings' && <SettingsView onSaved={() => void reload()} />}
      </main>

      <PrivacyInspectorDrawer
        isOpen={isPrivacyInspectorOpen}
        onClose={() => setIsPrivacyInspectorOpen(false)}
        sessionId={chatSessionId}
      />
      <NewAuditModal
        isOpen={isNewAuditOpen}
        onClose={() => setIsNewAuditOpen(false)}
        settings={settings}
        onAuditCreated={handleAuditCreated}
      />
      {currentModel && (
        <ModelLineageModal
          isOpen={isLineageOpen}
          onClose={() => setIsLineageOpen(false)}
          currentModel={currentModel}
          onVersionCreated={() => void reload()}
        />
      )}
      <NotificationsDrawer
        isOpen={isNotificationsOpen}
        onClose={() => setIsNotificationsOpen(false)}
        onSelectModel={(id) => void openModelById(id)}
        onUnreadCountChange={setUnreadCount}
      />
      {currentModel && (
        <ExportReportModal
          isOpen={isExportOpen}
          onClose={() => setIsExportOpen(false)}
          currentModel={currentModel}
        />
      )}
      <ProfileModal isOpen={isProfileOpen} onClose={() => setIsProfileOpen(false)} />
      <HelpModal isOpen={isHelpOpen} onClose={() => setIsHelpOpen(false)} />
    </div>
  );
}
