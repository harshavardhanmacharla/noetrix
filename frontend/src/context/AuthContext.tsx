import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { AuthContextType, LoginCredentials, RegisterPayload, User, UserProfile } from '../types';
import { authApi } from '../api/auth';
import { setAuthToken, setOnUnauthorized } from '../api/client';

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const refreshSession = useCallback(async () => {
    try {
      const userProfile = await authApi.me();
      setUser(userProfile.user);
      setProfile(userProfile);
      setIsAuthenticated(true);
    } catch {
      setUser(null);
      setProfile(null);
      setToken(null);
      setAuthToken(null);
      setIsAuthenticated(false);
    }
  }, []);

  useEffect(() => {
    let mounted = true;

    const initAuth = async () => {
      try {
        const userProfile = await authApi.me();
        if (mounted) {
          setUser(userProfile.user);
          setProfile(userProfile);
          setIsAuthenticated(true);
        }
      } catch {
        if (mounted) {
          setUser(null);
          setProfile(null);
          setToken(null);
          setAuthToken(null);
          setIsAuthenticated(false);
        }
      } finally {
        if (mounted) {
          setIsLoading(false);
        }
      }
    };

    // Global 401 handler when a session is revoked or expired
    setOnUnauthorized(() => {
      if (mounted) {
        setUser(null);
        setProfile(null);
        setToken(null);
        setIsAuthenticated(false);
      }
    });

    initAuth();

    return () => {
      mounted = false;
      setOnUnauthorized(null);
    };
  }, []);

  const login = useCallback(async (credentials: LoginCredentials) => {
    const tokenResp = await authApi.login(credentials);
    setToken(tokenResp.access_token);
    setUser(tokenResp.user);
    setIsAuthenticated(true);

    // Attempt to load full user profile with organization memberships
    try {
      const userProfile = await authApi.me();
      setProfile(userProfile);
      setUser(userProfile.user);
    } catch {
      // Fallback: minimal profile from token response
      setProfile({
        user: tokenResp.user,
        memberships: [],
      });
    }
  }, []);

  const register = useCallback(async (data: RegisterPayload) => {
    const tokenResp = await authApi.register(data);
    setToken(tokenResp.access_token);
    setUser(tokenResp.user);
    setIsAuthenticated(true);

    try {
      const userProfile = await authApi.me();
      setProfile(userProfile);
      setUser(userProfile.user);
    } catch {
      setProfile({
        user: tokenResp.user,
        memberships: [],
      });
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // Even if server call fails, clear local auth state safely
    } finally {
      setUser(null);
      setProfile(null);
      setToken(null);
      setAuthToken(null);
      setIsAuthenticated(false);
    }
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        profile,
        token,
        isAuthenticated,
        isLoading,
        login,
        register,
        logout,
        refreshSession,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

export default AuthContext;
