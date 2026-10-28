import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  Play,
  RotateCw,
  Plus,
  Trash2,
  Copy,
  Eye,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ExternalLink,
  Table,
  HelpCircle,
  ShieldAlert,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { Layout } from '../components/layout/Layout';
import { PageLoader, LoadingSpinner } from '../components/ui/LoadingSpinner';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { EmptyState } from '../components/ui/EmptyState';
import { StatusBadge } from '../components/ui/StatusBadge';
import { RunIdBadge } from '../components/ui/RunIdBadge';
import { projectsApi } from '../api/projects';
import { testCasesApi } from '../api/testCases';
import { testRunsApi } from '../api/testRuns';
import { dataDrivenApi } from '../api/dataDriven';
import {
  Project,
  TestCase,
  TestRun,
  TestResult,
  TestCasePlaceholdersResponse,
  DataDrivenPreviewResponse,
} from '../types';

export const DataDrivenExecution: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  // Project and TestCase Selection
  const [projects, setProjects] = useState<Project[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const initialProject = searchParams.get('project') ?? '';
  const [selectedProjectId, setSelectedProjectId] = useState<string>(initialProject);

  const [testCases, setTestCases] = useState<TestCase[]>([]);
  const [loadingCases, setLoadingCases] = useState(false);
  const initialCase = searchParams.get('case') ?? '';
  const [selectedCaseId, setSelectedCaseId] = useState<string>(initialCase);

  // Placeholders Discovery
  const [placeholdersMeta, setPlaceholdersMeta] = useState<TestCasePlaceholdersResponse | null>(null);
  const [loadingPlaceholders, setLoadingPlaceholders] = useState(false);

  // Table Data Records (list of row objects mapping placeholder -> value)
  const [records, setRecords] = useState<Record<string, string>[]>([]);
  const [stopOnFailure, setStopOnFailure] = useState(true);

  // Validation State
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [hasValidated, setHasValidated] = useState(false);

  // Preview Modal
  const [previewData, setPreviewData] = useState<DataDrivenPreviewResponse | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  // Confirmation Modal
  const [showConfirmModal, setShowConfirmModal] = useState(false);

  // Execution State
  const [executing, setExecuting] = useState(false);
  const [startingRun, setStartingRun] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeRun, setActiveRun] = useState<TestRun | null>(null);
  const [runResults, setRunResults] = useState<TestResult[]>([]);
  const [expandedResultId, setExpandedResultId] = useState<string | null>(null);
  const pollIntervalRef = useRef<number | null>(null);

  // 1. Fetch available projects
  const fetchProjects = useCallback(async () => {
    setLoadingProjects(true);
    setError(null);
    try {
      const data = await projectsApi.list();
      const list = Array.isArray(data) ? data : [];
      setProjects(list);

      const urlParam = searchParams.get('project');
      if (urlParam && list.some((p) => p.id === urlParam)) {
        setSelectedProjectId(urlParam);
      } else if (!selectedProjectId && list.length > 0) {
        const defId = list[0].id;
        setSelectedProjectId(defId);
        setSearchParams({ project: defId }, { replace: true });
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

  // 2. Load test cases when project changes
  const loadCases = useCallback(async (projectId: string) => {
    if (!projectId) {
      setTestCases([]);
      setSelectedCaseId('');
      setPlaceholdersMeta(null);
      setRecords([]);
      return;
    }
    setLoadingCases(true);
    setError(null);
    try {
      const cases = await testCasesApi.list(projectId);
      const caseList = Array.isArray(cases) ? cases : [];
      setTestCases(caseList);

      const urlCase = searchParams.get('case');
      if (urlCase && caseList.some((c) => c.id === urlCase)) {
        setSelectedCaseId(urlCase);
      } else if (caseList.length > 0) {
        setSelectedCaseId(caseList[0].id);
      } else {
        setSelectedCaseId('');
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load test cases');
      setTestCases([]);
      setSelectedCaseId('');
    } finally {
      setLoadingCases(false);
    }
  }, [searchParams]);

  useEffect(() => {
    if (selectedProjectId) {
      loadCases(selectedProjectId);
    }
  }, [selectedProjectId, loadCases]);

  // 3. Inspect placeholders when selectedCaseId changes
  useEffect(() => {
    if (!selectedCaseId) {
      setPlaceholdersMeta(null);
      setRecords([]);
      setValidationErrors([]);
      return;
    }

    let active = true;
    setLoadingPlaceholders(true);
    dataDrivenApi
      .getPlaceholders(selectedCaseId)
      .then((meta) => {
        if (!active) return;
        setPlaceholdersMeta(meta);

        // Initialize 1 default row with detected placeholders if not already set
        if (meta.has_placeholders && meta.placeholders.length > 0) {
          const initialRow: Record<string, string> = {};
          meta.placeholders.forEach((ph) => {
            initialRow[ph] = '';
          });
          setRecords([initialRow]);
        } else {
          setRecords([]);
        }
        setValidationErrors([]);
        setHasValidated(false);
      })
      .catch((err) => {
        if (!active) return;
        console.error('Failed to load placeholders:', err);
        setPlaceholdersMeta(null);
        setRecords([]);
      })
      .finally(() => {
        if (active) setLoadingPlaceholders(false);
      });

    return () => {
      active = false;
    };
  }, [selectedCaseId, selectedProjectId]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        window.clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  // Record management helpers
  const handleCellChange = (rowIndex: number, field: string, value: string) => {
    setRecords((prev) => {
      const copy = [...prev];
      copy[rowIndex] = { ...copy[rowIndex], [field]: value };
      return copy;
    });
    if (hasValidated) {
      // Re-validate locally
      validateLocalRecords();
    }
  };

  const handleAddRow = () => {
    if (!placeholdersMeta || !placeholdersMeta.placeholders) return;
    const newRow: Record<string, string> = {};
    placeholdersMeta.placeholders.forEach((ph) => {
      newRow[ph] = '';
    });
    setRecords((prev) => [...prev, newRow]);
  };

  const handleDuplicateRow = (rowIndex: number) => {
    setRecords((prev) => {
      const copy = [...prev];
      const target = { ...copy[rowIndex] };
      copy.splice(rowIndex + 1, 0, target);
      return copy;
    });
  };

  const handleDeleteRow = (rowIndex: number) => {
    setRecords((prev) => {
      if (prev.length <= 1) return prev;
      return prev.filter((_, idx) => idx !== rowIndex);
    });
  };

  const validateLocalRecords = (): boolean => {
    if (!placeholdersMeta || !placeholdersMeta.has_placeholders) return false;
    const errs: string[] = [];

    if (records.length === 0) {
      errs.push('At least one data record row is required.');
    }

    records.forEach((row, rowIdx) => {
      placeholdersMeta.placeholders.forEach((ph) => {
        const val = row[ph];
        if (val === undefined || val === null || val.trim() === '') {
          errs.push(`Record #${rowIdx + 1}: missing value for field '{{${ph}}}'.`);
        }
      });
    });

    setValidationErrors(errs);
    setHasValidated(true);
    return errs.length === 0;
  };

  // Preview record substitution
  const handlePreviewRecord = async (rowIndex: number) => {
    if (!selectedCaseId || !records[rowIndex]) return;
    setLoadingPreview(true);
    setPreviewError(null);
    setPreviewData(null);
    try {
      const res = await dataDrivenApi.previewData(selectedCaseId, records[rowIndex]);
      setPreviewData(res);
    } catch (err: unknown) {
      setPreviewError(err instanceof Error ? err.message : 'Failed to preview substituted steps');
    } finally {
      setLoadingPreview(false);
    }
  };

  // Status Polling for active run
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
      } catch (pollErr: unknown) {
        console.warn('Data-driven run status poll error:', pollErr);
      }
    }, 2000);
  }, []);

  // Execution Initiation with Safety Lock
  const handleStartExecution = async () => {
    if (!selectedProjectId || !selectedCaseId || records.length === 0) return;
    if (startingRun || executing) return; // double-start guard

    const isValid = validateLocalRecords();
    if (!isValid) {
      setShowConfirmModal(false);
      return;
    }

    setStartingRun(true);
    setError(null);
    setShowConfirmModal(false);
    setActiveRun(null);
    setRunResults([]);

    try {
      const run = await dataDrivenApi.startRun(selectedProjectId, {
        test_case_id: selectedCaseId,
        records,
        stop_on_failure: stopOnFailure,
      });

      setExecuting(true);
      setActiveRun(run);
      pollRunStatus(run.id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to launch data-driven test run');
      setExecuting(false);
    } finally {
      setStartingRun(false);
    }
  };

  const selectedProject = projects.find((p) => p.id === selectedProjectId);
  const selectedTestCase = testCases.find((tc) => tc.id === selectedCaseId);

  return (
    <Layout title="Data-Driven Testing" subtitle="Execute test scenarios repeatedly with different data records">
      <div className="space-y-6 max-w-7xl mx-auto pb-12">
        {/* Header */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 border-b border-slate-200 pb-5">
          <div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-2.5">
              <Table className="w-6 h-6 text-primary-600" />
              <span>Data-Driven Test Execution</span>
            </h1>
            <p className="text-sm text-slate-500 mt-1">
              Enter test data directly in the UI and execute an existing saved test case multiple times with distinct records.
            </p>
          </div>

          {activeRun && (
            <button
              onClick={() => {
                setActiveRun(null);
                setRunResults([]);
                setExecuting(false);
              }}
              className="btn-secondary flex items-center gap-1.5 text-xs"
            >
              <RotateCw className="w-3.5 h-3.5 text-slate-500" />
              <span>Configure New Run</span>
            </button>
          )}
        </div>

        {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

        {/* Section 1: Project & Test Case Selection Controls */}
        <div className="card p-5 bg-white border border-slate-200 shadow-sm space-y-4">
          <h2 className="text-sm font-bold uppercase tracking-wider text-slate-700">
            1. Select Test Scenario
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label htmlFor="select-project" className="block text-xs font-semibold text-slate-600 mb-1">
                Project *
              </label>
              <select
                id="select-project"
                value={selectedProjectId}
                disabled={loadingProjects || executing}
                onChange={(e) => {
                  const pid = e.target.value;
                  setSelectedProjectId(pid);
                  setSearchParams({ project: pid });
                }}
                className="input w-full text-sm font-medium"
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} {p.app_url ? `(${p.app_url})` : ''}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="select-test-case" className="block text-xs font-semibold text-slate-600 mb-1">
                Target Test Case *
              </label>
              <select
                id="select-test-case"
                value={selectedCaseId}
                disabled={loadingCases || testCases.length === 0 || executing}
                onChange={(e) => {
                  const cid = e.target.value;
                  setSelectedCaseId(cid);
                  setSearchParams({ project: selectedProjectId, case: cid });
                }}
                className="input w-full text-sm font-medium"
              >
                {testCases.map((tc) => (
                  <option key={tc.id} value={tc.id}>
                    {tc.name} ({tc.steps?.length ?? 0} steps)
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {/* Section 2: Placeholder Inspection & Data Entry Table */}
        {loadingPlaceholders ? (
          <div className="card p-10 flex flex-col items-center justify-center text-slate-500 space-y-3">
            <LoadingSpinner size="lg" />
            <p className="text-sm font-medium">Inspecting test case placeholders…</p>
          </div>
        ) : placeholdersMeta && !placeholdersMeta.has_placeholders ? (
          /* Case A: No remaining data columns */
          (placeholdersMeta.all_placeholders?.length ?? 0) > 0 ? (
            /* Subcase A1: All detected placeholders are configured in Project Variables */
            <div className="card p-8 border-blue-200 bg-blue-50/70 rounded-xl space-y-4">
              <div className="flex items-start gap-3">
                <CheckCircle2 className="w-6 h-6 text-blue-600 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <h3 className="text-base font-bold text-blue-900">
                    All Placeholders are Configured in Project Test Variables
                  </h3>
                  <p className="text-sm text-blue-800 leading-relaxed">
                    All detected placeholder variables in <strong className="font-semibold break-words">{placeholdersMeta.test_case_name}</strong> are already defined in Project Test Variables for this project:
                  </p>
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {placeholdersMeta.all_placeholders?.map((ph) => (
                      <span
                        key={ph}
                        className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-medium bg-blue-100 text-blue-800 border border-blue-200"
                      >
                        {`{{${ph}}}`}
                      </span>
                    ))}
                  </div>
                  <p className="text-xs text-blue-700 pt-2 leading-relaxed">
                    These will be resolved automatically from Project Settings during execution. Data-driven testing requires at least one custom record-specific variable (e.g. <code className="font-mono bg-blue-100 px-1 py-0.5 rounded">{'{{first_name}}'}</code>, <code className="font-mono bg-blue-100 px-1 py-0.5 rounded">{'{{last_name}}'}</code>) to run across multiple data records.
                  </p>
                </div>
              </div>
            </div>
          ) : (
            /* Subcase A2: Selected test case has NO placeholders at all */
            <div className="card p-8 border-amber-200 bg-amber-50/70 rounded-xl space-y-4">
              <div className="flex items-start gap-3">
                <AlertTriangle className="w-6 h-6 text-amber-600 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <h3 className="text-base font-bold text-amber-900">
                    Selected Test Case Does Not Support Placeholders
                  </h3>
                  <p className="text-sm text-amber-800 leading-relaxed">
                    Test case <strong className="font-semibold break-words">{placeholdersMeta.test_case_name}</strong> currently uses static values in all its steps. Data-driven execution requires at least one placeholder variable to map UI data against.
                  </p>
                </div>
              </div>

              <div className="bg-white/80 p-4 rounded-lg border border-amber-200 text-xs text-slate-700 space-y-2">
                <span className="font-bold text-slate-800 flex items-center gap-1.5">
                  <HelpCircle className="w-4 h-4 text-primary-600" />
                  How to enable data-driven testing for this test case:
                </span>
                <p>
                  In your CSV file or Natural Language instructions, use double curly-braces for fields you want to customize per record:
                </p>
                <div className="font-mono bg-slate-900 text-slate-100 p-2.5 rounded text-[11px] leading-relaxed">
                  open https://oracle.example.com/hcmUI<br />
                  fill "Legal Employer field" with <span className="text-emerald-400">{'{{legal_employer}}'}</span><br />
                  fill "First Name" with <span className="text-emerald-400">{'{{first_name}}'}</span><br />
                  fill "Last Name" with <span className="text-emerald-400">{'{{last_name}}'}</span><br />
                  fill "Work Email" with <span className="text-emerald-400">{'{{email}}'}</span><br />
                  click "Next"
                </div>
                <p className="text-slate-500 pt-1">
                  You can edit your test case in the <strong className="text-slate-700">Test Cases</strong> tab and re-upload with placeholders.
                </p>
              </div>
            </div>
          )
        ) : placeholdersMeta && placeholdersMeta.has_placeholders ? (
          /* Case B: Test case has detected placeholders -> Table Editor */
          <div className="card p-6 bg-white border border-slate-200 shadow-sm space-y-6">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-slate-100 pb-4">
              <div>
                <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
                  <span>2. Test Data Records ({records.length})</span>
                </h2>
                <div className="flex flex-wrap items-center gap-3 mt-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-xs text-slate-600 font-bold mr-1">Data Columns:</span>
                    {placeholdersMeta.placeholders.map((ph) => (
                      <span
                        key={ph}
                        className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold bg-primary-50 text-primary-700 border border-primary-200"
                      >
                        {`{{${ph}}}`}
                      </span>
                    ))}
                  </div>

                  {(placeholdersMeta.project_variables?.length ?? 0) > 0 && (
                    <div className="flex flex-wrap items-center gap-1.5 pl-2 border-l border-slate-200">
                      <span className="text-xs text-slate-500 font-medium mr-1">
                        Auto-Resolved Project Variables:
                      </span>
                      {placeholdersMeta.project_variables?.map((pv) => (
                        <span
                          key={pv}
                          className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-mono bg-slate-100 text-slate-600 border border-slate-200"
                          title="Configured at project level — resolved automatically at runtime"
                        >
                          {`{{${pv}}}`}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2 self-end sm:self-auto">
                <button
                  type="button"
                  onClick={handleAddRow}
                  disabled={executing}
                  className="btn-secondary text-xs flex items-center gap-1.5 py-1.5 px-3"
                >
                  <Plus className="w-3.5 h-3.5 text-primary-600" />
                  <span>Add Record Row</span>
                </button>
              </div>
            </div>

            {/* Validation Alerts */}
            {hasValidated && validationErrors.length > 0 && (
              <div className="p-4 rounded-xl border border-red-200 bg-red-50/80 space-y-2">
                <div className="flex items-center gap-2 text-red-800 font-bold text-xs">
                  <XCircle className="w-4 h-4 text-red-600 shrink-0" />
                  <span>Validation Failed — Please complete all required fields before running:</span>
                </div>
                <ul className="list-disc list-inside text-xs text-red-700 space-y-0.5 pl-1 font-mono">
                  {validationErrors.slice(0, 5).map((err, i) => (
                    <li key={i}>{err}</li>
                  ))}
                  {validationErrors.length > 5 && (
                    <li className="font-sans text-red-600 italic">
                      + {validationErrors.length - 5} more empty fields
                    </li>
                  )}
                </ul>
              </div>
            )}

            {/* Table of Records */}
            <div className="overflow-x-auto border border-slate-200 rounded-xl">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-200 text-slate-700 font-semibold uppercase tracking-wider">
                    <th className="py-3 px-3.5 w-16 text-center">Row</th>
                    {placeholdersMeta.placeholders.map((ph) => (
                      <th key={ph} className="py-3 px-3.5 font-mono text-primary-800">
                        {ph}
                        <span className="text-red-500 ml-0.5">*</span>
                      </th>
                    ))}
                    <th className="py-3 px-3.5 w-28 text-center">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {records.map((row, rowIdx) => {
                    return (
                      <tr key={rowIdx} className="hover:bg-slate-50/60 transition-colors">
                        <td className="py-2.5 px-3 text-center font-bold text-slate-400 font-mono text-xs">
                          #{rowIdx + 1}
                        </td>
                        {placeholdersMeta.placeholders.map((ph) => {
                          const val = row[ph] ?? '';
                          const isInvalid = hasValidated && val.trim() === '';
                          return (
                            <td key={ph} className="py-2 px-3">
                              <input
                                type="text"
                                value={val}
                                disabled={executing}
                                placeholder={`Enter ${ph}`}
                                onChange={(e) => handleCellChange(rowIdx, ph, e.target.value)}
                                className={`input w-full text-xs font-medium py-1.5 px-2.5 ${
                                  isInvalid
                                    ? 'border-red-400 focus:border-red-500 bg-red-50/30'
                                    : 'border-slate-300'
                                }`}
                              />
                            </td>
                          );
                        })}
                        <td className="py-2 px-3 text-center">
                          <div className="flex items-center justify-center gap-1.5">
                            <button
                              type="button"
                              onClick={() => handlePreviewRecord(rowIdx)}
                              title="Preview substituted steps for this record"
                              className="p-1.5 text-slate-500 hover:text-primary-600 hover:bg-slate-100 rounded transition-colors"
                            >
                              <Eye className="w-3.5 h-3.5" />
                            </button>
                            <button
                              type="button"
                              onClick={() => handleDuplicateRow(rowIdx)}
                              disabled={executing}
                              title="Duplicate row"
                              className="p-1.5 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded transition-colors"
                            >
                              <Copy className="w-3.5 h-3.5" />
                            </button>
                            <button
                              type="button"
                              onClick={() => handleDeleteRow(rowIdx)}
                              disabled={executing || records.length <= 1}
                              title="Delete row"
                              className={`p-1.5 rounded transition-colors ${
                                records.length <= 1
                                  ? 'text-slate-300 cursor-not-allowed'
                                  : 'text-slate-400 hover:text-red-600 hover:bg-red-50'
                              }`}
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Bottom Actions Bar */}
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pt-4 border-t border-slate-100">
              <label className="flex items-center gap-2 cursor-pointer text-xs text-slate-700 select-none">
                <input
                  type="checkbox"
                  checked={stopOnFailure}
                  disabled={executing}
                  onChange={(e) => setStopOnFailure(e.target.checked)}
                  className="rounded border-slate-300 text-primary-600 focus:ring-primary-500"
                />
                <span className="font-semibold">Halt on failure</span>
                <span className="text-slate-400 font-normal">
                  (prevents duplicate creations if a record submission fails)
                </span>
              </label>

              <button
                type="button"
                disabled={executing || startingRun || records.length === 0}
                onClick={() => {
                  const valid = validateLocalRecords();
                  if (valid) {
                    setShowConfirmModal(true);
                  }
                }}
                className="btn-primary flex items-center gap-2 shadow-sm font-semibold px-5 py-2.5 text-sm"
              >
                {startingRun ? (
                  <LoadingSpinner size="sm" />
                ) : (
                  <Play className="w-4 h-4 fill-white" />
                )}
                <span>
                  {startingRun
                    ? 'Starting Execution…'
                    : `Execute with ${records.length} Record${records.length > 1 ? 's' : ''}`}
                </span>
              </button>
            </div>
          </div>
        ) : null}

        {/* Section 3: Live Execution Tracker & Record Outcomes */}
        {activeRun && (
          <div className="card p-6 bg-white border border-slate-200 shadow-sm space-y-6">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 border-b border-slate-200 pb-4">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
                    Execution Run
                  </span>
                  <RunIdBadge runId={activeRun.id} />
                </div>
                <h2 className="text-lg font-bold text-slate-900 mt-0.5 flex items-center gap-2.5">
                  <span>Data-Driven Run Progress</span>
                  <StatusBadge status={activeRun.status} />
                </h2>
              </div>

              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => navigate(`/reports?run=${activeRun.id}`)}
                  className="btn-secondary flex items-center gap-1.5 text-xs font-semibold py-2 px-3"
                >
                  <ExternalLink className="w-3.5 h-3.5 text-primary-600" />
                  <span>Open Full Execution Report</span>
                </button>
              </div>
            </div>

            {/* Run Metrics Bar */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 p-4 bg-slate-50 rounded-xl border border-slate-200">
              <div>
                <span className="text-xs text-slate-500 block font-medium">Total Records</span>
                <span className="text-xl font-bold text-slate-800 font-mono">
                  {activeRun.total_tests}
                </span>
              </div>
              <div>
                <span className="text-xs text-emerald-600 block font-medium">Passed</span>
                <span className="text-xl font-bold text-emerald-700 font-mono">
                  {activeRun.passed_tests}
                </span>
              </div>
              <div>
                <span className="text-xs text-red-600 block font-medium">Failed</span>
                <span className="text-xl font-bold text-red-700 font-mono">
                  {activeRun.failed_tests}
                </span>
              </div>
              <div>
                <span className="text-xs text-slate-500 block font-medium">Status</span>
                <span className="text-sm font-bold capitalize text-slate-800 mt-1 block">
                  {activeRun.status === 'running' ? 'In Progress…' : activeRun.status}
                </span>
              </div>
            </div>

            {/* Per-Record Results Table */}
            <div className="space-y-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-700">
                Individual Record Outcomes
              </h3>

              {runResults.length === 0 && executing ? (
                <div className="p-6 text-center text-slate-500 text-xs">
                  <LoadingSpinner size="md" className="mx-auto mb-2" />
                  Executing first record through browser automation…
                </div>
              ) : (
                <div className="space-y-2">
                  {runResults.map((result, resIdx) => {
                    const isExpanded = expandedResultId === result.id;
                    const logSnippet = (result.log_output || '').split('\n')[0] || '';
                    return (
                      <div
                        key={result.id}
                        className={`border rounded-xl p-4 transition-all ${
                          result.status === 'passed'
                            ? 'border-emerald-200 bg-emerald-50/40'
                            : result.status === 'failed' || result.status === 'error'
                            ? 'border-red-200 bg-red-50/40'
                            : 'border-slate-200 bg-slate-50/40'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex items-center gap-3 min-w-0">
                            <span className="font-mono font-bold text-xs text-slate-600">
                              Record #{resIdx + 1}
                            </span>
                            <StatusBadge status={result.status} />
                            {logSnippet && (
                              <span className="text-xs text-slate-600 truncate font-mono hidden md:inline">
                                {logSnippet}
                              </span>
                            )}
                          </div>

                          <div className="flex items-center gap-3 shrink-0">
                            {result.error_message && (
                              <span className="text-xs text-red-700 font-medium max-w-xs truncate hidden lg:inline">
                                {result.error_message}
                              </span>
                            )}
                            <button
                              type="button"
                              onClick={() =>
                                setExpandedResultId(isExpanded ? null : result.id)
                              }
                              className="text-xs font-semibold text-primary-700 hover:text-primary-800 flex items-center gap-1"
                            >
                              <span>{isExpanded ? 'Hide Details' : 'View Steps & Logs'}</span>
                              {isExpanded ? (
                                <ChevronUp className="w-3.5 h-3.5" />
                              ) : (
                                <ChevronDown className="w-3.5 h-3.5" />
                              )}
                            </button>
                          </div>
                        </div>

                        {/* Expanded details */}
                        {isExpanded && (
                          <div className="mt-4 pt-4 border-t border-slate-200/60 space-y-3 text-xs">
                            {result.error_message && (
                              <div className="p-3 bg-red-100/70 border border-red-200 rounded-lg text-red-800 font-mono text-[11px]">
                                {result.error_message}
                              </div>
                            )}

                            {result.log_output && (
                              <div>
                                <span className="font-bold text-slate-700 block mb-1">
                                  Execution Logs:
                                </span>
                                <pre className="bg-slate-900 text-slate-200 p-3 rounded-lg text-[11px] font-mono overflow-x-auto max-h-48 leading-relaxed">
                                  {result.log_output}
                                </pre>
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

        {/* Modal 1: Step Substitution Preview Dialog */}
        {previewData && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150">
              <div className="p-5 border-b border-slate-200 flex items-center justify-between bg-slate-50">
                <div className="flex items-center gap-2">
                  <Eye className="w-5 h-5 text-primary-600" />
                  <h3 className="font-bold text-base text-slate-900">
                    Substituted Test Steps Preview
                  </h3>
                </div>
                <button
                  type="button"
                  onClick={() => setPreviewData(null)}
                  className="text-slate-400 hover:text-slate-600 font-bold p-1 text-lg leading-none"
                >
                  ×
                </button>
              </div>

              <div className="p-5 overflow-y-auto space-y-4">
                <div className="bg-slate-50 p-3 rounded-lg border border-slate-200 text-xs">
                  <span className="font-bold text-slate-700 block mb-1">Record Values Applied:</span>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(previewData.record).map(([k, v]) => (
                      <span key={k} className="font-mono bg-white px-2 py-0.5 rounded border border-slate-200">
                        <strong className="text-slate-600">{k}:</strong> {v}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="border border-slate-200 rounded-xl overflow-hidden">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="bg-slate-100 text-slate-700 font-semibold border-b border-slate-200">
                        <th className="py-2.5 px-3 w-12 text-center">Step</th>
                        <th className="py-2.5 px-3 w-24">Action</th>
                        <th className="py-2.5 px-3">Target</th>
                        <th className="py-2.5 px-3">Substituted Value</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 font-mono text-[11px]">
                      {previewData.steps.map((st) => (
                        <tr key={st.step_number} className="hover:bg-slate-50">
                          <td className="py-2 px-3 text-center text-slate-400">{st.step_number}</td>
                          <td className="py-2 px-3 font-semibold text-primary-700">{st.action}</td>
                          <td className="py-2 px-3 text-slate-600">{st.target || '—'}</td>
                          <td className="py-2 px-3 text-slate-900 font-bold">
                            {st.value || <span className="text-slate-300 font-normal">—</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="p-4 border-t border-slate-200 flex justify-end bg-slate-50">
                <button
                  type="button"
                  onClick={() => setPreviewData(null)}
                  className="btn-secondary text-xs px-4"
                >
                  Close Preview
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Modal 2: Explicit Safety Confirmation Dialog */}
        {showConfirmModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6 space-y-4 animate-in fade-in zoom-in-95 duration-150">
              <div className="w-12 h-12 bg-amber-100 text-amber-600 rounded-full flex items-center justify-center mx-auto">
                <ShieldAlert className="w-6 h-6" />
              </div>

              <div className="text-center space-y-2">
                <h3 className="text-lg font-bold text-slate-900">
                  Confirm Data-Driven Execution
                </h3>
                <p className="text-xs text-slate-500 leading-relaxed">
                  You are about to execute{' '}
                  <strong className="text-slate-900 font-semibold">{records.length} record(s)</strong>{' '}
                  against{' '}
                  <strong className="text-slate-900 font-semibold">{selectedProject?.name}</strong>{' '}
                  {selectedProject?.app_url ? `(${selectedProject.app_url})` : ''}.
                </p>
              </div>

              <div className="p-3 bg-amber-50 rounded-xl border border-amber-200 text-xs text-amber-900 space-y-1 text-left">
                <span className="font-bold flex items-center gap-1.5 text-amber-950">
                  <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
                  Live Workflow Notice:
                </span>
                <p className="text-[11px] leading-relaxed text-amber-800">
                  This execution interacts with real browser forms and may create or modify actual records in your application (e.g. Oracle Fusion).
                </p>
              </div>

              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  type="button"
                  disabled={startingRun}
                  onClick={() => setShowConfirmModal(false)}
                  className="btn-secondary text-xs px-4 py-2"
                >
                  Cancel
                </button>

                <button
                  type="button"
                  disabled={startingRun}
                  onClick={handleStartExecution}
                  className="btn-primary text-xs px-4 py-2 font-bold flex items-center gap-1.5 shadow-sm"
                >
                  {startingRun ? <LoadingSpinner size="sm" /> : <Play className="w-3.5 h-3.5 fill-white" />}
                  <span>{startingRun ? 'Launching…' : 'Confirm & Execute'}</span>
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
};

export default DataDrivenExecution;
