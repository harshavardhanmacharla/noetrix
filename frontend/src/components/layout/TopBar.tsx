import React from 'react';
import { Bell, LogOut, Shield } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

interface TopBarProps {
  title: string;
  subtitle?: string;
}

export const TopBar: React.FC<TopBarProps> = ({ title, subtitle }) => {
  const { user, logout } = useAuth();

  const getInitials = (): string => {
    if (!user) return 'NX';
    if (user.full_name) {
      const parts = user.full_name.trim().split(/\s+/);
      if (parts.length >= 2) {
        return (parts[0][0] + parts[1][0]).toUpperCase();
      }
      return user.full_name.substring(0, 2).toUpperCase();
    }
    return user.email.substring(0, 2).toUpperCase();
  };

  const handleLogout = async () => {
    try {
      await logout();
    } catch {
      // Auth context handles cleanup
    }
  };

  return (
    <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-6 shrink-0">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
      </div>

      <div className="flex items-center gap-4">
        {/* User Context & Info */}
        {user && (
          <div className="hidden sm:flex flex-col items-end text-right">
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-semibold text-slate-800">
                {user.full_name || user.email.split('@')[0]}
              </span>
              {user.is_superuser && (
                <span className="inline-flex items-center gap-0.5 px-1.5 py-0.2 rounded text-[10px] font-medium bg-amber-100 text-amber-800">
                  <Shield className="w-2.5 h-2.5" />
                  Admin
                </span>
              )}
            </div>
            <span className="text-[11px] text-slate-500 truncate max-w-[180px]">
              {user.email}
            </span>
          </div>
        )}

        <button
          className="relative p-2 text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors"
          title="Notifications"
          aria-label="Notifications"
        >
          <Bell className="w-4 h-4" />
          <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 bg-primary-600 rounded-full" />
        </button>

        {/* User Avatar */}
        <div
          className="w-8 h-8 bg-primary-600 rounded-full flex items-center justify-center shadow-sm"
          title={user?.email || 'User'}
        >
          <span className="text-white text-xs font-semibold select-none">
            {getInitials()}
          </span>
        </div>

        {/* Logout Button */}
        <button
          onClick={handleLogout}
          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:text-red-700 hover:bg-red-50 rounded-lg transition-colors border border-slate-200 hover:border-red-200"
          title="Log out of Noetrix"
          aria-label="Log out"
        >
          <LogOut className="w-3.5 h-3.5" />
          <span className="hidden md:inline">Log Out</span>
        </button>
      </div>
    </header>
  );
};

export default TopBar;
