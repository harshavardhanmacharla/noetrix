import apiClient from './client';
import { ProjectVariable, ProjectVariableCreate, ProjectVariableUpdate } from '../types';

export const projectVariablesApi = {
  list: async (projectId: string): Promise<ProjectVariable[]> => {
    const res = await apiClient.get(`/api/projects/${projectId}/variables`);
    return res.data;
  },

  create: async (projectId: string, data: ProjectVariableCreate): Promise<ProjectVariable> => {
    const res = await apiClient.post(`/api/projects/${projectId}/variables`, data);
    return res.data;
  },

  update: async (
    projectId: string,
    variableId: string,
    data: ProjectVariableUpdate
  ): Promise<ProjectVariable> => {
    const res = await apiClient.put(`/api/projects/${projectId}/variables/${variableId}`, data);
    return res.data;
  },

  delete: async (projectId: string, variableId: string): Promise<void> => {
    await apiClient.delete(`/api/projects/${projectId}/variables/${variableId}`);
  },
};

