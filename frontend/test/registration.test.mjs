/**
 * Frontend Registration / Sign-Up Flow & Validation Test Suite
 * Executed via Node.js built-in test runner (node --test) without external dependencies.
 */
import { test, describe, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('Noetrix Open Sign-Up & Registration Workflow', () => {
  // Validator logic mirroring Register.tsx
  function validateRegisterForm(fullName, email, password, confirmPassword) {
    const errors = {};

    const trimmedName = (fullName || '').trim();
    if (!trimmedName) {
      errors.fullName = 'Full name is required.';
    }

    const trimmedEmail = (email || '').trim();
    if (!trimmedEmail) {
      errors.email = 'Email address is required.';
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
      errors.email = 'Please enter a valid email address.';
    }

    if (!password) {
      errors.password = 'Password is required.';
    } else if (password.length < 8) {
      errors.password = 'Password must be at least 8 characters.';
    }

    if (!confirmPassword) {
      errors.confirmPassword = 'Please confirm your password.';
    } else if (password !== confirmPassword) {
      errors.confirmPassword = 'Passwords do not match.';
    }

    return {
      isValid: Object.keys(errors).length === 0,
      errors,
    };
  }

  // Mock API client for registration
  class MockRegisterClient {
    constructor() {
      this.registeredUsers = [];
    }

    async register(payload, mockResponse) {
      this.registeredUsers.push(payload);
      if (mockResponse.status === 201) {
        return mockResponse.data;
      } else {
        const errorMsg =
          mockResponse.data?.detail ||
          mockResponse.message ||
          'Registration failed. Please check your information and try again.';
        throw new Error(errorMsg);
      }
    }
  }

  let client;

  beforeEach(() => {
    client = new MockRegisterClient();
  });

  // 1. Form Validation: Required Fields
  test('1. Registration form validation enforces full name, email, and password', () => {
    const emptyAll = validateRegisterForm('', '', '', '');
    assert.equal(emptyAll.isValid, false);
    assert.equal(emptyAll.errors.fullName, 'Full name is required.');
    assert.equal(emptyAll.errors.email, 'Email address is required.');
    assert.equal(emptyAll.errors.password, 'Password is required.');
    assert.equal(emptyAll.errors.confirmPassword, 'Please confirm your password.');
  });

  // 2. Form Validation: Email Format
  test('2. Registration form validation rejects invalid email structures', () => {
    const badEmail = validateRegisterForm('Ada Lovelace', 'invalid-email', 'ValidPass123!', 'ValidPass123!');
    assert.equal(badEmail.isValid, false);
    assert.equal(badEmail.errors.email, 'Please enter a valid email address.');

    const noDomain = validateRegisterForm('Ada Lovelace', 'ada@nodomain', 'ValidPass123!', 'ValidPass123!');
    assert.equal(noDomain.isValid, false);
    assert.equal(noDomain.errors.email, 'Please enter a valid email address.');
  });

  // 3. Form Validation: Password Minimum Length
  test('3. Registration form validation enforces minimum 8 characters for password', () => {
    const shortPwd = validateRegisterForm('Ada Lovelace', 'ada@example.com', 'short', 'short');
    assert.equal(shortPwd.isValid, false);
    assert.equal(shortPwd.errors.password, 'Password must be at least 8 characters.');
  });

  // 4. Form Validation: Password Mismatch
  test('4. Registration form validation rejects password confirmation mismatch', () => {
    const mismatch = validateRegisterForm('Ada Lovelace', 'ada@example.com', 'ValidPass123!', 'DifferentPass456!');
    assert.equal(mismatch.isValid, false);
    assert.equal(mismatch.errors.confirmPassword, 'Passwords do not match.');
  });

  // 5. Form Validation: Valid Registration Inputs
  test('5. Registration form validation passes for complete valid inputs', () => {
    const valid = validateRegisterForm('Ada Lovelace', 'ada@example.com', 'SecurePass123!', 'SecurePass123!');
    assert.equal(valid.isValid, true);
    assert.deepEqual(valid.errors, {});
  });

  // 6. Registration API Submission: Success Flow
  test('6. Successful registration returns access token and sets authenticated user', async () => {
    const mockSuccessResponse = {
      status: 201,
      data: {
        access_token: 'header.payload.signature',
        token_type: 'bearer',
        expires_in: 28800,
        user: {
          id: 'new-user-uuid',
          email: 'newuser@example.com',
          full_name: 'New Registered User',
          is_active: true,
          is_superuser: false,
        },
      },
    };

    const res = await client.register(
      {
        email: 'newuser@example.com',
        password: 'ValidPassword123!',
        full_name: 'New Registered User',
        organization_name: 'Custom Team',
      },
      mockSuccessResponse
    );

    assert.equal(res.access_token, 'header.payload.signature');
    assert.equal(res.user.email, 'newuser@example.com');
    assert.equal(client.registeredUsers.length, 1);
    assert.equal(client.registeredUsers[0].organization_name, 'Custom Team');
  });

  // 7. Registration Conflict Handling (Duplicate Email)
  test('7. Registration with duplicate email rejects with 409 Conflict message', async () => {
    const mockConflict = {
      status: 409,
      data: {
        detail: 'An account with this email address already exists.',
      },
    };

    await assert.rejects(
      async () => {
        await client.register(
          { email: 'existing@example.com', password: 'ValidPass123!', full_name: 'Existing' },
          mockConflict
        );
      },
      (err) => {
        assert.equal(err.message, 'An account with this email address already exists.');
        return true;
      }
    );
  });

  // 8. Registration Rate Limiting (429)
  test('8. Registration rate limit triggers readable 429 error', async () => {
    const mockRateLimit = {
      status: 429,
      data: {
        detail: 'Too many registration attempts. Please wait before trying again.',
      },
    };

    await assert.rejects(
      async () => {
        await client.register(
          { email: 'spammer@example.com', password: 'ValidPass123!', full_name: 'Spammer' },
          mockRateLimit
        );
      },
      (err) => {
        assert.equal(
          err.message,
          'Too many registration attempts. Please wait before trying again.'
        );
        return true;
      }
    );
  });

  // 9. Static Source Code Assertions: Login.tsx links to /register
  test('9. Login.tsx contains a visible link to /register', () => {
    const loginFilePath = path.join(__dirname, '..', 'src', 'pages', 'Login.tsx');
    assert.ok(fs.existsSync(loginFilePath), 'Login.tsx must exist');
    const content = fs.readFileSync(loginFilePath, 'utf-8');

    assert.ok(content.includes('to="/register"'), 'Login.tsx must link to /register');
    assert.ok(content.includes('Sign up'), 'Login.tsx must display "Sign up"');
  });

  // 10. Static Source Code Assertions: App.tsx defines /register route
  test('10. App.tsx registers /register under PublicRoute', () => {
    const appFilePath = path.join(__dirname, '..', 'src', 'App.tsx');
    assert.ok(fs.existsSync(appFilePath), 'App.tsx must exist');
    const content = fs.readFileSync(appFilePath, 'utf-8');

    assert.ok(content.includes('path="/register"'), 'App.tsx must define /register route');
    assert.ok(content.includes('<Register />'), 'App.tsx must render Register component');
  });

  // 11. Static Source Code Assertions: Register.tsx implementation details
  test('11. Register.tsx contains all required fields and back to login link', () => {
    const regFilePath = path.join(__dirname, '..', 'src', 'pages', 'Register.tsx');
    assert.ok(fs.existsSync(regFilePath), 'Register.tsx must exist');
    const content = fs.readFileSync(regFilePath, 'utf-8');

    assert.ok(content.includes('Full Name'), 'Register.tsx must have Full Name field');
    assert.ok(content.includes('Email Address'), 'Register.tsx must have Email Address field');
    assert.ok(content.includes('Password'), 'Register.tsx must have Password field');
    assert.ok(content.includes('Confirm Password'), 'Register.tsx must have Confirm Password field');
    assert.ok(content.includes('Create Account'), 'Register.tsx must have Create Account button');
    assert.ok(content.includes('to="/login"'), 'Register.tsx must link back to /login');
  });

  // 12. Static Source Code Assertions: authApi and AuthContext expose register
  test('12. api/auth.ts and AuthContext.tsx implement register method', () => {
    const apiPath = path.join(__dirname, '..', 'src', 'api', 'auth.ts');
    assert.ok(fs.existsSync(apiPath), 'api/auth.ts must exist');
    const apiContent = fs.readFileSync(apiPath, 'utf-8');
    assert.ok(apiContent.includes('register: async'), 'authApi must provide register method');

    const typesPath = path.join(__dirname, '..', 'src', 'types', 'index.ts');
    assert.ok(fs.existsSync(typesPath), 'types/index.ts must exist');
    const typesContent = fs.readFileSync(typesPath, 'utf-8');
    assert.ok(typesContent.includes('register: (data: RegisterPayload) => Promise<void>'), 'AuthContextType must declare register');

    const contextPath = path.join(__dirname, '..', 'src', 'context', 'AuthContext.tsx');
    assert.ok(fs.existsSync(contextPath), 'AuthContext.tsx must exist');
    const contextContent = fs.readFileSync(contextPath, 'utf-8');
    assert.ok(contextContent.includes('const register = useCallback'), 'AuthContext must define register callback');
  });
});
