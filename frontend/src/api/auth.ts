import apiClient, { setAuthToken } from './client';
import { LoginCredentials, TokenResponse, UserProfile } from '../types';

export const authApi = {
  login: async (credentials: LoginCredentials): Promise<TokenResponse> => {
    const res = await apiClient.post<TokenResponse>('/api/auth/login', credentials);
    if (res.data?.access_token) {
      setAuthToken(res.data.access_token);
    }
    return res.data;
  },

  logout: async (): Promise<void> => {
    try {
      await apiClient.post('/api/auth/logout');
    } finally {
      setAuthToken(null);
    }
  },

  me: async (): Promise<UserProfile> => {
    const res = await apiClient.get<UserProfile>('/api/auth/me');
    return res.data;
  },
};

export default authApi;
