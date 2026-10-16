import apiClient from './client';
import { TestRun, TestResult, Artifact } from '../types';

export const testRunsApi = {
  list: async (projectId?: string): Promise<TestRun[]> => {
    const params = projectId ? { project_id: projectId } : {};
    const res = await apiClient.get('/api/runs', { params });
    return res.data;
  },

  get: async (id: string): Promise<TestRun> => {
    const res = await apiClient.get(`/api/runs/${id}`);
    return res.data;
  },

  create: async (data: {
    project_id: string;
    test_case_ids?: string[];
  }): Promise<TestRun> => {
    const res = await apiClient.post('/api/runs', data);
    return res.data;
  },

  getResults: async (runId: string): Promise<TestResult[]> => {
    const res = await apiClient.get(`/api/runs/${runId}/results`);
    return res.data;
  },

  getArtifacts: async (runId: string): Promise<Artifact[]> => {
    const res = await apiClient.get(`/api/runs/${runId}/artifacts`);
    return res.data;
  },

  cancel: async (id: string): Promise<void> => {
    await apiClient.post(`/api/runs/${id}/cancel`);
  },
};
