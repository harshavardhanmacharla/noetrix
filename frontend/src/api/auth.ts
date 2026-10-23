import apiClient, { setAuthToken } from './client';
import {
  ForgotPasswordPayload,
  GenericMessageResponse,
  LoginCredentials,
  RegisterPayload,
  ResetPasswordPayload,
  TokenResponse,
  TokenVerificationResponse,
  UserProfile,
} from '../types';

export const authApi = {
  login: async (credentials: LoginCredentials): Promise<TokenResponse> => {
    const res = await apiClient.post<TokenResponse>('/api/auth/login', credentials);
    if (res.data?.access_token) {
      setAuthToken(res.data.access_token);
    }
    return res.data;
  },

  register: async (payload: RegisterPayload): Promise<TokenResponse> => {
    const res = await apiClient.post<TokenResponse>('/api/auth/register', payload);
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

  forgotPassword: async (payload: ForgotPasswordPayload): Promise<GenericMessageResponse> => {
    const res = await apiClient.post<GenericMessageResponse>('/api/auth/forgot-password', payload);
    return res.data;
  },

  resetPassword: async (payload: ResetPasswordPayload): Promise<GenericMessageResponse> => {
    const res = await apiClient.post<GenericMessageResponse>('/api/auth/reset-password', payload);
    return res.data;
  },

  verifyResetToken: async (token: string): Promise<TokenVerificationResponse> => {
    const res = await apiClient.get<TokenVerificationResponse>(
      `/api/auth/verify-reset-token?token=${encodeURIComponent(token)}`
    );
    return res.data;
  },

  getDevLatestResetLink: async (email: string): Promise<{ email: string; reset_url: string }> => {
    const res = await apiClient.get<{ email: string; reset_url: string }>(
      `/api/auth/dev/latest-reset-link?email=${encodeURIComponent(email)}`
    );
    return res.data;
  },
};

export default authApi;
