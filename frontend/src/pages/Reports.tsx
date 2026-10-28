import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  BarChart3,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  Film,
  Camera,
  Terminal,
  Calendar,
  ChevronRight,
  RefreshCw,
  Layers,
  Check,
  X,
  Minus,
  ChevronDown,
  Info,
  Search,
  Copy,
  ExternalLink,
  ShieldAlert,
  ArrowLeft,
  VideoOff,
  SlidersHorizontal,
} from 'lucide-react';
import { Layout } from '../components/layout/Layout';
import { PageLoader } from '../components/ui/LoadingSpinner';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { EmptyState } from '../components/ui/EmptyState';
import { StatusBadge } from '../components/ui/StatusBadge';
import { RunIdBadge } from '../components/ui/RunIdBadge';
import { AuthenticatedImage, AuthenticatedVideo } from '../components/ui/AuthenticatedMedia';
import { testRunsApi } from '../api/testRuns';
import { testCasesApi } from '../api/testCases';
import { apiClient } from '../api/client';
import { TestRun, TestResult, Artifact, TestCase } from '../types';

interface FullRunReport {
  run: TestRun;
  results: TestResult[];
  artifacts: Artifact[];
  summary: {
    total: number;
    passed: number;
    failed: number;
    errors: number;
    pass_rate: number;
    duration_seconds?: number;
    total_steps?: number;
    passed_steps?: number;
    failed_steps?: number;
    skipped_steps?: number;
    step_pass_rate?: number;
  };
}

type SidebarStatusFilter = 'all' | 'passed' | 'failed';

export const Reports: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const runIdFromUrl = searchParams.get('run');

  const [runs, setRuns] = useState<TestRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(runIdFromUrl);
  const [report, setReport] = useState<FullRunReport | null>(null);

  const [loadingRuns, setLoadingRuns] = useState(true);
  const [refreshingRuns, setRefreshingRuns] = useState(false);
  const [loadingReport, setLoadingReport] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null);
  const [showLogs, setShowLogs] = useState(false);
  const [copiedLogs, setCopiedLogs] = useState(false);
  const [copiedTcId, setCopiedTcId] = useState(false);
  const [testCaseMap, setTestCaseMap] = useState<Record<string, TestCase>>({});

  // Left sidebar filters
  const [sidebarSearch, setSidebarSearch] = useState('');
  const [sidebarStatus, setSidebarStatus] = useState<SidebarStatusFilter>('all');

  const loadRuns = useCallback(async (isRefresh = false) => {
    if (isRefresh) {
      setRefreshingRuns(true);
    } else {
      setLoadingRuns(true);
    }
    setError(null);

    try {
      const data = await testRunsApi.list();
      setRuns(data);
      if (runIdFromUrl && data.some((r) => r.id === runIdFromUrl)) {
        setSelectedRunId(runIdFromUrl);
      } else if (data.length > 0 && !selectedRunId) {
        setSelectedRunId(data[0].id);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load test runs');
    } finally {
      setLoadingRuns(false);
      setRefreshingRuns(false);
    }
  }, [runIdFromUrl, selectedRunId]);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  // Load full report for selected run
  useEffect(() => {
    if (!selectedRunId) {
      setReport(null);
      return;
    }

    const fetchReport = async () => {
      setLoadingReport(true);
      try {
        const res = await apiClient.get(`/api/runs/${selectedRunId}/report`);
        setReport(res.data);
        if (res.data.results?.length > 0) {
          setSelectedResultId(res.data.results[0].id);
        }
      } catch (err: any) {
        // Fallback: load run + results separately
        try {
          const [run, results] = await Promise.all([
            testRunsApi.get(selectedRunId),
            testRunsApi.getResults(selectedRunId),
          ]);
          setReport({
            run,
            results,
            artifacts: [],
            summary: {
              total: run.total_tests,
              passed: run.passed_tests,
              failed: run.failed_tests,
              errors: run.status === 'error' ? 1 : 0,
              pass_rate:
                run.total_tests > 0
                  ? Math.round((run.passed_tests / run.total_tests) * 100)
                  : 0,
            },
          });
          if (results.length > 0) {
            setSelectedResultId(results[0].id);
          }
        } catch (innerErr: any) {
          setError(innerErr.message || 'Failed to load report');
        }
      } finally {
        setLoadingReport(false);
      }
    };

    fetchReport();
  }, [selectedRunId]);

  // Fetch project test cases so results can display saved names rather than raw IDs
  useEffect(() => {
    const projectId = report?.run?.project_id;
    if (!projectId) {
      setTestCaseMap({});
      return;
    }

    let isMounted = true;
    testCasesApi
      .list(projectId)
      .then((cases) => {
        if (isMounted && Array.isArray(cases)) {
          const map: Record<string, TestCase> = {};
          for (const tc of cases) {
            if (tc.id) {
              map[tc.id] = tc;
            }
          }
          setTestCaseMap(map);
        }
      })
      .catch(() => {
        // Graceful fallback: map remains empty, falls back to ID-based labels
      });

    return () => {
      isMounted = false;
    };
  }, [report?.run?.project_id]);

  const getTestCaseInfo = useCallback(
    (result?: TestResult | null) => {
      if (!result) {
        return {
          name: 'Test Case',
          idLabel: '',
          fullId: '',
          description: undefined,
        };
      }

      const tcFromMap = result.test_case_id ? testCaseMap[result.test_case_id] : undefined;
      const name =
        result.test_case?.name ||
        tcFromMap?.name ||
        (result.test_case_id ? `Test Case #${result.test_case_id.slice(0, 8)}` : 'Test Case');

      const description = result.test_case?.description || tcFromMap?.description;
      const fullId = result.test_case_id || '';
      const idLabel = fullId ? `ID: ${fullId.slice(0, 8)}…` : '';

      return { name, idLabel, fullId, description };
    },
    [testCaseMap]
  );

  const handleSelectRun = (runId: string) => {
    setSelectedRunId(runId);
    setSearchParams({ run: runId });
  };

  const handleCopyLogs = (logText: string) => {
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(logText);
      setCopiedLogs(true);
      setTimeout(() => setCopiedLogs(false), 1500);
    }
  };

  const handleCopyTcId = (id: string) => {
    if (navigator?.clipboard?.writeText && id) {
      navigator.clipboard.writeText(id);
      setCopiedTcId(true);
      setTimeout(() => setCopiedTcId(false), 1500);
    }
  };

  // Filtered runs in sidebar
  const filteredRuns = useMemo(() => {
    const query = sidebarSearch.trim().toLowerCase();
    return runs.filter((r) => {
      if (sidebarStatus !== 'all' && r.status !== sidebarStatus) {
        return false;
      }
      if (query) {
        const fullId = r.id.toLowerCase();
        const formattedId = `run-${r.id.replace(/-/g, '').slice(0, 8)}`.toLowerCase();
        const status = (r.status || '').toLowerCase();
        return fullId.includes(query) || formattedId.includes(query) || status.includes(query);
      }
      return true;
    });
  }, [runs, sidebarSearch, sidebarStatus]);

  const selectedResult = report?.results.find((r) => r.id === selectedResultId);
  const selectedTcInfo = getTestCaseInfo(selectedResult);

  const getCategoryBadge = (category?: string | null) => {
    if (!category) return null;
    const map: Record<string, { label: string; bg: string; text: string; border: string }> = {
      missing_element: {
        label: 'Missing Element',
        bg: 'bg-amber-50',
        text: 'text-amber-800',
        border: 'border-amber-200',
      },
      ambiguous_target: {
        label: 'Ambiguous Target',
        bg: 'bg-purple-50',
        text: 'text-purple-800',
        border: 'border-purple-200',
      },
      assertion_failure: {
        label: 'Assertion Failed',
        bg: 'bg-rose-50',
        text: 'text-rose-800',
        border: 'border-rose-200',
      },
      timeout: {
        label: 'Timeout',
        bg: 'bg-orange-50',
        text: 'text-orange-800',
        border: 'border-orange-200',
      },
      parsing_failure: {
        label: 'Syntax / Action Error',
        bg: 'bg-yellow-50',
        text: 'text-yellow-800',
        border: 'border-yellow-200',
      },
      execution_error: {
        label: 'Execution Error',
        bg: 'bg-red-50',
        text: 'text-red-800',
        border: 'border-red-200',
      },
    };
    const config = map[category] || {
      label: category,
      bg: 'bg-slate-100',
      text: 'text-slate-700',
      border: 'border-slate-200',
    };
    return (
      <span
        className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border ${config.bg} ${config.text} ${config.border}`}
      >
        {config.label}
      </span>
    );
  };

  const formatDurationString = (seconds?: number) => {
    if (seconds === undefined || seconds === null) return '—';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const rem = Math.round(seconds % 60);
    return `${mins}m ${rem}s`;
  };

  return (
    <Layout
      title="Reports & Evidence"
      subtitle="Execution history, step-level diagnostics, browser recordings, and failure screenshots"
    >
      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left column: Run history sidebar */}
        <div className="lg:col-span-4 space-y-4">
          <div className="card p-4">
            {/* Sidebar Header */}
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 mb-3">
              <div className="flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-primary-600" />
                <h3 className="font-semibold text-slate-800 text-sm">
                  Run History
                </h3>
                <span className="px-1.5 py-0.2 rounded-full text-[11px] font-semibold bg-slate-100 text-slate-600">
                  {runs.length}
                </span>
              </div>
              <button
                type="button"
                onClick={() => loadRuns(true)}
                disabled={refreshingRuns}
                className="text-xs text-slate-500 hover:text-slate-800 flex items-center gap-1 cursor-pointer transition-colors"
                title="Refresh execution history"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${refreshingRuns ? 'animate-spin' : ''}`} />
                {refreshingRuns ? 'Refreshing…' : 'Refresh'}
              </button>
            </div>

            {/* Sidebar Search & Status Filter */}
            <div className="space-y-2 mb-3">
              <div className="relative">
                <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                <input
                  type="text"
                  value={sidebarSearch}
                  onChange={(e) => setSidebarSearch(e.target.value)}
                  placeholder="Search Run ID or status…"
                  className="input pl-8 pr-7 text-xs py-1.5 rounded-lg"
                />
                {sidebarSearch && (
                  <button
                    type="button"
                    onClick={() => setSidebarSearch('')}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>

              {/* Status pills */}
              <div className="flex items-center gap-1">
                {(['all', 'passed', 'failed'] as const).map((filterKey) => {
                  const isActive = sidebarStatus === filterKey;
                  return (
                    <button
                      key={filterKey}
                      type="button"
                      onClick={() => setSidebarStatus(filterKey)}
                      className={`flex-1 py-1 text-center text-xs font-medium rounded capitalize transition-colors cursor-pointer ${
                        isActive
                          ? 'bg-slate-800 text-white shadow-2xs font-semibold'
                          : 'bg-slate-100 text-slate-600 hover:bg-slate-200/70'
                      }`}
                    >
                      {filterKey}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Run List Container */}
            {loadingRuns ? (
              <PageLoader message="Loading execution history..." />
            ) : runs.length === 0 ? (
              <EmptyState
                icon={BarChart3}
                title="No runs yet"
                description="Execute test cases to generate reports and evidence."
              />
            ) : filteredRuns.length === 0 ? (
              <div className="py-8 text-center text-xs text-slate-400">
                No runs match your search filters.
                <button
                  type="button"
                  onClick={() => {
                    setSidebarSearch('');
                    setSidebarStatus('all');
                  }}
                  className="block mx-auto mt-2 text-primary-600 hover:underline cursor-pointer"
                >
                  Reset filters
                </button>
              </div>
            ) : (
              <div className="space-y-2 max-h-[650px] overflow-y-auto pr-1">
                {filteredRuns.map((r) => {
                  const isSelected = r.id === selectedRunId;
                  const dateStr = new Date(r.created_at).toLocaleString(undefined, {
                    month: 'short',
                    day: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit',
                  });

                  return (
                    <div
                      key={r.id}
                      onClick={() => handleSelectRun(r.id)}
                      className={`p-3 rounded-lg border text-left transition-all cursor-pointer ${
                        isSelected
                          ? 'border-primary-500 bg-primary-50/50 ring-1 ring-primary-500/20 shadow-xs'
                          : 'border-slate-200/90 hover:bg-slate-50/80'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1.5">
                        <RunIdBadge runId={r.id} size="sm" showCopy={false} />
                        <StatusBadge status={r.status} size="sm" />
                      </div>

                      <div className="flex items-center justify-between text-xs text-slate-600 mt-2">
                        <span className="font-medium">
                          <span className="text-emerald-600 font-semibold">{r.passed_tests}✓</span>
                          {' / '}
                          <span className="text-rose-600 font-semibold">{r.failed_tests}✗</span>
                          <span className="text-slate-400 font-normal"> of {r.total_tests} cases</span>
                        </span>
                        <span className="text-[11px] text-slate-400 flex items-center gap-1">
                          <Clock className="w-3 h-3 text-slate-400" />
                          {dateStr}
                        </span>
                      </div>

                      {r.total_steps !== undefined && r.total_steps > 0 && (
                        <div className="mt-2 pt-1.5 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
                          <span>
                            Steps: <strong className="text-slate-700">{r.passed_steps || 0}</strong> passed /{' '}
                            <strong className="text-slate-700">{r.failed_steps || 0}</strong> failed
                          </span>
                          {r.skipped_steps ? (
                            <span className="text-slate-400">{r.skipped_steps} skipped</span>
                          ) : null}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Right column: Run details, results, and artifacts */}
        <div className="lg:col-span-8 space-y-5">
          {loadingReport ? (
            <div className="card p-12 text-center">
              <PageLoader message="Loading run report & diagnostics..." />
            </div>
          ) : !report ? (
            <div className="card p-12 text-center text-slate-400">
              <BarChart3 className="w-12 h-12 mx-auto mb-2 text-slate-300 stroke-[1.5]" />
              <p className="font-medium text-slate-600">No Run Selected</p>
              <p className="text-xs text-slate-400 mt-1">
                Select an execution run from the left panel to inspect detailed evidence.
              </p>
            </div>
          ) : (
            <>
              {/* Selected Run Banner */}
              <div className="card p-4 sm:p-5">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2.5">
                      <h2 className="text-base font-bold text-slate-900 tracking-tight">
                        Execution Run
                      </h2>
                      <RunIdBadge runId={report.run.id} showCopy={true} />
                      <StatusBadge status={report.run.status} size="sm" />
                    </div>
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
                      <span className="flex items-center gap-1">
                        <Calendar className="w-3.5 h-3.5 text-slate-400" />
                        Created: {new Date(report.run.created_at).toLocaleString()}
                      </span>
                      {report.run.started_at && (
                        <span>Started: {new Date(report.run.started_at).toLocaleTimeString()}</span>
                      )}
                      {report.run.triggered_by && (
                        <span className="px-1.5 py-0.2 rounded bg-slate-100 text-slate-600 text-[11px]">
                          Trigger: {report.run.triggered_by}
                        </span>
                      )}
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={() => navigate('/dashboard')}
                    className="btn-ghost btn-sm self-start sm:self-center"
                  >
                    <ArrowLeft className="w-3.5 h-3.5" />
                    Back to Dashboard
                  </button>
                </div>
              </div>

              {/* Summary Metrics */}
              <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
                <div className="card p-3.5 text-center">
                  <p className="text-xs text-slate-500 font-medium">Test Cases</p>
                  <p className="text-xl font-bold text-slate-900 mt-1">
                    {report.summary?.pass_rate ?? 0}%
                  </p>
                  <p className="text-[11px] text-slate-400 mt-0.5">
                    {report.run.passed_tests}/{report.run.total_tests} passed
                  </p>
                </div>
                <div className="card p-3.5 text-center">
                  <p className="text-xs text-slate-500 font-medium">Step Pass Rate</p>
                  <p className="text-xl font-bold text-emerald-600 mt-1">
                    {report.summary?.step_pass_rate ?? 0}%
                  </p>
                  <p className="text-[11px] text-slate-400 mt-0.5">
                    {report.summary?.passed_steps ?? 0}/{report.summary?.total_steps ?? 0} steps
                  </p>
                </div>
                <div className="card p-3.5 text-center">
                  <p className="text-xs text-slate-500 font-medium">Passed Steps</p>
                  <p className="text-xl font-bold text-emerald-600 mt-1">
                    {report.summary?.passed_steps ?? 0}
                  </p>
                  <p className="text-[11px] text-emerald-600/70 mt-0.5">verified steps</p>
                </div>
                <div className="card p-3.5 text-center">
                  <p className="text-xs text-slate-500 font-medium">Failed Steps</p>
                  <p className="text-xl font-bold text-rose-600 mt-1">
                    {report.summary?.failed_steps ?? 0}
                  </p>
                  <p className="text-[11px] text-rose-500/70 mt-0.5">errors & breaks</p>
                </div>
                <div className="card p-3.5 text-center">
                  <p className="text-xs text-slate-500 font-medium">Skipped Steps</p>
                  <p className="text-xl font-bold text-slate-600 mt-1">
                    {report.summary?.skipped_steps ?? 0}
                  </p>
                  <p className="text-[11px] text-slate-400 mt-0.5">not reached</p>
                </div>
                <div className="card p-3.5 text-center">
                  <p className="text-xs text-slate-500 font-medium">Total Duration</p>
                  <p className="text-xl font-bold text-slate-700 mt-1 font-mono">
                    {formatDurationString(report.summary?.duration_seconds)}
                  </p>
                  <p className="text-[11px] text-slate-400 mt-0.5">execution runtime</p>
                </div>
              </div>

              {report.run.error_message && (
                <div className="p-4 bg-amber-50 border border-amber-200/80 rounded-xl text-xs text-amber-900 flex items-start gap-2.5 shadow-2xs">
                  <ShieldAlert className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                  <div>
                    <strong className="font-semibold text-amber-900">Run Notice:</strong>{' '}
                    <span>{report.run.error_message}</span>
                  </div>
                </div>
              )}

              {/* Recorded Browser Video Container */}
              {(() => {
                const selectedVideoArtifact = selectedResult
                  ? report.artifacts.find(
                      (a) => a.result_id === selectedResult.id && a.artifact_type === 'video'
                    )
                  : null;
                const activeVideoArtifact =
                  selectedVideoArtifact || report.artifacts.find((a) => a.artifact_type === 'video');
                const activeVideoPath =
                  selectedResult?.video_path || selectedVideoArtifact?.file_path || report.run.video_path;

                if (!activeVideoPath) {
                  return (
                    <div className="card p-4">
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2.5 min-w-0 text-xs">
                          <div className="w-7 h-7 rounded-lg bg-slate-100 flex items-center justify-center text-slate-500 shrink-0 border border-slate-200/60">
                            <VideoOff className="w-4 h-4 text-slate-500" />
                          </div>
                          <div className="min-w-0">
                            <span className="font-semibold text-slate-800">Browser Recording Unavailable</span>
                            <span className="hidden sm:inline text-slate-400 mx-1.5">—</span>
                            <span className="hidden sm:inline text-[11px] text-slate-500">
                              No browser recording was captured or preserved for this test case or execution run.
                            </span>
                          </div>
                        </div>
                        <span className="badge badge-gray text-[10px] uppercase font-semibold tracking-wider shrink-0">
                          No Video
                        </span>
                      </div>
                    </div>
                  );
                }

                return (
                  <div className="card p-4 sm:p-5">
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2 text-slate-800 font-semibold text-sm">
                        <Film className="w-4 h-4 text-primary-600" />
                        <span>Browser Session Recording</span>
                        {selectedResult && (
                          <span className="text-xs font-normal text-slate-500">
                            — {selectedTcInfo.name}
                          </span>
                        )}
                      </div>
                      {report.results.length > 1 && (
                        <span className="text-[11px] text-slate-400">
                          {selectedVideoArtifact ? 'Showing test case recording' : 'Showing suite recording'}
                        </span>
                      )}
                    </div>
                    <div className="rounded-xl overflow-hidden bg-slate-950 flex justify-center border border-slate-800 shadow-inner">
                      <AuthenticatedVideo
                        key={activeVideoArtifact?.id || activeVideoPath}
                        artifactId={activeVideoArtifact?.id}
                        filePath={activeVideoPath}
                        className="max-h-80 w-full"
                      />
                    </div>
                  </div>
                );
              })()}

              {/* Test Case Results Breakdown & Step Diagnostics */}
              <div className="card p-4 sm:p-5">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <Layers className="w-4 h-4 text-primary-600" />
                    <h3 className="font-semibold text-slate-800 text-sm">
                      Test Cases & Step Diagnostics
                    </h3>
                  </div>
                  <span className="text-xs text-slate-400">
                    {report.results.length} {report.results.length === 1 ? 'case' : 'cases'}
                  </span>
                </div>

                {report.results.length === 0 ? (
                  <p className="text-xs text-slate-400 py-6 text-center">
                    No individual results recorded for this run.
                  </p>
                ) : (
                  <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
                    {/* Result Selector (Left) */}
                    <div className="lg:col-span-4 space-y-2 lg:border-r border-slate-100 lg:pr-3">
                      <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2">
                        Select Test Case
                      </p>
                      {report.results.map((res) => {
                        const isSelected = res.id === selectedResultId;
                        const tcInfo = getTestCaseInfo(res);
                        return (
                          <button
                            key={res.id}
                            type="button"
                            onClick={() => setSelectedResultId(res.id)}
                            className={`w-full p-2.5 rounded-lg text-left text-xs transition-colors flex items-center justify-between gap-2 cursor-pointer ${
                              isSelected
                                ? 'bg-primary-50 text-primary-900 font-medium border border-primary-200 shadow-2xs'
                                : 'hover:bg-slate-50 text-slate-700 border border-slate-200/60'
                            }`}
                          >
                            <div className="flex flex-col min-w-0 pr-1">
                              <span className="truncate font-semibold text-xs text-slate-800" title={tcInfo.name}>
                                {tcInfo.name}
                              </span>
                              {tcInfo.idLabel && (
                                <span
                                  className="font-mono text-[10px] text-slate-400 truncate mt-0.5"
                                  title={tcInfo.fullId ? `Full ID: ${tcInfo.fullId}` : undefined}
                                >
                                  {tcInfo.idLabel}
                                </span>
                              )}
                            </div>
                            <StatusBadge status={res.status} size="sm" className="shrink-0" />
                          </button>
                        );
                      })}
                    </div>

                    {/* Result Details / Evidence (Right) */}
                    <div className="lg:col-span-8 space-y-4">
                      {selectedResult ? (
                        <>
                          {/* Selected Case Header */}
                          <div className="flex items-start justify-between pb-3 border-b border-slate-100 gap-3">
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <h4 className="font-bold text-slate-900 text-sm break-words" title={selectedTcInfo.name}>
                                  {selectedTcInfo.name}
                                </h4>
                                {selectedTcInfo.fullId && (
                                  <button
                                    type="button"
                                    onClick={() => handleCopyTcId(selectedTcInfo.fullId)}
                                    className="inline-flex items-center gap-1 font-mono text-[11px] text-slate-500 hover:text-slate-800 bg-slate-100 hover:bg-slate-200/80 px-2 py-0.5 rounded border border-slate-200 transition-colors cursor-pointer"
                                    title={`Click to copy full ID: ${selectedTcInfo.fullId}`}
                                    aria-label="Copy test case ID"
                                  >
                                    <span>{selectedTcInfo.idLabel}</span>
                                    {copiedTcId ? (
                                      <Check className="w-3 h-3 text-emerald-600" />
                                    ) : (
                                      <Copy className="w-3 h-3 text-slate-400" />
                                    )}
                                  </button>
                                )}
                              </div>
                              {selectedTcInfo.description && (
                                <p className="text-xs text-slate-500 mt-1 break-words">
                                  {selectedTcInfo.description}
                                </p>
                              )}
                            </div>
                            <StatusBadge status={selectedResult.status} className="shrink-0" />
                          </div>

                          {/* Failure Summary Diagnostic Banner */}
                          {selectedResult.error_message && (
                            <div className="p-3.5 bg-rose-50/80 border border-rose-200 rounded-xl space-y-1 shadow-2xs">
                              <p className="text-xs font-bold text-rose-900 flex items-center gap-1.5">
                                <AlertTriangle className="w-4 h-4 text-rose-600 shrink-0" />
                                Execution Diagnostic
                              </p>
                              <div className="text-xs font-mono text-rose-950 break-words leading-relaxed pl-5.5">
                                {selectedResult.error_message}
                              </div>
                            </div>
                          )}

                          {/* Step-by-Step Diagnostics Table */}
                          {selectedResult.steps && selectedResult.steps.length > 0 ? (
                            <div className="space-y-2">
                              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                                <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-700 uppercase tracking-wider">
                                  <Layers className="w-3.5 h-3.5 text-primary-600" />
                                  Step Details ({selectedResult.steps.length})
                                </div>
                                {selectedResult.step_summary && (
                                  <div className="flex items-center gap-2 text-xs">
                                    <span className="text-emerald-700 font-semibold bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200/50">
                                      ✓ {selectedResult.step_summary.passed} passed
                                    </span>
                                    {selectedResult.step_summary.failed > 0 && (
                                      <span className="text-rose-700 font-semibold bg-rose-50 px-2 py-0.5 rounded border border-rose-200/50">
                                        ✗ {selectedResult.step_summary.failed} failed
                                      </span>
                                    )}
                                    {selectedResult.step_summary.skipped > 0 && (
                                      <span className="text-slate-600 font-medium bg-slate-100 px-2 py-0.5 rounded border border-slate-200">
                                        ⏸ {selectedResult.step_summary.skipped} skipped
                                      </span>
                                    )}
                                  </div>
                                )}
                              </div>

                              <div className="border border-slate-200 rounded-xl overflow-hidden bg-white shadow-2xs">
                                <div className="overflow-x-auto">
                                  <table className="w-full min-w-[560px] text-left border-collapse text-xs">
                                    <thead className="bg-slate-50/80 border-b border-slate-200 text-slate-600">
                                      <tr>
                                        <th className="py-2.5 px-3 font-semibold w-10 text-center">#</th>
                                        <th className="py-2.5 px-3 font-semibold w-24">Status</th>
                                        <th className="py-2.5 px-3 font-semibold">Instruction & Action</th>
                                        <th className="py-2.5 px-3 font-semibold w-24 text-right whitespace-nowrap">Duration</th>
                                        <th className="py-2.5 px-3 font-semibold w-36">Category</th>
                                      </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-100">
                                      {selectedResult.steps.map((st) => {
                                        const isPassed = st.status === 'passed';
                                        const isFailed = st.status === 'failed' || st.status === 'error';
                                        const isSkipped = st.status === 'skipped';
                                        return (
                                          <tr
                                            key={st.step_number}
                                            className={`hover:bg-slate-50/80 transition-colors ${
                                              isFailed ? 'bg-rose-50/30' : ''
                                            }`}
                                          >
                                            <td className="py-2.5 px-3 text-center font-mono text-slate-400 font-semibold">
                                              {st.step_number}
                                            </td>
                                            <td className="py-2.5 px-3">
                                              <span
                                                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold ${
                                                  isPassed
                                                    ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                                                    : isFailed
                                                    ? 'bg-rose-50 text-rose-700 border border-rose-200'
                                                    : 'bg-slate-100 text-slate-600 border border-slate-200'
                                                }`}
                                              >
                                                {isPassed && <Check className="w-3 h-3 text-emerald-600" />}
                                                {isFailed && <X className="w-3 h-3 text-rose-600" />}
                                                {isSkipped && <Minus className="w-3 h-3 text-slate-400" />}
                                                {st.status}
                                              </span>
                                            </td>
                                            <td className="py-2.5 px-3">
                                              <div className="font-semibold text-slate-800">
                                                {st.original_instruction || `${st.action} ${st.target || ''}`}
                                              </div>
                                              <div className="flex flex-wrap items-center gap-1.5 mt-1 text-[11px] text-slate-500 font-mono">
                                                <span className="px-1.5 py-0.5 bg-slate-100 rounded text-slate-700 font-semibold">
                                                  [{st.action}]
                                                </span>
                                                {st.target && (
                                                  <span className="truncate max-w-[220px] bg-slate-50 px-1 rounded border border-slate-200/60 text-slate-600">
                                                    target: {st.target}
                                                  </span>
                                                )}
                                                {st.value && (
                                                  <span className="truncate max-w-[180px] bg-slate-50 px-1 rounded border border-slate-200/60 text-slate-600">
                                                    value: {st.value}
                                                  </span>
                                                )}
                                              </div>
                                              {isFailed && st.failure_reason && (
                                                <div className="mt-2 p-2 bg-rose-50/90 border border-rose-200 rounded-lg text-[11px] font-mono text-rose-950 break-words leading-relaxed">
                                                  {st.failure_reason}
                                                </div>
                                              )}
                                              {st.verification_result && st.verification_result.type && (
                                                <div className="mt-1 text-[11px] text-slate-500">
                                                  Expected: <span className="font-mono text-slate-700">{st.verification_result.expected}</span>
                                                </div>
                                              )}
                                            </td>
                                            <td className="py-2.5 px-3 text-right font-mono text-slate-600 whitespace-nowrap">
                                              {st.duration_ms !== null && st.duration_ms !== undefined
                                                ? `${st.duration_ms.toFixed(1)} ms`
                                                : '—'}
                                            </td>
                                            <td className="py-2.5 px-3">
                                              {isFailed ? (
                                                getCategoryBadge(st.category)
                                              ) : isPassed ? (
                                                <span className="text-[11px] text-emerald-600 font-medium">
                                                  Success
                                                </span>
                                              ) : (
                                                <span className="text-[11px] text-slate-400">
                                                  Skipped
                                                </span>
                                              )}
                                            </td>
                                          </tr>
                                        );
                                      })}
                                    </tbody>
                                  </table>
                                </div>
                              </div>
                            </div>
                          ) : null}

                          {/* Failure Screenshot */}
                          {selectedResult.screenshot_path && (
                            <div>
                              <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-700 uppercase tracking-wider mb-2">
                                <Camera className="w-3.5 h-3.5 text-slate-500" />
                                Failure Screenshot
                              </div>
                              <div className="border border-slate-200 rounded-xl overflow-hidden bg-slate-900 shadow-2xs">
                                <AuthenticatedImage
                                  artifactId={
                                    report.artifacts.find(
                                      (a) => a.result_id === selectedResult.id
                                    )?.id
                                  }
                                  filePath={selectedResult.screenshot_path}
                                  alt="Failure Screenshot"
                                  className="w-full object-contain max-h-96"
                                />
                              </div>
                            </div>
                          )}

                          {/* Technical Execution Logs */}
                          <div>
                            <div className="flex items-center justify-between mb-2">
                              <button
                                type="button"
                                onClick={() => setShowLogs(!showLogs)}
                                className="flex items-center gap-1.5 text-xs font-semibold text-slate-700 uppercase tracking-wider cursor-pointer hover:text-slate-900 transition-colors"
                              >
                                <Terminal className="w-3.5 h-3.5 text-slate-500" />
                                Technical Execution Logs
                                <ChevronDown
                                  className={`w-3.5 h-3.5 transition-transform duration-200 ${
                                    showLogs ? 'rotate-180' : ''
                                  }`}
                                />
                              </button>

                              {showLogs && selectedResult.log_output && (
                                <button
                                  type="button"
                                  onClick={() => handleCopyLogs(selectedResult.log_output || '')}
                                  className="inline-flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-800 bg-slate-100 hover:bg-slate-200 px-2 py-0.5 rounded cursor-pointer transition-colors"
                                >
                                  {copiedLogs ? (
                                    <>
                                      <Check className="w-3 h-3 text-emerald-600" />
                                      <span className="text-emerald-600 font-medium">Copied!</span>
                                    </>
                                  ) : (
                                    <>
                                      <Copy className="w-3 h-3" />
                                      <span>Copy Logs</span>
                                    </>
                                  )}
                                </button>
                              )}
                            </div>

                            {showLogs && (
                              <pre className="p-3.5 bg-slate-900 text-slate-200 text-xs font-mono rounded-xl overflow-x-auto max-h-64 border border-slate-800 shadow-inner">
                                {selectedResult.log_output || 'No log output captured.'}
                              </pre>
                            )}
                          </div>
                        </>
                      ) : (
                        <p className="text-xs text-slate-400 py-6 text-center">
                          Select a test case to view evidence.
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </Layout>
  );
};

export default Reports;
