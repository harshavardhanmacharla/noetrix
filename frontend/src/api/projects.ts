import apiClient from './client';
import { Project } from '../types';

export const projectsApi = {
  list: async (orgId?: string): Promise<Project[]> => {
    const params = orgId ? { org_id: orgId } : {};
    const res = await apiClient.get('/api/projects', { params });
    return res.data;
  },

  get: async (id: string): Promise<Project> => {
    const res = await apiClient.get(`/api/projects/${id}`);
    return res.data;
  },

  create: async (data: {
    name: string;
    slug: string;
    description?: string;
    org_id: string;
    app_url?: string;
  }): Promise<Project> => {
    const res = await apiClient.post('/api/projects', data);
    return res.data;
  },

  update: async (id: string, data: Partial<Project>): Promise<Project> => {
    const res = await apiClient.put(`/api/projects/${id}`, data);
    return res.data;
  },

  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/api/projects/${id}`);
  },
};
