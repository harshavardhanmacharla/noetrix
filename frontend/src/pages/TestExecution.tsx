import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  Play,
  RotateCw,
  Clock,
  ExternalLink,
  CheckSquare,
  Square,
  FolderOpen,
  AlertCircle,
} from 'lucide-react';
import { Layout } from '../components/layout/Layout';
import { PageLoader, LoadingSpinner } from '../components/ui/LoadingSpinner';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { EmptyState } from '../components/ui/EmptyState';
import { StatusBadge } from '../components/ui/StatusBadge';
import { projectsApi } from '../api/projects';
import { testCasesApi } from '../api/testCases';
import { testRunsApi } from '../api/testRuns';
import { Project, TestCase, TestRun, TestResult } from '../types';

export const TestExecution: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const [projects, setProjects] = useState<Project[]>([]);
  const initialProjectFromUrl = searchParams.get('project') ?? '';
  const [selectedProjectId, setSelectedProjectId] = useState<string>(initialProjectFromUrl);

  const [testCases, setTestCases] = useState<TestCase[]>([]);
  const [selectedCaseIds, setSelectedCaseIds] = useState<Set<string>>(new Set());

  const [loadingProjects, setLoadingProjects] = useState(true);
  const [loadingCases, setLoadingCases] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Active run state
  const [activeRun, setActiveRun] = useState<TestRun | null>(null);
  const [runResults, setRunResults] = useState<TestResult[]>([]);
  const pollIntervalRef = useRef<number | null>(null);

  // 1. Fetch available projects
  const fetchProjects = useCallback(async () => {
    setLoadingProjects(true);
    setError(null);
    try {
      const data = await projectsApi.list();
      const projectList = Array.isArray(data) ? data : [];
      setProjects(projectList);

      const urlParam = searchParams.get('project');
      if (urlParam && projectList.some((p) => p.id === urlParam)) {
        setSelectedProjectId(urlParam);
      } else if (!selectedProjectId && projectList.length > 0) {
        const defaultId = projectList[0].id;
        setSelectedProjectId(defaultId);
        setSearchParams({ project: defaultId }, { replace: true });
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load projects');
    } finally {
      setLoadingProjects(false);
    }
  }, [searchParams, selectedProjectId, setSearchParams]);

  useEffect(() => {
    fetchProjects();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 2. Synchronize selectedProjectId when URL changes
  useEffect(() => {
    const urlParam = searchParams.get('project');
    if (urlParam && urlParam !== selectedProjectId) {
      setSelectedProjectId(urlParam);
    }
  }, [searchParams, selectedProjectId]);

  // 3. Load test cases whenever selectedProjectId changes
  const loadCases = useCallback(async (projectId?: string) => {
    const idToLoad = projectId ?? selectedProjectId;
    if (!idToLoad) {
      setTestCases([]);
      setSelectedCaseIds(new Set());
      return;
    }
    setLoadingCases(true);
    setError(null);
    try {
      const cases = await testCasesApi.list(idToLoad);
      const caseList = Array.isArray(cases) ? cases : [];
      setTestCases(caseList);
      // Select all by default
      setSelectedCaseIds(new Set(caseList.map((c) => c.id)));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load test cases');
      setTestCases([]);
      setSelectedCaseIds(new Set());
    } finally {
      setLoadingCases(false);
    }
  }, [selectedProjectId]);

  useEffect(() => {
    if (selectedProjectId) {
      loadCases(selectedProjectId);
    } else {
      setTestCases([]);
      setSelectedCaseIds(new Set());
    }
  }, [selectedProjectId, loadCases]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        window.clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  const handleProjectChange = (projectId: string) => {
    setSelectedProjectId(projectId);
    setError(null);
    if (projectId) {
      setSearchParams({ project: projectId });
    } else {
      setSearchParams({});
    }
  };

  const pollRunStatus = useCallback((runId: string) => {
    if (pollIntervalRef.current) {
      window.clearInterval(pollIntervalRef.current);
    }

    pollIntervalRef.current = window.setInterval(async () => {
      try {
        const [updatedRun, results] = await Promise.all([
          testRunsApi.get(runId),
          testRunsApi.getResults(runId).catch(() => []),
        ]);

        setActiveRun(updatedRun);
        setRunResults(Array.isArray(results) ? results : []);

        if (
          updatedRun.status === 'passed' ||
          updatedRun.status === 'failed' ||
          updatedRun.status === 'error'
        ) {
          setExecuting(false);
          if (pollIntervalRef.current) {
            window.clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
          }
        }
      } catch (err: unknown) {
        // Log polling error quietly so active UI isn't destroyed
        console.warn('Test run status poll error:', err);
      }
    }, 2000);
  }, []);

  const handleRunTests = async () => {
    if (!selectedProjectId || selectedCaseIds.size === 0) return;

    setExecuting(true);
    setError(null);
    setActiveRun(null);
    setRunResults([]);

    try {
      const run = await testRunsApi.create({
        project_id: selectedProjectId,
        test_case_ids: Array.from(selectedCaseIds),
      });

      setActiveRun(run);
      pollRunStatus(run.id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to launch test run');
      setExecuting(false);
    }
  };

  const toggleCase = (id: string) => {
    const next = new Set(selectedCaseIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    setSelectedCaseIds(next);
  };

  const selectAll = () => {
    setSelectedCaseIds(new Set(testCases.map((c) => c.id)));
  };

  const clearSelection = () => {
    setSelectedCaseIds(new Set());
  };

  const currentProject = projects.find((p) => p.id === selectedProjectId);

  const retryOperation = () => {
    if (projects.length === 0) {
      fetchProjects();
    } else if (selectedProjectId) {
      loadCases(selectedProjectId);
    }
  };

  return (
    <Layout
      title="Test Execution"
      subtitle="Select test scenarios and execute browser automation via Playwright"
    >
      {error && (
        <div className="mb-6">
          <ErrorAlert
            message={error}
            onRetry={retryOperation}
            onDismiss={() => setError(null)}
          />
        </div>
      )}

      {/* Top Controls Bar */}
      <div className="card p-5 mb-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex flex-1 items-center gap-3">
            <label htmlFor="execution-project-select" className="text-sm font-medium text-slate-700 whitespace-nowrap">
              Project:
            </label>
            {loadingProjects ? (
              <div className="flex items-center gap-2 text-sm text-slate-500 py-1.5 px-3 bg-slate-50 rounded-lg border border-slate-200">
                <LoadingSpinner size="sm" />
                <span>Loading projects...</span>
              </div>
            ) : (
              <select
                id="execution-project-select"
                value={selectedProjectId}
                onChange={(e) => handleProjectChange(e.target.value)}
                className="input max-w-xs font-medium text-slate-800"
                disabled={executing}
              >
                <option value="">Select a project…</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            )}
            {currentProject?.app_url && (
              <span className="text-xs text-slate-500 font-mono hidden md:inline truncate max-w-sm bg-slate-100 px-2.5 py-1 rounded-md">
                Target: {currentProject.app_url}
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={handleRunTests}
              disabled={executing || selectedCaseIds.size === 0 || !selectedProjectId}
              className="btn-primary"
            >
              {executing ? (
                <>
                  <RotateCw className="w-4 h-4 animate-spin" />
                  Running Tests...
                </>
              ) : (
                <>
                  <Play className="w-4 h-4" />
                  Run {selectedCaseIds.size} Selected Test{selectedCaseIds.size === 1 ? '' : 's'}
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Test Case Selection */}
        <div className="lg:col-span-5 space-y-4">
          <div className="card p-5">
            <div className="flex items-center justify-between mb-4 pb-3 border-b border-slate-100">
              <h3 className="font-semibold text-slate-800 text-sm">
                Available Test Cases ({testCases.length})
              </h3>
              {testCases.length > 0 && (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={selectAll}
                    disabled={executing}
                    className="text-xs text-primary-600 hover:text-primary-700 font-medium"
                  >
                    Select All
                  </button>
                  <span className="text-slate-300">|</span>
                  <button
                    type="button"
                    onClick={clearSelection}
                    disabled={executing}
                    className="text-xs text-slate-500 hover:text-slate-700"
                  >
                    Clear
                  </button>
                </div>
              )}
            </div>

            {loadingCases ? (
              <PageLoader message="Loading test cases..." />
            ) : !selectedProjectId ? (
              <EmptyState
                icon={FolderOpen}
                title="No project selected"
                description="Select a project above to view and execute its test cases."
              />
            ) : testCases.length === 0 ? (
              <EmptyState
                icon={AlertCircle}
                title="No test cases found"
                description="Upload test cases using CSV to execute them here."
                action={{
                  label: 'Upload CSV',
                  onClick: () => navigate(`/test-cases?project=${selectedProjectId}`),
                }}
              />
            ) : (
              <div className="space-y-2 max-h-[500px] overflow-y-auto pr-1">
                {testCases.map((tc) => {
                  const isChecked = selectedCaseIds.has(tc.id);
                  const stepCount = tc.steps?.length ?? 0;
                  return (
                    <div
                      key={tc.id}
                      onClick={() => !executing && toggleCase(tc.id)}
                      className={`flex items-start gap-3 p-3 rounded-lg border transition-colors cursor-pointer ${
                        isChecked
                          ? 'border-primary-200 bg-primary-50/40'
                          : 'border-slate-200 hover:bg-slate-50'
                      }`}
                    >
                      <button
                        type="button"
                        aria-label={isChecked ? `Deselect ${tc.name}` : `Select ${tc.name}`}
                        className="mt-0.5 text-primary-600 focus:outline-none"
                      >
                        {isChecked ? (
                          <CheckSquare className="w-4 h-4 text-primary-600" />
                        ) : (
                          <Square className="w-4 h-4 text-slate-400" />
                        )}
                      </button>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between">
                          <p className="font-medium text-sm text-slate-900 truncate">
                            {tc.name}
                          </p>
                          <span className="text-xs text-slate-400 font-mono">
                            {stepCount} {stepCount === 1 ? 'step' : 'steps'}
                          </span>
                        </div>
                        {tc.description && (
                          <p className="text-xs text-slate-500 truncate mt-0.5">
                            {tc.description}
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Live Execution Monitor */}
        <div className="lg:col-span-7 space-y-4">
          <div className="card p-5">
            <div className="flex items-center justify-between mb-4 pb-3 border-b border-slate-100">
              <h3 className="font-semibold text-slate-800 text-sm">Execution Monitor</h3>
              {activeRun && (
                <div className="flex items-center gap-2">
                  <StatusBadge status={activeRun.status} />
                  <button
                    onClick={() => navigate('/reports')}
                    className="btn-secondary !py-1 !px-2.5 text-xs inline-flex items-center gap-1"
                  >
                    Reports <ExternalLink className="w-3 h-3" />
                  </button>
                </div>
              )}
            </div>

            {!activeRun ? (
              <div className="py-12 text-center text-slate-400">
                <Clock className="w-12 h-12 mx-auto mb-3 text-slate-300 stroke-[1.5]" />
                <p className="font-medium text-slate-600 text-sm">Ready to Execute</p>
                <p className="text-xs text-slate-400 max-w-sm mx-auto mt-1">
                  Select the test cases you wish to run, then click "Run Selected Tests".
                  Playwright will launch a headless browser session to execute the actions.
                </p>
              </div>
            ) : (
              <div className="space-y-5">
                {/* Status Header */}
                <div className="bg-slate-50 rounded-lg p-4 border border-slate-200/80">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-center">
                    <div>
                      <p className="text-xs text-slate-500 font-medium">Status</p>
                      <p className="text-sm font-semibold capitalize mt-1">
                        {activeRun.status}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500 font-medium">Total</p>
                      <p className="text-sm font-semibold text-slate-800 mt-1">
                        {activeRun.total_tests}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500 font-medium">Passed</p>
                      <p className="text-sm font-semibold text-emerald-600 mt-1">
                        {activeRun.passed_tests}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500 font-medium">Failed</p>
                      <p className="text-sm font-semibold text-red-600 mt-1">
                        {activeRun.failed_tests}
                      </p>
                    </div>
                  </div>

                  {/* Progress bar */}
                  <div className="mt-4 pt-3 border-t border-slate-200">
                    <div className="w-full bg-slate-200 rounded-full h-2 overflow-hidden flex">
                      <div
                        className="bg-emerald-500 transition-all duration-300"
                        style={{
                          width: `${
                            activeRun.total_tests > 0
                              ? (activeRun.passed_tests / activeRun.total_tests) * 100
                              : 0
                          }%`,
                        }}
                      />
                      <div
                        className="bg-red-500 transition-all duration-300"
                        style={{
                          width: `${
                            activeRun.total_tests > 0
                              ? (activeRun.failed_tests / activeRun.total_tests) * 100
                              : 0
                          }%`,
                        }}
                      />
                    </div>
                  </div>
                </div>

                {/* Error Banner if error status */}
                {activeRun.error_message && (
                  <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">
                    <strong>Run Notice:</strong> {activeRun.error_message}
                  </div>
                )}

                {/* Individual Test Case Results */}
                <div>
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">
                    Step Results
                  </h4>
                  <div className="space-y-2 max-h-[350px] overflow-y-auto">
                    {runResults.length === 0 ? (
                      <div className="py-6 text-center text-xs text-slate-400">
                        {executing ? (
                          <div className="inline-flex items-center gap-2">
                            <RotateCw className="w-4 h-4 animate-spin text-primary-600" />
                            Executing test cases via browser automation...
                          </div>
                        ) : (
                          'Waiting for test execution results...'
                        )}
                      </div>
                    ) : (
                      runResults.map((res) => {
                        const tcName =
                          testCases.find((c) => c.id === res.test_case_id)?.name ??
                          res.test_case_id;
                        return (
                          <div
                            key={res.id}
                            className="p-3 rounded-lg border border-slate-200 bg-white space-y-2"
                          >
                            <div className="flex items-center justify-between">
                              <span className="font-medium text-sm text-slate-900">
                                {tcName}
                              </span>
                              <StatusBadge status={res.status} />
                            </div>
                            {res.error_message && (
                              <p className="text-xs text-red-600 font-mono bg-red-50/60 p-2 rounded">
                                {res.error_message}
                              </p>
                            )}
                            {res.log_output && (
                              <pre className="text-[11px] font-mono text-slate-200 bg-slate-900 p-2.5 rounded overflow-x-auto max-h-32">
                                {res.log_output}
                              </pre>
                            )}
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </Layout>
  );
};

export default TestExecution;
