import React from 'react';
import { LucideIcon } from 'lucide-react';

export interface StatCardProps {
  title: string;
  value: number | string;
  icon: LucideIcon;
  iconColor?: string;
  iconBg?: string;
  subtitle?: string;
  trend?: {
    value: number;
    label: string;
    positive?: boolean;
  };
  onClick?: () => void;
  className?: string;
}

export const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  icon: Icon,
  iconColor = 'text-primary-600',
  iconBg = 'bg-primary-50',
  subtitle,
  trend,
  onClick,
  className = '',
}) => {
  return (
    <div
      onClick={onClick}
      className={`card p-5 ${
        onClick ? 'cursor-pointer hover:border-slate-300 hover:shadow-sm active:bg-slate-50/50' : ''
      } transition-all ${className}`}
    >
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
          {title}
        </span>
        <div
          className={`w-9 h-9 rounded-lg ${iconBg} flex items-center justify-center shrink-0 shadow-2xs`}
        >
          <Icon className={`w-4 h-4 ${iconColor}`} />
        </div>
      </div>
      <div className="flex items-baseline justify-between gap-2">
        <div className="text-2xl font-bold text-slate-900 tracking-tight">{value}</div>
        {trend && (
          <span
            className={`text-xs font-semibold px-1.5 py-0.5 rounded ${
              trend.positive
                ? 'text-emerald-700 bg-emerald-50'
                : 'text-rose-700 bg-rose-50'
            }`}
          >
            {trend.positive ? '+' : '-'}{trend.value} {trend.label}
          </span>
        )}
      </div>
      {subtitle && (
        <div className="text-xs text-slate-400 mt-1 font-normal truncate">{subtitle}</div>
      )}
    </div>
  );
};

export default StatCard;
