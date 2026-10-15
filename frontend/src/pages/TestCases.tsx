import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  FileText,
  Download,
  Upload,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Trash2,
  FolderOpen,
} from 'lucide-react';
import { Layout } from '../components/layout/Layout';
import { PageLoader, LoadingSpinner } from '../components/ui/LoadingSpinner';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { EmptyState } from '../components/ui/EmptyState';
import { testCasesApi } from '../api/testCases';
import { projectsApi } from '../api/projects';
import { TestCase, Project, ValidationResult } from '../types';

const TestCases: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [projectsError, setProjectsError] = useState<string | null>(null);

  const initialProjectFromUrl = searchParams.get('project') ?? '';
  const [selectedProjectId, setSelectedProjectId] = useState<string>(initialProjectFromUrl);

  const [testCases, setTestCases] = useState<TestCase[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [isDragging, setIsDragging] = useState(false);
  const [uploadResult, setUploadResult] = useState<ValidationResult | null>(null);
  const [uploading, setUploading] = useState(false);
  const [downloadingTemplate, setDownloadingTemplate] = useState(false);
  const [templateError, setTemplateError] = useState<string | null>(null);

  const [expandedCaseId, setExpandedCaseId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 1. Fetch available projects on mount
  const fetchProjects = useCallback(async () => {
    setProjectsLoading(true);
    setProjectsError(null);
    try {
      const data = await projectsApi.list();
      const projectList = Array.isArray(data) ? data : [];
      setProjects(projectList);

      // Auto-select logic if none currently selected
      const currentParam = searchParams.get('project');
      if (currentParam && projectList.some((p) => p.id === currentParam)) {
        setSelectedProjectId(currentParam);
      } else if (!selectedProjectId && projectList.length > 0) {
        const defaultId = projectList[0].id;
        setSelectedProjectId(defaultId);
        setSearchParams({ project: defaultId }, { replace: true });
      }
    } catch (err: unknown) {
      setProjectsError(err instanceof Error ? err.message : 'Failed to load projects');
    } finally {
      setProjectsLoading(false);
    }
  }, [searchParams, selectedProjectId, setSearchParams]);

  useEffect(() => {
    fetchProjects();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 2. Synchronize selectedProjectId when URL search param changes
  useEffect(() => {
    const projectFromUrl = searchParams.get('project');
    if (projectFromUrl && projectFromUrl !== selectedProjectId) {
      setSelectedProjectId(projectFromUrl);
    }
  }, [searchParams, selectedProjectId]);

  // 3. Load test cases whenever selectedProjectId changes
  const fetchTestCases = useCallback(async (projectId: string) => {
    if (!projectId) {
      setTestCases([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await testCasesApi.list(projectId);
      setTestCases(Array.isArray(data) ? data : []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load test cases');
      setTestCases([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedProjectId) {
      fetchTestCases(selectedProjectId);
    } else {
      setTestCases([]);
    }
  }, [selectedProjectId, fetchTestCases]);

  // Handlers
  const handleProjectChange = (projectId: string) => {
    setSelectedProjectId(projectId);
    setUploadResult(null);
    setError(null);
    if (projectId) {
      setSearchParams({ project: projectId });
    } else {
      setSearchParams({});
    }
  };

  const handleFile = async (file: File) => {
    if (!selectedProjectId) {
      setError('Please select a project before uploading test cases.');
      return;
    }
    if (!file.name.toLowerCase().endsWith('.csv')) {
      setError('Invalid file type. Please upload a standard .csv file.');
      return;
    }
    setUploading(true);
    setUploadResult(null);
    setError(null);
    try {
      const result = await testCasesApi.uploadCsv(selectedProjectId, file);
      setUploadResult(result);
      if (result.is_valid) {
        await fetchTestCases(selectedProjectId);
      }
    } catch (err: unknown) {
      setUploadResult({
        is_valid: false,
        errors: [{ row: 0, column: file.name, message: err instanceof Error ? err.message : 'Upload failed' }],
        warnings: [],
        row_count: 0,
        test_case_count: 0,
      });
    } finally {
      setUploading(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  };

  const downloadTemplate = async () => {
    setDownloadingTemplate(true);
    setTemplateError(null);
    try {
      const blob = await testCasesApi.downloadTemplate();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'testpilot_template.csv';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err: unknown) {
      setTemplateError(err instanceof Error ? err.message : 'Failed to download CSV template');
    } finally {
      setDownloadingTemplate(false);
    }
  };

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`Delete test case "${name}"?`)) return;
    try {
      await testCasesApi.delete(id);
      setTestCases((prev) => prev.filter((tc) => tc.id !== id));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to delete test case');
    }
  };

  const selectedProject = projects.find((p) => p.id === selectedProjectId);

  return (
    <Layout
      title="Test Cases"
      subtitle={
        selectedProject
          ? `Manage test scenarios for project: ${selectedProject.name}`
          : 'Upload and manage your test scenarios'
      }
    >
      <div className="space-y-6">
        {/* Global error alerts */}
        {projectsError && (
          <ErrorAlert
            message={projectsError}
            onRetry={fetchProjects}
            onDismiss={() => setProjectsError(null)}
          />
        )}
        {templateError && (
          <ErrorAlert
            message={templateError}
            onRetry={downloadTemplate}
            onDismiss={() => setTemplateError(null)}
          />
        )}
        {error && (
          <ErrorAlert
            message={error}
            onRetry={selectedProjectId ? () => fetchTestCases(selectedProjectId) : undefined}
            onDismiss={() => setError(null)}
          />
        )}

        {/* Controls row: Project Selector & Actions */}
        <div className="card p-4 flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <label htmlFor="project-select" className="text-sm font-medium text-slate-700">
              Active Project:
            </label>
            {projectsLoading ? (
              <div className="flex items-center gap-2 text-sm text-slate-500 py-1.5 px-3 bg-slate-50 rounded-lg border border-slate-200">
                <LoadingSpinner size="sm" />
                <span>Loading projects...</span>
              </div>
            ) : (
              <select
                id="project-select"
                className="input max-w-xs font-medium text-slate-800"
                value={selectedProjectId}
                onChange={(e) => handleProjectChange(e.target.value)}
              >
                <option value="">Select a project…</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            )}
            {selectedProject?.app_url && (
              <span className="text-xs text-slate-500 font-mono bg-slate-100 px-2.5 py-1 rounded-md hidden md:inline">
                Target: {selectedProject.app_url}
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={downloadTemplate}
              disabled={downloadingTemplate}
              className="btn-secondary"
              title="Download standard CSV template with required columns"
            >
              {downloadingTemplate ? (
                <LoadingSpinner size="sm" />
              ) : (
                <Download className="w-4 h-4 text-slate-500" />
              )}
              <span>{downloadingTemplate ? 'Downloading…' : 'Download CSV Template'}</span>
            </button>
          </div>
        </div>

        {/* CSV Upload area */}
        {selectedProjectId ? (
          <div
            className={`border-2 border-dashed rounded-xl p-8 text-center transition-colors cursor-pointer ${
              isDragging
                ? 'border-primary-400 bg-primary-50'
                : 'border-slate-300 hover:border-primary-300 hover:bg-slate-50'
            }`}
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleFile(file);
                e.target.value = '';
              }}
            />
            {uploading ? (
              <div className="flex flex-col items-center justify-center py-2">
                <LoadingSpinner size="md" className="mb-3" />
                <p className="text-sm font-medium text-slate-700">Uploading and validating CSV…</p>
                <p className="text-xs text-slate-400 mt-1">Checking column formats, step actions, and values</p>
              </div>
            ) : (
              <>
                <Upload className="w-10 h-10 text-slate-400 mx-auto mb-3" />
                <p className="text-sm font-medium text-slate-700">
                  Drop a CSV test case file here or click to browse
                </p>
                <p className="text-xs text-slate-500 mt-1">
                  Required columns: <span className="font-mono text-slate-600">test_case_id, test_name, step_number, action, target, value, expected_result</span>
                </p>
              </>
            )}
          </div>
        ) : null}

        {/* Upload Validation Result */}
        {uploadResult && (
          <div
            className={`card p-5 ${
              uploadResult.is_valid
                ? 'border-emerald-200 bg-emerald-50/70'
                : 'border-red-200 bg-red-50/70'
            }`}
          >
            <div className="flex items-center gap-2 mb-2">
              {uploadResult.is_valid ? (
                <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
              ) : (
                <XCircle className="w-5 h-5 text-red-600 shrink-0" />
              )}
              <span
                className={`font-semibold text-sm ${
                  uploadResult.is_valid ? 'text-emerald-800' : 'text-red-800'
                }`}
              >
                {uploadResult.is_valid
                  ? `Validation Succeeded! ${uploadResult.test_case_count ?? 0} test case(s) imported from ${uploadResult.row_count ?? 0} rows.`
                  : `Validation Failed — ${(uploadResult.errors?.length ?? 0)} error(s) found in CSV.`}
              </span>
            </div>

            {/* Errors Table */}
            {(uploadResult.errors?.length ?? 0) > 0 && (
              <div className="mt-3 overflow-x-auto bg-white rounded-lg border border-red-200 p-3">
                <p className="text-xs font-semibold text-red-800 mb-2">Issues preventing test execution:</p>
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-red-700 font-semibold border-b border-red-100">
                      <th className="pb-1.5 pr-4">Row</th>
                      <th className="pb-1.5 pr-4">Column</th>
                      <th className="pb-1.5">Error Message</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-red-50">
                    {(uploadResult.errors || []).map((err, i) => (
                      <tr key={i} className="text-red-700">
                        <td className="pr-4 py-1 font-mono font-medium">{err.row > 0 ? err.row : '—'}</td>
                        <td className="pr-4 py-1 font-mono font-medium">{err.column || 'General'}</td>
                        <td className="py-1">{err.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Warnings List */}
            {(uploadResult.warnings?.length ?? 0) > 0 && (
              <div className="mt-3 bg-white rounded-lg border border-amber-200 p-3">
                <p className="text-xs font-semibold text-amber-800 mb-1 flex items-center gap-1">
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
                  {uploadResult.warnings?.length ?? 0} Warning(s)
                </p>
                <ul className="text-xs text-amber-700 list-disc list-inside space-y-0.5 mt-1">
                  {(uploadResult.warnings || []).map((w, i) => (
                    <li key={i}>
                      {w.row > 0 && <span className="font-mono font-medium">Row {w.row}: </span>}
                      {w.message}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Test Cases Display Section */}
        {selectedProjectId ? (
          <>
            {loading ? (
              <PageLoader message="Loading test cases..." />
            ) : testCases.length === 0 ? (
              <EmptyState
                icon={FileText}
                title="No test cases found"
                description="This project doesn't have any test cases yet. Upload a CSV file above or download the sample template to get started."
                action={{
                  label: 'Download CSV Template',
                  onClick: downloadTemplate,
                }}
              />
            ) : (
              <div className="card overflow-hidden">
                <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
                  <div className="flex items-center gap-2">
                    <FileText className="w-4 h-4 text-primary-600" />
                    <h2 className="text-sm font-semibold text-slate-800">
                      Test Cases ({testCases.length})
                    </h2>
                  </div>
                  <span className="text-xs text-slate-500">
                    Click a test case to inspect its execution steps
                  </span>
                </div>
                <div className="divide-y divide-slate-100">
                  {testCases.map((tc) => {
                    const stepCount = tc.steps?.length ?? 0;
                    const isExpanded = expandedCaseId === tc.id;
                    return (
                      <div key={tc.id}>
                        <div className="flex items-center gap-3 px-6 py-4 hover:bg-slate-50 transition-colors">
                          <button
                            type="button"
                            className="flex-1 flex items-center gap-3 text-left focus:outline-none"
                            onClick={() =>
                              setExpandedCaseId((prev) => (prev === tc.id ? null : tc.id))
                            }
                          >
                            <FileText className="w-4 h-4 text-slate-400 shrink-0" />
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium text-slate-800">{tc.name}</p>
                              {tc.description ? (
                                <p className="text-xs text-slate-500 truncate">{tc.description}</p>
                              ) : tc.csv_filename ? (
                                <p className="text-xs text-slate-400 font-mono truncate">
                                  Source: {tc.csv_filename}
                                </p>
                              ) : null}
                            </div>
                            <span className="text-xs px-2.5 py-0.5 rounded-full font-medium bg-slate-100 text-slate-600 shrink-0">
                              {stepCount} {stepCount === 1 ? 'step' : 'steps'}
                            </span>
                            {isExpanded ? (
                              <ChevronUp className="w-4 h-4 text-slate-400" />
                            ) : (
                              <ChevronDown className="w-4 h-4 text-slate-400" />
                            )}
                          </button>
                          <button
                            type="button"
                            title="Delete test case"
                            onClick={() => handleDelete(tc.id, tc.name)}
                            className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors rounded-lg"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>

                        {/* Expanded Step Details */}
                        {isExpanded && (
                          <div className="px-6 py-4 bg-slate-50 border-t border-slate-100">
                            {stepCount === 0 ? (
                              <p className="text-xs text-slate-500 italic">
                                No steps recorded for this test case.
                              </p>
                            ) : (
                              <div className="overflow-x-auto">
                                <table className="w-full text-xs">
                                  <thead>
                                    <tr className="text-left text-slate-500 font-semibold border-b border-slate-200">
                                      <th className="pb-1.5 pr-3 w-12">Step #</th>
                                      <th className="pb-1.5 pr-3 w-28">Action</th>
                                      <th className="pb-1.5 pr-3">Target</th>
                                      <th className="pb-1.5 pr-3">Value</th>
                                      <th className="pb-1.5">Expected Result</th>
                                    </tr>
                                  </thead>
                                  <tbody className="divide-y divide-slate-200/60">
                                    {(tc.steps || []).map((step) => (
                                      <tr key={step.id} className="text-slate-700">
                                        <td className="py-2 pr-3 font-mono font-medium text-slate-500">
                                          {step.step_number}
                                        </td>
                                        <td className="py-2 pr-3">
                                          <span className="px-2 py-0.5 rounded text-[11px] font-mono font-semibold bg-primary-100 text-primary-800">
                                            {step.action}
                                          </span>
                                        </td>
                                        <td className="py-2 pr-3 font-mono text-slate-800 truncate max-w-xs">
                                          {step.target || '—'}
                                        </td>
                                        <td className="py-2 pr-3 font-mono text-slate-600 truncate max-w-xs">
                                          {step.value || '—'}
                                        </td>
                                        <td className="py-2 text-slate-600">
                                          {step.expected_result || '—'}
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </>
        ) : (
          !projectsLoading && (
            <EmptyState
              icon={FolderOpen}
              title="Select a project to begin"
              description="Choose a project from the dropdown above to view, upload, and manage Playwright test scenarios."
            />
          )
        )}
      </div>
    </Layout>
  );
};

export default TestCases;
