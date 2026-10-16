import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { FolderOpen, Plus, X, ExternalLink, Trash2 } from 'lucide-react';
import { Layout } from '../components/layout/Layout';
import { PageLoader } from '../components/ui/LoadingSpinner';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { EmptyState } from '../components/ui/EmptyState';
import { projectsApi } from '../api/projects';
import { organizationsApi } from '../api/organizations';
import { Project, Organization } from '../types';
import { getSafeUrlDisplay } from '../utils/url';

const Projects: React.FC = () => {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState({
    name: '',
    slug: '',
    description: '',
    org_id: '',
    app_url: '',
  });
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Deletion state
  const [projectToDelete, setProjectToDelete] = useState<Project | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [projectData, orgData] = await Promise.all([
        projectsApi.list(),
        organizationsApi.list(),
      ]);
      setProjects(projectData);
      setOrgs(orgData);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load projects');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const slugify = (val: string) =>
    val
      .toLowerCase()
      .replace(/\s+/g, '-')
      .replace(/[^a-z0-9-]/g, '');

  const getOrgName = (orgId: string) =>
    orgs.find((o) => o.id === orgId)?.name ?? '—';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim() || !form.slug.trim() || !form.org_id) {
      setFormError('Name, slug and organization are required.');
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      const project = await projectsApi.create({
        name: form.name.trim(),
        slug: form.slug.trim(),
        description: form.description.trim() || undefined,
        org_id: form.org_id,
        app_url: form.app_url.trim() || undefined,
      });
      setProjects((prev) => [project, ...prev]);
      setShowModal(false);
      setForm({ name: '', slug: '', description: '', org_id: '', app_url: '' });
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : 'Failed to create project');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteProject = async () => {
    if (!projectToDelete) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await projectsApi.delete(projectToDelete.id);
      setProjects((prev) => prev.filter((p) => p.id !== projectToDelete.id));
      setProjectToDelete(null);
    } catch (err: unknown) {
      const anyErr = err as { response?: { data?: { detail?: string } }; message?: string };
      setDeleteError(anyErr.response?.data?.detail || anyErr.message || 'Failed to delete project');
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Layout title="Projects" subtitle="Manage your test projects">
      <div className="flex justify-end mb-6">
        <button onClick={() => setShowModal(true)} className="btn-primary">
          <Plus className="w-4 h-4" />
          New Project
        </button>
      </div>

      {loading ? (
        <PageLoader />
      ) : error ? (
        <ErrorAlert message={error} onRetry={fetchData} />
      ) : projects.length === 0 ? (
        <EmptyState
          icon={FolderOpen}
          title="No projects yet"
          description="Create a project to start uploading test cases and running tests."
          action={{ label: 'New Project', onClick: () => setShowModal(true) }}
        />
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100">
                {['Project', 'Organization', 'App URL', 'Created', ''].map((h, idx) => (
                  <th
                    key={idx}
                    className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {projects.map((project) => (
                <tr
                  key={project.id}
                  className="hover:bg-slate-50 cursor-pointer transition-colors"
                  onClick={() => navigate(`/test-cases?project=${project.id}`)}
                >
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 bg-blue-50 rounded-lg flex items-center justify-center shrink-0">
                        <FolderOpen className="w-4 h-4 text-blue-600" />
                      </div>
                      <div>
                        <p className="font-medium text-slate-900">{project.name}</p>
                        <p className="text-xs text-slate-400 font-mono">{project.slug}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-slate-600">{getOrgName(project.org_id)}</td>
                  <td className="px-6 py-4">
                    {(() => {
                      const safeUrl = getSafeUrlDisplay(project.app_url);
                      if (!safeUrl) {
                        return <span className="text-slate-400">—</span>;
                      }
                      if (safeUrl.href) {
                        return (
                          <a
                            href={safeUrl.href}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-primary-600 hover:text-primary-700"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {safeUrl.display}
                            <ExternalLink className="w-3 h-3" />
                          </a>
                        );
                      }
                      return (
                        <span className="text-slate-600 font-mono text-xs" title={project.app_url}>
                          {safeUrl.display}
                        </span>
                      );
                    })()}
                  </td>
                  <td className="px-6 py-4 text-slate-500">
                    {new Date(project.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-6 py-4 text-right">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setProjectToDelete(project);
                        setDeleteError(null);
                      }}
                      title="Delete project"
                      className="p-1.5 text-slate-400 hover:text-red-600 rounded-lg hover:bg-red-50 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create project modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => setShowModal(false)}
          />
          <div className="relative bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 p-6">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-semibold text-slate-900">New Project</h2>
              <button
                onClick={() => setShowModal(false)}
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {formError && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                {formError}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">
                    Name <span className="text-red-500">*</span>
                  </label>
                  <input
                    className="input"
                    placeholder="My Project"
                    value={form.name}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        name: e.target.value,
                        slug: slugify(e.target.value),
                      }))
                    }
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">
                    Slug <span className="text-red-500">*</span>
                  </label>
                  <input
                    className="input font-mono"
                    placeholder="my-project"
                    value={form.slug}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, slug: slugify(e.target.value) }))
                    }
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Organization <span className="text-red-500">*</span>
                </label>
                <select
                  className="input"
                  value={form.org_id}
                  onChange={(e) => setForm((f) => ({ ...f, org_id: e.target.value }))}
                >
                  <option value="">Select organization…</option>
                  {orgs.map((org) => (
                    <option key={org.id} value={org.id}>
                      {org.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  App URL
                </label>
                <input
                  className="input"
                  placeholder="https://example.com"
                  value={form.app_url}
                  onChange={(e) => setForm((f) => ({ ...f, app_url: e.target.value }))}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Description
                </label>
                <textarea
                  className="input resize-none"
                  rows={2}
                  placeholder="Optional"
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                />
              </div>
              <div className="flex gap-3 justify-end pt-2">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="btn-secondary"
                >
                  Cancel
                </button>
                <button type="submit" className="btn-primary" disabled={submitting}>
                  {submitting ? 'Creating…' : 'Create Project'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete project confirmation modal */}
      {projectToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => !deleting && setProjectToDelete(null)}
          />
          <div className="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-slate-900">Delete Project</h2>
              <button
                type="button"
                onClick={() => !deleting && setProjectToDelete(null)}
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {deleteError ? (
              <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800">
                {deleteError}
              </div>
            ) : (
              <p className="text-sm text-slate-600 mb-4">
                Are you sure you want to delete <span className="font-semibold text-slate-900">{projectToDelete.name}</span>?
                This action cannot be undone.
              </p>
            )}

            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs text-slate-500 mb-5">
              <strong>Evidence Retention Guarantee:</strong> Projects containing historical test runs, results, or test cases cannot be deleted through this action to protect audit integrity.
            </div>

            <div className="flex gap-3 justify-end">
              <button
                type="button"
                onClick={() => setProjectToDelete(null)}
                className="btn-secondary"
                disabled={deleting}
              >
                {deleteError ? 'Close' : 'Cancel'}
              </button>
              {!deleteError && (
                <button
                  type="button"
                  onClick={handleDeleteProject}
                  className="inline-flex items-center gap-2 px-4 py-2 bg-red-600 text-white rounded-lg font-medium text-sm hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  disabled={deleting}
                >
                  {deleting ? 'Deleting…' : 'Delete Project'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
};

export default Projects;
