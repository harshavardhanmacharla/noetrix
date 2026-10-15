import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Building2,
  FolderOpen,
  FileText,
  Play,
  BarChart3,
  Settings,
  ShieldCheck,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

interface NavItem {
  label: string;
  to: string;
  icon: React.ElementType;
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', to: '/', icon: LayoutDashboard },
  { label: 'Organizations', to: '/organizations', icon: Building2 },
  { label: 'Projects', to: '/projects', icon: FolderOpen },
  { label: 'Test Cases', to: '/test-cases', icon: FileText },
  { label: 'Test Execution', to: '/execution', icon: Play },
  { label: 'Reports', to: '/reports', icon: BarChart3 },
  { label: 'Settings', to: '/settings', icon: Settings },
];

export const Sidebar: React.FC = () => {
  const { profile } = useAuth();
  const currentOrg = profile?.memberships?.[0]?.org_name;

  return (
    <aside className="fixed inset-y-0 left-0 w-64 bg-sidebar flex flex-col z-30">
      {/* Brand & Workspace Logo */}
      <div className="flex items-center gap-3 px-6 py-5 border-b border-slate-700">
        <div className="w-8 h-8 bg-primary-600 rounded-lg flex items-center justify-center shadow-sm">
          <ShieldCheck className="w-4 h-4 text-white" />
        </div>
        <div className="flex flex-col min-w-0">
          <span className="text-white font-bold text-lg tracking-tight leading-none">
            Noetrix
          </span>
          {currentOrg && (
            <span className="text-slate-400 text-xs truncate mt-1">
              {currentOrg}
            </span>
          )}
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {NAV_ITEMS.map(({ label, to, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-primary-600 text-white'
                  : 'text-slate-400 hover:text-white hover:bg-slate-700'
              }`
            }
          >
            <Icon className="w-4 h-4 shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Version badge */}
      <div className="px-6 py-4 border-t border-slate-700">
        <span className="text-xs text-slate-500 font-mono">v1.0.0 · Noetrix Platform</span>
      </div>
    </aside>
  );
};

export default Sidebar;
