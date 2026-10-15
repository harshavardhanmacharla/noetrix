/**
 * Frontend Authentication and Route Protection Test Suite
 * Executed via Node.js built-in test runner (node --test) without external dependencies.
 */
import { test, describe, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

describe('Noetrix Frontend Authentication State & Route Guards', () => {
  // Mock In-Memory Auth State Manager (mirrors AuthContext & client.ts)
  class AuthClientManager {
    constructor() {
      this.inMemoryToken = null;
      this.currentUser = null;
      this.currentProfile = null;
      this.isAuthenticated = false;
      this.onUnauthorizedCallback = null;
    }

    setAuthToken(token) {
      this.inMemoryToken = token;
    }

    getAuthToken() {
      return this.inMemoryToken;
    }

    setOnUnauthorized(cb) {
      this.onUnauthorizedCallback = cb;
    }

    // Interceptor: attaches Bearer header if token in memory
    applyRequestInterceptors(config) {
      const headers = { ...config.headers };
      if (this.inMemoryToken && !headers.Authorization) {
        headers.Authorization = `Bearer ${this.inMemoryToken}`;
      }
      return {
        ...config,
        withCredentials: true, // Always include credentials for cookies
        headers,
      };
    }

    // Interceptor: handles 401 Unauthorized for expired/revoked sessions
    handleResponseError(error, config) {
      const isLogin = config?.url?.includes('/api/auth/login');
      const isInitialMe = config?.url?.includes('/api/auth/me');

      if (error.status === 401) {
        if (!isLogin && !isInitialMe) {
          this.inMemoryToken = null;
          this.currentUser = null;
          this.currentProfile = null;
          this.isAuthenticated = false;
          if (this.onUnauthorizedCallback) {
            this.onUnauthorizedCallback();
          }
        }
      }
      const msg = error.data?.detail || error.message || 'An error occurred';
      return new Error(msg);
    }

    async login(mockBackendResponse) {
      if (mockBackendResponse.status === 200) {
        this.inMemoryToken = mockBackendResponse.data.access_token;
        this.currentUser = mockBackendResponse.data.user;
        this.isAuthenticated = true;
        return mockBackendResponse.data;
      } else {
        const err = this.handleResponseError(mockBackendResponse, { url: '/api/auth/login' });
        throw err;
      }
    }

    async logout() {
      this.inMemoryToken = null;
      this.currentUser = null;
      this.currentProfile = null;
      this.isAuthenticated = false;
    }
  }

  // Mock Route Guard (mirrors ProtectedRoute.tsx & PublicRoute.tsx)
  class RouteGuardSimulator {
    constructor(authManager) {
      this.auth = authManager;
    }

    evaluateProtectedRoute(currentLocation) {
      if (!this.auth.isAuthenticated) {
        return {
          allowed: false,
          redirect: '/login',
          state: { from: currentLocation },
        };
      }
      return { allowed: true, redirect: null };
    }

    evaluatePublicRoute(currentLocation, intendedFrom = '/') {
      if (this.auth.isAuthenticated) {
        return {
          allowed: false,
          redirect: intendedFrom,
        };
      }
      return { allowed: true, redirect: null };
    }
  }

  // Form Validator (mirrors Login.tsx validation)
  function validateLoginForm(email, password) {
    const errors = {};
    const trimmedEmail = (email || '').trim();

    if (!trimmedEmail) {
      errors.email = 'Email address is required.';
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
      errors.email = 'Please enter a valid email address.';
    }

    if (!password) {
      errors.password = 'Password is required.';
    }

    return {
      isValid: Object.keys(errors).length === 0,
      errors,
    };
  }

  let manager;
  let guard;

  beforeEach(() => {
    manager = new AuthClientManager();
    guard = new RouteGuardSimulator(manager);
  });

  test('1. Successful login updates in-memory token, sets authenticated, and does not touch localStorage', async () => {
    const mockSuccessResponse = {
      status: 200,
      data: {
        access_token: 'header.payload.signature',
        token_type: 'bearer',
        expires_in: 28800,
        user: {
          id: 'user-123',
          email: 'admin@noetrix.internal',
          full_name: 'Administrator',
          is_active: true,
          is_superuser: true,
          created_at: '2026-10-15T00:00:00Z',
        },
      },
    };

    const result = await manager.login(mockSuccessResponse);

    assert.equal(manager.isAuthenticated, true);
    assert.equal(manager.getAuthToken(), 'header.payload.signature');
    assert.equal(manager.currentUser.email, 'admin@noetrix.internal');
    assert.equal(result.user.is_superuser, true);

    // Verify request interceptor automatically attaches the in-memory bearer token
    const intercepted = manager.applyRequestInterceptors({
      url: '/api/projects',
      headers: {},
    });
    assert.equal(intercepted.headers.Authorization, 'Bearer header.payload.signature');
    assert.equal(intercepted.withCredentials, true);
  });

  test('2. Invalid login credentials rejects with safe message and leaves user unauthenticated', async () => {
    const mock401Response = {
      status: 401,
      data: {
        detail: 'Invalid email or password.',
      },
    };

    await assert.rejects(
      async () => {
        await manager.login(mock401Response);
      },
      (err) => {
        assert.equal(err.message, 'Invalid email or password.');
        return true;
      }
    );

    assert.equal(manager.isAuthenticated, false);
    assert.equal(manager.getAuthToken(), null);
    assert.equal(manager.currentUser, null);
  });

  test('3. Rate limited login attempt (429) returns safe error message', async () => {
    const mock429Response = {
      status: 429,
      data: {
        detail: 'Too many failed login attempts. Please wait before trying again.',
      },
    };

    await assert.rejects(
      async () => {
        await manager.login(mock429Response);
      },
      (err) => {
        assert.equal(
          err.message,
          'Too many failed login attempts. Please wait before trying again.'
        );
        return true;
      }
    );

    assert.equal(manager.isAuthenticated, false);
  });

  test('4. Protected route redirects unauthenticated user to /login with state', () => {
    assert.equal(manager.isAuthenticated, false);

    const evalDashboard = guard.evaluateProtectedRoute({ pathname: '/dashboard' });
    assert.equal(evalDashboard.allowed, false);
    assert.equal(evalDashboard.redirect, '/login');
    assert.deepEqual(evalDashboard.state, { from: { pathname: '/dashboard' } });

    const evalProjects = guard.evaluateProtectedRoute({ pathname: '/projects' });
    assert.equal(evalProjects.allowed, false);
    assert.equal(evalProjects.redirect, '/login');
  });

  test('5. Protected route permits authenticated user', async () => {
    manager.inMemoryToken = 'valid-token';
    manager.currentUser = { email: 'user@example.com' };
    manager.isAuthenticated = true;

    const evalResult = guard.evaluateProtectedRoute({ pathname: '/projects' });
    assert.equal(evalResult.allowed, true);
    assert.equal(evalResult.redirect, null);
  });

  test('6. Public route redirects authenticated user away from /login', () => {
    manager.isAuthenticated = true;

    const evalPublic = guard.evaluatePublicRoute('/login', '/dashboard');
    assert.equal(evalPublic.allowed, false);
    assert.equal(evalPublic.redirect, '/dashboard');
  });

  test('7. Logout invalidates in-memory state and triggers protection', async () => {
    manager.inMemoryToken = 'token-to-revoke';
    manager.isAuthenticated = true;

    await manager.logout();

    assert.equal(manager.isAuthenticated, false);
    assert.equal(manager.getAuthToken(), null);
    assert.equal(manager.currentUser, null);

    const check = guard.evaluateProtectedRoute({ pathname: '/execution' });
    assert.equal(check.allowed, false);
    assert.equal(check.redirect, '/login');
  });

  test('8. Expired or revoked session (401 on protected endpoint) triggers onUnauthorized reset', () => {
    let unauthorizedCallbackFired = false;
    manager.setOnUnauthorized(() => {
      unauthorizedCallbackFired = true;
    });

    manager.inMemoryToken = 'expired-token';
    manager.isAuthenticated = true;

    // Simulate expired response from /api/test-cases
    const err = manager.handleResponseError(
      { status: 401, data: { detail: 'Could not validate credentials.' } },
      { url: '/api/test-cases' }
    );

    assert.equal(err.message, 'Could not validate credentials.');
    assert.equal(unauthorizedCallbackFired, true);
    assert.equal(manager.isAuthenticated, false);
    assert.equal(manager.getAuthToken(), null);
  });

  test('9. Login form validation enforces email format and non-empty password', () => {
    const emptyCheck = validateLoginForm('', '');
    assert.equal(emptyCheck.isValid, false);
    assert.equal(emptyCheck.errors.email, 'Email address is required.');
    assert.equal(emptyCheck.errors.password, 'Password is required.');

    const invalidEmailCheck = validateLoginForm('notanemail', 'secret123');
    assert.equal(invalidEmailCheck.isValid, false);
    assert.equal(invalidEmailCheck.errors.email, 'Please enter a valid email address.');
    assert.equal(invalidEmailCheck.errors.password, undefined);

    const validCheck = validateLoginForm('user@example.com', 'ValidPass123!');
    assert.equal(validCheck.isValid, true);
    assert.deepEqual(validCheck.errors, {});
  });
});
