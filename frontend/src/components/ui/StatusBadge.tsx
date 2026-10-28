import React from 'react';
import { CheckCircle2, XCircle, Loader2, Clock, AlertTriangle, Minus, LucideIcon } from 'lucide-react';
import { TestRun, TestResult } from '../../types';

type Status = TestRun['status'] | TestResult['status'] | string;

interface StatusConfig {
  label: string;
  className: string;
  icon: LucideIcon;
  iconColor: string;
  animate?: boolean;
}

const STATUS_CONFIG: Record<string, StatusConfig> = {
  passed: {
    label: 'Passed',
    className: 'badge-passed',
    icon: CheckCircle2,
    iconColor: 'text-emerald-600',
  },
  failed: {
    label: 'Failed',
    className: 'badge-failed',
    icon: XCircle,
    iconColor: 'text-rose-600',
  },
  running: {
    label: 'Running',
    className: 'badge-running',
    icon: Loader2,
    iconColor: 'text-blue-600',
    animate: true,
  },
  pending: {
    label: 'Pending',
    className: 'badge-pending',
    icon: Clock,
    iconColor: 'text-slate-500',
  },
  error: {
    label: 'Error',
    className: 'badge-error',
    icon: AlertTriangle,
    iconColor: 'text-amber-600',
  },
  skipped: {
    label: 'Skipped',
    className: 'badge-skipped',
    icon: Minus,
    iconColor: 'text-slate-400',
  },
};

export interface StatusBadgeProps {
  status: Status;
  size?: 'sm' | 'md';
  showIcon?: boolean;
  className?: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  status,
  size = 'md',
  showIcon = true,
  className = '',
}) => {
  const normalized = (status || 'pending').toLowerCase();
  const config = STATUS_CONFIG[normalized] ?? {
    label: status,
    className: 'badge-pending',
    icon: Clock,
    iconColor: 'text-slate-500',
  };

  const Icon = config.icon;
  const sizeClasses = size === 'sm' ? 'text-[11px] px-2 py-0.5' : 'text-xs px-2.5 py-0.5';
  const iconSize = size === 'sm' ? 'w-3 h-3' : 'w-3.5 h-3.5';

  return (
    <span
      className={`${config.className} ${sizeClasses} ${className}`}
      data-status={normalized}
    >
      {showIcon && (
        <Icon
          className={`${iconSize} ${config.iconColor} ${config.animate ? 'animate-spin' : ''} shrink-0`}
          aria-hidden="true"
        />
      )}
      <span>{config.label}</span>
    </span>
  );
};

export default StatusBadge;
