import React, { useEffect, useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
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
    total_steps?: number;
    passed_steps?: number;
    failed_steps?: number;
    skipped_steps?: number;
    step_pass_rate?: number;
  };
}

export const Reports: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const runIdFromUrl = searchParams.get('run');

  const [runs, setRuns] = useState<TestRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(runIdFromUrl);
  const [report, setReport] = useState<FullRunReport | null>(null);

  const [loadingRuns, setLoadingRuns] = useState(true);
  const [loadingReport, setLoadingReport] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null);
  const [showLogs, setShowLogs] = useState(false);

  const loadRuns = useCallback(async () => {
    setLoadingRuns(true);
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

  const handleSelectRun = (runId: string) => {
    setSelectedRunId(runId);
    setSearchParams({ run: runId });
  };

  const selectedResult = report?.results.find((r) => r.id === selectedResultId);

  const getCategoryBadge = (category?: string | null) => {
    if (!category) return null;
    const map: Record<string, { label: string; bg: string; text: string; border: string }> = {
      missing_element: {
        label: 'Missing Element',
        bg: 'bg-amber-50',
        text: 'text-amber-700',
        border: 'border-amber-200',
      },
      ambiguous_target: {
        label: 'Ambiguous Target',
        bg: 'bg-purple-50',
        text: 'text-purple-700',
        border: 'border-purple-200',
      },
      assertion_failure: {
        label: 'Assertion Failed',
        bg: 'bg-rose-50',
        text: 'text-rose-700',
        border: 'border-rose-200',
      },
      timeout: {
        label: 'Timeout',
        bg: 'bg-orange-50',
        text: 'text-orange-700',
        border: 'border-orange-200',
      },
      parsing_failure: {
        label: 'Syntax / Action Error',
        bg: 'bg-yellow-50',
        text: 'text-yellow-700',
        border: 'border-yellow-200',
      },
      execution_error: {
        label: 'Execution Error',
        bg: 'bg-red-50',
        text: 'text-red-700',
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
        className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium border ${config.bg} ${config.text} ${config.border}`}
      >
        {config.label}
      </span>
    );
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
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 mb-3">
              <h3 className="font-semibold text-slate-800 text-sm">
                Execution Runs ({runs.length})
              </h3>
              <button
                onClick={loadRuns}
                className="text-xs text-slate-500 hover:text-slate-800 flex items-center gap-1 cursor-pointer"
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
                      onClick={() => handleSelectRun(r.id)}
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
                          {r.passed_tests}✓ / {r.failed_tests}✗ of {r.total_tests} cases
                        </span>
                        <span className="text-[11px]">{dateStr}</span>
                      </div>
                      {r.total_steps !== undefined && r.total_steps > 0 && (
                        <div className="mt-1.5 pt-1.5 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-400">
                          <span>
                            Steps: {r.passed_steps || 0} passed / {r.failed_steps || 0} failed
                          </span>
                          {r.skipped_steps ? <span>{r.skipped_steps} skipped</span> : null}
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
              <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
                <div className="card p-3.5 text-center">
                  <p className="text-xs text-slate-500 font-medium">Test Cases</p>
                  <p className="text-xl font-bold text-slate-800 mt-1">
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
                </div>
                <div className="card p-3.5 text-center">
                  <p className="text-xs text-slate-500 font-medium">Failed Steps</p>
                  <p className="text-xl font-bold text-red-600 mt-1">
                    {report.summary?.failed_steps ?? 0}
                  </p>
                </div>
                <div className="card p-3.5 text-center">
                  <p className="text-xs text-slate-500 font-medium">Skipped Steps</p>
                  <p className="text-xl font-bold text-slate-500 mt-1">
                    {report.summary?.skipped_steps ?? 0}
                  </p>
                </div>
                <div className="card p-3.5 text-center">
                  <p className="text-xs text-slate-500 font-medium">Duration</p>
                  <p className="text-xl font-bold text-slate-700 mt-1">
                    {report.summary?.duration_seconds
                      ? `${report.summary.duration_seconds.toFixed(1)}s`
                      : '—'}
                  </p>
                </div>
              </div>

              {report.run.error_message && (
                <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800">
                  <strong>Run notice:</strong> {report.run.error_message}
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
                  Test Case Results & Step Diagnostics
                </h3>

                {report.results.length === 0 ? (
                  <p className="text-xs text-slate-400 py-4 text-center">
                    No individual results recorded for this run.
                  </p>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-12 gap-5">
                    {/* Result Selector */}
                    <div className="md:col-span-4 space-y-2 border-r border-slate-100 pr-3">
                      {report.results.map((res) => {
                        const isSelected = res.id === selectedResultId;
                        return (
                          <button
                            key={res.id}
                            type="button"
                            onClick={() => setSelectedResultId(res.id)}
                            className={`w-full p-2.5 rounded-lg text-left text-xs transition-colors flex items-center justify-between cursor-pointer ${
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
                    <div className="md:col-span-8 space-y-4">
                      {selectedResult ? (
                        <>
                          <div className="flex items-center justify-between pb-2 border-b border-slate-100">
                            <div>
                              <h4 className="font-semibold text-slate-900 text-sm">
                                {selectedResult.test_case?.name || `Test Case #${selectedResult.test_case_id?.slice(0, 8)}`}
                              </h4>
                              {selectedResult.test_case?.description && (
                                <p className="text-xs text-slate-500 mt-0.5">
                                  {selectedResult.test_case.description}
                                </p>
                              )}
                            </div>
                            <StatusBadge status={selectedResult.status} />
                          </div>

                          {/* Failure Summary Banner */}
                          {selectedResult.error_message && (
                            <div className="p-3 bg-red-50 border border-red-200 rounded-lg space-y-1">
                              <p className="text-xs font-semibold text-red-800 flex items-center gap-1.5">
                                <AlertTriangle className="w-4 h-4 text-red-600" />
                                Execution Diagnostic
                              </p>
                              <div className="text-xs font-mono text-red-900 break-words">
                                {selectedResult.error_message}
                              </div>
                            </div>
                          )}

                          {/* Step-by-Step Diagnostics Table */}
                          {selectedResult.steps && selectedResult.steps.length > 0 ? (
                            <div className="space-y-2">
                              <div className="flex items-center justify-between">
                                <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-700 uppercase tracking-wider">
                                  <Layers className="w-3.5 h-3.5 text-primary-600" />
                                  Step Details ({selectedResult.steps.length})
                                </div>
                                {selectedResult.step_summary && (
                                  <div className="flex items-center gap-2 text-xs">
                                    <span className="text-emerald-600 font-medium">
                                      ✓ {selectedResult.step_summary.passed} passed
                                    </span>
                                    {selectedResult.step_summary.failed > 0 && (
                                      <span className="text-red-600 font-medium">
                                        ✗ {selectedResult.step_summary.failed} failed
                                      </span>
                                    )}
                                    {selectedResult.step_summary.skipped > 0 && (
                                      <span className="text-slate-400 font-medium">
                                        ⏸ {selectedResult.step_summary.skipped} skipped
                                      </span>
                                    )}
                                  </div>
                                )}
                              </div>

                              <div className="border border-slate-200 rounded-lg overflow-hidden bg-white shadow-xs">
                                <div className="overflow-x-auto">
                                  <table className="w-full text-left border-collapse text-xs">
                                    <thead className="bg-slate-50 border-b border-slate-200 text-slate-600">
                                      <tr>
                                        <th className="py-2 px-2.5 font-semibold w-10 text-center">#</th>
                                        <th className="py-2 px-2.5 font-semibold w-24">Status</th>
                                        <th className="py-2 px-2.5 font-semibold">Instruction & Action</th>
                                        <th className="py-2 px-2.5 font-semibold w-20 text-right">Duration</th>
                                        <th className="py-2 px-2.5 font-semibold w-36">Category</th>
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
                                              isFailed ? 'bg-red-50/40' : ''
                                            }`}
                                          >
                                            <td className="py-2 px-2.5 text-center font-mono text-slate-500">
                                              {st.step_number}
                                            </td>
                                            <td className="py-2 px-2.5">
                                              <span
                                                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold ${
                                                  isPassed
                                                    ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                                                    : isFailed
                                                    ? 'bg-red-50 text-red-700 border border-red-200'
                                                    : 'bg-slate-100 text-slate-600 border border-slate-200'
                                                }`}
                                              >
                                                {isPassed && <Check className="w-3 h-3 text-emerald-600" />}
                                                {isFailed && <X className="w-3 h-3 text-red-600" />}
                                                {isSkipped && <Minus className="w-3 h-3 text-slate-400" />}
                                                {st.status}
                                              </span>
                                            </td>
                                            <td className="py-2 px-2.5">
                                              <div className="font-medium text-slate-800">
                                                {st.original_instruction || `${st.action} ${st.target || ''}`}
                                              </div>
                                              <div className="flex flex-wrap items-center gap-2 mt-0.5 text-[11px] text-slate-500 font-mono">
                                                <span className="px-1.5 py-0.2 bg-slate-100 rounded text-slate-600">
                                                  [{st.action}]
                                                </span>
                                                {st.target && <span className="truncate max-w-[200px]">target: {st.target}</span>}
                                                {st.value && <span className="truncate max-w-[150px]">value: {st.value}</span>}
                                              </div>
                                              {isFailed && st.failure_reason && (
                                                <div className="mt-1.5 p-2 bg-red-50/80 border border-red-200 rounded text-[11px] font-mono text-red-900 break-words">
                                                  {st.failure_reason}
                                                </div>
                                              )}
                                              {st.verification_result && st.verification_result.type && (
                                                <div className="mt-1 text-[11px] text-slate-500">
                                                  Verified: <span className="font-mono">{st.verification_result.expected}</span>
                                                </div>
                                              )}
                                            </td>
                                            <td className="py-2 px-2.5 text-right font-mono text-slate-600">
                                              {st.duration_ms !== null && st.duration_ms !== undefined
                                                ? `${st.duration_ms.toFixed(1)} ms`
                                                : '—'}
                                            </td>
                                            <td className="py-2 px-2.5">
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
                              <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5">
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
                                  className="w-full object-contain max-h-80"
                                />
                              </div>
                            </div>
                          )}

                          {/* Collapsible Execution Logs */}
                          <div>
                            <button
                              type="button"
                              onClick={() => setShowLogs(!showLogs)}
                              className="flex items-center gap-1.5 text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5 cursor-pointer hover:text-slate-900"
                            >
                              <Terminal className="w-3.5 h-3.5 text-slate-500" />
                              Technical Execution Logs
                              <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showLogs ? 'rotate-180' : ''}`} />
                            </button>
                            {showLogs && (
                              <pre className="p-3 bg-slate-900 text-slate-200 text-xs font-mono rounded-lg overflow-x-auto max-h-56">
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
