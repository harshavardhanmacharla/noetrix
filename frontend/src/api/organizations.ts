import apiClient from './client';
import { Organization, OrganizationMember } from '../types';

export const organizationsApi = {
  list: async (): Promise<Organization[]> => {
    const res = await apiClient.get('/api/organizations');
    return res.data;
  },

  get: async (id: string): Promise<Organization> => {
    const res = await apiClient.get(`/api/organizations/${id}`);
    return res.data;
  },

  create: async (data: { name: string; slug: string; description?: string }): Promise<Organization> => {
    const res = await apiClient.post('/api/organizations', data);
    return res.data;
  },

  update: async (id: string, data: Partial<Organization>): Promise<Organization> => {
    const res = await apiClient.put(`/api/organizations/${id}`, data);
    return res.data;
  },

  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/api/organizations/${id}`);
  },

  listMembers: async (orgId: string): Promise<OrganizationMember[]> => {
    const res = await apiClient.get(`/api/organizations/${orgId}/members`);
    return res.data;
  },

  addMember: async (
    orgId: string,
    data: { email: string; role: 'owner' | 'admin' | 'member' }
  ): Promise<OrganizationMember> => {
    const res = await apiClient.post(`/api/organizations/${orgId}/members`, data);
    return res.data;
  },

  updateMemberRole: async (
    orgId: string,
    userId: string,
    data: { role: 'owner' | 'admin' | 'member' }
  ): Promise<OrganizationMember> => {
    const res = await apiClient.patch(`/api/organizations/${orgId}/members/${userId}`, data);
    return res.data;
  },

  removeMember: async (orgId: string, userId: string): Promise<void> => {
    await apiClient.delete(`/api/organizations/${orgId}/members/${userId}`);
  },

  leaveOrganization: async (orgId: string): Promise<void> => {
    await apiClient.post(`/api/organizations/${orgId}/leave`);
  },
};
