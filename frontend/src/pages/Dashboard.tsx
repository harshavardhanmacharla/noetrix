import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FolderOpen,
  FileText,
  CheckCircle2,
  XCircle,
  TrendingUp,
  Play,
  Upload,
  Search,
  X,
  RefreshCw,
  ArrowRight,
  Filter,
  Layers,
  Clock,
  Sparkles,
} from 'lucide-react';
import { Layout } from '../components/layout/Layout';
import { StatCard } from '../components/ui/StatCard';
import { StatusBadge } from '../components/ui/StatusBadge';
import { RunIdBadge } from '../components/ui/RunIdBadge';
import { Pagination } from '../components/ui/Pagination';
import { PageLoader } from '../components/ui/LoadingSpinner';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { EmptyState } from '../components/ui/EmptyState';
import { reportsApi } from '../api/reports';
import { projectsApi } from '../api/projects';
import { testCasesApi } from '../api/testCases';
import { testRunsApi } from '../api/testRuns';
import { DashboardStats, TestRun } from '../types';

type StatusFilter = 'all' | 'passed' | 'failed' | 'running' | 'error';
type SortField = 'date_desc' | 'date_asc' | 'duration' | 'tests';

export const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [allRuns, setAllRuns] = useState<TestRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters, search, pagination state
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [sortBy, setSortBy] = useState<SortField>('date_desc');
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const fetchStats = useCallback(async (isRefresh = false) => {
    if (isRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);

    try {
      const [statsResult, runsResult] = await Promise.allSettled([
        reportsApi.getDashboardStats(),
        testRunsApi.list(),
      ]);

      let runsList: TestRun[] = [];
      if (runsResult.status === 'fulfilled' && Array.isArray(runsResult.value)) {
        runsList = runsResult.value;
      }

      if (statsResult.status === 'fulfilled') {
        const statsData = statsResult.value;
        const effectiveRuns = runsList.length > 0 ? runsList : statsData.recent_runs || [];
        setStats({
          ...statsData,
          recent_runs: effectiveRuns,
          total_runs: Math.max(statsData.total_runs, effectiveRuns.length),
        });
        setAllRuns(effectiveRuns);
      } else {
        // Fallback: derive stats from individual endpoints
        const [projects, testCases] = await Promise.all([
          projectsApi.list().catch(() => []),
          testCasesApi.list().catch(() => []),
        ]);
        const passedRuns = runsList.filter((r) => r.status === 'passed').length;
        const failedRuns = runsList.filter((r) => r.status === 'failed').length;
        setStats({
          total_organizations: 0,
          total_projects: projects.length,
          total_test_cases: testCases.length,
          total_runs: runsList.length,
          passed_runs: passedRuns,
          failed_runs: failedRuns,
          recent_runs: runsList,
        });
        setAllRuns(runsList);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return '—';
    return new Date(dateStr).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getRunDuration = (run: TestRun): number | null => {
    if (!run.started_at || !run.completed_at) return null;
    const start = new Date(run.started_at).getTime();
    const end = new Date(run.completed_at).getTime();
    return Math.max(0, (end - start) / 1000);
  };

  const formatDuration = (run: TestRun) => {
    if (run.status === 'running') {
      return (
        <span className="inline-flex items-center gap-1 text-blue-600 font-medium">
          <Clock className="w-3 h-3 animate-spin" /> In progress…
        </span>
      );
    }
    const sec = getRunDuration(run);
    if (sec === null) return '—';
    if (sec < 60) return `${sec.toFixed(1)}s`;
    const mins = Math.floor(sec / 60);
    const remSec = Math.round(sec % 60);
    return `${mins}m ${remSec}s`;
  };

  // Status counts for filter pills
  const statusCounts = useMemo(() => {
    const counts = { all: allRuns.length, passed: 0, failed: 0, running: 0, error: 0 };
    for (const r of allRuns) {
      if (r.status === 'passed') counts.passed++;
      else if (r.status === 'failed') counts.failed++;
      else if (r.status === 'running') counts.running++;
      else if (r.status === 'error') counts.error++;
    }
    return counts;
  }, [allRuns]);

  // Filtered & sorted runs
  const filteredAndSortedRuns = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();

    const filtered = allRuns.filter((run) => {
      // Status filter
      if (statusFilter !== 'all' && run.status !== statusFilter) {
        return false;
      }

      // Search query filter (matches Run UUID, RUN- formatted id, status, or error)
      if (query) {
        const fullId = run.id.toLowerCase();
        const formattedId = `run-${run.id.replace(/-/g, '').slice(0, 8)}`.toLowerCase();
        const status = (run.status || '').toLowerCase();
        const errorMsg = (run.error_message || '').toLowerCase();
        const trigger = (run.triggered_by || '').toLowerCase();

        return (
          fullId.includes(query) ||
          formattedId.includes(query) ||
          status.includes(query) ||
          errorMsg.includes(query) ||
          trigger.includes(query)
        );
      }

      return true;
    });

    // Sorting
    return filtered.sort((a, b) => {
      if (sortBy === 'date_asc') {
        return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
      }
      if (sortBy === 'duration') {
        const durA = getRunDuration(a) ?? -1;
        const durB = getRunDuration(b) ?? -1;
        return durB - durA;
      }
      if (sortBy === 'tests') {
        return (b.total_tests || 0) - (a.total_tests || 0);
      }
      // default: date_desc
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });
  }, [allRuns, statusFilter, searchQuery, sortBy]);

  // Paginated runs
  const paginatedRuns = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredAndSortedRuns.slice(start, start + pageSize);
  }, [filteredAndSortedRuns, currentPage, pageSize]);

  // Reset to page 1 on filter or search changes
  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, statusFilter, sortBy]);

  const passRate =
    stats && stats.total_runs > 0
      ? Math.round((stats.passed_runs / stats.total_runs) * 100)
      : 0;

  return (
    <Layout
      title="Dashboard"
      subtitle="Enterprise test automation overview, reliability metrics, and execution history"
    >
      {loading ? (
        <PageLoader message="Loading dashboard and execution metrics..." />
      ) : error ? (
        <ErrorAlert message={error} onRetry={() => fetchStats(false)} />
      ) : stats ? (
        <div className="space-y-6">
          {/* Header Actions & Quick Nav Bar */}
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-1">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-slate-500">Platform status:</span>
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                Operational
              </span>
            </div>

            <div className="flex items-center gap-2.5">
              <button
                type="button"
                onClick={() => fetchStats(true)}
                disabled={refreshing}
                className="btn-secondary btn-sm"
                title="Refresh metrics and runs"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
                {refreshing ? 'Refreshing…' : 'Refresh'}
              </button>
              <button
                type="button"
                onClick={() => navigate('/test-cases')}
                className="btn-secondary btn-sm"
              >
                <Upload className="w-3.5 h-3.5" />
                Upload CSV
              </button>
              <button
                type="button"
                onClick={() => navigate('/execution')}
                className="btn-primary btn-sm"
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                Run Tests
              </button>
            </div>
          </div>

          {/* Stat Cards Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
            <StatCard
              title="Active Projects"
              value={stats.total_projects}
              icon={FolderOpen}
              iconBg="bg-blue-50"
              iconColor="text-blue-600"
              subtitle="Organized test suites"
              onClick={() => navigate('/projects')}
            />
            <StatCard
              title="Test Cases"
              value={stats.total_test_cases}
              icon={FileText}
              iconBg="bg-purple-50"
              iconColor="text-purple-600"
              subtitle="Natural-language & CSV steps"
              onClick={() => navigate('/test-cases')}
            />
            <StatCard
              title="Passed Runs"
              value={stats.passed_runs}
              icon={CheckCircle2}
              iconBg="bg-emerald-50"
              iconColor="text-emerald-600"
              subtitle={`${passRate}% overall pass rate`}
              onClick={() => {
                setStatusFilter('passed');
                const el = document.getElementById('recent-runs-card');
                el?.scrollIntoView({ behavior: 'smooth' });
              }}
            />
            <StatCard
              title="Failed Runs"
              value={stats.failed_runs}
              icon={XCircle}
              iconBg="bg-rose-50"
              iconColor="text-rose-600"
              subtitle={`${stats.failed_runs} require inspection`}
              onClick={() => {
                setStatusFilter('failed');
                const el = document.getElementById('recent-runs-card');
                el?.scrollIntoView({ behavior: 'smooth' });
              }}
            />
          </div>

          {/* Reliability & Pass Rate Banner */}
          {stats.total_runs > 0 && (
            <div className="card p-5">
              <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mb-3">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center">
                    <TrendingUp className="w-4 h-4" />
                  </div>
                  <div>
                    <h2 className="text-sm font-semibold text-slate-800">Overall Suite Pass Rate</h2>
                    <p className="text-xs text-slate-500">
                      Reliability aggregated across all execution runs
                    </p>
                  </div>
                </div>
                <div className="flex items-baseline gap-2">
                  <span className="text-2xl font-bold text-slate-900">{passRate}%</span>
                  <span className="text-xs text-slate-500">
                    ({stats.passed_runs} passed / {stats.total_runs} total)
                  </span>
                </div>
              </div>

              {/* Multi-segment Progress Bar */}
              <div className="w-full bg-slate-100 rounded-full h-2.5 overflow-hidden flex">
                <div
                  className="bg-emerald-500 h-full transition-all duration-500"
                  style={{ width: `${passRate}%` }}
                  title={`Passed: ${stats.passed_runs} runs`}
                />
                <div
                  className="bg-rose-500 h-full transition-all duration-500"
                  style={{
                    width: `${
                      stats.total_runs > 0
                        ? Math.round((stats.failed_runs / stats.total_runs) * 100)
                        : 0
                    }%`,
                  }}
                  title={`Failed: ${stats.failed_runs} runs`}
                />
              </div>

              <div className="flex items-center justify-between text-xs text-slate-500 mt-2.5">
                <div className="flex items-center gap-4">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-emerald-500" />
                    Passed: <strong className="text-slate-700">{stats.passed_runs}</strong>
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-rose-500" />
                    Failed: <strong className="text-slate-700">{stats.failed_runs}</strong>
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => navigate('/reports')}
                  className="text-primary-600 hover:text-primary-700 font-medium inline-flex items-center gap-1 hover:underline cursor-pointer"
                >
                  Inspect in Reports
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          )}

          {/* Execution Runs Management Section */}
          <div id="recent-runs-card" className="card">
            {/* Card Header & Controls */}
            <div className="p-5 border-b border-slate-100 space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <Layers className="w-4 h-4 text-primary-600" />
                  <h2 className="text-base font-semibold text-slate-800">
                    Execution Runs
                  </h2>
                  <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-slate-100 text-slate-600">
                    {filteredAndSortedRuns.length}
                  </span>
                </div>

                {/* Sort selector */}
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-slate-400 font-medium">Sort by:</span>
                  <select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value as SortField)}
                    className="px-2.5 py-1.5 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-700 focus:outline-none focus:ring-1 focus:ring-primary-500 cursor-pointer"
                  >
                    <option value="date_desc">Newest First</option>
                    <option value="date_asc">Oldest First</option>
                    <option value="duration">Longest Duration</option>
                    <option value="tests">Most Test Cases</option>
                  </select>
                </div>
              </div>

              {/* Search & Filter Toolbar */}
              <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3 pt-1">
                {/* Search Bar */}
                <div className="relative flex-1 max-w-md">
                  <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search by Run ID (e.g. RUN-3F9A...), status, or keyword..."
                    className="input pl-9 pr-8 text-xs py-2"
                  />
                  {searchQuery && (
                    <button
                      type="button"
                      onClick={() => setSearchQuery('')}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 p-0.5"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>

                {/* Status Filter Pills */}
                <div className="flex items-center gap-1.5 overflow-x-auto pb-1 sm:pb-0">
                  <Filter className="w-3.5 h-3.5 text-slate-400 shrink-0 mr-1" />
                  {(
                    [
                      { key: 'all', label: 'All', count: statusCounts.all },
                      { key: 'passed', label: 'Passed', count: statusCounts.passed },
                      { key: 'failed', label: 'Failed', count: statusCounts.failed },
                      { key: 'running', label: 'Running', count: statusCounts.running },
                    ] as const
                  ).map((filter) => {
                    const isActive = statusFilter === filter.key;
                    return (
                      <button
                        key={filter.key}
                        type="button"
                        onClick={() => setStatusFilter(filter.key)}
                        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-colors cursor-pointer shrink-0 ${
                          isActive
                            ? 'bg-primary-600 text-white shadow-2xs'
                            : 'bg-slate-100/80 text-slate-600 hover:bg-slate-200/80 hover:text-slate-800'
                        }`}
                      >
                        <span>{filter.label}</span>
                        <span
                          className={`text-[11px] px-1.5 py-0.2 rounded-full ${
                            isActive
                              ? 'bg-primary-700 text-white'
                              : 'bg-white text-slate-600 border border-slate-200'
                          }`}
                        >
                          {filter.count}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* Table Content */}
            {allRuns.length === 0 ? (
              <EmptyState
                icon={Play}
                title="No test runs executed yet"
                description="Upload test cases from a CSV or write natural-language steps, then execute your test suites."
                action={{
                  label: 'Launch First Execution',
                  onClick: () => navigate('/execution'),
                }}
              />
            ) : filteredAndSortedRuns.length === 0 ? (
              <div className="p-12 text-center">
                <Search className="w-10 h-10 mx-auto text-slate-300 mb-2 stroke-[1.5]" />
                <p className="text-sm font-semibold text-slate-700">No matching runs found</p>
                <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">
                  No execution runs match your current search query "{searchQuery}" or selected
                  status filter.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setSearchQuery('');
                    setStatusFilter('all');
                  }}
                  className="mt-3.5 btn-secondary btn-sm"
                >
                  Reset all filters
                </button>
              </div>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="table-enterprise">
                    <thead>
                      <tr>
                        <th className="table-header-cell w-36">Run ID</th>
                        <th className="table-header-cell w-28">Status</th>
                        <th className="table-header-cell">Results Breakdown</th>
                        <th className="table-header-cell w-28 text-right">Duration</th>
                        <th className="table-header-cell w-36">Started At</th>
                        <th className="table-header-cell w-32 text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {paginatedRuns.map((run: TestRun) => (
                        <tr
                          key={run.id}
                          className="hover:bg-slate-50/80 transition-colors group cursor-pointer"
                          onClick={() => navigate(`/reports?run=${encodeURIComponent(run.id)}`)}
                        >
                          <td className="table-cell font-mono">
                            <RunIdBadge runId={run.id} linkToReport={true} />
                          </td>

                          <td className="table-cell">
                            <StatusBadge status={run.status} size="sm" />
                          </td>

                          <td className="table-cell">
                            <div className="flex flex-wrap items-center gap-1.5 text-xs">
                              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 font-semibold text-[11px] border border-emerald-200/60">
                                ✓ {run.passed_tests}
                              </span>
                              {run.failed_tests > 0 && (
                                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-rose-50 text-rose-700 font-semibold text-[11px] border border-rose-200/60">
                                  ✗ {run.failed_tests}
                                </span>
                              )}
                              <span className="text-slate-400 text-xs font-normal">
                                of {run.total_tests} test cases
                              </span>

                              {run.total_steps !== undefined && run.total_steps > 0 && (
                                <span className="text-slate-400 text-[11px] ml-1 border-l border-slate-200 pl-2">
                                  {run.passed_steps || 0}/{run.total_steps} steps
                                </span>
                              )}
                            </div>
                          </td>

                          <td className="table-cell text-right font-mono text-xs text-slate-600">
                            {formatDuration(run)}
                          </td>

                          <td className="table-cell text-xs text-slate-500 whitespace-nowrap">
                            {formatDate(run.started_at ?? run.created_at)}
                          </td>

                          <td className="table-cell text-right">
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                navigate(`/reports?run=${encodeURIComponent(run.id)}`);
                              }}
                              className="inline-flex items-center gap-1 text-xs font-medium text-primary-600 group-hover:text-primary-700 hover:underline cursor-pointer"
                            >
                              Report
                              <ArrowRight className="w-3.5 h-3.5" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Pagination footer */}
                <Pagination
                  currentPage={currentPage}
                  totalItems={filteredAndSortedRuns.length}
                  pageSize={pageSize}
                  onPageChange={setCurrentPage}
                  pageSizeOptions={[10, 20, 50]}
                  onPageSizeChange={setPageSize}
                />
              </>
            )}
          </div>
        </div>
      ) : null}
    </Layout>
  );
};

export default Dashboard;
