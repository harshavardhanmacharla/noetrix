import React, { useEffect, useState, useCallback } from 'react';
import {
  Building2,
  Plus,
  X,
  ChevronRight,
  FolderOpen,
  Pencil,
  Trash2,
  Users,
  Shield,
  LogOut,
  RefreshCw,
  AlertCircle,
} from 'lucide-react';
import { Layout } from '../components/layout/Layout';
import { PageLoader } from '../components/ui/LoadingSpinner';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { EmptyState } from '../components/ui/EmptyState';
import { organizationsApi } from '../api/organizations';
import { projectsApi } from '../api/projects';
import { Organization, OrganizationMember, Project } from '../types';
import { useAuth } from '../context/AuthContext';

const Organizations: React.FC = () => {
  const { user, profile, refreshSession } = useAuth();

  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [expandedOrgId, setExpandedOrgId] = useState<string | null>(null);

  // Tab state for expanded org: 'projects' | 'members'
  const [activeTab, setActiveTab] = useState<Record<string, 'projects' | 'members'>>({});

  // Projects state
  const [orgProjects, setOrgProjects] = useState<Record<string, Project[]>>({});
  const [loadingProjects, setLoadingProjects] = useState<string | null>(null);

  // Members state per organization
  const [orgMembers, setOrgMembers] = useState<Record<string, OrganizationMember[]>>({});
  const [loadingMembers, setLoadingMembers] = useState<Record<string, boolean>>({});
  const [membersError, setMembersError] = useState<Record<string, string | null>>({});

  // Form state for creating org
  const [form, setForm] = useState({ name: '', slug: '', description: '' });
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Edit form state
  const [editingOrg, setEditingOrg] = useState<Organization | null>(null);
  const [editForm, setEditForm] = useState({ name: '', slug: '', description: '' });
  const [editError, setEditError] = useState<string | null>(null);
  const [editSubmitting, setEditSubmitting] = useState(false);

  // Deletion state for organization
  const [orgToDelete, setOrgToDelete] = useState<Organization | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Add Member state
  const [activeOrgForAdd, setActiveOrgForAdd] = useState<Organization | null>(null);
  const [addMemberForm, setAddMemberForm] = useState<{ email: string; role: 'owner' | 'admin' | 'member' }>({
    email: '',
    role: 'member',
  });
  const [addMemberError, setAddMemberError] = useState<string | null>(null);
  const [addingMember, setAddingMember] = useState(false);

  // Change Role state
  const [roleTargetOrg, setRoleTargetOrg] = useState<Organization | null>(null);
  const [roleTargetMember, setRoleTargetMember] = useState<OrganizationMember | null>(null);
  const [newRole, setNewRole] = useState<'owner' | 'admin' | 'member'>('member');
  const [changeRoleError, setChangeRoleError] = useState<string | null>(null);
  const [changingRole, setChangingRole] = useState(false);

  // Remove Member state
  const [removeTargetOrg, setRemoveTargetOrg] = useState<Organization | null>(null);
  const [removeTargetMember, setRemoveTargetMember] = useState<OrganizationMember | null>(null);
  const [removeMemberError, setRemoveMemberError] = useState<string | null>(null);
  const [removingMember, setRemovingMember] = useState(false);

  // Leave Organization state
  const [leaveTargetOrg, setLeaveTargetOrg] = useState<Organization | null>(null);
  const [leaveError, setLeaveError] = useState<string | null>(null);
  const [leavingOrg, setLeavingOrg] = useState(false);

  // Helper to determine caller's role in a specific organization
  const getCallerRoleInOrg = useCallback(
    (orgId: string): string | null => {
      if (user?.is_superuser) return 'superuser';
      const m = profile?.memberships?.find((mem) => mem.org_id === orgId);
      return m ? m.role : null;
    },
    [user, profile]
  );

  const fetchOrgs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await organizationsApi.list();
      setOrgs(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load organizations');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOrgs();
  }, [fetchOrgs]);

  const fetchProjects = async (orgId: string) => {
    if (orgProjects[orgId]) return;
    setLoadingProjects(orgId);
    try {
      const projects = await projectsApi.list(orgId);
      setOrgProjects((prev) => ({ ...prev, [orgId]: projects }));
    } catch {
      setOrgProjects((prev) => ({ ...prev, [orgId]: [] }));
    } finally {
      setLoadingProjects(null);
    }
  };

  const fetchOrgMembers = useCallback(async (orgId: string) => {
    setLoadingMembers((prev) => ({ ...prev, [orgId]: true }));
    setMembersError((prev) => ({ ...prev, [orgId]: null }));
    try {
      const members = await organizationsApi.listMembers(orgId);
      setOrgMembers((prev) => ({ ...prev, [orgId]: members }));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load organization members';
      setMembersError((prev) => ({ ...prev, [orgId]: msg }));
    } finally {
      setLoadingMembers((prev) => ({ ...prev, [orgId]: false }));
    }
  }, []);

  const toggleOrg = async (orgId: string) => {
    if (expandedOrgId === orgId) {
      setExpandedOrgId(null);
      return;
    }
    setExpandedOrgId(orgId);
    const currentTab = activeTab[orgId] || 'projects';
    if (currentTab === 'projects') {
      fetchProjects(orgId);
    } else {
      fetchOrgMembers(orgId);
    }
  };

  const switchTab = (orgId: string, tab: 'projects' | 'members') => {
    setActiveTab((prev) => ({ ...prev, [orgId]: tab }));
    if (tab === 'projects') {
      fetchProjects(orgId);
    } else {
      fetchOrgMembers(orgId);
    }
  };

  const openMembersDirectly = (org: Organization) => {
    setExpandedOrgId(org.id);
    switchTab(org.id, 'members');
  };

  // Create Org Handler
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim() || !form.slug.trim()) {
      setFormError('Name and slug are required.');
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      const org = await organizationsApi.create({
        name: form.name.trim(),
        slug: form.slug.trim(),
        description: form.description.trim() || undefined,
      });
      setOrgs((prev) => [org, ...prev]);
      setShowModal(false);
      setForm({ name: '', slug: '', description: '' });
      await refreshSession();
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : 'Failed to create organization');
    } finally {
      setSubmitting(false);
    }
  };

  // Edit Org Handlers
  const openEditModal = (org: Organization) => {
    setEditingOrg(org);
    setEditForm({
      name: org.name,
      slug: org.slug,
      description: org.description || '',
    });
    setEditError(null);
  };

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingOrg) return;
    if (!editForm.name.trim() || !editForm.slug.trim()) {
      setEditError('Name and slug are required.');
      return;
    }
    setEditSubmitting(true);
    setEditError(null);
    try {
      const updated = await organizationsApi.update(editingOrg.id, {
        name: editForm.name.trim(),
        slug: editForm.slug.trim(),
        description: editForm.description.trim() || undefined,
      });
      setOrgs((prev) => prev.map((o) => (o.id === updated.id ? updated : o)));
      setEditingOrg(null);
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : 'Failed to update organization');
    } finally {
      setEditSubmitting(false);
    }
  };

  // Delete Org Handler
  const handleDeleteOrg = async () => {
    if (!orgToDelete) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await organizationsApi.delete(orgToDelete.id);
      setOrgs((prev) => prev.filter((o) => o.id !== orgToDelete.id));
      setOrgToDelete(null);
      await refreshSession();
    } catch (err: unknown) {
      const anyErr = err as { response?: { data?: { detail?: string } }; message?: string };
      setDeleteError(anyErr.response?.data?.detail || anyErr.message || 'Failed to delete organization');
    } finally {
      setDeleting(false);
    }
  };

  // Add Member Handler
  const openAddMemberModal = (org: Organization) => {
    setActiveOrgForAdd(org);
    setAddMemberForm({ email: '', role: 'member' });
    setAddMemberError(null);
  };

  const handleAddMemberSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeOrgForAdd) return;
    if (!addMemberForm.email.trim()) {
      setAddMemberError('User email is required.');
      return;
    }
    setAddingMember(true);
    setAddMemberError(null);
    try {
      await organizationsApi.addMember(activeOrgForAdd.id, {
        email: addMemberForm.email.trim(),
        role: addMemberForm.role,
      });
      await fetchOrgMembers(activeOrgForAdd.id);
      setActiveOrgForAdd(null);
    } catch (err: unknown) {
      setAddMemberError(err instanceof Error ? err.message : 'Failed to add member to organization');
    } finally {
      setAddingMember(false);
    }
  };

  // Change Role Handler
  const openChangeRoleModal = (org: Organization, member: OrganizationMember) => {
    setRoleTargetOrg(org);
    setRoleTargetMember(member);
    setNewRole(member.role);
    setChangeRoleError(null);
  };

  const handleChangeRoleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!roleTargetOrg || !roleTargetMember) return;
    setChangingRole(true);
    setChangeRoleError(null);
    try {
      await organizationsApi.updateMemberRole(roleTargetOrg.id, roleTargetMember.user_id, {
        role: newRole,
      });
      await fetchOrgMembers(roleTargetOrg.id);
      if (roleTargetMember.email === user?.email) {
        await refreshSession();
      }
      setRoleTargetOrg(null);
      setRoleTargetMember(null);
    } catch (err: unknown) {
      setChangeRoleError(err instanceof Error ? err.message : 'Failed to update member role');
    } finally {
      setChangingRole(false);
    }
  };

  // Remove Member Handler
  const openRemoveMemberModal = (org: Organization, member: OrganizationMember) => {
    setRemoveTargetOrg(org);
    setRemoveTargetMember(member);
    setRemoveMemberError(null);
  };

  const handleRemoveMemberSubmit = async () => {
    if (!removeTargetOrg || !removeTargetMember) return;
    setRemovingMember(true);
    setRemoveMemberError(null);
    try {
      await organizationsApi.removeMember(removeTargetOrg.id, removeTargetMember.user_id);
      await fetchOrgMembers(removeTargetOrg.id);
      if (removeTargetMember.email === user?.email) {
        await refreshSession();
      }
      setRemoveTargetOrg(null);
      setRemoveTargetMember(null);
    } catch (err: unknown) {
      setRemoveMemberError(err instanceof Error ? err.message : 'Failed to remove member');
    } finally {
      setRemovingMember(false);
    }
  };

  // Leave Org Handler
  const openLeaveModal = (org: Organization) => {
    setLeaveTargetOrg(org);
    setLeaveError(null);
  };

  const handleLeaveOrgSubmit = async () => {
    if (!leaveTargetOrg) return;
    setLeavingOrg(true);
    setLeaveError(null);
    try {
      await organizationsApi.leaveOrganization(leaveTargetOrg.id);
      await refreshSession();
      await fetchOrgs();
      setLeaveTargetOrg(null);
    } catch (err: unknown) {
      setLeaveError(err instanceof Error ? err.message : 'Failed to leave organization');
    } finally {
      setLeavingOrg(false);
    }
  };

  const slugify = (val: string) =>
    val
      .toLowerCase()
      .replace(/\s+/g, '-')
      .replace(/[^a-z0-9-]/g, '');

  const formatDate = (dateStr?: string | null): string => {
    if (!dateStr) return 'Unavailable';
    try {
      const d = new Date(dateStr);
      return isNaN(d.getTime())
        ? 'Unavailable'
        : d.toLocaleDateString(undefined, {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
          });
    } catch {
      return 'Unavailable';
    }
  };

  return (
    <Layout title="Organizations" subtitle="Manage your organizations and team members">
      {/* Header action */}
      <div className="flex justify-end mb-6">
        <button onClick={() => setShowModal(true)} className="btn-primary">
          <Plus className="w-4 h-4" />
          New Organization
        </button>
      </div>

      {loading ? (
        <PageLoader />
      ) : error ? (
        <ErrorAlert message={error} onRetry={fetchOrgs} />
      ) : orgs.length === 0 ? (
        <EmptyState
          icon={Building2}
          title="No organizations yet"
          description="Create your first organization to group projects and test runs."
          action={{ label: 'New Organization', onClick: () => setShowModal(true) }}
        />
      ) : (
        <div className="space-y-3">
          {orgs.map((org) => {
            const callerRole = getCallerRoleInOrg(org.id);
            const canManageMembers = callerRole === 'owner' || callerRole === 'admin' || callerRole === 'superuser';
            const isCurrentTabMembers = activeTab[org.id] === 'members';

            return (
              <div key={org.id} className="card overflow-hidden">
                <div className="flex items-center hover:bg-slate-50 transition-colors">
                  <button
                    type="button"
                    className="flex-1 flex items-center gap-4 p-5 text-left min-w-0"
                    onClick={() => toggleOrg(org.id)}
                    aria-expanded={expandedOrgId === org.id}
                  >
                    <div className="w-10 h-10 bg-primary-100 rounded-lg flex items-center justify-center shrink-0">
                      <Building2 className="w-5 h-5 text-primary-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="font-semibold text-slate-900 truncate">{org.name}</p>
                        {callerRole && (
                          <span
                            className={`inline-flex items-center text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
                              callerRole === 'owner'
                                ? 'bg-purple-50 text-purple-700 border-purple-200'
                                : callerRole === 'admin'
                                ? 'bg-blue-50 text-blue-700 border-blue-200'
                                : callerRole === 'superuser'
                                ? 'bg-amber-50 text-amber-700 border-amber-200'
                                : 'bg-slate-100 text-slate-600 border-slate-200'
                            }`}
                          >
                            {callerRole.toUpperCase()}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-slate-400 font-mono mt-0.5">{org.slug}</p>
                      {org.description && (
                        <p className="text-sm text-slate-500 mt-1 truncate">{org.description}</p>
                      )}
                    </div>
                  </button>

                  <div className="flex items-center gap-1 pr-5">
                    {/* Quick Members button */}
                    <button
                      type="button"
                      onClick={() => openMembersDirectly(org)}
                      title="Manage team members"
                      className="p-2 text-slate-400 hover:text-primary-600 rounded-lg hover:bg-primary-50 transition-colors flex items-center gap-1.5 text-xs font-medium"
                    >
                      <Users className="w-4 h-4" />
                      <span className="hidden sm:inline">Members</span>
                    </button>

                    {/* Edit button */}
                    <button
                      type="button"
                      onClick={() => openEditModal(org)}
                      title="Edit organization"
                      className="p-2 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-200/60 transition-colors"
                    >
                      <Pencil className="w-4 h-4" />
                    </button>

                    {/* Delete button */}
                    <button
                      type="button"
                      onClick={() => {
                        setOrgToDelete(org);
                        setDeleteError(null);
                      }}
                      title="Delete organization"
                      className="p-2 text-slate-400 hover:text-red-600 rounded-lg hover:bg-red-50 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>

                    {/* Expand/Collapse chevron */}
                    <button
                      type="button"
                      onClick={() => toggleOrg(org.id)}
                      className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg transition-colors"
                      aria-label={expandedOrgId === org.id ? 'Collapse organization' : 'Expand organization'}
                    >
                      <ChevronRight
                        className={`w-4 h-4 text-slate-400 transition-transform ${
                          expandedOrgId === org.id ? 'rotate-90' : ''
                        }`}
                      />
                    </button>
                  </div>
                </div>

                {/* Expanded content */}
                {expandedOrgId === org.id && (
                  <div className="border-t border-slate-100 bg-slate-50 px-5 py-4">
                    {/* Tabs navigation */}
                    <div className="flex items-center gap-2 mb-4 border-b border-slate-200">
                      <button
                        type="button"
                        onClick={() => switchTab(org.id, 'projects')}
                        className={`pb-2.5 px-3 text-xs font-semibold uppercase tracking-wider flex items-center gap-2 transition-colors border-b-2 -mb-px ${
                          !isCurrentTabMembers
                            ? 'border-primary-600 text-primary-600'
                            : 'border-transparent text-slate-500 hover:text-slate-700'
                        }`}
                      >
                        <FolderOpen className="w-4 h-4" />
                        Projects ({orgProjects[org.id]?.length ?? '…'})
                      </button>
                      <button
                        type="button"
                        onClick={() => switchTab(org.id, 'members')}
                        className={`pb-2.5 px-3 text-xs font-semibold uppercase tracking-wider flex items-center gap-2 transition-colors border-b-2 -mb-px ${
                          isCurrentTabMembers
                            ? 'border-primary-600 text-primary-600'
                            : 'border-transparent text-slate-500 hover:text-slate-700'
                        }`}
                      >
                        <Users className="w-4 h-4" />
                        Team Members ({orgMembers[org.id]?.length ?? '…'})
                      </button>
                    </div>

                    {/* Projects Tab */}
                    {!isCurrentTabMembers && (
                      <div>
                        {loadingProjects === org.id ? (
                          <div className="py-6 text-center text-slate-400 text-sm flex items-center justify-center gap-2">
                            <RefreshCw className="w-4 h-4 animate-spin" />
                            Loading projects…
                          </div>
                        ) : (orgProjects[org.id] ?? []).length === 0 ? (
                          <p className="text-sm text-slate-400 py-4">No projects in this organization.</p>
                        ) : (
                          <div className="space-y-2">
                            {(orgProjects[org.id] ?? []).map((project) => (
                              <div
                                key={project.id}
                                className="flex items-center gap-3 bg-white rounded-lg border border-slate-200 px-4 py-2.5"
                              >
                                <FolderOpen className="w-4 h-4 text-slate-400" />
                                <div className="flex-1 min-w-0">
                                  <p className="text-sm font-medium text-slate-800">{project.name}</p>
                                  {project.app_url && (
                                    <p className="text-xs text-slate-400 truncate">{project.app_url}</p>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Members Tab */}
                    {isCurrentTabMembers && (
                      <div className="space-y-4">
                        {/* Member Actions Bar */}
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-xs text-slate-500">
                            Members of <span className="font-semibold text-slate-700">{org.name}</span> with tenant access.
                          </p>
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => fetchOrgMembers(org.id)}
                              disabled={loadingMembers[org.id]}
                              title="Refresh members"
                              className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-200/60 transition-colors disabled:opacity-50"
                            >
                              <RefreshCw className={`w-3.5 h-3.5 ${loadingMembers[org.id] ? 'animate-spin' : ''}`} />
                            </button>

                            {/* Leave Organization Button */}
                            {callerRole && (
                              <button
                                type="button"
                                onClick={() => openLeaveModal(org)}
                                className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-slate-200 hover:border-red-300 text-slate-600 hover:text-red-700 rounded-lg text-xs font-medium hover:bg-red-50 transition-colors"
                              >
                                <LogOut className="w-3.5 h-3.5" />
                                Leave Organization
                              </button>
                            )}

                            {/* Add Member Button */}
                            {canManageMembers && (
                              <button
                                type="button"
                                onClick={() => openAddMemberModal(org)}
                                className="btn-primary text-xs py-1.5 px-3"
                              >
                                <Plus className="w-3.5 h-3.5" />
                                Add Member
                              </button>
                            )}
                          </div>
                        </div>

                        {/* Loading / Error / Table States */}
                        {loadingMembers[org.id] && !orgMembers[org.id] ? (
                          <div className="py-6 text-center text-slate-400 text-sm flex items-center justify-center gap-2">
                            <RefreshCw className="w-4 h-4 animate-spin" />
                            Loading team members…
                          </div>
                        ) : membersError[org.id] ? (
                          <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 flex items-center justify-between">
                            <span>{membersError[org.id]}</span>
                            <button
                              type="button"
                              onClick={() => fetchOrgMembers(org.id)}
                              className="text-xs font-semibold underline hover:no-underline ml-4"
                            >
                              Retry
                            </button>
                          </div>
                        ) : (orgMembers[org.id] ?? []).length === 0 ? (
                          <p className="text-sm text-slate-400 py-4">No members found in this organization.</p>
                        ) : (
                          <div className="bg-white rounded-lg border border-slate-200 overflow-hidden shadow-xs">
                            <div className="overflow-x-auto">
                              <table className="w-full text-left text-sm">
                                <thead className="bg-slate-50 border-b border-slate-200 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                                  <tr>
                                    <th className="py-2.5 px-4">Member</th>
                                    <th className="py-2.5 px-4">Role</th>
                                    <th className="py-2.5 px-4">Joined</th>
                                    <th className="py-2.5 px-4 text-right">Actions</th>
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-100">
                                  {(orgMembers[org.id] ?? []).map((member) => {
                                    const isSelf = user?.email === member.email;
                                    const canModifyThisMember =
                                      canManageMembers &&
                                      (callerRole === 'owner' ||
                                        callerRole === 'superuser' ||
                                        (callerRole === 'admin' && member.role === 'member'));

                                    return (
                                      <tr key={member.id} className="hover:bg-slate-50/60 transition-colors">
                                        <td className="py-3 px-4">
                                          <div className="flex items-center gap-3">
                                            <div className="w-7 h-7 rounded-full bg-primary-50 text-primary-700 font-semibold text-xs flex items-center justify-center shrink-0">
                                              {member.email.charAt(0).toUpperCase()}
                                            </div>
                                            <div className="min-w-0">
                                              <p className="font-medium text-slate-900 text-sm flex items-center gap-1.5 truncate">
                                                {member.email}
                                                {isSelf && (
                                                  <span className="text-[10px] font-semibold bg-primary-100 text-primary-700 px-1.5 py-0.2 rounded border border-primary-200">
                                                    You
                                                  </span>
                                                )}
                                              </p>
                                            </div>
                                          </div>
                                        </td>
                                        <td className="py-3 px-4">
                                          <span
                                            className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium border ${
                                              member.role === 'owner'
                                                ? 'bg-purple-50 text-purple-700 border-purple-200'
                                                : member.role === 'admin'
                                                ? 'bg-blue-50 text-blue-700 border-blue-200'
                                                : 'bg-slate-100 text-slate-700 border-slate-200'
                                            }`}
                                          >
                                            {member.role === 'owner' && <Shield className="w-3 h-3 text-purple-600" />}
                                            {member.role.charAt(0).toUpperCase() + member.role.slice(1)}
                                          </span>
                                        </td>
                                        <td className="py-3 px-4 text-xs text-slate-400">
                                          {formatDate(member.created_at)}
                                        </td>
                                        <td className="py-3 px-4 text-right">
                                          <div className="flex items-center justify-end gap-1">
                                            {canModifyThisMember && (
                                              <button
                                                type="button"
                                                onClick={() => openChangeRoleModal(org, member)}
                                                title="Change member role"
                                                className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100 transition-colors"
                                              >
                                                <Pencil className="w-3.5 h-3.5" />
                                              </button>
                                            )}

                                            {canModifyThisMember && (
                                              <button
                                                type="button"
                                                onClick={() => openRemoveMemberModal(org, member)}
                                                title="Remove member"
                                                className="p-1.5 text-slate-400 hover:text-red-600 rounded-lg hover:bg-red-50 transition-colors"
                                              >
                                                <Trash2 className="w-3.5 h-3.5" />
                                              </button>
                                            )}
                                          </div>
                                        </td>
                                      </tr>
                                    );
                                  })}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Create Org Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true" aria-labelledby="create-org-title">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setShowModal(false)} />
          <div className="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
            <div className="flex items-center justify-between mb-5">
              <h2 id="create-org-title" className="text-lg font-semibold text-slate-900">New Organization</h2>
              <button type="button" onClick={() => setShowModal(false)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            {formError && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                {formError}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Name <span className="text-red-500">*</span>
                </label>
                <input
                  className="input"
                  placeholder="Acme Corp"
                  value={form.name}
                  onChange={(e) => {
                    setForm((f) => ({
                      ...f,
                      name: e.target.value,
                      slug: slugify(e.target.value),
                    }));
                  }}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Slug <span className="text-red-500">*</span>
                </label>
                <input
                  className="input font-mono"
                  placeholder="acme-corp"
                  value={form.slug}
                  onChange={(e) => setForm((f) => ({ ...f, slug: slugify(e.target.value) }))}
                />
                <p className="text-xs text-slate-400 mt-1">URL-friendly identifier</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Description</label>
                <textarea
                  className="input resize-none"
                  rows={3}
                  placeholder="Optional description"
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                />
              </div>
              <div className="flex gap-3 justify-end pt-2">
                <button type="button" onClick={() => setShowModal(false)} className="btn-secondary" disabled={submitting}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary" disabled={submitting}>
                  {submitting ? 'Creating…' : 'Create Organization'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Org Modal */}
      {editingOrg && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true" aria-labelledby="edit-org-title">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setEditingOrg(null)} />
          <div className="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
            <div className="flex items-center justify-between mb-5">
              <h2 id="edit-org-title" className="text-lg font-semibold text-slate-900">Edit Organization</h2>
              <button type="button" onClick={() => setEditingOrg(null)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            {editError && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                {editError}
              </div>
            )}

            <form onSubmit={handleEditSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Name <span className="text-red-500">*</span>
                </label>
                <input
                  className="input"
                  placeholder="Acme Corp"
                  value={editForm.name}
                  onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Slug <span className="text-red-500">*</span>
                </label>
                <input
                  className="input font-mono"
                  placeholder="acme-corp"
                  value={editForm.slug}
                  onChange={(e) => setEditForm((f) => ({ ...f, slug: slugify(e.target.value) }))}
                />
                <p className="text-xs text-slate-400 mt-1">URL-friendly identifier</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Description</label>
                <textarea
                  className="input resize-none"
                  rows={3}
                  placeholder="Optional description"
                  value={editForm.description}
                  onChange={(e) => setEditForm((f) => ({ ...f, description: e.target.value }))}
                />
              </div>
              <div className="flex gap-3 justify-end pt-2">
                <button type="button" onClick={() => setEditingOrg(null)} className="btn-secondary" disabled={editSubmitting}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary" disabled={editSubmitting}>
                  {editSubmitting ? 'Saving…' : 'Save Changes'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete Org Confirmation Modal */}
      {orgToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true" aria-labelledby="delete-org-title">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => !deleting && setOrgToDelete(null)} />
          <div className="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 id="delete-org-title" className="text-lg font-semibold text-slate-900">Delete Organization</h2>
              <button type="button" onClick={() => !deleting && setOrgToDelete(null)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            {deleteError ? (
              <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800">
                {deleteError}
              </div>
            ) : (
              <p className="text-sm text-slate-600 mb-4">
                Are you sure you want to delete <span className="font-semibold text-slate-900">{orgToDelete.name}</span>? This action cannot be undone.
              </p>
            )}

            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs text-slate-500 mb-5">
              <strong>Dependency Protection:</strong> Organizations containing active projects or members, or the last remaining organization, cannot be deleted to preserve tenant data.
            </div>

            <div className="flex gap-3 justify-end">
              <button type="button" onClick={() => setOrgToDelete(null)} className="btn-secondary" disabled={deleting}>
                {deleteError ? 'Close' : 'Cancel'}
              </button>
              {!deleteError && (
                <button
                  type="button"
                  onClick={handleDeleteOrg}
                  className="inline-flex items-center gap-2 px-4 py-2 bg-red-600 text-white rounded-lg font-medium text-sm hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  disabled={deleting}
                >
                  {deleting ? 'Deleting…' : 'Delete Organization'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Add Member Modal */}
      {activeOrgForAdd && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true" aria-labelledby="add-member-title">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => !addingMember && setActiveOrgForAdd(null)} />
          <div className="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 id="add-member-title" className="text-lg font-semibold text-slate-900">Add Team Member</h2>
                <p className="text-xs text-slate-500 mt-0.5">Add a registered user to {activeOrgForAdd.name}</p>
              </div>
              <button type="button" onClick={() => !addingMember && setActiveOrgForAdd(null)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            {addMemberError && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                {addMemberError}
              </div>
            )}

            <form onSubmit={handleAddMemberSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  User Email <span className="text-red-500">*</span>
                </label>
                <input
                  type="email"
                  className="input"
                  placeholder="colleague@example.com"
                  value={addMemberForm.email}
                  onChange={(e) => setAddMemberForm((f) => ({ ...f, email: e.target.value }))}
                  required
                />
                <p className="text-xs text-slate-400 mt-1">
                  The user must already have a registered account on Noetrix.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Role <span className="text-red-500">*</span>
                </label>
                <select
                  className="input"
                  value={addMemberForm.role}
                  onChange={(e) =>
                    setAddMemberForm((f) => ({
                      ...f,
                      role: e.target.value as 'owner' | 'admin' | 'member',
                    }))
                  }
                >
                  <option value="member">Member (Can run tests, view reports)</option>
                  {(getCallerRoleInOrg(activeOrgForAdd.id) === 'owner' || user?.is_superuser) && (
                    <>
                      <option value="admin">Admin (Can manage projects and members)</option>
                      <option value="owner">Owner (Full tenant control)</option>
                    </>
                  )}
                </select>
                {getCallerRoleInOrg(activeOrgForAdd.id) === 'admin' && (
                  <p className="text-xs text-slate-400 mt-1">
                    Admins may add members with the &apos;member&apos; role only. Owner privileges are required to assign admin or owner roles.
                  </p>
                )}
              </div>

              <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs text-slate-500">
                <strong>Account Requirement:</strong> Adding a member grants them immediate access to this organization. This action does not send email invitations.
              </div>

              <div className="flex gap-3 justify-end pt-2">
                <button
                  type="button"
                  onClick={() => setActiveOrgForAdd(null)}
                  className="btn-secondary"
                  disabled={addingMember}
                >
                  Cancel
                </button>
                <button type="submit" className="btn-primary" disabled={addingMember}>
                  {addingMember ? 'Adding…' : 'Add Member'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Change Member Role Modal */}
      {roleTargetOrg && roleTargetMember && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true" aria-labelledby="change-role-title">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => !changingRole && setRoleTargetOrg(null)} />
          <div className="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 id="change-role-title" className="text-lg font-semibold text-slate-900">Change Member Role</h2>
                <p className="text-xs text-slate-500 mt-0.5">{roleTargetMember.email} in {roleTargetOrg.name}</p>
              </div>
              <button type="button" onClick={() => !changingRole && setRoleTargetOrg(null)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            {changeRoleError && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                {changeRoleError}
              </div>
            )}

            <form onSubmit={handleChangeRoleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Select New Role</label>
                <select
                  className="input"
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value as 'owner' | 'admin' | 'member')}
                >
                  <option value="member">Member</option>
                  {(getCallerRoleInOrg(roleTargetOrg.id) === 'owner' || user?.is_superuser) && (
                    <>
                      <option value="admin">Admin</option>
                      <option value="owner">Owner</option>
                    </>
                  )}
                </select>
              </div>

              {roleTargetMember.role === 'owner' && newRole !== 'owner' && (
                <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-800 flex gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0 text-amber-600 mt-0.5" />
                  <div>
                    <strong>Last-Owner Guard:</strong> If this member is the sole owner of {roleTargetOrg.name}, demotion will be rejected by the server to prevent an ownerless organization.
                  </div>
                </div>
              )}

              <div className="flex gap-3 justify-end pt-2">
                <button
                  type="button"
                  onClick={() => {
                    setRoleTargetOrg(null);
                    setRoleTargetMember(null);
                  }}
                  className="btn-secondary"
                  disabled={changingRole}
                >
                  Cancel
                </button>
                <button type="submit" className="btn-primary" disabled={changingRole}>
                  {changingRole ? 'Updating…' : 'Update Role'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Remove Member Confirmation Modal */}
      {removeTargetOrg && removeTargetMember && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true" aria-labelledby="remove-member-title">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => !removingMember && setRemoveTargetOrg(null)} />
          <div className="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 id="remove-member-title" className="text-lg font-semibold text-slate-900">Remove Member</h2>
              <button type="button" onClick={() => !removingMember && setRemoveTargetOrg(null)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            {removeMemberError ? (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                {removeMemberError}
              </div>
            ) : (
              <p className="text-sm text-slate-600 mb-4">
                Are you sure you want to remove <span className="font-semibold text-slate-900">{removeTargetMember.email}</span> from <span className="font-semibold text-slate-900">{removeTargetOrg.name}</span>?
              </p>
            )}

            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs text-slate-500 mb-5">
              <strong>Evidence Retention:</strong> Removing a member revokes their organization access immediately. All historical test cases, runs, and artifacts created by this user will be preserved.
            </div>

            {removeTargetMember.role === 'owner' && (
              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-800 mb-5 flex gap-2">
                <AlertCircle className="w-4 h-4 shrink-0 text-amber-600 mt-0.5" />
                <div>
                  <strong>Last-Owner Guard:</strong> An organization cannot have zero owners. Removal will be blocked if this user is the last remaining owner.
                </div>
              </div>
            )}

            <div className="flex gap-3 justify-end">
              <button
                type="button"
                onClick={() => {
                  setRemoveTargetOrg(null);
                  setRemoveTargetMember(null);
                }}
                className="btn-secondary"
                disabled={removingMember}
              >
                {removeMemberError ? 'Close' : 'Cancel'}
              </button>
              {!removeMemberError && (
                <button
                  type="button"
                  onClick={handleRemoveMemberSubmit}
                  className="inline-flex items-center gap-2 px-4 py-2 bg-red-600 text-white rounded-lg font-medium text-sm hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  disabled={removingMember}
                >
                  {removingMember ? 'Removing…' : 'Remove Member'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Leave Organization Confirmation Modal */}
      {leaveTargetOrg && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true" aria-labelledby="leave-org-title">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => !leavingOrg && setLeaveTargetOrg(null)} />
          <div className="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 id="leave-org-title" className="text-lg font-semibold text-slate-900">Leave Organization</h2>
              <button type="button" onClick={() => !leavingOrg && setLeaveTargetOrg(null)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            {leaveError ? (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                {leaveError}
              </div>
            ) : (
              <p className="text-sm text-slate-600 mb-4">
                Are you sure you want to leave <span className="font-semibold text-slate-900">{leaveTargetOrg.name}</span>? You will lose access to its projects and test suites.
              </p>
            )}

            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-800 mb-5 flex gap-2">
              <AlertCircle className="w-4 h-4 shrink-0 text-amber-600 mt-0.5" />
              <div>
                <strong>Sole Owner Warning:</strong> If you are the only owner of this organization, you must assign another owner before leaving. Your user account and other organization memberships will not be affected.
              </div>
            </div>

            <div className="flex gap-3 justify-end">
              <button
                type="button"
                onClick={() => setLeaveTargetOrg(null)}
                className="btn-secondary"
                disabled={leavingOrg}
              >
                {leaveError ? 'Close' : 'Cancel'}
              </button>
              {!leaveError && (
                <button
                  type="button"
                  onClick={handleLeaveOrgSubmit}
                  className="inline-flex items-center gap-2 px-4 py-2 bg-amber-600 text-white rounded-lg font-medium text-sm hover:bg-amber-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  disabled={leavingOrg}
                >
                  {leavingOrg ? 'Leaving…' : 'Leave Organization'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
};

export default Organizations;
