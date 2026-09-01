import { useEffect, useState } from 'react';
import { X, Shield } from 'lucide-react';

import type {
  NavItem,
  ModelSummary,
  DashboardMetrics,
  RedactedEntity,
  TenantSettings,
} from '@/types';
import { listModels, getSettings, getDashboardMetrics } from '@/lib/api';
import { toModelSummary, toSettings, toDashboardMetrics } from '@/lib/adapters';
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

export default function App() {
  const { user, ready, logout } = useAuth();
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');

  const [activeNav, setActiveNav] = useState<NavItem>('overview');
  const [models, setModels] = useState<ModelSummary[]>([]);
  const [currentModel, setCurrentModel] = useState<ModelSummary | null>(null);
  const [metrics, setMetrics] = useState<DashboardMetrics>({
    activeModels: 0,
    documentsAnalyzed: 0,
    complianceIssues: 0,
    aiReviews: 0,
  });
  const [settings, setSettings] = useState<TenantSettings | undefined>(undefined);
  const [redactedEntities, setRedactedEntities] = useState<RedactedEntity[]>([]);
  const [loading, setLoading] = useState(true);

  // Modals & drawers
  const [isPrivacyInspectorOpen, setIsPrivacyInspectorOpen] = useState(false);
  const [isNewAuditOpen, setIsNewAuditOpen] = useState(false);
  const [isLineageOpen, setIsLineageOpen] = useState(false);
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false);
  const [isExportOpen, setIsExportOpen] = useState(false);
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const [isHelpOpen, setIsHelpOpen] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  useEffect(() => {
    if (!user) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const s = toSettings(await getSettings());
        const raw = (await listModels()) as unknown[];
        const adapted = raw.map((d) => toModelSummary(d, s));
        const dm = toDashboardMetrics(await getDashboardMetrics());
        if (cancelled) return;
        setSettings(s);
        setModels(adapted);
        setCurrentModel(adapted[0] ?? null);
        setMetrics(dm);
      } catch {
        // keep empty state on failure
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user]);

  const handleAuditCreated = (newModel: ModelSummary) => {
    setModels((prev) => [newModel, ...prev]);
    setCurrentModel(newModel);
    setActiveNav('workspace');
  };

  const handleSelectModelById = (modelId: string) => {
    const found = models.find((m) => m.id === modelId);
    if (found) {
      setCurrentModel(found);
      setActiveNav('workspace');
    }
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
        onSelectNav={(item) => setActiveNav(item)}
        onOpenNewAudit={() => setIsNewAuditOpen(true)}
        onOpenProfile={() => setIsProfileOpen(true)}
        onOpenHelp={() => setIsHelpOpen(true)}
        onLogout={logout}
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
                    setActiveNav(item);
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

      {currentModel && (
        <TopNav
          currentModel={currentModel}
          models={models}
          onSelectModel={(m) => setCurrentModel(m)}
          onOpenPrivacyInspector={() => setIsPrivacyInspectorOpen(true)}
          onOpenLineage={() => setIsLineageOpen(true)}
          onOpenNotifications={() => setIsNotificationsOpen(true)}
          onToggleMobileMenu={() => setIsMobileMenuOpen(true)}
        />
      )}

      <main className="md:ml-[304px] pt-28 px-6 pb-12 transition-all">
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
              currentModel={currentModel}
              onExportReport={() => setIsExportOpen(true)}
              onNavigateToCompare={() => setActiveNav('compare')}
              onOpenRegulatoryStandard={() => setActiveNav('library')}
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
            onAnalyzeDocument={() => setActiveNav('workspace')}
          />
        )}

        {!loading && activeNav === 'settings' && <SettingsView />}
      </main>

      <PrivacyInspectorDrawer
        isOpen={isPrivacyInspectorOpen}
        onClose={() => setIsPrivacyInspectorOpen(false)}
        redactedEntities={redactedEntities}
      />
      <NewAuditModal
        isOpen={isNewAuditOpen}
        onClose={() => setIsNewAuditOpen(false)}
        onAuditCreated={handleAuditCreated}
      />
      {currentModel && (
        <ModelLineageModal
          isOpen={isLineageOpen}
          onClose={() => setIsLineageOpen(false)}
          currentModel={currentModel}
        />
      )}
      <NotificationsDrawer
        isOpen={isNotificationsOpen}
        onClose={() => setIsNotificationsOpen(false)}
        onSelectModel={handleSelectModelById}
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