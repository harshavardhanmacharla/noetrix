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
  Sparkles,
  Edit3,
  Save,
  HelpCircle,
  RefreshCw,
} from 'lucide-react';
import { Layout } from '../components/layout/Layout';
import { PageLoader, LoadingSpinner } from '../components/ui/LoadingSpinner';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { EmptyState } from '../components/ui/EmptyState';
import { testCasesApi } from '../api/testCases';
import { projectsApi } from '../api/projects';
import { TestCase, Project, ValidationResult, ParseInstructionsResponse } from '../types';

const SAMPLE_INSTRUCTIONS = `open https://example.com/login
type "admin" into "#username"
enter "secret123" into "#password"
click the "Sign In" button
verify that text "Dashboard" is visible
verify current url contains "/dashboard"`;

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

  // Creation Mode Switcher: Natural Language vs CSV Upload
  const [creationMode, setCreationMode] = useState<'natural_language' | 'csv'>('natural_language');

  // Natural Language Creator State
  const [nlName, setNlName] = useState('');
  const [nlDescription, setNlDescription] = useState('');
  const [nlInstructions, setNlInstructions] = useState('');
  const [nlParsing, setNlParsing] = useState(false);
  const [nlParseResult, setNlParseResult] = useState<ParseInstructionsResponse | null>(null);
  const [nlParseError, setNlParseError] = useState<string | null>(null);
  const [nlSaving, setNlSaving] = useState(false);
  const [nlSaveError, setNlSaveError] = useState<string | null>(null);
  const [nlSuccessMessage, setNlSuccessMessage] = useState<string | null>(null);
  const [nlPreviewMode, setNlPreviewMode] = useState(false);
  const [showSyntaxGuide, setShowSyntaxGuide] = useState(false);

  // CSV Upload State
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

  // Project selector change handler
  const handleProjectChange = (projectId: string) => {
    setSelectedProjectId(projectId);
    setUploadResult(null);
    setError(null);
    setNlParseResult(null);
    setNlPreviewMode(false);
    setNlSuccessMessage(null);
    if (projectId) {
      setSearchParams({ project: projectId });
    } else {
      setSearchParams({});
    }
  };

  // =========================================================================
  // Natural Language Creator Handlers
  // =========================================================================

  const handleParseInstructions = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!selectedProjectId) {
      setNlParseError('Please select a project before parsing instructions.');
      return;
    }
    if (!nlName.trim()) {
      setNlParseError('Please enter a test case name.');
      return;
    }
    if (!nlInstructions.trim()) {
      setNlParseError('Please enter at least one natural-language instruction.');
      return;
    }

    setNlParsing(true);
    setNlParseError(null);
    setNlSaveError(null);
    setNlSuccessMessage(null);

    try {
      const result = await testCasesApi.parseInstructions(selectedProjectId, nlInstructions);
      setNlParseResult(result);
      if (result.is_valid && result.steps.length > 0) {
        setNlPreviewMode(true);
      } else {
        setNlPreviewMode(false);
      }
    } catch (err: unknown) {
      setNlParseError(err instanceof Error ? err.message : 'Failed to parse instructions.');
      setNlParseResult(null);
      setNlPreviewMode(false);
    } finally {
      setNlParsing(false);
    }
  };

  const handleSaveNaturalLanguageTestCase = async () => {
    if (!selectedProjectId) {
      setNlSaveError('Please select a project first.');
      return;
    }
    if (!nlName.trim()) {
      setNlSaveError('Test case name is required.');
      return;
    }

    setNlSaving(true);
    setNlSaveError(null);

    try {
      const created = await testCasesApi.createFromInstructions(
        selectedProjectId,
        nlName.trim(),
        nlInstructions,
        nlDescription.trim() || undefined
      );

      // Refresh test cases list
      await fetchTestCases(selectedProjectId);

      // Expand the newly created case
      setExpandedCaseId(created.id);

      // Reset editor state and show success
      setNlSuccessMessage(
        `Test case "${created.name}" created successfully with ${created.steps?.length ?? 0} step(s)!`
      );
      setNlName('');
      setNlDescription('');
      setNlInstructions('');
      setNlParseResult(null);
      setNlPreviewMode(false);
    } catch (err: unknown) {
      setNlSaveError(err instanceof Error ? err.message : 'Failed to save test case.');
    } finally {
      setNlSaving(false);
    }
  };

  const handleReturnToEditor = () => {
    setNlPreviewMode(false);
    setNlSaveError(null);
  };

  // =========================================================================
  // CSV Upload Handlers (Preserved)
  // =========================================================================

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

        {/* Top Controls Row: Project Selector */}
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
                aria-label="Active Project"
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
              className="btn-secondary text-xs"
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

        {/* Creation Modes Tabs */}
        {selectedProjectId && (
          <div className="flex items-center gap-3 border-b border-slate-200 pb-2">
            <button
              type="button"
              onClick={() => {
                setCreationMode('natural_language');
                setError(null);
              }}
              className={`px-4 py-2 rounded-lg text-sm font-semibold flex items-center gap-2 transition-all ${
                creationMode === 'natural_language'
                  ? 'bg-primary-600 text-white shadow-sm'
                  : 'bg-white text-slate-600 hover:text-slate-900 hover:bg-slate-50 border border-slate-200'
              }`}
            >
              <Sparkles className="w-4 h-4" />
              <span>Create with Natural Language</span>
            </button>

            <button
              type="button"
              onClick={() => {
                setCreationMode('csv');
                setError(null);
              }}
              className={`px-4 py-2 rounded-lg text-sm font-semibold flex items-center gap-2 transition-all ${
                creationMode === 'csv'
                  ? 'bg-primary-600 text-white shadow-sm'
                  : 'bg-white text-slate-600 hover:text-slate-900 hover:bg-slate-50 border border-slate-200'
              }`}
            >
              <Upload className="w-4 h-4" />
              <span>Upload CSV File</span>
            </button>
          </div>
        )}

        {/* Mode 1: Natural Language Test Case Creator */}
        {selectedProjectId && creationMode === 'natural_language' && (
          <div className="card p-6 border-primary-200 bg-gradient-to-b from-white to-primary-50/20">
            <div className="flex flex-wrap items-center justify-between gap-4 mb-5 pb-4 border-b border-slate-100">
              <div>
                <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
                  <Sparkles className="w-5 h-5 text-primary-600" />
                  <span>Natural Language Test Creator</span>
                </h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  Type instructions in plain English (one per line). Noetrix automatically interprets, validates, and converts them into structured Playwright steps.
                </p>
              </div>

              <button
                type="button"
                onClick={() => setShowSyntaxGuide((prev) => !prev)}
                className="text-xs text-primary-600 hover:text-primary-800 font-medium flex items-center gap-1.5 py-1 px-2.5 rounded-lg border border-primary-200 bg-primary-50 hover:bg-primary-100/70 transition-colors"
              >
                <HelpCircle className="w-3.5 h-3.5" />
                <span>{showSyntaxGuide ? 'Hide Supported Syntax' : 'Supported Phrasings'}</span>
              </button>
            </div>

            {/* Syntax cheat sheet modal / card */}
            {showSyntaxGuide && (
              <div className="mb-5 p-4 rounded-xl border border-primary-200 bg-white shadow-sm text-xs space-y-2">
                <p className="font-semibold text-slate-800">Supported Plain-English Instructions:</p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-slate-600">
                  <div className="bg-slate-50 p-2 rounded border border-slate-100">
                    <strong className="text-slate-800">Navigation:</strong> <span className="font-mono">open https://example.com</span>, <span className="font-mono">visit /dashboard</span>, <span className="font-mono">go to /login</span>
                  </div>
                  <div className="bg-slate-50 p-2 rounded border border-slate-100">
                    <strong className="text-slate-800">Text Entry:</strong> <span className="font-mono">type "admin" into "#username"</span>, <span className="font-mono">fill "Email" with "user@test.com"</span>
                  </div>
                  <div className="bg-slate-50 p-2 rounded border border-slate-100">
                    <strong className="text-slate-800">Clicking:</strong> <span className="font-mono">click "#submit-btn"</span>, <span className="font-mono">click the "Sign In" button</span>, <span className="font-mono">press "Save"</span>
                  </div>
                  <div className="bg-slate-50 p-2 rounded border border-slate-100">
                    <strong className="text-slate-800">Checkboxes:</strong> <span className="font-mono">check "Remember me"</span>, <span className="font-mono">uncheck "#marketing"</span>, <span className="font-mono">mark "Terms" as checked</span>
                  </div>
                  <div className="bg-slate-50 p-2 rounded border border-slate-100">
                    <strong className="text-slate-800">Dropdowns:</strong> <span className="font-mono">select "California" from "#state"</span>, <span className="font-mono">choose "Admin" from the "Role" dropdown</span>
                  </div>
                  <div className="bg-slate-50 p-2 rounded border border-slate-100">
                    <strong className="text-slate-800">Clearing:</strong> <span className="font-mono">clear the "Search" field</span>, <span className="font-mono">erase "#notes"</span>
                  </div>
                  <div className="bg-slate-50 p-2 rounded border border-slate-100">
                    <strong className="text-slate-800">Assertions:</strong> <span className="font-mono">verify text "Success" is visible</span>, <span className="font-mono">verify url does not contain "/error"</span>
                  </div>
                </div>
                <p className="text-[11px] text-slate-400 italic">
                  Note: Compound instructions (e.g. "click submit and enter password") and conditional logic ("if ...") are intentionally rejected to maintain step atomicity.
                </p>
              </div>
            )}

            {/* Success Message Banner */}
            {nlSuccessMessage && (
              <div className="mb-5 p-3.5 rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-800 text-xs font-medium flex items-center justify-between">
                <span className="flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                  {nlSuccessMessage}
                </span>
                <button
                  type="button"
                  onClick={() => setNlSuccessMessage(null)}
                  className="text-emerald-700 hover:text-emerald-900 font-bold px-1"
                >
                  ×
                </button>
              </div>
            )}

            {/* Parse / Save Error Alerts */}
            {nlParseError && (
              <div className="mb-5">
                <ErrorAlert message={nlParseError} onDismiss={() => setNlParseError(null)} />
              </div>
            )}
            {nlSaveError && (
              <div className="mb-5">
                <ErrorAlert message={nlSaveError} onDismiss={() => setNlSaveError(null)} />
              </div>
            )}

            {!nlPreviewMode ? (
              /* State A: Editing View */
              <form onSubmit={handleParseInstructions} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="md:col-span-1">
                    <label htmlFor="nl-test-name" className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                      Test Case Name *
                    </label>
                    <input
                      id="nl-test-name"
                      type="text"
                      className="input w-full text-sm font-medium"
                      placeholder="e.g. User Authentication & Dashboard"
                      value={nlName}
                      onChange={(e) => setNlName(e.target.value)}
                      required
                    />
                  </div>
                  <div className="md:col-span-2">
                    <label htmlFor="nl-description" className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
                      Description <span className="text-slate-400 font-normal lowercase">(optional)</span>
                    </label>
                    <input
                      id="nl-description"
                      type="text"
                      className="input w-full text-sm"
                      placeholder="Brief note about the purpose or flow of this test scenario"
                      value={nlDescription}
                      onChange={(e) => setNlDescription(e.target.value)}
                    />
                  </div>
                </div>

                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label htmlFor="nl-instructions" className="block text-xs font-bold text-slate-700 uppercase tracking-wider">
                      Natural Language Instructions * (1 step per line)
                    </label>
                    <button
                      type="button"
                      onClick={() => {
                        if (!nlName) setNlName('Login and Dashboard Verification');
                        setNlInstructions(SAMPLE_INSTRUCTIONS);
                        setNlParseResult(null);
                      }}
                      className="text-xs text-primary-600 hover:text-primary-800 font-medium underline"
                    >
                      Insert Example Instructions
                    </button>
                  </div>

                  <textarea
                    id="nl-instructions"
                    rows={7}
                    className="input w-full font-mono text-xs leading-relaxed p-3.5 bg-slate-50 focus:bg-white"
                    placeholder={`open https://example.com/login\ntype "admin" into "#username"\nclick the "Sign In" button\nverify that text "Welcome" is visible`}
                    value={nlInstructions}
                    onChange={(e) => {
                      setNlInstructions(e.target.value);
                      if (nlParseResult) setNlParseResult(null);
                    }}
                    required
                  />
                  <p className="text-[11px] text-slate-400 mt-1">
                    Enter one action per line. Empty lines between steps are permitted and automatically skipped.
                  </p>
                </div>

                {/* Validation errors list (if parsing was attempted and failed) */}
                {nlParseResult && !nlParseResult.is_valid && (
                  <div className="rounded-xl border border-red-200 bg-red-50/80 p-4 space-y-2">
                    <div className="flex items-center gap-2 text-red-800 font-semibold text-xs">
                      <XCircle className="w-4 h-4 text-red-600 shrink-0" />
                      <span>
                        Parsing Failed — {nlParseResult.errors.length} issue(s) detected:
                      </span>
                    </div>
                    <ul className="divide-y divide-red-100 text-xs text-red-700 bg-white rounded-lg border border-red-200 p-2.5">
                      {nlParseResult.errors.map((err, i) => (
                        <li key={i} className="py-1.5 px-2">
                          <span className="font-mono font-bold text-red-900">Line {err.line}: </span>
                          <span className="italic text-slate-600">"{err.instruction}"</span> —{' '}
                          <span className="font-medium text-red-700">{err.message}</span>
                        </li>
                      ))}
                    </ul>
                    <p className="text-[11px] text-red-600">
                      Please correct the highlighted instructions in the editor above and click <strong>Parse Instructions</strong> again.
                    </p>
                  </div>
                )}

                <div className="flex items-center justify-end gap-3 pt-2">
                  <button
                    type="submit"
                    disabled={nlParsing || !nlInstructions.trim()}
                    className="btn-primary flex items-center gap-2"
                  >
                    {nlParsing ? <LoadingSpinner size="sm" /> : <Sparkles className="w-4 h-4" />}
                    <span>{nlParsing ? 'Parsing Instructions…' : 'Parse Instructions'}</span>
                  </button>
                </div>
              </form>
            ) : (
              /* State B: Preview Table Mode */
              <div className="space-y-4">
                <div className="p-4 rounded-xl border border-emerald-200 bg-emerald-50 flex items-center justify-between">
                  <div className="flex items-center gap-2.5 text-xs font-semibold text-emerald-800">
                    <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
                    <span>
                      Parsing Succeeded! All {nlParseResult?.valid_steps_count ?? 0} instructions successfully mapped to canonical actions.
                    </span>
                  </div>
                  <span className="text-xs text-slate-500 font-medium">
                    Test Case: <strong className="text-slate-800">{nlName}</strong>
                  </span>
                </div>

                {/* Structured Steps Preview Table */}
                <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-left text-slate-500 font-semibold bg-slate-50/80 border-b border-slate-200">
                        <th className="py-2.5 px-3 w-12 text-center">Step #</th>
                        <th className="py-2.5 px-3">Original Instruction</th>
                        <th className="py-2.5 px-3 w-28">Canonical Action</th>
                        <th className="py-2.5 px-3">Target Element</th>
                        <th className="py-2.5 px-3">Value</th>
                        <th className="py-2.5 px-3">Expected Result</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {(nlParseResult?.steps || []).map((step, idx) => (
                        <tr key={idx} className="hover:bg-slate-50/60 transition-colors">
                          <td className="py-2.5 px-3 text-center font-mono font-bold text-slate-600">
                            {idx + 1}
                          </td>
                          <td className="py-2.5 px-3 font-mono text-slate-800">
                            {step.raw_instruction}
                          </td>
                          <td className="py-2.5 px-3">
                            <span className="px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-primary-100 text-primary-800">
                              {step.action}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 font-mono text-slate-700">
                            {step.target || <span className="text-slate-300">—</span>}
                          </td>
                          <td className="py-2.5 px-3 font-mono text-slate-700">
                            {step.value || <span className="text-slate-300">—</span>}
                          </td>
                          <td className="py-2.5 px-3 text-slate-700">
                            {step.expected_result || <span className="text-slate-300">—</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Preview Actions: Return to Editing vs Confirm & Save */}
                <div className="flex items-center justify-between pt-2">
                  <button
                    type="button"
                    onClick={handleReturnToEditor}
                    className="btn-secondary flex items-center gap-2 text-xs"
                    disabled={nlSaving}
                  >
                    <Edit3 className="w-3.5 h-3.5 text-slate-500" />
                    <span>Return to Edit Instructions</span>
                  </button>

                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={() => handleParseInstructions()}
                      className="btn-secondary flex items-center gap-1.5 text-xs"
                      disabled={nlSaving || nlParsing}
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${nlParsing ? 'animate-spin' : ''}`} />
                      <span>Re-Parse</span>
                    </button>

                    <button
                      type="button"
                      onClick={handleSaveNaturalLanguageTestCase}
                      disabled={nlSaving}
                      className="btn-primary flex items-center gap-2 shadow-sm font-semibold"
                    >
                      {nlSaving ? <LoadingSpinner size="sm" /> : <Save className="w-4 h-4" />}
                      <span>{nlSaving ? 'Saving Test Case…' : 'Save Test Case'}</span>
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Mode 2: Existing CSV Upload Area (Preserved) */}
        {selectedProjectId && creationMode === 'csv' && (
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
        )}

        {/* CSV Upload Validation Result (Preserved) */}
        {uploadResult && creationMode === 'csv' && (
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

        {/* Test Cases Display Section (Accordion) */}
        {selectedProjectId ? (
          <>
            {loading ? (
              <PageLoader message="Loading test cases..." />
            ) : testCases.length === 0 ? (
              <EmptyState
                icon={FileText}
                title="No test cases found"
                description="This project doesn't have any test cases yet. Use the Natural Language Creator above or upload a CSV file to get started."
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
              description="Choose a project from the dropdown above to view, create, and manage Playwright test scenarios."
            />
          )
        )}
      </div>
    </Layout>
  );
};

export default TestCases;
