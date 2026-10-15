import React, { useEffect, useState } from 'react';
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
} from 'lucide-react';
import { Layout } from '../components/layout/Layout';
import { PageLoader } from '../components/ui/LoadingSpinner';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { projectsApi } from '../api/projects';
import { reportsApi } from '../api/reports';
import { Project } from '../types';

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
        }
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoadingProjects(false));

    checkSystemHealth();
  }, []);

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
    </Layout>
  );
};

export default Settings;
