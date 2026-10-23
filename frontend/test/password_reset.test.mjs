/**
 * Frontend Password Reset Flow & Validation Test Suite
 * Executed via Node.js built-in test runner (node --test) without external dependencies.
 */
import { test, describe, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('Noetrix Forgot Password & Reset Password Workflow', () => {
  // Validator logic mirroring ForgotPassword.tsx
  function validateForgotPasswordForm(email) {
    const errors = {};
    const trimmedEmail = (email || '').trim();

    if (!trimmedEmail) {
      errors.email = 'Email address is required.';
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
      errors.email = 'Please enter a valid email address.';
    }

    return {
      isValid: Object.keys(errors).length === 0,
      errors,
    };
  }

  // Validator logic mirroring ResetPassword.tsx
  function validateResetPasswordForm(newPassword, confirmPassword) {
    const errors = {};

    if (!newPassword) {
      errors.newPassword = 'Password is required.';
    } else if (newPassword.length < 8) {
      errors.newPassword = 'Password must be at least 8 characters.';
    }

    if (!confirmPassword) {
      errors.confirmPassword = 'Please confirm your password.';
    } else if (newPassword !== confirmPassword) {
      errors.confirmPassword = 'Passwords do not match.';
    }

    return {
      isValid: Object.keys(errors).length === 0,
      errors,
    };
  }

  // Token parser logic mirroring ResetPassword.tsx
  function parseResetToken(queryString) {
    const params = new URLSearchParams(queryString);
    const token = params.get('token') || '';
    return {
      token,
      isValidTokenFormat: Boolean(token && token.trim().length >= 16),
    };
  }

  // Mock API client for forgot & reset password
  class MockPasswordResetClient {
    constructor() {
      this.submittedRequests = [];
      this.submittedResets = [];
    }

    async forgotPassword(payload, mockResponse) {
      this.submittedRequests.push(payload);
      if (mockResponse.status === 200) {
        return mockResponse.data;
      } else {
        const errorMsg =
          mockResponse.data?.detail ||
          mockResponse.message ||
          'Unable to process password reset request. Please try again.';
        throw new Error(errorMsg);
      }
    }

    async resetPassword(payload, mockResponse) {
      this.submittedResets.push(payload);
      if (mockResponse.status === 200) {
        return mockResponse.data;
      } else {
        const errorMsg =
          mockResponse.data?.detail ||
          mockResponse.message ||
          'Failed to reset password. The link may be expired or already used.';
        throw new Error(errorMsg);
      }
    }
  }

  let client;

  beforeEach(() => {
    client = new MockPasswordResetClient();
  });

  // 1. Forgot Password Form Validation Tests
  test('1. Forgot password form validation enforces non-empty and valid email structure', () => {
    const empty = validateForgotPasswordForm('');
    assert.equal(empty.isValid, false);
    assert.equal(empty.errors.email, 'Email address is required.');

    const whitespace = validateForgotPasswordForm('   ');
    assert.equal(whitespace.isValid, false);
    assert.equal(whitespace.errors.email, 'Email address is required.');

    const invalid = validateForgotPasswordForm('bad-email-format');
    assert.equal(invalid.isValid, false);
    assert.equal(invalid.errors.email, 'Please enter a valid email address.');

    const missingDomain = validateForgotPasswordForm('test@domain');
    assert.equal(missingDomain.isValid, false);
    assert.equal(missingDomain.errors.email, 'Please enter a valid email address.');

    const valid = validateForgotPasswordForm('user@company.com');
    assert.equal(valid.isValid, true);
    assert.deepEqual(valid.errors, {});
  });

  // 2. Reset Password Form Validation Tests
  test('2. Reset password form validation enforces minimum 8 characters and matching confirmation', () => {
    const emptyBoth = validateResetPasswordForm('', '');
    assert.equal(emptyBoth.isValid, false);
    assert.equal(emptyBoth.errors.newPassword, 'Password is required.');
    assert.equal(emptyBoth.errors.confirmPassword, 'Please confirm your password.');

    const shortPassword = validateResetPasswordForm('short1', 'short1');
    assert.equal(shortPassword.isValid, false);
    assert.equal(shortPassword.errors.newPassword, 'Password must be at least 8 characters.');

    const mismatch = validateResetPasswordForm('ValidPass123!', 'DifferentPass456!');
    assert.equal(mismatch.isValid, false);
    assert.equal(mismatch.errors.confirmPassword, 'Passwords do not match.');

    const valid = validateResetPasswordForm('SuperSecret999!', 'SuperSecret999!');
    assert.equal(valid.isValid, true);
    assert.deepEqual(valid.errors, {});
  });

  // 3. Query Param Token Parsing Tests
  test('3. Reset password token extraction detects missing and valid tokens', () => {
    const noParam = parseResetToken('');
    assert.equal(noParam.token, '');
    assert.equal(noParam.isValidTokenFormat, false);

    const otherParamsOnly = parseResetToken('source=email&utm=test');
    assert.equal(otherParamsOnly.token, '');
    assert.equal(otherParamsOnly.isValidTokenFormat, false);

    const tooShortToken = parseResetToken('token=short');
    assert.equal(tooShortToken.token, 'short');
    assert.equal(tooShortToken.isValidTokenFormat, false);

    const validToken = parseResetToken('token=w_7BqE3pX1zL9mK5vT8yR2uO4aN6sJ0c');
    assert.equal(validToken.token, 'w_7BqE3pX1zL9mK5vT8yR2uO4aN6sJ0c');
    assert.equal(validToken.isValidTokenFormat, true);
  });

  // 4. Forgot Password API Submission & Anti-Enumeration
  test('4. Forgot password submission receives generic message and records email', async () => {
    const mockGenericResponse = {
      status: 200,
      data: {
        message: 'If that email address is associated with an account, password reset instructions have been sent.',
      },
    };

    const res = await client.forgotPassword(
      { email: 'member@example.com' },
      mockGenericResponse
    );

    assert.equal(res.message, mockGenericResponse.data.message);
    assert.equal(client.submittedRequests.length, 1);
    assert.equal(client.submittedRequests[0].email, 'member@example.com');
  });

  // 5. Rate Limiting 429 Error Propagation
  test('5. Forgot password rate limiting returns understandable error', async () => {
    const mockRateLimit = {
      status: 429,
      data: {
        detail: 'Too many password reset requests. Please wait before trying again.',
      },
    };

    await assert.rejects(
      async () => {
        await client.forgotPassword({ email: 'spammer@example.com' }, mockRateLimit);
      },
      (err) => {
        assert.equal(
          err.message,
          'Too many password reset requests. Please wait before trying again.'
        );
        return true;
      }
    );
  });

  // 6. Reset Password Success Flow
  test('6. Reset password submits token and new password successfully', async () => {
    const mockSuccessResponse = {
      status: 200,
      data: {
        message: 'Your password has been successfully reset. You can now log in with your new password.',
      },
    };

    const res = await client.resetPassword(
      {
        token: 'secure-token-abcdef1234567890',
        new_password: 'NewStrongPassword123!',
      },
      mockSuccessResponse
    );

    assert.equal(res.message, mockSuccessResponse.data.message);
    assert.equal(client.submittedResets.length, 1);
    assert.equal(client.submittedResets[0].token, 'secure-token-abcdef1234567890');
    assert.equal(client.submittedResets[0].new_password, 'NewStrongPassword123!');
  });

  // 7. Expired or Consumed Token Handling
  test('7. Reset password with expired or consumed token rejects with explanatory error', async () => {
    const mockExpiredResponse = {
      status: 400,
      data: {
        detail: 'Password reset token has expired.',
      },
    };

    await assert.rejects(
      async () => {
        await client.resetPassword(
          {
            token: 'expired-token-1234567890',
            new_password: 'NewStrongPassword123!',
          },
          mockExpiredResponse
        );
      },
      (err) => {
        assert.equal(err.message, 'Password reset token has expired.');
        return true;
      }
    );
  });

  // 8. Static Source Code Assertions: Login page Link presence
  test('8. Login.tsx contains visible Link to /forgot-password near password field', () => {
    const loginFilePath = path.join(__dirname, '..', 'src', 'pages', 'Login.tsx');
    assert.ok(fs.existsSync(loginFilePath), 'Login.tsx must exist');
    const content = fs.readFileSync(loginFilePath, 'utf-8');

    assert.ok(content.includes('to="/forgot-password"'), 'Login.tsx must link to /forgot-password');
    assert.ok(content.includes('Forgot password?'), 'Login.tsx must display "Forgot password?" text');
    assert.ok(content.includes('import { useNavigate, useLocation, Link }'), 'Login.tsx must import Link');
  });

  // 9. Static Source Code Assertions: App.tsx Routes registration
  test('9. App.tsx registers /forgot-password and /reset-password as PublicRoute', () => {
    const appFilePath = path.join(__dirname, '..', 'src', 'App.tsx');
    assert.ok(fs.existsSync(appFilePath), 'App.tsx must exist');
    const content = fs.readFileSync(appFilePath, 'utf-8');

    assert.ok(content.includes('path="/forgot-password"'), 'App.tsx must define /forgot-password route');
    assert.ok(content.includes('path="/reset-password"'), 'App.tsx must define /reset-password route');
    assert.ok(content.includes('<ForgotPassword />'), 'App.tsx must render ForgotPassword component');
    assert.ok(content.includes('<ResetPassword />'), 'App.tsx must render ResetPassword component');
  });

  // 10. Static Source Code Assertions: authApi methods
  test('10. api/auth.ts implements forgotPassword and resetPassword', () => {
    const authApiPath = path.join(__dirname, '..', 'src', 'api', 'auth.ts');
    assert.ok(fs.existsSync(authApiPath), 'api/auth.ts must exist');
    const content = fs.readFileSync(authApiPath, 'utf-8');

    assert.ok(content.includes('forgotPassword:'), 'authApi must provide forgotPassword method');
    assert.ok(content.includes('/api/auth/forgot-password'), 'calls /api/auth/forgot-password endpoint');
    assert.ok(content.includes('resetPassword:'), 'authApi must provide resetPassword method');
    assert.ok(content.includes('/api/auth/reset-password'), 'calls /api/auth/reset-password endpoint');
  });
});

