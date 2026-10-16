import React, { useEffect, useState, useCallback } from 'react';
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
} from 'lucide-react';
import { Layout } from '../components/layout/Layout';
import { PageLoader } from '../components/ui/LoadingSpinner';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { EmptyState } from '../components/ui/EmptyState';
import { StatusBadge } from '../components/ui/StatusBadge';
import { AuthenticatedImage, AuthenticatedVideo } from '../components/ui/AuthenticatedMedia';
import { testRunsApi } from '../api/testRuns';
import { apiClient } from '../api/client';
import { TestRun, TestResult, Artifact } from '../types';

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
  };
}

export const Reports: React.FC = () => {
  const [runs, setRuns] = useState<TestRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [report, setReport] = useState<FullRunReport | null>(null);

  const [loadingRuns, setLoadingRuns] = useState(true);
  const [loadingReport, setLoadingReport] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null);

  const loadRuns = useCallback(async () => {
    setLoadingRuns(true);
    setError(null);
    try {
      const data = await testRunsApi.list();
      setRuns(data);
      if (data.length > 0 && !selectedRunId) {
        setSelectedRunId(data[0].id);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load test runs');
    } finally {
      setLoadingRuns(false);
    }
  }, [selectedRunId]);

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

  const selectedResult = report?.results.find((r) => r.id === selectedResultId);

  // Helper for artifact media URL
  const getArtifactUrl = (artifact: Artifact) => {
    const base = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
    return `${base}/api/artifacts/${artifact.id}`;
  };

  const getVideoUrl = (filePath: string) => {
    const base = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
    const videoArt = report?.artifacts?.find((a) => a.artifact_type === 'video');
    if (videoArt) {
      return `${base}/api/artifacts/${videoArt.id}`;
    }
    return `${base}/api/artifacts/file?path=${encodeURIComponent(filePath)}`;
  };

  return (
    <Layout
      title="Reports & Evidence"
      subtitle="Execution history, browser recordings, logs, and failure screenshots"
    >
      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left column: Run history sidebar */}
        <div className="lg:col-span-4 space-y-4">
          <div className="card p-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 mb-3">
              <h3 className="font-semibold text-slate-800 text-sm">
                Execution Runs ({runs.length})
              </h3>
              <button
                onClick={loadRuns}
                className="text-xs text-slate-500 hover:text-slate-800 flex items-center gap-1"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Refresh
              </button>
            </div>

            {loadingRuns ? (
              <PageLoader message="Loading execution history..." />
            ) : runs.length === 0 ? (
              <EmptyState
                icon={BarChart3}
                title="No runs yet"
                description="Execute test cases to generate reports and evidence."
              />
            ) : (
              <div className="space-y-2 max-h-[650px] overflow-y-auto pr-1">
                {runs.map((r) => {
                  const isSelected = r.id === selectedRunId;
                  const dateStr = new Date(r.created_at).toLocaleString();
                  return (
                    <div
                      key={r.id}
                      onClick={() => setSelectedRunId(r.id)}
                      className={`p-3 rounded-lg border text-left transition-all cursor-pointer ${
                        isSelected
                          ? 'border-primary-500 bg-primary-50/50 shadow-xs'
                          : 'border-slate-200 hover:bg-slate-50'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-mono text-xs font-semibold text-slate-800">
                          Run #{r.id.slice(0, 8)}
                        </span>
                        <StatusBadge status={r.status} />
                      </div>
                      <div className="flex items-center justify-between text-xs text-slate-500 mt-2">
                        <span>
                          {r.passed_tests}✓ / {r.failed_tests}✗ of {r.total_tests}
                        </span>
                        <span className="text-[11px]">{dateStr}</span>
                      </div>
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
              <PageLoader message="Loading run report & evidence..." />
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
              {/* Summary Metrics */}
              <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-4">
                <div className="card p-4 text-center">
                  <p className="text-xs text-slate-500 font-medium">Pass Rate</p>
                  <p className="text-2xl font-bold text-slate-800 mt-1">
                    {report.summary?.pass_rate ?? 0}%
                  </p>
                </div>
                <div className="card p-4 text-center">
                  <p className="text-xs text-slate-500 font-medium">Passed</p>
                  <p className="text-2xl font-bold text-emerald-600 mt-1">
                    {report.run.passed_tests}
                  </p>
                </div>
                <div className="card p-4 text-center">
                  <p className="text-xs text-slate-500 font-medium">Failed</p>
                  <p className="text-2xl font-bold text-red-600 mt-1">
                    {report.run.failed_tests}
                  </p>
                </div>
                <div className="card p-4 text-center">
                  <p className="text-xs text-slate-500 font-medium">Errors</p>
                  <p className="text-2xl font-bold text-amber-600 mt-1">
                    {report.summary?.errors ?? 0}
                  </p>
                </div>
                <div className="card p-4 text-center">
                  <p className="text-xs text-slate-500 font-medium">Duration</p>
                  <p className="text-2xl font-bold text-slate-700 mt-1">
                    {report.summary?.duration_seconds
                      ? `${report.summary.duration_seconds.toFixed(1)}s`
                      : '—'}
                  </p>
                </div>
              </div>

              {report.run.error_message && (
                <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800">
                  <strong>Run error:</strong> {report.run.error_message}
                </div>
              )}

              {/* Recorded Browser Video */}
              {report.run.video_path && (
                <div className="card p-5">
                  <div className="flex items-center gap-2 mb-3 text-slate-800 font-semibold text-sm">
                    <Film className="w-4 h-4 text-primary-600" />
                    Browser Session Recording
                  </div>
                  <div className="rounded-lg overflow-hidden bg-black flex justify-center">
                    <AuthenticatedVideo
                      artifactId={report.artifacts.find((a) => a.artifact_type === 'video')?.id}
                      filePath={report.run.video_path}
                      className="max-h-80 w-full"
                    />
                  </div>
                </div>
              )}

              {/* Test Case Results Breakdown */}
              <div className="card p-5">
                <h3 className="font-semibold text-slate-800 text-sm mb-4">
                  Test Case Results & Evidence
                </h3>

                {report.results.length === 0 ? (
                  <p className="text-xs text-slate-400 py-4 text-center">
                    No individual results recorded for this run.
                  </p>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-12 gap-4">
                    {/* Result Selector */}
                    <div className="md:col-span-5 space-y-2 border-r border-slate-100 pr-2">
                      {report.results.map((res) => {
                        const isSelected = res.id === selectedResultId;
                        return (
                          <button
                            key={res.id}
                            type="button"
                            onClick={() => setSelectedResultId(res.id)}
                            className={`w-full p-2.5 rounded-lg text-left text-xs transition-colors flex items-center justify-between ${
                              isSelected
                                ? 'bg-primary-50 text-primary-900 font-medium border border-primary-200'
                                : 'hover:bg-slate-50 text-slate-700 border border-transparent'
                            }`}
                          >
                            <span className="truncate">
                              {res.test_case?.name || `Test Case ${res.test_case_id?.slice(0, 8)}`}
                            </span>
                            <StatusBadge status={res.status} />
                          </button>
                        );
                      })}
                    </div>

                    {/* Result Details / Evidence */}
                    <div className="md:col-span-7 space-y-4">
                      {selectedResult ? (
                        <>
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-semibold text-slate-700 uppercase tracking-wider">
                              Status
                            </span>
                            <StatusBadge status={selectedResult.status} />
                          </div>

                          {selectedResult.error_message && (
                            <div>
                              <p className="text-xs font-medium text-red-600 mb-1">
                                Failure Details
                              </p>
                              <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs font-mono text-red-800">
                                {selectedResult.error_message}
                              </div>
                            </div>
                          )}

                          {/* Failure Screenshot */}
                          {selectedResult.screenshot_path && (
                            <div>
                              <div className="flex items-center gap-1.5 text-xs font-medium text-slate-700 mb-1.5">
                                <Camera className="w-3.5 h-3.5 text-slate-500" />
                                Failure Screenshot
                              </div>
                              <div className="border border-slate-200 rounded-lg overflow-hidden bg-slate-100">
                                <AuthenticatedImage
                                  artifactId={
                                    report.artifacts.find(
                                      (a) => a.result_id === selectedResult.id
                                    )?.id
                                  }
                                  filePath={selectedResult.screenshot_path}
                                  alt="Failure Screenshot"
                                  className="w-full object-contain max-h-72"
                                />
                              </div>
                            </div>
                          )}

                          {/* Execution Logs */}
                          <div>
                            <div className="flex items-center gap-1.5 text-xs font-medium text-slate-700 mb-1.5">
                              <Terminal className="w-3.5 h-3.5 text-slate-500" />
                              Execution Logs
                            </div>
                            <pre className="p-3 bg-slate-900 text-slate-200 text-xs font-mono rounded-lg overflow-x-auto max-h-56">
                              {selectedResult.log_output || 'No log output captured.'}
                            </pre>
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
