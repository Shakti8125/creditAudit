import type { NavItem } from '@/types';
import {
  BarChart3,
  GitCompareArrows,
  HardDrive,
  HelpCircle,
  LayoutDashboard,
  Library,
  LogOut,
  Plus,
  Settings,
  Shield,
  UserCircle2,
} from 'lucide-react';

interface SideNavProps {
  activeNav: NavItem;
  onSelectNav: (item: NavItem) => void;
  onOpenNewAudit: () => void;
  onOpenProfile: () => void;
  onOpenHelp: () => void;
  onLogout: () => void;
}

const NAV_ITEMS: { key: NavItem; label: string; icon: typeof LayoutDashboard }[] = [
  { key: 'overview', label: 'Overview', icon: LayoutDashboard },
  { key: 'workspace', label: 'Workspace', icon: BarChart3 },
  { key: 'compare', label: 'Compare Models', icon: GitCompareArrows },
  { key: 'library', label: 'Regulatory Library', icon: Library },
  { key: 'settings', label: 'Settings', icon: Settings },
];

export default function SideNav({
  activeNav,
  onSelectNav,
  onOpenNewAudit,
  onOpenProfile,
  onOpenHelp,
  onLogout,
}: SideNavProps) {
  return (
    <aside className="hidden md:flex flex-col fixed left-0 top-0 bottom-0 w-[280px] bg-white border-r border-slate-200 p-6 space-y-6 z-40">
      {/* Brand Identity */}
      <div className="flex items-center gap-2.5 px-1">
        <div className="w-9 h-9 rounded-xl bg-indigo-600 text-white flex items-center justify-center shadow-md shadow-indigo-200">
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

      {/* New Audit CTA */}
      <button
        onClick={onOpenNewAudit}
        className="w-full flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-700 active:scale-[0.98] text-white rounded-xl py-2.5 px-4 text-sm font-semibold transition-all shadow-md shadow-indigo-100 cursor-pointer"
      >
        <Plus className="w-4 h-4" />
        <span>New Audit</span>
      </button>

      {/* Primary Navigation */}
      <nav className="flex-1 space-y-1.5">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const isActive = activeNav === item.key;
          return (
            <button
              key={item.key}
              onClick={() => onSelectNav(item.key)}
              className={`w-full flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-semibold text-left transition-colors cursor-pointer ${
                isActive
                  ? 'bg-indigo-50 text-indigo-700'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              <Icon className={`w-4.5 h-4.5 shrink-0 ${isActive ? 'text-indigo-600' : 'text-slate-400'}`} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      {/* Storage Widget */}
      <div className="sleek-card p-4">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-bold uppercase tracking-widest text-slate-400 flex items-center gap-1.5">
            <HardDrive className="w-3.5 h-3.5" />
            Audit Storage
          </span>
          <span className="text-[10px] font-mono text-indigo-500 font-semibold">72%</span>
        </div>
        <div className="h-1.5 w-full bg-slate-100 rounded-full overflow-hidden mt-2.5">
          <div className="h-full w-[72%] bg-indigo-500 rounded-full" />
        </div>
        <p className="text-[11px] text-slate-400 mt-2">7.2 GB of 10 GB used</p>
      </div>

      {/* Secondary actions */}
      <div className="pt-3 border-t border-slate-100 space-y-2">
        <div className="flex items-center justify-between text-xs text-slate-500">
          <button
            onClick={onOpenProfile}
            className="flex items-center gap-1.5 hover:text-slate-900 transition-colors cursor-pointer py-1"
          >
            <UserCircle2 className="w-4 h-4" />
            <span>Profile</span>
          </button>
          <button
            onClick={onOpenHelp}
            className="flex items-center gap-1.5 hover:text-slate-900 transition-colors cursor-pointer py-1"
          >
            <HelpCircle className="w-4 h-4" />
            <span>Guidelines</span>
          </button>
        </div>
        <button
          onClick={onLogout}
          className="w-full flex items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-semibold text-slate-500 hover:bg-slate-100 hover:text-slate-900 transition-colors cursor-pointer"
        >
          <LogOut className="w-4 h-4" />
          <span>Logout</span>
        </button>
      </div>
    </aside>
  );
}