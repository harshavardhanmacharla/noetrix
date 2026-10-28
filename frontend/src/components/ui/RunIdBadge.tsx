import React, { useState } from 'react';
import { Copy, Check, ExternalLink } from 'lucide-react';
import { Link } from 'react-router-dom';

export interface RunIdBadgeProps {
  runId: string;
  linkToReport?: boolean;
  showCopy?: boolean;
  size?: 'sm' | 'md';
  className?: string;
}

export const RunIdBadge: React.FC<RunIdBadgeProps> = ({
  runId,
  linkToReport = false,
  showCopy = true,
  size = 'md',
  className = '',
}) => {
  const [copied, setCopied] = useState(false);

  if (!runId) {
    return <span className="text-slate-400 font-mono text-xs">—</span>;
  }

  // Format display as RUN-XXXXXXXX
  const shortId = runId.replace(/-/g, '').slice(0, 8).toUpperCase();
  const displayLabel = `RUN-${shortId}`;

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(runId);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };

  const isSmall = size === 'sm';
  const badgeClasses = `inline-flex items-center gap-1.5 font-mono ${
    isSmall ? 'text-[11px] px-1.5 py-0.5' : 'text-xs px-2 py-0.5'
  } bg-slate-100/90 text-slate-800 rounded border border-slate-200/80 font-semibold transition-colors group ${className}`;

  const badgeContent = (
    <>
      <span className="tracking-tight" title={`Full UUID: ${runId}`}>
        {displayLabel}
      </span>

      {showCopy && (
        <button
          type="button"
          onClick={handleCopy}
          title={copied ? 'Copied UUID!' : `Copy full UUID: ${runId}`}
          className={`p-0.5 rounded hover:bg-slate-200/70 text-slate-400 hover:text-slate-700 transition-colors focus:outline-none cursor-pointer ${
            copied ? 'text-emerald-600 hover:text-emerald-700' : ''
          }`}
          aria-label="Copy run UUID"
        >
          {copied ? (
            <Check className={`${isSmall ? 'w-2.5 h-2.5' : 'w-3 h-3'} text-emerald-600`} />
          ) : (
            <Copy className={`${isSmall ? 'w-2.5 h-2.5' : 'w-3 h-3'}`} />
          )}
        </button>
      )}

      {linkToReport && (
        <ExternalLink className={`${isSmall ? 'w-2.5 h-2.5' : 'w-3 h-3'} text-slate-400 group-hover:text-primary-600 shrink-0`} />
      )}
    </>
  );

  if (linkToReport) {
    return (
      <Link
        to={`/reports?run=${encodeURIComponent(runId)}`}
        className={`${badgeClasses} hover:bg-primary-50 hover:border-primary-300 hover:text-primary-900`}
        onClick={(e) => e.stopPropagation()}
        title={`View report for ${runId}`}
      >
        {badgeContent}
      </Link>
    );
  }

  return (
    <span className={badgeClasses} title={`Full UUID: ${runId}`}>
      {badgeContent}
    </span>
  );
};

export default RunIdBadge;

