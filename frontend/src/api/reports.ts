import apiClient from './client';
import { DashboardStats, TestRun, TestResult } from '../types';

export const reportsApi = {
  getDashboardStats: async (): Promise<DashboardStats> => {
    const res = await apiClient.get('/api/dashboard/stats');
    return res.data;
  },

  getRunReport: async (runId: string): Promise<{ run: TestRun; results: TestResult[] }> => {
    const [runRes, resultsRes] = await Promise.all([
      apiClient.get(`/api/runs/${runId}`),
      apiClient.get(`/api/runs/${runId}/results`),
    ]);
    return { run: runRes.data, results: resultsRes.data };
  },

  getArtifactUrl: (filePath: string): string => {
    const base = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
    return `${base}/api/artifacts/file?path=${encodeURIComponent(filePath)}`;
  },

  fetchArtifactBlob: async (options: { id?: string; path?: string }): Promise<Blob> => {
    let url: string;
    if (options.id) {
      url = `/api/artifacts/${options.id}`;
    } else if (options.path) {
      url = `/api/artifacts/file?path=${encodeURIComponent(options.path)}`;
    } else {
      throw new Error('No artifact ID or path provided');
    }
    const res = await apiClient.get<Blob>(url, { responseType: 'blob' });
    return res.data;
  },

  checkHealth: async (): Promise<{ status: string; playwright_available: boolean }> => {
    const res = await apiClient.get('/health');
    return res.data;
  },
};

