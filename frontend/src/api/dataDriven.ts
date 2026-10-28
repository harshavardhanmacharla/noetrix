import apiClient from './client';
import {
  TestCasePlaceholdersResponse,
  DataDrivenValidationResponse,
  DataDrivenRunRequest,
  DataDrivenPreviewResponse,
  TestRun,
} from '../types';

export const dataDrivenApi = {
  getPlaceholders: async (testCaseId: string): Promise<TestCasePlaceholdersResponse> => {
    const res = await apiClient.get(`/api/test-cases/${testCaseId}/placeholders`);
    return res.data;
  },

  validateData: async (
    testCaseId: string,
    records: Record<string, string>[]
  ): Promise<DataDrivenValidationResponse> => {
    const res = await apiClient.post(`/api/test-cases/${testCaseId}/validate-data`, {
      test_case_id: testCaseId,
      records,
    });
    return res.data;
  },

  previewData: async (
    testCaseId: string,
    record: Record<string, string>
  ): Promise<DataDrivenPreviewResponse> => {
    const res = await apiClient.post(`/api/test-cases/${testCaseId}/preview-data`, {
      test_case_id: testCaseId,
      record,
    });
    return res.data;
  },

  startRun: async (
    projectId: string,
    payload: DataDrivenRunRequest
  ): Promise<TestRun> => {
    const res = await apiClient.post(`/api/projects/${projectId}/data-driven-runs`, payload);
    return res.data;
  },
};

