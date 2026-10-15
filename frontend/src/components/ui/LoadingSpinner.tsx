import React from 'react';

interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

const SIZE_MAP = {
  sm: 'w-4 h-4 border-2',
  md: 'w-8 h-8 border-2',
  lg: 'w-12 h-12 border-4',
};

export const LoadingSpinner: React.FC<LoadingSpinnerProps> = ({
  size = 'md',
  className = '',
}) => {
  return (
    <div
      className={`${SIZE_MAP[size]} rounded-full border-slate-200 border-t-primary-600 animate-spin ${className}`}
      role="status"
      aria-label="Loading"
    />
  );
};

export const PageLoader: React.FC<{ message?: string }> = ({ message }) => (
  <div className="flex flex-col items-center justify-center h-64 gap-3">
    <LoadingSpinner size="lg" />
    {message && <p className="text-sm text-slate-500 font-medium">{message}</p>}
  </div>
);

