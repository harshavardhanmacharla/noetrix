import React, { useEffect, useState, useCallback } from 'react';
import {
  Settings as SettingsIcon,
  Globe,
  Save,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Terminal,
  Activity,
  Layers,
  Key,
  Lock,
  Plus,
  Trash2,
  Edit2,
  Copy,
  Check,
  Shield,
  HelpCircle,
  Eye,
  EyeOff,
  X,
} from 'lucide-react';
import { Layout } from '../components/layout/Layout';
import { PageLoader, LoadingSpinner } from '../components/ui/LoadingSpinner';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { projectsApi } from '../api/projects';
import { reportsApi } from '../api/reports';
import { projectVariablesApi } from '../api/projectVariables';
import { Project, ProjectVariable } from '../types';

export const Settings: React.FC = () => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [appUrl, setAppUrl] = useState<string>('');
  const [projectName, setProjectName] = useState<string>('');
  const [description, setDescription] = useState<string>('');

  const [loadingProjects, setLoadingProjects] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Health and Playwright status
  const [healthStatus, setHealthStatus] = useState<{
    status: string;
    version?: string;
    db?: string;
    playwright_available?: boolean;
  } | null>(null);
  const [checkingHealth, setCheckingHealth] = useState(false);

  // Project Variables state
  const [variables, setVariables] = useState<ProjectVariable[]>([]);
  const [loadingVars, setLoadingVars] = useState(false);
  const [varError, setVarError] = useState<string | null>(null);
  const [varSuccess, setVarSuccess] = useState<string | null>(null);
  const [copiedVar, setCopiedVar] = useState<string | null>(null);

  // Create Variable Modal state
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [createName, setCreateName] = useState('');
  const [createValue, setCreateValue] = useState('');
  const [createIsSecret, setCreateIsSecret] = useState(false);
  const [createDescription, setCreateDescription] = useState('');
  const [creatingVar, setCreatingVar] = useState(false);
  const [showCreateVal, setShowCreateVal] = useState(false);

  // Edit Variable Modal state
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [editingVar, setEditingVar] = useState<ProjectVariable | null>(null);
  const [editName, setEditName] = useState('');
  const [editValue, setEditValue] = useState('');
  const [editIsSecret, setEditIsSecret] = useState(false);
  const [editDescription, setEditDescription] = useState('');
  const [editingLoading, setEditingLoading] = useState(false);
  const [showEditVal, setShowEditVal] = useState(false);

  // Delete Variable Dialog state
  const [deletingVar, setDeletingVar] = useState<ProjectVariable | null>(null);

  const fetchVariables = useCallback(async (projId: string) => {
    if (!projId) {
      setVariables([]);
      return;
    }
    setLoadingVars(true);
    setVarError(null);
    try {
      const data = await projectVariablesApi.list(projId);
      setVariables(data);
    } catch (err: any) {
      setVarError(err.response?.data?.detail || err.message || 'Failed to load variables');
    } finally {
      setLoadingVars(false);
    }
  }, []);

  useEffect(() => {
    projectsApi
      .list()
      .then((data) => {
        setProjects(data);
        if (data.length > 0) {
          setSelectedProjectId(data[0].id);
          setAppUrl(data[0].app_url || '');
          setProjectName(data[0].name || '');
          setDescription(data[0].description || '');
          fetchVariables(data[0].id);
        }
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoadingProjects(false));

    checkSystemHealth();
  }, [fetchVariables]);

  const checkSystemHealth = async () => {
    setCheckingHealth(true);
    try {
      const data: any = await reportsApi.checkHealth();
      setHealthStatus(data);
    } catch {
      setHealthStatus({ status: 'unreachable', db: 'error' });
    } finally {
      setCheckingHealth(false);
    }
  };

  const handleProjectSelect = (id: string) => {
    setSelectedProjectId(id);
    const p = projects.find((proj) => proj.id === id);
    if (p) {
      setAppUrl(p.app_url || '');
      setProjectName(p.name || '');
      setDescription(p.description || '');
    }
    setSaveSuccess(false);
    setVarSuccess(null);
    setVarError(null);
    fetchVariables(id);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedProjectId) return;

    setSaving(true);
    setError(null);
    setSaveSuccess(false);

    try {
      const updated = await projectsApi.update(selectedProjectId, {
        name: projectName,
        app_url: appUrl,
        description: description,
      });

      setProjects((prev) =>
        prev.map((p) => (p.id === updated.id ? updated : p))
      );
      setSaveSuccess(true);
    } catch (err: any) {
      setError(err.message || 'Failed to update project settings');
    } finally {
      setSaving(false);
    }
  };

  const copyPlaceholder = (name: string) => {
    navigator.clipboard.writeText(`{{${name}}}`);
    setCopiedVar(name);
    setTimeout(() => setCopiedVar(null), 2000);
  };

  const handleCreateVar = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedProjectId) return;
    const trimmedName = createName.trim();
    if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(trimmedName)) {
      setVarError('Variable name must start with a letter/underscore and contain only alphanumeric characters or underscores.');
      return;
    }

    setCreatingVar(true);
    setVarError(null);
    setVarSuccess(null);
    try {
      await projectVariablesApi.create(selectedProjectId, {
        name: trimmedName,
        value: createValue,
        is_secret: createIsSecret,
        description: createDescription.trim() || undefined,
      });
      setVarSuccess(`Variable '{{${trimmedName}}}' created successfully.`);
      setIsCreateOpen(false);
      setCreateName('');
      setCreateValue('');
      setCreateIsSecret(false);
      setCreateDescription('');
      setShowCreateVal(false);
      await fetchVariables(selectedProjectId);
    } catch (err: any) {
      setVarError(err.response?.data?.detail || err.message || 'Failed to create variable');
    } finally {
      setCreatingVar(false);
    }
  };

  const handleOpenEdit = (v: ProjectVariable) => {
    setEditingVar(v);
    setEditName(v.name);
    setEditValue(v.is_secret ? '' : (v.value || ''));
    setEditIsSecret(v.is_secret);
    setEditDescription(v.description || '');
    setShowEditVal(false);
    setVarError(null);
    setVarSuccess(null);
    setIsEditOpen(true);
  };

  const handleUpdateVar = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedProjectId || !editingVar) return;
    const trimmedName = editName.trim();
    if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(trimmedName)) {
      setVarError('Variable name must start with a letter/underscore and contain only alphanumeric characters or underscores.');
      return;
    }

    setEditingLoading(true);
    setVarError(null);
    setVarSuccess(null);
    try {
      const payload: any = {
        name: trimmedName,
        is_secret: editIsSecret,
        description: editDescription.trim() || undefined,
      };
      if (editValue !== '') {
        payload.value = editValue;
      }
      await projectVariablesApi.update(selectedProjectId, editingVar.id, payload);
      setVarSuccess(`Variable '{{${trimmedName}}}' updated successfully.`);
      setIsEditOpen(false);
      setEditingVar(null);
      await fetchVariables(selectedProjectId);
    } catch (err: any) {
      setVarError(err.response?.data?.detail || err.message || 'Failed to update variable');
    } finally {
      setEditingLoading(false);
    }
  };

  const handleDeleteVar = async () => {
    if (!selectedProjectId || !deletingVar) return;
    setVarError(null);
    setVarSuccess(null);
    try {
      await projectVariablesApi.delete(selectedProjectId, deletingVar.id);
      setVarSuccess(`Variable '{{${deletingVar.name}}}' deleted successfully.`);
      setDeletingVar(null);
      await fetchVariables(selectedProjectId);
    } catch (err: any) {
      setVarError(err.response?.data?.detail || err.message || 'Failed to delete variable');
    }
  };

  return (
    <Layout
      title="Settings"
      subtitle="Project web application configuration and automation runtime diagnostics"
    >
      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      <div className="max-w-4xl space-y-6">
        {/* Project Application URL Configuration */}
        <div className="card p-6">
          <div className="flex items-center gap-2 mb-4 pb-3 border-b border-slate-100">
            <Globe className="w-5 h-5 text-primary-600" />
            <h3 className="font-semibold text-slate-800 text-base">
              Target Web Application URL
            </h3>
          </div>

          {loadingProjects ? (
            <PageLoader message="Loading projects..." />
          ) : projects.length === 0 ? (
            <p className="text-sm text-slate-500 py-3">
              No projects created yet. Please create an organization and project first.
            </p>
          ) : (
            <form onSubmit={handleSave} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
                  Select Project
                </label>
                <select
                  value={selectedProjectId}
                  onChange={(e) => handleProjectSelect(e.target.value)}
                  className="input max-w-md"
                  disabled={saving}
                >
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.slug})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
                  Project Name
                </label>
                <input
                  type="text"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  className="input max-w-md"
                  required
                  disabled={saving}
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
                  Application Base URL
                </label>
                <input
                  type="url"
                  value={appUrl}
                  onChange={(e) => setAppUrl(e.target.value)}
                  placeholder="https://example.com or http://localhost:3000"
                  className="input max-w-lg font-mono text-sm"
                  disabled={saving}
                />
                <p className="text-xs text-slate-500 mt-1">
                  Base URL against which Playwright automation steps will navigate and execute
                  relative paths (e.g. <code>/timesheet</code>, <code>/login</code>).
                </p>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
                  Description
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={2}
                  className="input max-w-lg"
                  disabled={saving}
                />
              </div>

              <div className="pt-2 flex items-center gap-3">
                <button
                  type="submit"
                  disabled={saving || !selectedProjectId}
                  className="btn-primary"
                >
                  <Save className="w-4 h-4" />
                  {saving ? 'Saving...' : 'Save Configuration'}
                </button>

                {saveSuccess && (
                  <span className="text-sm font-medium text-emerald-600 flex items-center gap-1.5 animate-fadeIn">
                    <CheckCircle2 className="w-4 h-4" />
                    Configuration saved successfully!
                  </span>
                )}
              </div>
            </form>
          )}
        </div>

        {/* Project Test Variables */}
        <div className="card p-6">
          <div className="flex items-center justify-between mb-4 pb-3 border-b border-slate-100">
            <div className="flex items-center gap-2">
              <Key className="w-5 h-5 text-primary-600" />
              <div>
                <h3 className="font-semibold text-slate-800 text-base">
                  Project Test Variables
                </h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  Define reusable variables like <code>user_name</code>, <code>password</code>, or <code>base_url</code>. Reference them in test instructions using <code>{'{{variable_name}}'}</code>.
                </p>
              </div>
            </div>

            <button
              type="button"
              onClick={() => {
                setIsCreateOpen(true);
                setVarError(null);
                setVarSuccess(null);
              }}
              disabled={!selectedProjectId}
              className="btn-primary text-xs py-2 px-3 flex items-center gap-1.5 shrink-0"
            >
              <Plus className="w-4 h-4" />
              Add Variable
            </button>
          </div>

          {varError && (
            <div className="mb-4">
              <ErrorAlert message={varError} onDismiss={() => setVarError(null)} />
            </div>
          )}

          {varSuccess && (
            <div className="mb-4 p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-lg text-sm flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
              <span>{varSuccess}</span>
            </div>
          )}

          {!selectedProjectId ? (
            <p className="text-sm text-slate-500 py-4">Select a project above to manage variables.</p>
          ) : loadingVars ? (
            <PageLoader message="Loading test variables..." />
          ) : variables.length === 0 ? (
            <div className="text-center py-8 border border-dashed border-slate-200 rounded-lg">
              <Key className="w-8 h-8 text-slate-300 mx-auto mb-2" />
              <p className="text-sm font-medium text-slate-700">No test variables configured yet</p>
              <p className="text-xs text-slate-500 max-w-md mx-auto mt-1 mb-4">
                Add variables like <code>user_name</code>, <code>password</code>, or <code>base_url</code> to parameterize test cases across environments without hardcoding credentials.
              </p>
              <button
                type="button"
                onClick={() => setIsCreateOpen(true)}
                className="btn-secondary text-xs"
              >
                <Plus className="w-3.5 h-3.5" />
                Add Your First Variable
              </button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm border-collapse">
                <thead>
                  <tr className="border-b border-slate-200 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                    <th className="py-2.5 px-3">Variable</th>
                    <th className="py-2.5 px-3">Placeholder</th>
                    <th className="py-2.5 px-3">Type</th>
                    <th className="py-2.5 px-3">Value</th>
                    <th className="py-2.5 px-3">Description</th>
                    <th className="py-2.5 px-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {variables.map((v) => (
                    <tr key={v.id} className="hover:bg-slate-50/70 transition-colors">
                      <td className="py-3 px-3 font-medium text-slate-900 font-mono text-xs">
                        {v.name}
                      </td>
                      <td className="py-3 px-3">
                        <button
                          type="button"
                          onClick={() => copyPlaceholder(v.name)}
                          className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 font-mono text-xs transition-colors"
                          title="Click to copy placeholder syntax"
                        >
                          <span>{`{{${v.name}}}`}</span>
                          {copiedVar === v.name ? (
                            <Check className="w-3 h-3 text-emerald-600" />
                          ) : (
                            <Copy className="w-3 h-3 text-slate-400" />
                          )}
                        </button>
                      </td>
                      <td className="py-3 px-3">
                        {v.is_secret ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200">
                            <Lock className="w-3 h-3 text-amber-500" />
                            Secret (AES-256)
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700 border border-slate-200">
                            Plaintext
                          </span>
                        )}
                      </td>
                      <td className="py-3 px-3 font-mono text-xs text-slate-600">
                        {v.is_secret ? (
                          <span className="text-slate-400 select-none tracking-widest font-sans font-bold" title="Encrypted at rest with AES-256-GCM. Secret values are never exposed.">
                            ••••••••
                          </span>
                        ) : (
                          <span className="truncate max-w-[160px] inline-block align-middle" title={v.value || ''}>
                            {v.value || <span className="text-slate-400 italic">(empty)</span>}
                          </span>
                        )}
                      </td>
                      <td className="py-3 px-3 text-xs text-slate-500 max-w-[200px] truncate" title={v.description || ''}>
                        {v.description || <span className="text-slate-400 italic">—</span>}
                      </td>
                      <td className="py-3 px-3 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => handleOpenEdit(v)}
                            className="p-1.5 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded transition-colors"
                            title="Edit or replace value"
                          >
                            <Edit2 className="w-3.5 h-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={() => setDeletingVar(v)}
                            className="p-1.5 text-red-500 hover:text-red-700 hover:bg-red-50 rounded transition-colors"
                            title="Delete variable"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Runtime Diagnostics */}
        <div className="card p-6">
          <div className="flex items-center justify-between mb-4 pb-3 border-b border-slate-100">
            <div className="flex items-center gap-2">
              <Activity className="w-5 h-5 text-primary-600" />
              <h3 className="font-semibold text-slate-800 text-base">
                Automation Runtime Diagnostics
              </h3>
            </div>
            <button
              type="button"
              onClick={checkSystemHealth}
              disabled={checkingHealth}
              className="text-xs text-primary-600 hover:text-primary-700 font-medium"
            >
              {checkingHealth ? 'Checking...' : 'Re-check Status'}
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-4 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-xs text-slate-500 font-medium">Backend API</p>
              <div className="flex items-center gap-2 mt-1">
                {healthStatus?.status === 'ok' ? (
                  <>
                    <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                    <span className="text-sm font-semibold text-emerald-700">Healthy</span>
                  </>
                ) : (
                  <>
                    <XCircle className="w-4 h-4 text-red-500" />
                    <span className="text-sm font-semibold text-red-700">Unreachable</span>
                  </>
                )}
              </div>
              <p className="text-[11px] text-slate-400 mt-1">v{healthStatus?.version || '1.0.0'}</p>
            </div>

            <div className="p-4 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-xs text-slate-500 font-medium">Database (SQLAlchemy)</p>
              <div className="flex items-center gap-2 mt-1">
                {healthStatus?.db === 'connected' ? (
                  <>
                    <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                    <span className="text-sm font-semibold text-emerald-700">Connected</span>
                  </>
                ) : (
                  <>
                    <AlertTriangle className="w-4 h-4 text-amber-500" />
                    <span className="text-sm font-semibold text-amber-700">
                      {healthStatus?.db || 'Disconnected'}
                    </span>
                  </>
                )}
              </div>
              <p className="text-[11px] text-slate-400 mt-1">PostgreSQL / SQLite ready</p>
            </div>

            <div className="p-4 rounded-lg border border-slate-200 bg-slate-50">
              <p className="text-xs text-slate-500 font-medium">Playwright Chromium</p>
              <div className="flex items-center gap-2 mt-1">
                {healthStatus?.playwright_available ? (
                  <>
                    <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                    <span className="text-sm font-semibold text-emerald-700">Installed</span>
                  </>
                ) : (
                  <>
                    <AlertTriangle className="w-4 h-4 text-amber-500" />
                    <span className="text-sm font-semibold text-amber-700">Pending Install</span>
                  </>
                )}
              </div>
              <p className="text-[11px] text-slate-400 mt-1">Headless browser automation</p>
            </div>
          </div>

          <div className="mt-5 p-4 rounded-lg bg-slate-900 text-slate-200 text-xs">
            <div className="flex items-center gap-2 text-slate-400 mb-2 font-mono">
              <Terminal className="w-4 h-4" />
              Windows Playwright setup command:
            </div>
            <code className="text-emerald-400 font-mono select-all">
              playwright install chromium
            </code>
          </div>
        </div>
      </div>

      {/* Create Variable Modal */}
      {isCreateOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => !creatingVar && setIsCreateOpen(false)}
          />
          <div className="relative bg-white rounded-xl shadow-xl w-full max-w-lg p-6 animate-fadeIn">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 mb-4">
              <div className="flex items-center gap-2">
                <Key className="w-5 h-5 text-primary-600" />
                <h3 className="font-semibold text-slate-900 text-base">New Test Variable</h3>
              </div>
              <button
                type="button"
                onClick={() => setIsCreateOpen(false)}
                disabled={creatingVar}
                className="text-slate-400 hover:text-slate-600 p-1"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreateVar} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
                  Variable Name *
                </label>
                <input
                  type="text"
                  value={createName}
                  onChange={(e) => setCreateName(e.target.value)}
                  placeholder="e.g. user_name, password, base_url"
                  className="input font-mono text-sm"
                  required
                  autoFocus
                  disabled={creatingVar}
                />
                <p className="text-[11px] text-slate-500 mt-1">
                  Must be alphanumeric or underscores. Use in test steps as <code>{`{{${createName.trim() || 'variable_name'}}}`}</code>.
                </p>
              </div>

              <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                <label className="flex items-start gap-2.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={createIsSecret}
                    onChange={(e) => setCreateIsSecret(e.target.checked)}
                    className="mt-0.5 rounded border-slate-300 text-primary-600 focus:ring-primary-500"
                    disabled={creatingVar}
                  />
                  <div>
                    <span className="text-xs font-semibold text-slate-800 flex items-center gap-1.5">
                      <Lock className="w-3.5 h-3.5 text-amber-500" />
                      Treat as Secret Variable (AES-256-GCM)
                    </span>
                    <p className="text-[11px] text-slate-500 mt-0.5">
                      Encrypted at rest. Values are masked in logs, reports, test results, and are never returned to the browser.
                    </p>
                  </div>
                </label>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
                  {createIsSecret ? 'Secret Value *' : 'Value *'}
                </label>
                <div className="relative">
                  <input
                    type={createIsSecret && !showCreateVal ? 'password' : 'text'}
                    value={createValue}
                    onChange={(e) => setCreateValue(e.target.value)}
                    placeholder={createIsSecret ? 'Enter secret value...' : 'Enter variable value...'}
                    className="input font-mono text-sm pr-10"
                    required
                    disabled={creatingVar}
                  />
                  {createIsSecret && (
                    <button
                      type="button"
                      onClick={() => setShowCreateVal(!showCreateVal)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                      tabIndex={-1}
                    >
                      {showCreateVal ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  )}
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
                  Description (Optional)
                </label>
                <input
                  type="text"
                  value={createDescription}
                  onChange={(e) => setCreateDescription(e.target.value)}
                  placeholder="e.g. Staging credentials for admin account"
                  className="input text-sm"
                  disabled={creatingVar}
                />
              </div>

              <div className="pt-3 flex items-center justify-end gap-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setIsCreateOpen(false)}
                  disabled={creatingVar}
                  className="btn-secondary text-xs"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creatingVar || !createName.trim() || !createValue}
                  className="btn-primary text-xs"
                >
                  {creatingVar ? 'Creating...' : 'Create Variable'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Variable Modal */}
      {isEditOpen && editingVar && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => !editingLoading && setIsEditOpen(false)}
          />
          <div className="relative bg-white rounded-xl shadow-xl w-full max-w-lg p-6 animate-fadeIn">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 mb-4">
              <div className="flex items-center gap-2">
                <Edit2 className="w-5 h-5 text-primary-600" />
                <h3 className="font-semibold text-slate-900 text-base">
                  Edit Variable: <code className="font-mono text-primary-600">{editingVar.name}</code>
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setIsEditOpen(false)}
                disabled={editingLoading}
                className="text-slate-400 hover:text-slate-600 p-1"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleUpdateVar} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
                  Variable Name *
                </label>
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="input font-mono text-sm"
                  required
                  disabled={editingLoading}
                />
              </div>

              <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                <label className="flex items-start gap-2.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={editIsSecret}
                    onChange={(e) => setEditIsSecret(e.target.checked)}
                    className="mt-0.5 rounded border-slate-300 text-primary-600 focus:ring-primary-500"
                    disabled={editingLoading}
                  />
                  <div>
                    <span className="text-xs font-semibold text-slate-800 flex items-center gap-1.5">
                      <Lock className="w-3.5 h-3.5 text-amber-500" />
                      Treat as Secret Variable (AES-256-GCM)
                    </span>
                    <p className="text-[11px] text-slate-500 mt-0.5">
                      Secret values are encrypted and cannot be displayed once saved.
                    </p>
                  </div>
                </label>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
                  {editIsSecret ? 'Replace Secret Value' : 'Value'}
                </label>
                {editIsSecret && (
                  <div className="mb-2 p-2.5 bg-amber-50 border border-amber-200 rounded text-amber-800 text-xs flex items-center gap-2">
                    <Shield className="w-4 h-4 text-amber-600 shrink-0" />
                    <span>
                      Leave this blank to preserve the existing encrypted secret value. Enter a new value only to replace it.
                    </span>
                  </div>
                )}
                <div className="relative">
                  <input
                    type={editIsSecret && !showEditVal ? 'password' : 'text'}
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    placeholder={
                      editIsSecret
                        ? 'Leave blank to retain current secret...'
                        : 'Enter variable value...'
                    }
                    className="input font-mono text-sm pr-10"
                    disabled={editingLoading}
                  />
                  {editIsSecret && (
                    <button
                      type="button"
                      onClick={() => setShowEditVal(!showEditVal)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                      tabIndex={-1}
                    >
                      {showEditVal ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  )}
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
                  Description
                </label>
                <input
                  type="text"
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  placeholder="Optional description"
                  className="input text-sm"
                  disabled={editingLoading}
                />
              </div>

              <div className="pt-3 flex items-center justify-end gap-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setIsEditOpen(false)}
                  disabled={editingLoading}
                  className="btn-secondary text-xs"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={editingLoading || !editName.trim()}
                  className="btn-primary text-xs"
                >
                  {editingLoading ? 'Saving...' : 'Save Changes'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete Confirmation Dialog */}
      <ConfirmDialog
        open={Boolean(deletingVar)}
        title="Delete Test Variable"
        description={`Are you sure you want to delete the variable '{{${deletingVar?.name}}}'? Any test cases referencing this variable may fail if executed.`}
        confirmLabel="Delete Variable"
        variant="danger"
        onConfirm={handleDeleteVar}
        onCancel={() => setDeletingVar(null)}
      />
    </Layout>
  );
};

export default Settings;
