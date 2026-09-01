import { useEffect, useRef, useState } from 'react';
import type { ModelStatus, ModelSummary, SearchResult } from '@/types';
import * as api from '@/lib/api';
import {
  Bell,
  ChevronDown,
  Check,
  GitFork,
  Library,
  Menu,
  Search,
  ShieldCheck,
} from 'lucide-react';

interface TopNavProps {
  currentModel: ModelSummary;
  models: ModelSummary[];
  onSelectModel: (m: ModelSummary) => void;
  onOpenPrivacyInspector: () => void;
  onOpenLineage: () => void;
  onOpenNotifications: () => void;
  onToggleMobileMenu: () => void;
}

const STATUS_BADGE: Record<ModelStatus, string> = {
  PASS: 'bg-emerald-50 text-emerald-600 border-emerald-200',
  WARNING: 'bg-amber-50 text-amber-600 border-amber-200',
  BREACH: 'bg-rose-50 text-rose-600 border-rose-200',
};

const STATUS_DOT: Record<ModelStatus, string> = {
  PASS: 'bg-emerald-500',
  WARNING: 'bg-amber-500',
  BREACH: 'bg-rose-500',
};

export default function TopNav({
  currentModel,
  models,
  onSelectModel,
  onOpenPrivacyInspector,
  onOpenLineage,
  onOpenNotifications,
  onToggleMobileMenu,
}: TopNavProps) {
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);

  const modelDropdownRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      const target = event.target as Node;
      if (modelDropdownRef.current && !modelDropdownRef.current.contains(target)) {
        setModelDropdownOpen(false);
      }
      if (searchRef.current && !searchRef.current.contains(target)) {
        setSearchOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    const q = searchQuery.trim();
    if (!q) {
      setSearchResults([]);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const data = await api.globalSearch(q);
        const results = Array.isArray(data?.results)
          ? (data.results as SearchResult[])
          : [];
        setSearchResults(results);
      } catch {
        setSearchResults([]);
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  function handleModelResult(model: ModelSummary) {
    onSelectModel(model);
    setSearchOpen(false);
    setSearchQuery('');
    setSearchResults([]);
  }

  return (
    <header className="fixed top-0 left-0 md:left-[280px] right-0 h-20 bg-white border-b border-slate-200 flex items-center justify-between px-4 md:px-8 z-30">
      {/* Left: search + model selector */}
      <div className="flex items-center space-x-3 md:space-x-4 min-w-0 flex-1">
        {/* Global search */}
        <div className="relative flex-1 max-w-xs md:max-w-sm" ref={searchRef}>
          <div className="flex items-center gap-2 bg-slate-100 rounded-full px-4 py-2 text-sm focus-within:ring-2 focus-within:ring-indigo-600/30 transition-all">
            <Search className="w-4 h-4 text-slate-400 shrink-0" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setSearchOpen(true);
              }}
              onFocus={() => setSearchOpen(true)}
              placeholder="Search audits, metrics, clauses..."
              className="bg-transparent border-none outline-none text-xs w-full text-slate-800 placeholder:text-slate-400"
            />
          </div>

          {searchOpen && searchQuery.trim() && (
            <div className="absolute top-full left-0 right-0 mt-2 glass-dropdown rounded-2xl p-2 z-50">
              {searchResults.length === 0 ? (
                <p className="px-3 py-2 text-xs text-slate-400">No matches found.</p>
              ) : (
                <div className="space-y-0.5 max-h-80 overflow-y-auto">
                  {searchResults.map((result) => {
                    if (result.type === 'model') {
                      const model = models.find((m) => m.id === result.id);
                      if (!model) return null;
                      return (
                        <button
                          key={result.id}
                          onClick={() => handleModelResult(model)}
                          className="w-full flex items-center justify-between gap-2 p-2.5 rounded-xl text-left hover:bg-slate-50 transition-colors cursor-pointer"
                        >
                          <div className="min-w-0">
                            <div className="text-xs font-semibold text-slate-900 truncate">
                              {result.title}
                            </div>
                            <div className="text-[11px] text-slate-500 truncate">
                              {result.description ?? model.type}
                            </div>
                          </div>
                          <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border shrink-0 ${STATUS_BADGE[model.status]}`}>
                            {model.status}
                          </span>
                        </button>
                      );
                    }
                    return (
                      <div
                        key={result.id}
                        className="w-full flex items-center gap-2 p-2.5 rounded-xl text-left"
                      >
                        <Library className="w-4 h-4 text-slate-400 shrink-0" />
                        <div className="min-w-0">
                          <div className="text-xs font-semibold text-slate-700 truncate">
                            {result.title}
                          </div>
                          <div className="text-[11px] text-slate-400 truncate">
                            Regulatory standard
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Model selector */}
        <div className="relative shrink-0" ref={modelDropdownRef}>
          <button
            onClick={() => setModelDropdownOpen(!modelDropdownOpen)}
            className="flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-slate-100 hover:bg-slate-200 transition-colors cursor-pointer"
          >
            <span className={`w-2 h-2 rounded-full ${STATUS_DOT[currentModel.status]}`} />
            <span className="text-xs font-semibold text-slate-800 max-w-[120px] truncate">
              {currentModel.name}
            </span>
            <ChevronDown
              className={`w-3.5 h-3.5 text-slate-500 transition-transform ${modelDropdownOpen ? 'rotate-180' : ''}`}
            />
          </button>

          {modelDropdownOpen && (
            <div className="absolute top-full right-0 md:left-0 md:right-auto mt-2 w-72 glass-dropdown rounded-2xl p-2 z-50">
              <div className="px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                Switch Active Model
              </div>
              <div className="space-y-1">
                {models.map((model) => (
                  <button
                    key={model.id}
                    onClick={() => {
                      onSelectModel(model);
                      setModelDropdownOpen(false);
                    }}
                    className={`w-full flex items-center justify-between gap-2 p-2.5 rounded-xl text-left transition-colors cursor-pointer ${
                      model.id === currentModel.id
                        ? 'bg-indigo-50 text-indigo-700'
                        : 'hover:bg-slate-50 text-slate-700'
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-slate-900 truncate">
                        {model.name}
                      </div>
                      <div className="text-[11px] text-slate-500 truncate">{model.type}</div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${STATUS_BADGE[model.status]}`}>
                        {model.status}
                      </span>
                      {model.id === currentModel.id && (
                        <Check className="w-4 h-4 text-indigo-600 shrink-0" />
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Right: actions + mobile toggle */}
      <div className="flex items-center space-x-2.5 md:space-x-3 shrink-0">
        <button
          onClick={onOpenPrivacyInspector}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-indigo-50 border border-indigo-100 hover:bg-indigo-100 text-indigo-700 text-xs font-bold transition-all shadow-sm cursor-pointer"
          title="Open Zero-Trust Privacy Inspector"
        >
          <ShieldCheck className="w-4 h-4 text-indigo-600 shrink-0" />
          <span className="hidden lg:inline">Zero-Trust Protected</span>
        </button>

        <button
          onClick={onOpenLineage}
          className="w-9 h-9 rounded-full bg-slate-100 hover:bg-slate-200 flex items-center justify-center text-slate-600 hover:text-slate-900 transition-colors cursor-pointer"
          title="Model Lineage & Version History"
        >
          <GitFork className="w-4 h-4" />
        </button>

        <button
          onClick={onOpenNotifications}
          className="relative w-9 h-9 rounded-full bg-slate-100 hover:bg-slate-200 flex items-center justify-center text-slate-600 hover:text-slate-900 transition-colors cursor-pointer"
          title="Audit Notifications & Findings"
        >
          <Bell className="w-4 h-4" />
          <span className="absolute top-2 right-2 w-2 h-2 bg-rose-500 rounded-full ring-2 ring-white" />
        </button>

        <button
          onClick={onToggleMobileMenu}
          className="md:hidden p-2 rounded-xl hover:bg-slate-100 text-slate-700 cursor-pointer"
          aria-label="Toggle Navigation"
        >
          <Menu className="w-5 h-5" />
        </button>
      </div>
    </header>
  );
}