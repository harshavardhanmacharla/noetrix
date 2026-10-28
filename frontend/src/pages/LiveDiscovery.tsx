import React, { useEffect, useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Compass,
  Play,
  Square,
  RefreshCw,
  Search,
  Copy,
  Check,
  AlertTriangle,
  ExternalLink,
  Layers,
  Sparkles,
  CheckCircle2,
  XCircle,
  HelpCircle,
  Eye,
  Sliders,
  Download,
  Calendar,
  Clock,
  ArrowRight,
  FolderOpen,
  ChevronDown,
  ChevronUp,
  Code2,
  Globe,
  Monitor,
  Hash,
  Terminal,
} from 'lucide-react';
import { Layout } from '../components/layout/Layout';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { EmptyState } from '../components/ui/EmptyState';
import { StatusBadge } from '../components/ui/StatusBadge';
import { RunIdBadge } from '../components/ui/RunIdBadge';
import { projectsApi } from '../api/projects';
import {
  discoveryApi,
  DiscoverySession,
  DiscoverySnapshot,
  CapturedElement,
  ValidateTargetResult,
  SearchInventoryResponse,
} from '../api/discovery';
import { Project } from '../types';

export const LiveDiscovery: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(true);

  const initialProjectFromUrl = searchParams.get('project') ?? '';
  const initialTabFromUrl = (searchParams.get('tab') as 'live' | 'saved') || 'live';
  const initialSessionFromUrl = searchParams.get('session') ?? '';

  const [selectedProjectId, setSelectedProjectId] = useState<string>(initialProjectFromUrl);
  const [activeTab, setActiveTab] = useState<'live' | 'saved'>(initialTabFromUrl);

  // Live Discovery Session State
  const [urlInput, setUrlInput] = useState<string>('');
  const [isHeadless, setIsHeadless] = useState<boolean>(false);
  const [activeSession, setActiveSession] = useState<DiscoverySession | null>(null);
  const [snapshot, setSnapshot] = useState<DiscoverySnapshot | null>(null);

  // Status & Progress States
  const [isStarting, setIsStarting] = useState(false);
  const [isCapturing, setIsCapturing] = useState(false);
  const [isClosing, setIsClosing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notification, setNotification] = useState<string | null>(null);
  const [sessionClosedNotice, setSessionClosedNotice] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  // Filters & Search for Live Snapshot
  const [searchTerm, setSearchTerm] = useState('');
  const [activeCategory, setActiveCategory] = useState<string>('all');

  // Target Validation Sandbox (Live DOM)
  const [targetQuery, setTargetQuery] = useState('');
  const [targetAction, setTargetAction] = useState('click');
  const [isValidating, setIsValidating] = useState(false);
  const [validationResult, setValidationResult] = useState<ValidateTargetResult | null>(null);

  // Navigation within Live Session
  const [navUrl, setNavUrl] = useState('');
  const [isNavigating, setIsNavigating] = useState(false);

  // Saved Inventory State
  const [savedSessions, setSavedSessions] = useState<DiscoverySession[]>([]);
  const [savedSessionsLoading, setSavedSessionsLoading] = useState(false);
  const [selectedSessionId, setSelectedSessionId] = useState<string>(initialSessionFromUrl);
  const [sessionSnapshots, setSessionSnapshots] = useState<DiscoverySnapshot[]>([]);
  const [snapshotsLoading, setSnapshotsLoading] = useState(false);
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<string>('');
  const [expandedElementId, setExpandedElementId] = useState<string | null>(null);
  const [showRawJsonElementId, setShowRawJsonElementId] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);

  // Saved Inventory Search & Resolver Sandbox
  const [savedSearchQuery, setSavedSearchQuery] = useState('');
  const [savedSearchAction, setSavedSearchAction] = useState('click');
  const [isSearchingSaved, setIsSearchingSaved] = useState(false);
  const [savedSearchResults, setSavedSearchResults] = useState<SearchInventoryResponse | null>(null);

  // Saved Inventory Filter
  const [savedSearchTerm, setSavedSearchTerm] = useState('');
  const [savedCategory, setSavedCategory] = useState<string>('all');

  // Load Projects on Mount
  useEffect(() => {
    const loadProjects = async () => {
      try {
        setProjectsLoading(true);
        const data = await projectsApi.list();
        setProjects(data);
        if (data.length > 0 && !selectedProjectId) {
          const matched = initialProjectFromUrl
            ? data.find((p) => p.id === initialProjectFromUrl)
            : data[0];
          const chosen = matched ?? data[0];
          setSelectedProjectId(chosen.id);
          if (chosen.app_url) {
            setUrlInput(chosen.app_url);
          }
        }
      } catch (err: unknown) {
        setError('Failed to load projects. Please try refreshing.');
      } finally {
        setProjectsLoading(false);
      }
    };
    loadProjects();
  }, [initialProjectFromUrl]);

  // Update default URL when project changes
  useEffect(() => {
    if (selectedProjectId) {
      const proj = projects.find((p) => p.id === selectedProjectId);
      if (proj?.app_url && !urlInput) {
        setUrlInput(proj.app_url);
      }
    }
  }, [selectedProjectId, projects]);

  // Load Saved Sessions whenever project changes
  const loadSessions = useCallback(async () => {
    try {
      setSavedSessionsLoading(true);
      const list = await discoveryApi.listSessions(selectedProjectId || undefined);
      setSavedSessions(list);

      // Check if there is an active session
      const live = list.find((s) => s.status === 'active');
      if (live) {
        setActiveSession(live);
        if (live.latest_snapshot) {
          setSnapshot(live.latest_snapshot);
        }
      }

      // If user hasn't selected a saved session, pick the most recent one or one from URL
      if (list.length > 0) {
        if (!selectedSessionId || !list.some((s) => s.id === selectedSessionId)) {
          setSelectedSessionId(list[0].id);
        }
      }
    } catch {
      // Ignore initial load error
    } finally {
      setSavedSessionsLoading(false);
    }
  }, [selectedProjectId, selectedSessionId]);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  // Load Snapshots for Selected Saved Session
  useEffect(() => {
    if (!selectedSessionId) {
      setSessionSnapshots([]);
      setSelectedSnapshotId('');
      return;
    }

    const loadSnapshots = async () => {
      try {
        setSnapshotsLoading(true);
        const snaps = await discoveryApi.listSnapshots(selectedSessionId, 'asc');
        setSessionSnapshots(snaps);
        if (snaps.length > 0) {
          // Default to the first or last snapshot
          if (!selectedSnapshotId || !snaps.some((s) => s.id === selectedSnapshotId)) {
            setSelectedSnapshotId(snaps[snaps.length - 1].id);
          }
        } else {
          setSelectedSnapshotId('');
        }
      } catch {
        setError('Failed to load snapshots for this session.');
      } finally {
        setSnapshotsLoading(false);
      }
    };

    loadSnapshots();
  }, [selectedSessionId]);

  // Notification helper
  const showNotification = (msg: string) => {
    setNotification(msg);
    setTimeout(() => setNotification(null), 3500);
  };

  // Copy helper with localized feedback
  const copyToClipboard = (text: string, label: string, key?: string) => {
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(text);
    }
    if (key) {
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 1500);
    }
    showNotification(`Copied ${label} to clipboard!`);
  };

  // Start Live Discovery Session
  const handleStartSession = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedProjectId) {
      setError('Please select a project first.');
      return;
    }
    if (!urlInput.trim()) {
      setError('Please enter a target application URL.');
      return;
    }

    try {
      setError(null);
      setSessionClosedNotice(null);
      setIsStarting(true);
      const session = await discoveryApi.startSession({
        project_id: selectedProjectId,
        url: urlInput.trim(),
        headless: isHeadless,
      });
      setActiveSession(session);
      setSelectedSessionId(session.id);
      showNotification('Browser launched! Interactively navigate to your target page.');

      // Automatically capture initial inventory
      try {
        setIsCapturing(true);
        const snap = await discoveryApi.captureInventory(session.id);
        setSnapshot(snap);
      } catch {
        // May still be rendering initial page
      } finally {
        setIsCapturing(false);
      }
      await loadSessions();
    } catch (err: unknown) {
      const errMsg =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : String(err);
      setError(errMsg || 'Failed to start Live Discovery browser session.');
    } finally {
      setIsStarting(false);
    }
  };

  // Capture / Refresh Page Inventory
  const handleCaptureInventory = async () => {
    if (!activeSession) return;
    try {
      setError(null);
      setIsCapturing(true);
      const snap = await discoveryApi.captureInventory(activeSession.id);
      setSnapshot(snap);
      showNotification(`Captured ${snap.elements_count} elements from current page!`);
      await loadSessions();
      // Also update session snapshots list
      if (selectedSessionId === activeSession.id) {
        const snaps = await discoveryApi.listSnapshots(activeSession.id, 'asc');
        setSessionSnapshots(snaps);
        setSelectedSnapshotId(snap.id);
      }
    } catch (err: unknown) {
      const errMsg =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : String(err);
      setError(errMsg || 'Failed to capture live page inventory.');
    } finally {
      setIsCapturing(false);
    }
  };

  // End Discovery Session
  const handleCloseSession = async () => {
    if (!activeSession) return;
    const closedId = activeSession.id;
    try {
      setIsClosing(true);
      const res = await discoveryApi.closeSession(closedId);
      setActiveSession(null);
      const countSaved = res.snapshots_saved ?? 0;
      setSessionClosedNotice(
        `Session ended and browser closed. All ${countSaved} captured snapshots and elements are permanently saved.`
      );
      showNotification('Discovery browser closed and inventory saved.');
      await loadSessions();
      setSelectedSessionId(closedId);
    } catch (err: unknown) {
      setError('Failed to end discovery session.');
    } finally {
      setIsClosing(false);
    }
  };

  // Navigate within active session
  const handleNavigate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeSession || !navUrl.trim()) return;
    try {
      setError(null);
      setIsNavigating(true);
      const updated = await discoveryApi.navigate(activeSession.id, navUrl.trim());
      setActiveSession(updated);
      setNavUrl('');
      // Refresh inventory after navigation
      const snap = await discoveryApi.captureInventory(activeSession.id);
      setSnapshot(snap);
      showNotification(`Navigated to: ${updated.current_url}`);
      await loadSessions();
    } catch (err: unknown) {
      const errMsg =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : String(err);
      setError(errMsg || 'Failed to navigate.');
    } finally {
      setIsNavigating(false);
    }
  };

  // Test target against live DOM
  const handleValidateTarget = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeSession || !targetQuery.trim()) return;
    try {
      setIsValidating(true);
      setValidationResult(null);
      const res = await discoveryApi.validateTarget(activeSession.id, {
        target: targetQuery.trim(),
        action: targetAction,
      });
      setValidationResult(res);
    } catch (err: unknown) {
      const errMsg =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : String(err);
      setError(errMsg || 'Target validation failed.');
    } finally {
      setIsValidating(false);
    }
  };

  // Search Saved Inventory
  const handleSearchSavedInventory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedSessionId || !savedSearchQuery.trim()) return;
    try {
      setIsSearchingSaved(true);
      setSavedSearchResults(null);
      const res = await discoveryApi.searchInventory(selectedSessionId, {
        query: savedSearchQuery.trim(),
        action: savedSearchAction,
        snapshot_id: selectedSnapshotId || undefined,
      });
      setSavedSearchResults(res);
    } catch (err: unknown) {
      const errMsg =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : String(err);
      setError(errMsg || 'Failed to search saved inventory.');
    } finally {
      setIsSearchingSaved(false);
    }
  };

  // Export Complete Session Inventory as JSON
  const handleExportJson = async (sessionIdToExport?: string) => {
    const sessId = sessionIdToExport || selectedSessionId;
    if (!sessId) return;
    try {
      setIsExporting(true);
      const exportData = await discoveryApi.exportSessionJson(sessId);
      const jsonStr = JSON.stringify(exportData, null, 2);
      const blob = new Blob([jsonStr], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `discovery_inventory_${sessId}.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      showNotification(`Exported complete inventory as discovery_inventory_${sessId.slice(0, 8)}.json`);
    } catch (err: unknown) {
      setError('Failed to export session inventory.');
    } finally {
      setIsExporting(false);
    }
  };

  // Filter elements for Live Active Snapshot
  const allElements: CapturedElement[] = snapshot?.inventory_data?.elements || [];
  const filteredElements = allElements.filter((el) => {
    if (activeCategory === 'input') {
      const isInput =
        (['input', 'textarea'].includes(el.tag) ||
          el.role === 'textbox' ||
          el.role === 'searchbox') &&
        el.type !== 'checkbox' &&
        el.role !== 'checkbox';
      if (!isInput) return false;
    } else if (activeCategory === 'button') {
      if (el.tag !== 'button' && el.role !== 'button') return false;
    } else if (activeCategory === 'link') {
      if (el.tag !== 'a' && el.role !== 'link') return false;
    } else if (activeCategory === 'dropdown') {
      if (el.tag !== 'select' && el.role !== 'combobox') return false;
    } else if (activeCategory === 'checkbox') {
      if (el.role !== 'checkbox' && el.type !== 'checkbox') return false;
    } else if (activeCategory === 'image') {
      if (el.tag !== 'img' && el.tag !== 'svg') return false;
    }

    if (!searchTerm.trim()) return true;
    const q = searchTerm.toLowerCase();
    return (
      (el.accessible_name && el.accessible_name.toLowerCase().includes(q)) ||
      (el.label && el.label.toLowerCase().includes(q)) ||
      (el.placeholder && el.placeholder.toLowerCase().includes(q)) ||
      (el.suggested_intent && el.suggested_intent.toLowerCase().includes(q)) ||
      (el.element_id && el.element_id.toLowerCase().includes(q)) ||
      (el.data_testid && el.data_testid.toLowerCase().includes(q)) ||
      (el.visible_text && el.visible_text.toLowerCase().includes(q))
    );
  });

  // Selected Saved Session & Snapshot
  const currentSavedSession = savedSessions.find((s) => s.id === selectedSessionId);
  const currentSavedSnapshot = sessionSnapshots.find((s) => s.id === selectedSnapshotId);
  const savedSnapshotElements: CapturedElement[] = currentSavedSnapshot?.inventory_data?.elements || [];

  const filteredSavedElements = savedSnapshotElements.filter((el) => {
    if (savedCategory === 'input') {
      const isInput =
        (['input', 'textarea'].includes(el.tag) ||
          el.role === 'textbox' ||
          el.role === 'searchbox') &&
        el.type !== 'checkbox' &&
        el.role !== 'checkbox';
      if (!isInput) return false;
    } else if (savedCategory === 'button') {
      if (el.tag !== 'button' && el.role !== 'button') return false;
    } else if (savedCategory === 'link') {
      if (el.tag !== 'a' && el.role !== 'link') return false;
    } else if (savedCategory === 'dropdown') {
      if (el.tag !== 'select' && el.role !== 'combobox') return false;
    } else if (savedCategory === 'checkbox') {
      if (el.role !== 'checkbox' && el.type !== 'checkbox') return false;
    } else if (savedCategory === 'image') {
      if (el.tag !== 'img' && el.tag !== 'svg') return false;
    }

    if (!savedSearchTerm.trim()) return true;
    const q = savedSearchTerm.toLowerCase();
    return (
      (el.accessible_name && el.accessible_name.toLowerCase().includes(q)) ||
      (el.label && el.label.toLowerCase().includes(q)) ||
      (el.placeholder && el.placeholder.toLowerCase().includes(q)) ||
      (el.suggested_intent && el.suggested_intent.toLowerCase().includes(q)) ||
      (el.element_id && el.element_id.toLowerCase().includes(q)) ||
      (el.data_testid && el.data_testid.toLowerCase().includes(q)) ||
      (el.name && el.name.toLowerCase().includes(q)) ||
      (el.role && el.role.toLowerCase().includes(q)) ||
      (el.tag && el.tag.toLowerCase().includes(q)) ||
      (el.visible_text && el.visible_text.toLowerCase().includes(q))
    );
  });

  const isSessionActive = activeSession !== null && activeSession.status === 'active';

  return (
    <Layout
      title="Live Browser Discovery & Saved Inventory"
      subtitle="Interactively explore applications, capture live UI elements, and access persistent saved inventory"
    >
      <div className="max-w-7xl mx-auto space-y-5">
        {/* Top Header Card with Integrated Project Selection */}
        <div className="card p-5">
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-xl bg-primary-50 text-primary-600 flex items-center justify-center shrink-0 shadow-2xs">
                <Compass className="w-5 h-5" />
              </div>
              <div>
                <div className="flex items-center gap-2.5">
                  <h1 className="text-lg font-bold text-slate-900 tracking-tight">
                    Live Browser Discovery & Saved Inventory
                  </h1>
                  {isSessionActive && (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                      <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                      Live Browser Running
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-500 mt-0.5">
                  Explore applications interactively, scan live element DOM trees, and build reusable test inventories.
                </p>
              </div>
            </div>

            {/* Project Selection Pill */}
            <div className="flex items-center gap-2.5 bg-slate-50 p-1.5 rounded-xl border border-slate-200/80 self-start md:self-auto">
              <span className="text-xs font-semibold text-slate-500 pl-2 flex items-center gap-1.5">
                <FolderOpen className="w-3.5 h-3.5 text-slate-400" />
                Project:
              </span>
              <select
                id="project-select"
                value={selectedProjectId}
                onChange={(e) => {
                  setSelectedProjectId(e.target.value);
                  setSearchParams({ project: e.target.value, tab: activeTab });
                }}
                disabled={isStarting || isSessionActive}
                className="bg-white border border-slate-200 rounded-lg px-3 py-1.5 text-xs font-medium text-slate-800 shadow-2xs focus:outline-none focus:ring-2 focus:ring-primary-500/20 disabled:opacity-50 cursor-pointer"
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {/* Global Notifications & Error Alerts */}
        {notification && (
          <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 px-4 py-2.5 rounded-xl text-xs font-medium flex items-center justify-between shadow-2xs">
            <span className="flex items-center gap-2">
              <Check className="w-4 h-4 text-emerald-600 shrink-0" />
              {notification}
            </span>
            <button
              type="button"
              onClick={() => setNotification(null)}
              className="text-emerald-700 hover:text-emerald-900 text-xs cursor-pointer ml-3"
            >
              Dismiss
            </button>
          </div>
        )}
        {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

        {/* Post-Session Closed Confirmation Banner */}
        {sessionClosedNotice && (
          <div className="bg-blue-50/90 border border-blue-200 text-blue-900 p-4 rounded-xl shadow-2xs flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <CheckCircle2 className="w-5 h-5 text-blue-600 shrink-0" />
              <span className="text-xs font-medium">{sessionClosedNotice}</span>
            </div>
            <button
              onClick={() => {
                setActiveTab('saved');
                setSessionClosedNotice(null);
                setSearchParams({ project: selectedProjectId, tab: 'saved' });
              }}
              className="btn-primary btn-sm shrink-0"
            >
              <Layers className="w-3.5 h-3.5" />
              View Saved Inventory
            </button>
          </div>
        )}

        {/* Feature Navigation Tabs */}
        <div className="flex border-b border-slate-200 bg-white px-2 rounded-xl shadow-2xs">
          <button
            onClick={() => {
              setActiveTab('live');
              setSearchParams({ project: selectedProjectId, tab: 'live' });
            }}
            className={`px-4 py-3 text-xs sm:text-sm font-semibold border-b-2 flex items-center gap-2 transition-colors cursor-pointer ${
              activeTab === 'live'
                ? 'border-primary-600 text-primary-600'
                : 'border-transparent text-slate-500 hover:text-slate-800'
            }`}
          >
            <Compass className="w-4 h-4" />
            Live Exploration
            {isSessionActive && (
              <span className="flex h-2 w-2 relative ml-0.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
              </span>
            )}
          </button>

          <button
            onClick={() => {
              setActiveTab('saved');
              setSearchParams({ project: selectedProjectId, tab: 'saved' });
            }}
            className={`px-4 py-3 text-xs sm:text-sm font-semibold border-b-2 flex items-center gap-2 transition-colors cursor-pointer ${
              activeTab === 'saved'
                ? 'border-primary-600 text-primary-600'
                : 'border-transparent text-slate-500 hover:text-slate-800'
            }`}
          >
            <Layers className="w-4 h-4" />
            Saved Discovery Inventory
            {savedSessions.length > 0 && (
              <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full font-semibold ml-1">
                {savedSessions.length}
              </span>
            )}
          </button>
        </div>

        {/* ================================================================= */}
        {/* TAB 1: LIVE EXPLORATION                                           */}
        {/* ================================================================= */}
        {activeTab === 'live' && (
          <div className="space-y-5">
            {/* Live Session Launcher (When no session is active) */}
            {!activeSession && (
              <div className="card p-6 space-y-5">
                <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                  <div className="flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-primary-600" />
                    <h2 className="text-sm font-bold text-slate-900 tracking-tight">
                      Launch Interactive Discovery Session
                    </h2>
                  </div>
                  <span className="text-xs bg-slate-100 text-slate-600 px-2.5 py-0.5 rounded-full font-medium">
                    Ready to explore
                  </span>
                </div>

                <form onSubmit={handleStartSession} className="space-y-4">
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5">
                      Target Application URL
                    </label>
                    <div className="flex flex-col sm:flex-row gap-2.5">
                      <div className="relative flex-1">
                        <Globe className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                        <input
                          type="url"
                          value={urlInput}
                          onChange={(e) => setUrlInput(e.target.value)}
                          placeholder="https://fa-erzp-dev26-saasfademo1.ds-fa.oraclepdemos.com/"
                          required
                          className="input pl-9 pr-3 py-2 text-xs font-mono"
                        />
                      </div>
                      <button
                        type="submit"
                        disabled={isStarting}
                        className="btn-primary py-2 px-5 whitespace-nowrap cursor-pointer"
                      >
                        {isStarting ? (
                          <>
                            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                            Launching Chromium…
                          </>
                        ) : (
                          <>
                            <Play className="w-3.5 h-3.5 fill-current" />
                            Start Live Discovery
                          </>
                        )}
                      </button>
                    </div>
                    <p className="text-xs text-slate-400 mt-1.5">
                      Spawns a real browser session so you can log in, navigate pages, and capture full element inventories.
                    </p>
                  </div>

                  {/* Mode Options */}
                  <div className="pt-1">
                    <label className="inline-flex items-center gap-2.5 text-xs text-slate-700 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={!isHeadless}
                        onChange={(e) => setIsHeadless(!e.target.checked)}
                        className="w-4 h-4 rounded text-primary-600 focus:ring-primary-500 border-slate-300 cursor-pointer"
                      />
                      <span className="font-semibold text-slate-800">Visible Desktop Browser (Headless: False)</span>
                      <span className="text-slate-400">— Recommended for interactive login & Oracle Fusion workflows</span>
                    </label>
                  </div>
                </form>

                {/* 3-Step Guided Workflow */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5 pt-3 border-t border-slate-100">
                  <div className="bg-slate-50/70 p-3.5 rounded-xl border border-slate-200/60">
                    <div className="w-6 h-6 bg-primary-100 text-primary-700 rounded-full flex items-center justify-center font-bold text-xs mb-2 shadow-2xs">
                      1
                    </div>
                    <h4 className="text-xs font-bold text-slate-800">Launch & Authenticate</h4>
                    <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">
                      Click Start to open a visible browser. Enter your credentials and navigate to the application view.
                    </p>
                  </div>

                  <div className="bg-slate-50/70 p-3.5 rounded-xl border border-slate-200/60">
                    <div className="w-6 h-6 bg-indigo-100 text-indigo-700 rounded-full flex items-center justify-center font-bold text-xs mb-2 shadow-2xs">
                      2
                    </div>
                    <h4 className="text-xs font-bold text-slate-800">Capture Live Inventory</h4>
                    <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">
                      Click "Capture / Refresh Inventory" to scan buttons, fields, dropdowns, and accessible names.
                    </p>
                  </div>

                  <div className="bg-slate-50/70 p-3.5 rounded-xl border border-slate-200/60">
                    <div className="w-6 h-6 bg-emerald-100 text-emerald-700 rounded-full flex items-center justify-center font-bold text-xs mb-2 shadow-2xs">
                      3
                    </div>
                    <h4 className="text-xs font-bold text-slate-800">End & Persist</h4>
                    <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">
                      End session when done. All snapshots remain permanently saved under the "Saved Discovery Inventory" tab!
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Active Live Discovery Session Controls & Inspector */}
            {activeSession && (
              <div className="space-y-5">
                {/* Active Session Status Bar */}
                <div className="card p-5 border-emerald-200/80 bg-gradient-to-r from-emerald-50/30 via-white to-white">
                  <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
                    <div className="flex items-start gap-3">
                      <div className="relative mt-1">
                        <span className="flex h-3 w-3">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                          <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500" />
                        </span>
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <h2 className="text-sm font-bold text-slate-900 tracking-tight">
                            Active Browser Session
                          </h2>
                          <RunIdBadge runId={activeSession.id} size="sm" showCopy={true} />
                        </div>
                        <div className="flex flex-wrap items-center gap-2.5 text-xs text-slate-500 mt-1">
                          <span className="flex items-center gap-1 font-semibold text-slate-800">
                            <ExternalLink className="w-3.5 h-3.5 text-slate-400" />
                            {snapshot?.page_title || activeSession.current_title || 'Application Window'}
                          </span>
                          <span className="text-slate-300">•</span>
                          <span className="truncate max-w-md font-mono text-slate-600">
                            {snapshot?.page_url || activeSession.current_url || activeSession.app_url}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Session Action Controls with Distinct Hierarchy */}
                    <div className="flex flex-wrap items-center gap-2.5 self-start lg:self-center">
                      <button
                        type="button"
                        onClick={handleCaptureInventory}
                        disabled={isCapturing}
                        className="btn-primary btn-sm cursor-pointer shadow-xs"
                      >
                        {isCapturing ? (
                          <>
                            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                            Scanning DOM…
                          </>
                        ) : (
                          <>
                            <RefreshCw className="w-3.5 h-3.5" />
                            Capture / Refresh Inventory
                          </>
                        )}
                      </button>

                      <button
                        type="button"
                        onClick={handleCloseSession}
                        disabled={isClosing}
                        className="btn-danger btn-sm cursor-pointer"
                        title="Close the browser and save all snapshots permanently"
                      >
                        <Square className="w-3 h-3 fill-current" />
                        {isClosing ? 'Closing Browser…' : 'End Session'}
                      </button>
                    </div>
                  </div>

                  {/* Browser Omnibar Navigation */}
                  <form onSubmit={handleNavigate} className="flex gap-2 mt-4 pt-3.5 border-t border-slate-100">
                    <div className="relative flex-1">
                      <Globe className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                      <input
                        type="text"
                        value={navUrl}
                        onChange={(e) => setNavUrl(e.target.value)}
                        placeholder="Navigate active browser to URL or path (e.g. /ords/r/task1/home)..."
                        className="input pl-8 py-1.5 text-xs font-mono rounded-lg"
                      />
                    </div>
                    <button
                      type="submit"
                      disabled={isNavigating || !navUrl.trim()}
                      className="btn-secondary btn-sm cursor-pointer"
                    >
                      {isNavigating ? 'Navigating…' : 'Go'}
                    </button>
                  </form>
                </div>

                {/* Target Validation Sandbox */}
                <div className="card p-5 space-y-4">
                  <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                    <div className="flex items-center gap-2">
                      <Sliders className="w-4 h-4 text-indigo-600" />
                      <h3 className="text-sm font-bold text-slate-900 tracking-tight">
                        Live Target Resolver Sandbox
                      </h3>
                    </div>
                    <span className="text-xs text-slate-400">
                      Test natural-language target phrases against the active browser DOM in real time
                    </span>
                  </div>

                  <form onSubmit={handleValidateTarget} className="flex flex-col sm:flex-row gap-2">
                    <select
                      value={targetAction}
                      onChange={(e) => setTargetAction(e.target.value)}
                      className="px-2.5 py-1.5 bg-slate-50 border border-slate-200 rounded-lg text-xs font-medium text-slate-800 focus:outline-none focus:ring-1 focus:ring-primary-500 cursor-pointer"
                    >
                      <option value="click">click</option>
                      <option value="fill">fill</option>
                      <option value="select_option">select_option</option>
                      <option value="clear">clear</option>
                      <option value="check">check</option>
                      <option value="uncheck">uncheck</option>
                      <option value="verify_text">verify_text</option>
                    </select>

                    <input
                      type="text"
                      value={targetQuery}
                      onChange={(e) => setTargetQuery(e.target.value)}
                      placeholder="Enter target phrase (e.g. username field, Next button, eAppSys logo, Hire an Employee link)..."
                      required
                      className="input flex-1 py-1.5 text-xs"
                    />

                    <button
                      type="submit"
                      disabled={isValidating || !targetQuery.trim()}
                      className="btn-primary btn-sm whitespace-nowrap cursor-pointer"
                    >
                      {isValidating ? (
                        <>
                          <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                          Testing…
                        </>
                      ) : (
                        <>
                          <Search className="w-3.5 h-3.5" />
                          Test on Live DOM
                        </>
                      )}
                    </button>
                  </form>

                  {/* Validation Result Box */}
                  {validationResult && (
                    <div
                      className={`p-3.5 rounded-xl border text-xs space-y-2 shadow-2xs ${
                        validationResult.status === 'resolved_unique'
                          ? 'bg-emerald-50/80 border-emerald-200 text-emerald-950'
                          : validationResult.status === 'ambiguous'
                          ? 'bg-amber-50/80 border-amber-200 text-amber-950'
                          : 'bg-rose-50/80 border-rose-200 text-rose-950'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 font-bold text-xs">
                          {validationResult.status === 'resolved_unique' ? (
                            <>
                              <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                              <span>Resolved Uniquely (1 Match)</span>
                            </>
                          ) : validationResult.status === 'ambiguous' ? (
                            <>
                              <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
                              <span>Ambiguous Target (Matches {validationResult.matched_count} elements)</span>
                            </>
                          ) : (
                            <>
                              <XCircle className="w-4 h-4 text-rose-600 shrink-0" />
                              <span>Element Not Found</span>
                            </>
                          )}
                        </div>

                        {validationResult.status === 'resolved_unique' && (
                          <button
                            type="button"
                            onClick={() =>
                              copyToClipboard(
                                `TC001,Test,1,${targetAction},${targetQuery},,`,
                                'CSV step row',
                                'live-val-row'
                              )
                            }
                            className="btn-xs bg-emerald-600 hover:bg-emerald-700 text-white font-medium rounded shadow-2xs flex items-center gap-1 cursor-pointer"
                          >
                            {copiedKey === 'live-val-row' ? (
                              <Check className="w-3 h-3" />
                            ) : (
                              <Copy className="w-3 h-3" />
                            )}
                            {copiedKey === 'live-val-row' ? 'Copied!' : 'Copy CSV Row'}
                          </button>
                        )}
                      </div>

                      <p className="text-xs leading-relaxed">{validationResult.message}</p>

                      {validationResult.recommended_locator && (
                        <div className="flex items-center gap-2 pt-1 font-mono text-xs">
                          <span className="text-slate-500 font-sans font-medium">Recommended Locator:</span>
                          <code className="bg-white/80 px-2 py-0.5 rounded border border-slate-200/80 font-bold text-slate-800">
                            {validationResult.recommended_locator}
                          </code>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Active Snapshot Element Inventory Table */}
                <div className="card overflow-hidden">
                  <div className="p-4 sm:p-5 border-b border-slate-100 space-y-3.5">
                    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                      <div className="flex items-center gap-2">
                        <Layers className="w-4 h-4 text-primary-600" />
                        <h3 className="text-sm font-bold text-slate-900 tracking-tight">
                          Captured Element Inventory
                        </h3>
                        <span className="text-xs bg-primary-50 text-primary-700 font-semibold px-2 py-0.5 rounded-full border border-primary-200/60">
                          {filteredElements.length} of {allElements.length} elements
                        </span>
                      </div>

                      {/* Search Bar */}
                      <div className="relative w-full sm:w-72">
                        <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                        <input
                          type="text"
                          value={searchTerm}
                          onChange={(e) => setSearchTerm(e.target.value)}
                          placeholder="Filter by name, label, tag…"
                          className="input pl-8 py-1.5 text-xs rounded-lg"
                        />
                      </div>
                    </div>

                    {/* Category Filter Pills */}
                    <div className="flex flex-wrap gap-1.5">
                      {[
                        { id: 'all', label: 'All Elements' },
                        { id: 'input', label: 'Inputs & Textboxes' },
                        { id: 'button', label: 'Buttons' },
                        { id: 'link', label: 'Links' },
                        { id: 'dropdown', label: 'Dropdowns' },
                        { id: 'checkbox', label: 'Checkboxes' },
                        { id: 'image', label: 'Logos & Icons' },
                      ].map((cat) => (
                        <button
                          key={cat.id}
                          onClick={() => setActiveCategory(cat.id)}
                          className={`text-xs px-2.5 py-1 rounded-lg font-medium transition-colors cursor-pointer ${
                            activeCategory === cat.id
                              ? 'bg-primary-600 text-white shadow-2xs font-semibold'
                              : 'bg-slate-100 text-slate-600 hover:bg-slate-200/80 hover:text-slate-800'
                          }`}
                        >
                          {cat.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Elements List */}
                  {filteredElements.length === 0 ? (
                    <div className="p-10 text-center text-slate-400 text-xs">
                      {allElements.length === 0 ? (
                        <div className="space-y-2">
                          <p>No elements captured yet.</p>
                          <button
                            onClick={handleCaptureInventory}
                            className="btn-primary btn-xs cursor-pointer inline-flex items-center gap-1"
                          >
                            <RefreshCw className="w-3 h-3" />
                            Capture Page Inventory
                          </button>
                        </div>
                      ) : (
                        <p>No elements match your current search or category filter.</p>
                      )}
                    </div>
                  ) : (
                    <div className="divide-y divide-slate-100 max-h-[600px] overflow-y-auto">
                      {filteredElements.map((el) => {
                        const intent = el.suggested_intent || el.accessible_name || el.label || el.placeholder;
                        const actionName =
                          ['input', 'textarea'].includes(el.tag) || el.role === 'textbox'
                            ? 'fill'
                            : el.tag === 'select' || el.role === 'combobox'
                            ? 'select_option'
                            : el.role === 'checkbox' || el.type === 'checkbox'
                            ? 'check'
                            : 'click';

                        const copyIntentKey = `live-${el.id}-intent`;
                        const copyCsvKey = `live-${el.id}-csv`;
                        const copyLocKey = `live-${el.id}-loc`;

                        return (
                          <div
                            key={el.id}
                            className="p-3.5 hover:bg-slate-50/80 transition-colors flex flex-col md:flex-row md:items-center md:justify-between gap-3 text-xs"
                          >
                            <div className="space-y-1 min-w-0">
                              <div className="flex flex-wrap items-center gap-1.5">
                                <span className="font-mono text-[11px] bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded font-semibold uppercase">
                                  {el.tag}
                                  {el.type ? `:${el.type}` : ''}
                                </span>
                                {el.role && (
                                  <span className="text-[11px] bg-indigo-50 text-indigo-700 px-1.5 py-0.5 rounded font-medium">
                                    role={el.role}
                                  </span>
                                )}
                                {el.is_unique ? (
                                  <span className="text-[11px] bg-emerald-50 text-emerald-700 font-semibold px-1.5 py-0.5 rounded flex items-center gap-1 border border-emerald-200/60">
                                    <Check className="w-3 h-3 text-emerald-600" />
                                    Unique
                                  </span>
                                ) : (
                                  <span className="text-[11px] bg-amber-50 text-amber-700 font-medium px-1.5 py-0.5 rounded flex items-center gap-1 border border-amber-200/60">
                                    <AlertTriangle className="w-3 h-3 text-amber-600" />
                                    Multi-Match
                                  </span>
                                )}
                                {el.frame_context && (
                                  <span className="text-[11px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded">
                                    frame: {el.frame_context}
                                  </span>
                                )}
                              </div>

                              <div className="font-bold text-slate-900 text-xs truncate">
                                {el.accessible_name || el.label || el.placeholder || el.element_id || 'Unnamed element'}
                              </div>

                              {/* Attributes */}
                              <div className="flex flex-wrap gap-2 text-[11px] text-slate-500 font-mono">
                                {el.element_id && <span>id: #{el.element_id}</span>}
                                {el.data_testid && <span>testid: {el.data_testid}</span>}
                                {el.name && <span>name: {el.name}</span>}
                                {el.placeholder && <span>placeholder: "{el.placeholder}"</span>}
                              </div>

                              {/* Suggested Intent */}
                              {intent && (
                                <div className="flex items-center gap-1.5 pt-0.5 text-xs">
                                  <span className="text-slate-400 font-medium">Suggested Intent:</span>
                                  <span className="bg-primary-50 text-primary-800 font-semibold px-2 py-0.5 rounded font-mono text-[11px] border border-primary-200/60">
                                    {intent}
                                  </span>
                                </div>
                              )}
                            </div>

                            {/* Buttons with micro-feedback */}
                            <div className="flex items-center gap-1.5 shrink-0">
                              {intent && (
                                <button
                                  type="button"
                                  onClick={() => copyToClipboard(intent, 'Intent description', copyIntentKey)}
                                  title="Copy intent phrase for CSV target column"
                                  className="btn-ghost btn-xs cursor-pointer border border-slate-200 hover:bg-slate-100"
                                >
                                  {copiedKey === copyIntentKey ? (
                                    <Check className="w-3 h-3 text-emerald-600" />
                                  ) : (
                                    <Copy className="w-3 h-3" />
                                  )}
                                  {copiedKey === copyIntentKey ? 'Copied' : 'Intent'}
                                </button>
                              )}

                              {intent && (
                                <button
                                  type="button"
                                  onClick={() => {
                                    const sampleVal = actionName === 'fill' ? '{{VALUE}}' : '';
                                    copyToClipboard(
                                      `TC001,Test,1,${actionName},${intent},${sampleVal},`,
                                      'CSV row',
                                      copyCsvKey
                                    );
                                  }}
                                  title="Copy ready-to-paste CSV row"
                                  className="btn-primary btn-xs cursor-pointer"
                                >
                                  {copiedKey === copyCsvKey ? (
                                    <Check className="w-3 h-3" />
                                  ) : (
                                    <Sparkles className="w-3 h-3" />
                                  )}
                                  {copiedKey === copyCsvKey ? 'Copied!' : 'CSV Row'}
                                </button>
                              )}

                              {el.candidate_locators && el.candidate_locators.length > 0 && (
                                <button
                                  type="button"
                                  onClick={() =>
                                    copyToClipboard(el.candidate_locators[0], 'Technical locator', copyLocKey)
                                  }
                                  title="Copy technical Playwright selector"
                                  className="btn-secondary btn-xs font-mono cursor-pointer"
                                >
                                  {copiedKey === copyLocKey ? (
                                    <Check className="w-3 h-3 text-emerald-600" />
                                  ) : (
                                    <Code2 className="w-3 h-3" />
                                  )}
                                  {copiedKey === copyLocKey ? 'Copied' : '</>'}
                                </button>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ================================================================= */}
        {/* TAB 2: SAVED DISCOVERY INVENTORY                                  */}
        {/* ================================================================= */}
        {activeTab === 'saved' && (
          <div className="space-y-5">
            {/* Session Selector & Actions Bar */}
            <div className="card p-5 space-y-4">
              <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-primary-50 text-primary-700 flex items-center justify-center shrink-0 shadow-2xs">
                    <FolderOpen className="w-5 h-5" />
                  </div>
                  <div>
                    <h2 className="text-base font-bold text-slate-900 tracking-tight">
                      Saved Discovery Inventory
                    </h2>
                    <p className="text-xs text-slate-500 mt-0.5">
                      Access captured snapshots, inspect full element records, or export JSON without reopening the browser.
                    </p>
                  </div>
                </div>

                {/* Session Selector Dropdown & Export Button */}
                <div className="flex flex-wrap items-center gap-2.5">
                  <select
                    value={selectedSessionId}
                    onChange={(e) => {
                      setSelectedSessionId(e.target.value);
                      setSearchParams({ project: selectedProjectId, tab: 'saved', session: e.target.value });
                    }}
                    className="select py-2 text-xs min-w-[280px] shadow-2xs"
                  >
                    {savedSessions.length === 0 ? (
                      <option value="">No discovery sessions found</option>
                    ) : (
                      savedSessions.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.current_title || s.app_url} ({s.snapshots_count} snap{s.snapshots_count !== 1 ? 's' : ''}) — {new Date(s.created_at).toLocaleDateString()} [{s.status}]
                        </option>
                      ))
                    )}
                  </select>

                  <button
                    type="button"
                    onClick={() => handleExportJson()}
                    disabled={!selectedSessionId || isExporting}
                    className="btn-secondary btn-sm cursor-pointer shadow-2xs"
                  >
                    {isExporting ? (
                      <>
                        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                        Exporting…
                      </>
                    ) : (
                      <>
                        <Download className="w-3.5 h-3.5" />
                        Export JSON
                      </>
                    )}
                  </button>
                </div>
              </div>

              {/* Current Session Summary Card */}
              {currentSavedSession && (
                <div className="bg-slate-50/80 rounded-xl p-3.5 border border-slate-200/80 flex flex-wrap items-center justify-between gap-3 text-xs">
                  <div className="flex flex-wrap items-center gap-4 text-slate-600">
                    <div className="flex items-center gap-1.5">
                      <span className="font-semibold text-slate-700">Session ID:</span>
                      <RunIdBadge runId={currentSavedSession.id} size="sm" showCopy={true} />
                    </div>
                    <div className="flex items-center gap-1">
                      <Clock className="w-3.5 h-3.5 text-slate-400" />
                      <span>Created: {new Date(currentSavedSession.created_at).toLocaleString()}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className="font-semibold text-slate-700">Status:</span>
                      <StatusBadge status={currentSavedSession.status} size="sm" />
                    </div>
                    <div>
                      <span className="font-semibold text-slate-700">Snapshots: </span>
                      <span className="font-bold text-slate-800">{sessionSnapshots.length} saved</span>
                    </div>
                  </div>

                  <div className="truncate max-w-md font-mono text-slate-500 text-[11px]">
                    {currentSavedSession.app_url}
                  </div>
                </div>
              )}
            </div>

            {/* Snapshots Timeline Navigation */}
            {sessionSnapshots.length > 0 && (
              <div className="card p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Calendar className="w-4 h-4 text-primary-600" />
                    <h3 className="text-xs font-bold text-slate-900 tracking-tight uppercase">
                      Captured Snapshots Sequence ({sessionSnapshots.length})
                    </h3>
                  </div>
                  <span className="text-[11px] text-slate-400">
                    Chronological order (oldest to newest)
                  </span>
                </div>

                <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-thin">
                  {sessionSnapshots.map((snap, idx) => {
                    const isSelected = snap.id === selectedSnapshotId;
                    return (
                      <button
                        key={snap.id}
                        type="button"
                        onClick={() => setSelectedSnapshotId(snap.id)}
                        className={`shrink-0 text-left p-2.5 rounded-lg border transition-all cursor-pointer ${
                          isSelected
                            ? 'bg-primary-50/80 border-primary-500 ring-2 ring-primary-500/20 shadow-2xs'
                            : 'bg-white border-slate-200/80 hover:border-slate-300 hover:bg-slate-50'
                        }`}
                      >
                        <div className="flex items-center gap-1.5 mb-1">
                          <span
                            className={`w-4 h-4 rounded-full flex items-center justify-center text-[10px] font-bold ${
                              isSelected
                                ? 'bg-primary-600 text-white'
                                : 'bg-slate-100 text-slate-600'
                            }`}
                          >
                            {idx + 1}
                          </span>
                          <span className="text-xs font-semibold text-slate-800 truncate max-w-[180px]">
                            {snap.page_title || 'Untitled Page'}
                          </span>
                        </div>
                        <div className="text-[11px] text-slate-500 flex items-center justify-between gap-3">
                          <span className="font-medium text-slate-600">{snap.elements_count} elements</span>
                          <span className="text-slate-400">{new Date(snap.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Search Saved Inventory with Natural-Language Intent */}
            <div className="card p-5 space-y-4">
              <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                <div className="flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-indigo-600" />
                  <h3 className="text-sm font-bold text-slate-900 tracking-tight">
                    Natural-Language Target Search & Resolution
                  </h3>
                </div>
                <span className="text-xs text-slate-400">
                  Search across saved snapshots for candidate elements and locators
                </span>
              </div>

              <form onSubmit={handleSearchSavedInventory} className="flex flex-col sm:flex-row gap-2">
                <select
                  value={savedSearchAction}
                  onChange={(e) => setSavedSearchAction(e.target.value)}
                  className="px-2.5 py-1.5 bg-slate-50 border border-slate-200 rounded-lg text-xs font-medium text-slate-800 focus:outline-none focus:ring-1 focus:ring-primary-500 cursor-pointer"
                >
                  <option value="click">click</option>
                  <option value="fill">fill</option>
                  <option value="select_option">select_option</option>
                  <option value="check">check</option>
                  <option value="uncheck">uncheck</option>
                  <option value="verify_text">verify_text</option>
                </select>

                <input
                  type="text"
                  value={savedSearchQuery}
                  onChange={(e) => setSavedSearchQuery(e.target.value)}
                  placeholder="e.g. Find the Save button on the Hire an Employee page, or username field..."
                  required
                  className="input flex-1 py-1.5 text-xs"
                />

                <button
                  type="submit"
                  disabled={isSearchingSaved || !savedSearchQuery.trim()}
                  className="btn-primary btn-sm whitespace-nowrap cursor-pointer"
                >
                  {isSearchingSaved ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      Searching…
                    </>
                  ) : (
                    <>
                      <Search className="w-3.5 h-3.5" />
                      Search Saved Inventory
                    </>
                  )}
                </button>
              </form>

              {/* Search Results Display */}
              {savedSearchResults && (
                <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 space-y-3">
                  <div className="flex items-center justify-between text-xs text-slate-600 border-b border-slate-200 pb-2">
                    <span className="font-semibold">
                      Found {savedSearchResults.total_matches} candidate element match{savedSearchResults.total_matches !== 1 ? 'es' : ''} for "{savedSearchResults.query}"
                    </span>
                    <span className="text-slate-400">
                      Ranked by semantic intent and attribute relevance
                    </span>
                  </div>

                  {savedSearchResults.matches.length === 0 ? (
                    <p className="text-xs text-slate-500 py-2">
                      No matching elements found in the saved snapshots for this query.
                    </p>
                  ) : (
                    <div className="space-y-2.5">
                      {savedSearchResults.matches.slice(0, 5).map((match, mIdx) => {
                        const el = match.element;
                        const recLoc = match.recommended_locator || el.candidate_locators?.[0];
                        const matchLocKey = `saved-search-${mIdx}-loc`;
                        const matchCsvKey = `saved-search-${mIdx}-csv`;

                        return (
                          <div
                            key={mIdx}
                            className="bg-white p-3.5 rounded-lg border border-slate-200 shadow-2xs flex flex-col md:flex-row md:items-center md:justify-between gap-3 text-xs"
                          >
                            <div className="space-y-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <span className="text-[11px] font-bold bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded border border-indigo-200/50">
                                  Score: {match.match_score}
                                </span>
                                <span className="font-bold text-slate-900">
                                  {el.accessible_name || el.label || el.placeholder || el.element_id || 'Element'}
                                </span>
                                <span className="text-slate-400">
                                  in snapshot: <span className="font-medium text-slate-600">{match.snapshot_title || 'Snapshot'}</span>
                                </span>
                                {match.live_validated && (
                                  <span className="text-[11px] bg-emerald-100 text-emerald-800 font-semibold px-2 py-0.5 rounded flex items-center gap-1">
                                    <Check className="w-3 h-3 text-emerald-600" /> Live Validated
                                  </span>
                                )}
                              </div>

                              {recLoc && (
                                <div className="text-[11px] font-mono text-slate-600 flex items-center gap-2">
                                  <span className="text-slate-400 font-sans font-medium">Locator:</span>
                                  <code className="bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200 text-slate-800">
                                    {recLoc}
                                  </code>
                                </div>
                              )}
                            </div>

                            <div className="flex items-center gap-2 shrink-0">
                              {recLoc && (
                                <button
                                  type="button"
                                  onClick={() => copyToClipboard(recLoc, 'Locator', matchLocKey)}
                                  className="btn-secondary btn-xs font-mono cursor-pointer"
                                >
                                  {copiedKey === matchLocKey ? (
                                    <Check className="w-3 h-3 text-emerald-600" />
                                  ) : (
                                    <Copy className="w-3 h-3" />
                                  )}
                                  {copiedKey === matchLocKey ? 'Copied' : 'Selector'}
                                </button>
                              )}
                              <button
                                type="button"
                                onClick={() =>
                                  copyToClipboard(
                                    `TC001,AutoStep,1,${savedSearchAction},${recLoc || el.suggested_intent || el.accessible_name},,`,
                                    'CSV Row',
                                    matchCsvKey
                                  )
                                }
                                className="btn-primary btn-xs cursor-pointer"
                              >
                                {copiedKey === matchCsvKey ? (
                                  <Check className="w-3 h-3" />
                                ) : (
                                  <Sparkles className="w-3 h-3" />
                                )}
                                {copiedKey === matchCsvKey ? 'Copied!' : 'CSV Row'}
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Selected Snapshot Elements Table & Deep Inspection */}
            <div className="card overflow-hidden">
              <div className="p-4 sm:p-5 border-b border-slate-100 space-y-3.5">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <Layers className="w-4 h-4 text-primary-600" />
                      <h3 className="text-sm font-bold text-slate-900 tracking-tight">
                        Snapshot Elements Inventory
                      </h3>
                      <span className="text-xs bg-primary-50 text-primary-700 font-semibold px-2 py-0.5 rounded-full border border-primary-200/60">
                        {filteredSavedElements.length} of {savedSnapshotElements.length} elements
                      </span>
                    </div>
                    {currentSavedSnapshot && (
                      <p className="text-xs text-slate-500 mt-1">
                        Page: <span className="font-semibold text-slate-700">{currentSavedSnapshot.page_title || 'Untitled'}</span> |{' '}
                        <span className="font-mono text-slate-500">{currentSavedSnapshot.page_url}</span>
                      </p>
                    )}
                  </div>

                  {/* Search Bar for Snapshot */}
                  <div className="relative w-full sm:w-72">
                    <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                    <input
                      type="text"
                      value={savedSearchTerm}
                      onChange={(e) => setSavedSearchTerm(e.target.value)}
                      placeholder="Filter by name, label, tag, ID, role…"
                      className="input pl-8 py-1.5 text-xs rounded-lg"
                    />
                  </div>
                </div>

                {/* Category Filter Pills */}
                <div className="flex flex-wrap gap-1.5">
                  {[
                    { id: 'all', label: 'All Elements' },
                    { id: 'input', label: 'Inputs & Textboxes' },
                    { id: 'button', label: 'Buttons' },
                    { id: 'link', label: 'Links' },
                    { id: 'dropdown', label: 'Dropdowns' },
                    { id: 'checkbox', label: 'Checkboxes' },
                    { id: 'image', label: 'Logos & Icons' },
                  ].map((cat) => (
                    <button
                      key={cat.id}
                      onClick={() => setSavedCategory(cat.id)}
                      className={`text-xs px-2.5 py-1 rounded-lg font-medium transition-colors cursor-pointer ${
                        savedCategory === cat.id
                          ? 'bg-primary-600 text-white shadow-2xs font-semibold'
                          : 'bg-slate-100 text-slate-600 hover:bg-slate-200/80 hover:text-slate-800'
                      }`}
                    >
                      {cat.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Elements List */}
              {snapshotsLoading ? (
                <div className="p-12 text-center text-slate-400 flex flex-col items-center justify-center gap-2">
                  <LoadingSpinner size="md" />
                  <p className="text-xs">Loading snapshot elements…</p>
                </div>
              ) : filteredSavedElements.length === 0 ? (
                <div className="p-12 text-center text-slate-400 text-xs">
                  {savedSnapshotElements.length === 0 ? (
                    <p>No elements recorded in this snapshot.</p>
                  ) : (
                    <p>No elements match your search or filter.</p>
                  )}
                </div>
              ) : (
                <div className="divide-y divide-slate-100 max-h-[750px] overflow-y-auto">
                  {filteredSavedElements.map((el) => {
                    const isExpanded = expandedElementId === el.id;
                    const isRawJson = showRawJsonElementId === el.id;
                    const intent = el.suggested_intent || el.accessible_name || el.label || el.placeholder;
                    const actionName =
                      ['input', 'textarea'].includes(el.tag) || el.role === 'textbox'
                        ? 'fill'
                        : el.tag === 'select' || el.role === 'combobox'
                        ? 'select_option'
                        : el.role === 'checkbox' || el.type === 'checkbox'
                        ? 'check'
                        : 'click';

                    const savedIntentKey = `saved-${el.id}-intent`;
                    const savedCsvKey = `saved-${el.id}-csv`;

                    return (
                      <div key={el.id} className="p-4 hover:bg-slate-50/70 transition-colors space-y-3 text-xs">
                        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
                          <div className="space-y-1 min-w-0">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="font-mono text-[11px] bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded font-semibold uppercase">
                                {el.tag}
                                {el.type ? `:${el.type}` : ''}
                              </span>
                              {el.role && (
                                <span className="text-[11px] bg-indigo-50 text-indigo-700 px-1.5 py-0.5 rounded font-medium">
                                  role={el.role}
                                </span>
                              )}
                              {el.is_unique ? (
                                <span className="text-[11px] bg-emerald-50 text-emerald-700 font-semibold px-1.5 py-0.5 rounded flex items-center gap-1 border border-emerald-200/60">
                                  <Check className="w-3 h-3 text-emerald-600" />
                                  Unique
                                </span>
                              ) : (
                                <span className="text-[11px] bg-amber-50 text-amber-700 font-medium px-1.5 py-0.5 rounded flex items-center gap-1 border border-amber-200/60">
                                  <AlertTriangle className="w-3 h-3 text-amber-600" />
                                  Multi-Match
                                </span>
                              )}
                              <span className="text-[11px] text-slate-400 font-mono">
                                [{el.id}]
                              </span>
                            </div>

                            <div className="font-bold text-slate-900 truncate text-xs">
                              {el.accessible_name || el.label || el.placeholder || el.element_id || 'Unnamed element'}
                            </div>

                            <div className="flex flex-wrap gap-2 text-[11px] text-slate-500 font-mono">
                              {el.element_id && <span>id: #{el.element_id}</span>}
                              {el.data_testid && <span>testid: {el.data_testid}</span>}
                              {el.name && <span>name: {el.name}</span>}
                              {el.placeholder && <span>placeholder: "{el.placeholder}"</span>}
                            </div>
                          </div>

                          {/* Quick Actions & Expand Button */}
                          <div className="flex items-center gap-1.5 shrink-0">
                            {intent && (
                              <button
                                type="button"
                                onClick={() => copyToClipboard(intent, 'Intent description', savedIntentKey)}
                                title="Copy intent phrase for CSV target column"
                                className="btn-ghost btn-xs border border-slate-200 hover:bg-slate-100 cursor-pointer"
                              >
                                {copiedKey === savedIntentKey ? (
                                  <Check className="w-3 h-3 text-emerald-600" />
                                ) : (
                                  <Copy className="w-3 h-3" />
                                )}
                                {copiedKey === savedIntentKey ? 'Copied' : 'Intent'}
                              </button>
                            )}

                            {intent && (
                              <button
                                type="button"
                                onClick={() => {
                                  const sampleVal = actionName === 'fill' ? '{{VALUE}}' : '';
                                  copyToClipboard(
                                    `TC001,Test,1,${actionName},${intent},${sampleVal},`,
                                    'CSV row',
                                    savedCsvKey
                                  );
                                }}
                                title="Copy ready-to-paste CSV row"
                                className="btn-primary btn-xs cursor-pointer"
                              >
                                {copiedKey === savedCsvKey ? (
                                  <Check className="w-3 h-3" />
                                ) : (
                                  <Sparkles className="w-3 h-3" />
                                )}
                                {copiedKey === savedCsvKey ? 'Copied!' : 'CSV Row'}
                              </button>
                            )}

                            <button
                              type="button"
                              onClick={() => setExpandedElementId(isExpanded ? null : el.id)}
                              className={`btn-xs border font-medium flex items-center gap-1 transition-colors cursor-pointer ${
                                isExpanded
                                  ? 'bg-primary-50 text-primary-700 border-primary-200 shadow-2xs'
                                  : 'bg-white hover:bg-slate-50 text-slate-700 border-slate-200'
                              }`}
                            >
                              <Eye className="w-3 h-3" />
                              {isExpanded ? 'Hide Details' : 'Details'}
                              {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                            </button>
                          </div>
                        </div>

                        {/* Complete Element Details Drawer */}
                        {isExpanded && (
                          <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 space-y-4 text-xs">
                            <div className="flex items-center justify-between border-b border-slate-200 pb-2">
                              <span className="font-bold text-slate-800">
                                Complete Saved Element Metadata
                              </span>
                              <button
                                type="button"
                                onClick={() =>
                                  setShowRawJsonElementId(isRawJson ? null : el.id)
                                }
                                className="text-xs text-primary-600 hover:text-primary-700 flex items-center gap-1 cursor-pointer font-medium"
                              >
                                <Code2 className="w-3.5 h-3.5" />
                                {isRawJson ? 'View Structured Fields' : 'View Raw JSON'}
                              </button>
                            </div>

                            {isRawJson ? (
                              <pre className="bg-white p-3 rounded-lg border border-slate-200 text-slate-800 font-mono text-[11px] overflow-x-auto shadow-inner">
                                {JSON.stringify(el, null, 2)}
                              </pre>
                            ) : (
                              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                                <div>
                                  <span className="text-slate-400 block font-medium">Element ID:</span>
                                  <span className="font-mono text-slate-800">{el.id}</span>
                                </div>
                                <div>
                                  <span className="text-slate-400 block font-medium">Tag & Type:</span>
                                  <span className="font-mono text-slate-800">
                                    &lt;{el.tag}&gt; {el.type ? `(type: ${el.type})` : ''}
                                  </span>
                                </div>
                                <div>
                                  <span className="text-slate-400 block font-medium">ARIA Role:</span>
                                  <span className="font-mono text-slate-800">{el.role || '—'}</span>
                                </div>
                                <div>
                                  <span className="text-slate-400 block font-medium">Accessible Name:</span>
                                  <span className="text-slate-800 font-semibold">{el.accessible_name || '—'}</span>
                                </div>
                                <div>
                                  <span className="text-slate-400 block font-medium">Label:</span>
                                  <span className="text-slate-800">{el.label || '—'}</span>
                                </div>
                                <div>
                                  <span className="text-slate-400 block font-medium">Placeholder:</span>
                                  <span className="text-slate-800">{el.placeholder || '—'}</span>
                                </div>
                                <div>
                                  <span className="text-slate-400 block font-medium">HTML Element ID:</span>
                                  <span className="font-mono text-slate-800">{el.element_id ? `#${el.element_id}` : '—'}</span>
                                </div>
                                <div>
                                  <span className="text-slate-400 block font-medium">HTML Name Attribute:</span>
                                  <span className="font-mono text-slate-800">{el.name || '—'}</span>
                                </div>
                                <div>
                                  <span className="text-slate-400 block font-medium">Data TestID:</span>
                                  <span className="font-mono text-slate-800">{el.data_testid || '—'}</span>
                                </div>
                                <div>
                                  <span className="text-slate-400 block font-medium">Href:</span>
                                  <span className="font-mono text-slate-800 truncate block">{el.href || '—'}</span>
                                </div>
                                <div>
                                  <span className="text-slate-400 block font-medium">Visible Text:</span>
                                  <span className="text-slate-800 truncate block">{el.visible_text || '—'}</span>
                                </div>
                                <div>
                                  <span className="text-slate-400 block font-medium">Visibility & Enabled:</span>
                                  <span className="text-slate-800">
                                    {el.is_visible ? 'Visible' : 'Hidden'}, {el.is_enabled ? 'Enabled' : 'Disabled'}
                                  </span>
                                </div>
                                <div>
                                  <span className="text-slate-400 block font-medium">Locator Uniqueness:</span>
                                  <span className="text-slate-800">
                                    {el.is_unique ? 'Unique (Single element)' : 'Non-unique (Multiple matches)'}
                                  </span>
                                </div>
                                <div>
                                  <span className="text-slate-400 block font-medium">Frame Information:</span>
                                  <span className="text-slate-800">{el.frame_context || 'Main Window'}</span>
                                </div>
                                <div>
                                  <span className="text-slate-400 block font-medium">Suggested Intent:</span>
                                  <span className="font-semibold text-primary-700 bg-primary-50 px-1.5 py-0.5 rounded border border-primary-200/60">
                                    {el.suggested_intent || '—'}
                                  </span>
                                </div>
                              </div>
                            )}

                            {/* Candidate Playwright Locators */}
                            {el.candidate_locators && el.candidate_locators.length > 0 && (
                              <div className="pt-2.5 border-t border-slate-200 space-y-2">
                                <span className="text-slate-500 font-semibold block">
                                  Candidate Playwright Locators ({el.candidate_locators.length}):
                                </span>
                                <div className="space-y-1.5">
                                  {el.candidate_locators.map((loc, locIdx) => {
                                    const locKey = `candidate-${el.id}-${locIdx}`;
                                    return (
                                      <div
                                        key={locIdx}
                                        className="bg-white p-2 rounded-lg border border-slate-200 flex items-center justify-between gap-2 font-mono text-[11px] shadow-2xs"
                                      >
                                        <span className="truncate text-slate-800 font-medium">{loc}</span>
                                        <button
                                          type="button"
                                          onClick={() => copyToClipboard(loc, 'Locator', locKey)}
                                          className="btn-ghost btn-xs border border-slate-200 text-slate-600 hover:text-slate-900 shrink-0 flex items-center gap-1 cursor-pointer"
                                        >
                                          {copiedKey === locKey ? (
                                            <Check className="w-3 h-3 text-emerald-600" />
                                          ) : (
                                            <Copy className="w-3 h-3" />
                                          )}
                                          {copiedKey === locKey ? 'Copied' : 'Copy'}
                                        </button>
                                      </div>
                                    );
                                  })}
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
};

export default LiveDiscovery;
