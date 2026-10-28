import { apiClient } from './client';

export interface CapturedElement {
  id: string;
  tag: string;
  type?: string | null;
  role?: string | null;
  accessible_name?: string | null;
  label?: string | null;
  placeholder?: string | null;
  element_id?: string | null;
  name?: string | null;
  data_testid?: string | null;
  href?: string | null;
  visible_text?: string | null;
  is_visible: boolean;
  is_enabled: boolean;
  is_unique: boolean;
  frame_context?: string | null;
  candidate_locators: string[];
  suggested_intent?: string | null;
}

export interface DiscoverySnapshot {
  id: string;
  session_id: string;
  page_url: string;
  page_title?: string | null;
  elements_count: number;
  created_at: string;
  inventory_data?: {
    url: string;
    page_title: string;
    headings: Array<{ tag: string; text: string }>;
    elements: CapturedElement[];
    frames: Array<{ index: number; id: string; name: string; src: string }>;
  } | null;
}

export interface DiscoverySession {
  id: string;
  project_id: string;
  user_id: string;
  app_url: string;
  current_url?: string | null;
  current_title?: string | null;
  status: 'active' | 'completed' | 'expired' | 'failed';
  created_at: string;
  updated_at: string;
  closed_at?: string | null;
  snapshots_count: number;
  latest_snapshot?: DiscoverySnapshot | null;
}

export interface ValidateTargetResult {
  status: 'resolved_unique' | 'ambiguous' | 'not_found' | 'invalid_syntax';
  target: string;
  action: string;
  matched_count: number;
  candidates: Array<Record<string, unknown>>;
  recommended_locator?: string | null;
  suggested_intent?: string | null;
  message: string;
}

export interface CandidateElementMatch {
  snapshot_id: string;
  snapshot_title?: string | null;
  snapshot_url: string;
  element: CapturedElement;
  match_score: number;
  recommended_locator?: string | null;
  live_validated: boolean;
  live_match_count: number;
}

export interface SearchInventoryResponse {
  session_id: string;
  query: string;
  action?: string | null;
  matches: CandidateElementMatch[];
  total_matches: number;
}

export interface DiscoverySessionExport {
  schema_version: string;
  exported_at: string;
  session: DiscoverySession;
  total_snapshots: number;
  total_elements: number;
  snapshots: Array<{
    id: string;
    session_id: string;
    page_url: string;
    page_title?: string | null;
    elements_count: number;
    created_at: string;
    headings: Array<{ tag: string; text: string }>;
    frames: Array<{ index: number; id: string; name: string; src: string }>;
    elements: CapturedElement[];
  }>;
}

export const discoveryApi = {
  startSession: async (data: {
    project_id: string;
    url: string;
    headless?: boolean;
  }): Promise<DiscoverySession> => {
    const res = await apiClient.post<DiscoverySession>('/api/discovery/sessions', data);
    return res.data;
  },

  listSessions: async (projectId?: string): Promise<DiscoverySession[]> => {
    const res = await apiClient.get<DiscoverySession[]>('/api/discovery/sessions', {
      params: projectId ? { project_id: projectId } : undefined,
    });
    return res.data;
  },

  getSession: async (sessionId: string): Promise<DiscoverySession> => {
    const res = await apiClient.get<DiscoverySession>(`/api/discovery/sessions/${sessionId}`);
    return res.data;
  },

  captureInventory: async (sessionId: string): Promise<DiscoverySnapshot> => {
    const res = await apiClient.post<DiscoverySnapshot>(
      `/api/discovery/sessions/${sessionId}/inventory`
    );
    return res.data;
  },

  listSnapshots: async (sessionId: string, order: 'asc' | 'desc' = 'asc'): Promise<DiscoverySnapshot[]> => {
    const res = await apiClient.get<DiscoverySnapshot[]>(
      `/api/discovery/sessions/${sessionId}/snapshots`,
      { params: { order } }
    );
    return res.data;
  },

  getSnapshot: async (sessionId: string, snapshotId: string): Promise<DiscoverySnapshot> => {
    const res = await apiClient.get<DiscoverySnapshot>(
      `/api/discovery/sessions/${sessionId}/snapshots/${snapshotId}`
    );
    return res.data;
  },

  exportSessionJson: async (sessionId: string): Promise<DiscoverySessionExport> => {
    const res = await apiClient.get<DiscoverySessionExport>(
      `/api/discovery/sessions/${sessionId}/export`
    );
    return res.data;
  },

  searchInventory: async (
    sessionId: string,
    data: { query: string; action?: string; snapshot_id?: string }
  ): Promise<SearchInventoryResponse> => {
    const res = await apiClient.post<SearchInventoryResponse>(
      `/api/discovery/sessions/${sessionId}/search-inventory`,
      data
    );
    return res.data;
  },

  validateTarget: async (
    sessionId: string,
    data: { target: string; action: string }
  ): Promise<ValidateTargetResult> => {
    const res = await apiClient.post<ValidateTargetResult>(
      `/api/discovery/sessions/${sessionId}/validate-target`,
      data
    );
    return res.data;
  },

  navigate: async (sessionId: string, url: string): Promise<DiscoverySession> => {
    const res = await apiClient.post<DiscoverySession>(
      `/api/discovery/sessions/${sessionId}/navigate`,
      { url }
    );
    return res.data;
  },

  closeSession: async (sessionId: string): Promise<{ status: string; session_id: string; snapshots_saved?: number; message?: string }> => {
    const res = await apiClient.post<{ status: string; session_id: string; snapshots_saved?: number; message?: string }>(
      `/api/discovery/sessions/${sessionId}/close`
    );
    return res.data;
  },
};


