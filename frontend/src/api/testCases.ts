import apiClient from './client';
import { TestCase, ValidationResult, ParseInstructionsResponse } from '../types';

export const testCasesApi = {
  list: async (projectId?: string): Promise<TestCase[]> => {
    const params = projectId ? { project_id: projectId } : {};
    const res = await apiClient.get('/api/test-cases', { params });
    return res.data;
  },

  get: async (id: string): Promise<TestCase> => {
    const res = await apiClient.get(`/api/test-cases/${id}`);
    return res.data;
  },

  parseInstructions: async (
    projectId: string,
    instructions: string[] | string
  ): Promise<ParseInstructionsResponse> => {
    const payload =
      typeof instructions === 'string'
        ? { project_id: projectId, raw_text: instructions }
        : { project_id: projectId, instructions };
    const res = await apiClient.post('/api/test-cases/parse-instructions', payload);
    return res.data;
  },

  createFromInstructions: async (
    projectId: string,
    name: string,
    instructions: string[] | string,
    description?: string
  ): Promise<TestCase> => {
    const payload = {
      project_id: projectId,
      name,
      description,
      ...(typeof instructions === 'string' ? { raw_text: instructions } : { instructions }),
    };
    const res = await apiClient.post('/api/test-cases/create-from-instructions', payload);
    return res.data;
  },

  uploadCsv: async (projectId: string, file: File): Promise<ValidationResult> => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('project_id', projectId);
    const res = await apiClient.post('/api/test-cases/upload-csv', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    const val = res.data?.validation || res.data;
    return {
      is_valid: Boolean(val?.is_valid),
      errors: Array.isArray(val?.errors) ? val.errors : [],
      warnings: Array.isArray(val?.warnings) ? val.warnings : [],
      row_count: val?.row_count ?? 0,
      test_case_count: val?.test_case_count ?? 0,
      parsed_cases: val?.parsed_cases,
    };
  },

  validateCsv: async (file: File): Promise<ValidationResult> => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await apiClient.post('/api/test-cases/validate-csv', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    const val = res.data?.validation || res.data;
    return {
      is_valid: Boolean(val?.is_valid),
      errors: Array.isArray(val?.errors) ? val.errors : [],
      warnings: Array.isArray(val?.warnings) ? val.warnings : [],
      row_count: val?.row_count ?? 0,
      test_case_count: val?.test_case_count ?? 0,
      parsed_cases: val?.parsed_cases,
    };
  },

  downloadTemplate: async (): Promise<Blob> => {
    const res = await apiClient.get('/api/csv-template', { responseType: 'blob' });
    return res.data;
  },

  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/api/test-cases/${id}`);
  },
};
