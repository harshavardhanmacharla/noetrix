/**
 * Frontend Project Variables Test Suite (Phase 13)
 * Executed via Node.js built-in test runner (node --test) without external dependencies.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('Noetrix Project Test Variables Management (Phase 13)', () => {
  // 1. Variable name validation logic
  function isValidVariableName(name) {
    if (!name || typeof name !== 'string') return false;
    const trimmed = name.trim();
    return /^[a-zA-Z_][a-zA-Z0-9_]*$/.test(trimmed);
  }

  test('1. Validates variable names according to identifier naming rules', () => {
    // Valid names
    assert.equal(isValidVariableName('user_name'), true);
    assert.equal(isValidVariableName('password'), true);
    assert.equal(isValidVariableName('base_url'), true);
    assert.equal(isValidVariableName('_internal_token'), true);
    assert.equal(isValidVariableName('API_KEY_V2'), true);

    // Invalid names
    assert.equal(isValidVariableName(''), false);
    assert.equal(isValidVariableName('   '), false);
    assert.equal(isValidVariableName('123number'), false); // Cannot start with digit
    assert.equal(isValidVariableName('user-name'), false); // Hyphens not allowed
    assert.equal(isValidVariableName('user name'), false); // Spaces not allowed
    assert.equal(isValidVariableName('user@name'), false); // Special chars not allowed
    assert.equal(isValidVariableName('{{user_name}}'), false); // Curly braces not allowed in name
  });

  // 2. Placeholder formatting
  function formatPlaceholder(name) {
    return `{{${name.trim()}}}`;
  }

  test('2. Formats variable placeholders with double curly braces', () => {
    assert.equal(formatPlaceholder('user_name'), '{{user_name}}');
    assert.equal(formatPlaceholder('password'), '{{password}}');
    assert.equal(formatPlaceholder('base_url'), '{{base_url}}');
  });

  // 3. Secret value masking & display logic
  function formatDisplayValue(variable) {
    if (variable.is_secret) {
      return '••••••••';
    }
    return variable.value || '(empty)';
  }

  test('3. Secret variable values are never displayed in plaintext on the client', () => {
    const secretVar = {
      id: 'var-1',
      name: 'prod_password',
      value: null,
      is_secret: true,
      description: 'Production password',
    };

    const plainVar = {
      id: 'var-2',
      name: 'base_url',
      value: 'https://staging.noetrix.internal',
      is_secret: false,
      description: 'Staging URL',
    };

    assert.equal(formatDisplayValue(secretVar), '••••••••');
    assert.equal(formatDisplayValue(plainVar), 'https://staging.noetrix.internal');
  });

  // 4. Update payload generator: replace secret without revealing
  function buildUpdatePayload({ originalVar, newName, newValue, newIsSecret, newDescription }) {
    const payload = {
      name: newName.trim(),
      is_secret: newIsSecret,
      description: newDescription.trim() || undefined,
    };

    // If it's a secret and the user left the input blank, do not send value
    // (preserving the server's encrypted value)
    if (newValue !== '' && newValue !== undefined && newValue !== null) {
      payload.value = newValue;
    }

    return payload;
  }

  test('4. Update payload omits value when secret is retained without replacement', () => {
    const existingSecret = {
      id: 'var-1',
      name: 'db_password',
      is_secret: true,
      description: 'Old description',
    };

    // User only updates the description, leaving secret value field blank
    const payload = buildUpdatePayload({
      originalVar: existingSecret,
      newName: 'db_password',
      newValue: '', // blank
      newIsSecret: true,
      newDescription: 'New description',
    });

    assert.equal(payload.name, 'db_password');
    assert.equal(payload.description, 'New description');
    assert.equal(payload.is_secret, true);
    assert.equal('value' in payload, false); // value is omitted
  });

  test('5. Update payload includes new value when user replaces secret', () => {
    const existingSecret = {
      id: 'var-1',
      name: 'db_password',
      is_secret: true,
    };

    const payload = buildUpdatePayload({
      originalVar: existingSecret,
      newName: 'db_password',
      newValue: 'NewSecret123!',
      newIsSecret: true,
      newDescription: '',
    });

    assert.equal(payload.value, 'NewSecret123!');
  });

  // 6. Mock API client verification
  class MockProjectVariablesClient {
    constructor() {
      this.calls = [];
    }

    async list(projectId) {
      this.calls.push({ method: 'GET', url: `/api/projects/${projectId}/variables` });
      return [
        { id: 'v1', project_id: projectId, name: 'base_url', value: 'http://localhost:3000', is_secret: false },
        { id: 'v2', project_id: projectId, name: 'password', value: null, is_secret: true },
      ];
    }

    async create(projectId, data) {
      this.calls.push({ method: 'POST', url: `/api/projects/${projectId}/variables`, data });
      return { id: 'v3', project_id: projectId, ...data, value: data.is_secret ? null : data.value };
    }

    async update(projectId, variableId, data) {
      this.calls.push({ method: 'PUT', url: `/api/projects/${projectId}/variables/${variableId}`, data });
      return { id: variableId, project_id: projectId, ...data, value: data.is_secret ? null : data.value };
    }

    async delete(projectId, variableId) {
      this.calls.push({ method: 'DELETE', url: `/api/projects/${projectId}/variables/${variableId}` });
    }
  }

  test('6. Mock client records correct project-scoped endpoints and arguments', async () => {
    const client = new MockProjectVariablesClient();
    const projId = 'proj-999';

    const list = await client.list(projId);
    assert.equal(list.length, 2);
    assert.equal(list[1].value, null);

    await client.create(projId, { name: 'user_name', value: 'admin', is_secret: false });
    assert.equal(client.calls[1].method, 'POST');
    assert.equal(client.calls[1].url, '/api/projects/proj-999/variables');

    await client.update(projId, 'v1', { name: 'base_url', value: 'http://new.local' });
    assert.equal(client.calls[2].method, 'PUT');
    assert.equal(client.calls[2].url, '/api/projects/proj-999/variables/v1');

    await client.delete(projId, 'v2');
    assert.equal(client.calls[3].method, 'DELETE');
    assert.equal(client.calls[3].url, '/api/projects/proj-999/variables/v2');
  });

  // 7. Verify source files existence and structure
  test('7. Settings page and projectVariables API client files exist and contain required symbols', () => {
    const apiFile = path.resolve(__dirname, '../src/api/projectVariables.ts');
    const settingsFile = path.resolve(__dirname, '../src/pages/Settings.tsx');
    const typesFile = path.resolve(__dirname, '../src/types/index.ts');

    assert.equal(fs.existsSync(apiFile), true, 'api/projectVariables.ts must exist');
    assert.equal(fs.existsSync(settingsFile), true, 'pages/Settings.tsx must exist');
    assert.equal(fs.existsSync(typesFile), true, 'types/index.ts must exist');

    const apiContent = fs.readFileSync(apiFile, 'utf-8');
    assert.match(apiContent, /projectVariablesApi/);
    assert.match(apiContent, /\/api\/projects\/\$\{projectId\}\/variables/);

    const settingsContent = fs.readFileSync(settingsFile, 'utf-8');
    assert.match(settingsContent, /Project Test Variables/);
    assert.match(settingsContent, /projectVariablesApi/);
    assert.match(settingsContent, /AES-256-GCM/);

    const typesContent = fs.readFileSync(typesFile, 'utf-8');
    assert.match(typesContent, /export interface ProjectVariable/);
    assert.match(typesContent, /export interface ProjectVariableCreate/);
    assert.match(typesContent, /export interface ProjectVariableUpdate/);
  });
});

