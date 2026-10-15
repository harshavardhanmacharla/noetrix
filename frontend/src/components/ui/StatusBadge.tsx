import React from 'react';
import { TestRun, TestResult } from '../../types';

type Status = TestRun['status'] | TestResult['status'];

const STATUS_CONFIG: Record<Status, { label: string; className: string }> = {
  passed: { label: 'Passed', className: 'badge-passed' },
  failed: { label: 'Failed', className: 'badge-failed' },
  running: { label: 'Running', className: 'badge-running' },
  pending: { label: 'Pending', className: 'badge-pending' },
  error: { label: 'Error', className: 'badge-error' },
  skipped: { label: 'Skipped', className: 'badge-pending' },
};

interface StatusBadgeProps {
  status: Status;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status }) => {
  const config = STATUS_CONFIG[status] ?? { label: status, className: 'badge-pending' };
  return <span className={config.className}>{config.label}</span>;
};
