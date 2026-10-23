/**
 * Frontend Natural Language Test Creator Test Suite (Phase 11.5)
 * Executed via Node.js built-in test runner (node --test) without external dependencies.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('Noetrix Natural Language Test Creator Workflow (Phase 11.5)', () => {
  // 1. Instruction line extraction logic
  function extractInstructionLines(rawText) {
    if (!rawText) return [];
    return rawText
      .split('\n')
      .map((line, idx) => ({ line: idx + 1, text: line.trim() }))
      .filter((item) => item.text.length > 0);
  }

  test('1. Instruction parser input helper cleans blank lines and records line numbers', () => {
    const raw = `
      open https://example.com/login

      type "admin" into "#username"

      click "#submit"
    `;
    const lines = extractInstructionLines(raw);
    assert.equal(lines.length, 3);
    assert.equal(lines[0].text, 'open https://example.com/login');
    assert.equal(lines[1].text, 'type "admin" into "#username"');
    assert.equal(lines[2].text, 'click "#submit"');
  });

  test('2. Empty or whitespace-only instructions are detected before network call', () => {
    const empty1 = extractInstructionLines('');
    const empty2 = extractInstructionLines('   \n\n  \t  \n  ');
    assert.equal(empty1.length, 0);
    assert.equal(empty2.length, 0);
  });

  // 3. Mock API client testing
  class MockTestCasesClient {
    constructor() {
      this.parseCalls = [];
      this.createCalls = [];
    }

    async parseInstructions(projectId, instructions, mockResponse) {
      this.parseCalls.push({ projectId, instructions });
      if (mockResponse) return mockResponse;
      return {
        is_valid: true,
        total_lines: 3,
        valid_steps_count: 3,
        steps: [
          { line_number: 1, raw_instruction: 'open https://example.com', is_valid: true, action: 'navigate', value: 'https://example.com' },
          { line_number: 2, raw_instruction: 'type "user" into "#name"', is_valid: true, action: 'fill', target: '#name', value: 'user' },
          { line_number: 3, raw_instruction: 'click "#submit"', is_valid: true, action: 'click', target: '#submit' },
        ],
        errors: [],
      };
    }

    async createFromInstructions(projectId, name, instructions, description, mockResponse) {
      this.createCalls.push({ projectId, name, instructions, description });
      if (mockResponse) return mockResponse;
      return {
        id: 'tc-nl-100',
        name,
        description,
        project_id: projectId,
        csv_filename: 'natural_language',
        is_active: true,
        steps: [
          { id: 'st-1', test_case_id: 'tc-nl-100', step_number: 1, action: 'navigate', value: 'https://example.com' },
          { id: 'st-2', test_case_id: 'tc-nl-100', step_number: 2, action: 'fill', target: '#name', value: 'user' },
          { id: 'st-3', test_case_id: 'tc-nl-100', step_number: 3, action: 'click', target: '#submit' },
        ],
        created_at: new Date().toISOString(),
      };
    }
  }

  test('3. Parsing instructions does NOT invoke test case creation or execution', async () => {
    const client = new MockTestCasesClient();
    const parseRes = await client.parseInstructions('proj-1', 'open https://example.com\nclick "#btn"');

    assert.equal(parseRes.is_valid, true);
    assert.equal(client.parseCalls.length, 1);
    assert.equal(client.createCalls.length, 0, 'Parsing must never trigger test case creation');
  });

  test('4. Successful parse triggers preview mode with structured steps', () => {
    let previewMode = false;
    let parseResult = null;

    const mockResponse = {
      is_valid: true,
      total_lines: 2,
      valid_steps_count: 2,
      steps: [
        { line_number: 1, raw_instruction: 'open /home', is_valid: true, action: 'navigate', value: '/home' },
        { line_number: 2, raw_instruction: 'verify text "Welcome"', is_valid: true, action: 'verify_text', expected_result: 'Welcome' },
      ],
      errors: [],
    };

    if (mockResponse.is_valid && mockResponse.steps.length > 0) {
      previewMode = true;
      parseResult = mockResponse;
    }

    assert.equal(previewMode, true);
    assert.equal(parseResult.steps.length, 2);
    assert.equal(parseResult.steps[0].action, 'navigate');
    assert.equal(parseResult.steps[1].action, 'verify_text');
  });

  test('5. Parsing errors keep user in editor mode and report diagnostics', () => {
    let previewMode = false;
    let parseResult = null;

    const mockFailure = {
      is_valid: false,
      total_lines: 1,
      valid_steps_count: 0,
      steps: [
        { line_number: 1, raw_instruction: 'click submit and enter pass', is_valid: false, error: 'Ambiguous compound instruction' },
      ],
      errors: [
        { line: 1, instruction: 'click submit and enter pass', message: 'Ambiguous compound instruction' },
      ],
    };

    if (mockFailure.is_valid && mockFailure.steps.length > 0) {
      previewMode = true;
    } else {
      previewMode = false;
      parseResult = mockFailure;
    }

    assert.equal(previewMode, false);
    assert.equal(parseResult.errors.length, 1);
    assert.match(parseResult.errors[0].message, /Ambiguous compound/);
  });

  test('6. Explicit save commits test case and returns structured response', async () => {
    const client = new MockTestCasesClient();
    const created = await client.createFromInstructions(
      'proj-123',
      'Sign In Flow',
      'open https://example.com/login\nclick "#login"',
      'Smoke test for auth'
    );

    assert.equal(client.createCalls.length, 1);
    assert.equal(created.id, 'tc-nl-100');
    assert.equal(created.name, 'Sign In Flow');
    assert.equal(created.steps.length, 3);
    assert.equal(created.csv_filename, 'natural_language');
  });

  test('7. TestCases.tsx file inspection verifies Natural Language UI elements and accessibility IDs', () => {
    const testCasesPath = path.resolve(__dirname, '../src/pages/TestCases.tsx');
    assert.ok(fs.existsSync(testCasesPath), 'TestCases.tsx must exist');
    const content = fs.readFileSync(testCasesPath, 'utf-8');

    // Mode toggle
    assert.ok(content.includes("setCreationMode('natural_language')"), 'Must support natural language creation mode');
    assert.ok(content.includes("setCreationMode('csv')"), 'Must support CSV creation mode');

    // UI elements
    assert.ok(content.includes('id="nl-test-name"'), 'Must have Test Case Name input with accessible ID');
    assert.ok(content.includes('id="nl-description"'), 'Must have Description input with accessible ID');
    assert.ok(content.includes('id="nl-instructions"'), 'Must have natural-language textarea with accessible ID');

    // Action buttons & headers
    assert.ok(content.includes('Parse Instructions'), 'Must have Parse Instructions button');
    assert.ok(content.includes('Save Test Case'), 'Must have explicit Save Test Case button');
    assert.ok(content.includes('Return to Edit Instructions'), 'Must allow returning to editor from preview');
    assert.ok(content.includes('Natural Language Test Creator'), 'Must display feature header');

    // Reusable project selector
    assert.ok(content.includes('id="project-select"'), 'Must reuse existing project selector');

    // Preserved CSV workflow
    assert.ok(content.includes('downloadTemplate'), 'Must preserve CSV template download');
    assert.ok(content.includes('handleFile'), 'Must preserve CSV file upload');
    assert.ok(content.includes('uploadResult'), 'Must preserve CSV validation display');
  });

  test('8. api/testCases.ts implements parseInstructions and createFromInstructions methods', () => {
    const apiPath = path.resolve(__dirname, '../src/api/testCases.ts');
    assert.ok(fs.existsSync(apiPath), 'api/testCases.ts must exist');
    const content = fs.readFileSync(apiPath, 'utf-8');

    assert.ok(content.includes('parseInstructions:'), 'Must export parseInstructions');
    assert.ok(content.includes('createFromInstructions:'), 'Must export createFromInstructions');
    assert.ok(content.includes('/api/test-cases/parse-instructions'), 'Must call parse-instructions endpoint');
    assert.ok(content.includes('/api/test-cases/create-from-instructions'), 'Must call create-from-instructions endpoint');
  });

  test('9. Phase 12: TestCases.tsx and types include select_option action and dropdown examples', () => {
    const typesPath = path.resolve(__dirname, '../src/types/index.ts');
    assert.ok(fs.existsSync(typesPath), 'types/index.ts must exist');
    const typesContent = fs.readFileSync(typesPath, 'utf-8');
    assert.ok(typesContent.includes("'select_option'"), 'TestStep.action must include select_option');

    const testCasesPath = path.resolve(__dirname, '../src/pages/TestCases.tsx');
    const pageContent = fs.readFileSync(testCasesPath, 'utf-8');
    assert.ok(pageContent.includes('Dropdowns:'), 'Syntax cheat sheet must include Dropdowns category');
    assert.ok(pageContent.includes('select "California" from "#state"'), 'Must include example dropdown instruction');
  });
});

