import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FolderOpen,
  FileText,
  CheckCircle2,
  XCircle,
  TrendingUp,
  Play,
  Upload,
} from 'lucide-react';
import { Layout } from '../components/layout/Layout';
import { StatCard } from '../components/ui/StatCard';
import { StatusBadge } from '../components/ui/StatusBadge';
import { PageLoader } from '../components/ui/LoadingSpinner';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { EmptyState } from '../components/ui/EmptyState';
import { reportsApi } from '../api/reports';
import { projectsApi } from '../api/projects';
import { testCasesApi } from '../api/testCases';
import { testRunsApi } from '../api/testRuns';
import { DashboardStats, TestRun } from '../types';

const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStats = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Try the dashboard endpoint first; fall back to deriving from individual endpoints
      try {
        const data = await reportsApi.getDashboardStats();
        setStats(data);
      } catch {
        // Derive stats from individual endpoints
        const [projects, testCases, runs] = await Promise.all([
          projectsApi.list(),
          testCasesApi.list(),
          testRunsApi.list(),
        ]);
        const passedRuns = runs.filter((r) => r.status === 'passed').length;
        const failedRuns = runs.filter((r) => r.status === 'failed').length;
        const recentRuns = [...runs]
          .sort(
            (a, b) =>
              new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
          )
          .slice(0, 10);
        setStats({
          total_organizations: 0,
          total_projects: projects.length,
          total_test_cases: testCases.length,
          total_runs: runs.length,
          passed_runs: passedRuns,
          failed_runs: failedRuns,
          recent_runs: recentRuns,
        });
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard');
    } finally {
      setLoading(false);
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

  return (
    <Layout title="Dashboard" subtitle="Overview of your test automation platform">
      {loading ? (
        <PageLoader />
      ) : error ? (
        <ErrorAlert message={error} onRetry={fetchStats} />
      ) : stats ? (
        <div className="space-y-6">
          {/* Stat cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
            <StatCard
              title="Total Projects"
              value={stats.total_projects}
              icon={FolderOpen}
              iconBg="bg-blue-50"
              iconColor="text-blue-600"
            />
            <StatCard
              title="Test Cases"
              value={stats.total_test_cases}
              icon={FileText}
              iconBg="bg-purple-50"
              iconColor="text-purple-600"
            />
            <StatCard
              title="Passed Runs"
              value={stats.passed_runs}
              icon={CheckCircle2}
              iconBg="bg-emerald-50"
              iconColor="text-emerald-600"
            />
            <StatCard
              title="Failed Runs"
              value={stats.failed_runs}
              icon={XCircle}
              iconBg="bg-red-50"
              iconColor="text-red-600"
            />
          </div>

          {/* Pass rate summary */}
          {stats.total_runs > 0 && (
            <div className="card p-6">
              <div className="flex items-center gap-2 mb-4">
                <TrendingUp className="w-5 h-5 text-slate-500" />
                <h2 className="text-base font-semibold text-slate-800">Overall Pass Rate</h2>
              </div>
              <div className="flex items-center gap-4">
                <div className="flex-1 bg-slate-100 rounded-full h-3 overflow-hidden">
                  <div
                    className="h-full bg-emerald-500 rounded-full transition-all"
                    style={{
                      width: `${Math.round((stats.passed_runs / stats.total_runs) * 100)}%`,
                    }}
                  />
                </div>
                <span className="text-sm font-semibold text-slate-700 shrink-0">
                  {Math.round((stats.passed_runs / stats.total_runs) * 100)}%
                </span>
              </div>
              <p className="text-xs text-slate-500 mt-2">
                {stats.passed_runs} passed out of {stats.total_runs} total runs
              </p>
            </div>
          )}

          {/* Quick actions */}
          <div className="flex flex-wrap gap-3">
            <button
              onClick={() => navigate('/test-cases')}
              className="btn-primary"
            >
              <Upload className="w-4 h-4" />
              Upload Test Cases
            </button>
            <button
              onClick={() => navigate('/execution')}
              className="btn-secondary"
            >
              <Play className="w-4 h-4" />
              Run Tests
            </button>
          </div>

          {/* Recent runs */}
          <div className="card">
            <div className="px-6 py-4 border-b border-slate-100">
              <h2 className="text-base font-semibold text-slate-800">Recent Runs</h2>
            </div>
            {stats.recent_runs.length === 0 ? (
              <EmptyState
                icon={Play}
                title="No test runs yet"
                description="Run your first test to see results here."
                action={{ label: 'Go to Execution', onClick: () => navigate('/execution') }}
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100">
                      <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                        Run ID
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                        Status
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                        Results
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                        Started
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-50">
                    {stats.recent_runs.map((run: TestRun) => (
                      <tr
                        key={run.id}
                        className="hover:bg-slate-50 cursor-pointer transition-colors"
                        onClick={() => navigate('/reports')}
                      >
                        <td className="px-6 py-4 font-mono text-xs text-slate-600">
                          {run.id.slice(0, 8)}…
                        </td>
                        <td className="px-6 py-4">
                          <StatusBadge status={run.status} />
                        </td>
                        <td className="px-6 py-4">
                          <span className="text-emerald-600 font-medium">
                            {run.passed_tests}✓
                          </span>
                          {' / '}
                          <span className="text-red-500 font-medium">
                            {run.failed_tests}✗
                          </span>
                          {' / '}
                          <span className="text-slate-500">{run.total_tests} total</span>
                        </td>
                        <td className="px-6 py-4 text-slate-500">
                          {formatDate(run.started_at ?? run.created_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      ) : null}
    </Layout>
  );
};

export default Dashboard;
