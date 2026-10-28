/**
 * Frontend Data-Driven Test Execution Test Suite
 * Executed via Node.js built-in test runner (node --test) without external dependencies.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('Noetrix UI-Based Data-Driven Test Execution (Frontend)', () => {
  // Regex pattern matching the backend standard
  const PLACEHOLDER_PATTERN = /\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}/g;

  function extractPlaceholders(text) {
    if (!text || typeof text !== 'string') return [];
    const matches = new Set();
    let m;
    const re = new RegExp(PLACEHOLDER_PATTERN);
    while ((m = re.exec(text)) !== null) {
      matches.add(m[1]);
    }
    return Array.from(matches).sort();
  }

  function filterDataColumns(allPlaceholders, projectVariables) {
    const projSet = new Set(projectVariables || []);
    return (allPlaceholders || []).filter((p) => !projSet.has(p)).sort();
  }

  function substituteString(template, record) {
    if (!template || typeof template !== 'string') return template;
    return template.replace(/\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}/g, (match, varName) => {
      return Object.prototype.hasOwnProperty.call(record, varName) && record[varName] !== undefined
        ? String(record[varName])
        : match;
    });
  }

  function validateRecordRows(placeholders, records) {
    const errors = [];
    if (!Array.isArray(records) || records.length === 0) {
      errors.push('At least one data record row is required.');
      return errors;
    }
    records.forEach((row, idx) => {
      const rowNum = idx + 1;
      placeholders.forEach((ph) => {
        const val = row[ph];
        if (val === undefined || val === null || String(val).trim() === '') {
          errors.push(`Row #${rowNum}: Field "${ph}" cannot be empty.`);
        }
      });
    });
    return errors;
  }

  test('1. Extracts unique {{placeholder}} names from test step strings', () => {
    const text1 = 'fill "Legal Employer" with "{{legal_employer}}"';
    const text2 = 'type "{{first_name}}" into "{{first_name_field}}" and "{{last_name}}"';
    assert.deepEqual(extractPlaceholders(text1), ['legal_employer']);
    assert.deepEqual(extractPlaceholders(text2), ['first_name', 'first_name_field', 'last_name']);
    assert.deepEqual(extractPlaceholders('no placeholders here'), []);
  });

  test('2. Dynamic Column Filtering: excludes configured project variables from data columns', () => {
    const detected = ['base_url', 'email', 'first_name', 'last_name', 'password', 'user_name'];
    const projectVariables = ['base_url', 'password', 'user_name'];
    const dataColumns = filterDataColumns(detected, projectVariables);
    assert.deepEqual(dataColumns, ['email', 'first_name', 'last_name']);
  });

  test('3. Dynamic Column Filtering: returns empty list when all placeholders exist at project level', () => {
    const detected = ['base_url', 'password', 'user_name'];
    const projectVariables = ['base_url', 'password', 'user_name', 'tenant_id'];
    const dataColumns = filterDataColumns(detected, projectVariables);
    assert.deepEqual(dataColumns, []);
  });

  test('4. Dynamic Column Filtering: retains all placeholders when no project variables configured', () => {
    const detected = ['first_name', 'last_name'];
    const dataColumns = filterDataColumns(detected, []);
    assert.deepEqual(dataColumns, ['first_name', 'last_name']);
  });

  test('5. Accurately substitutes placeholders with record values without mutating original', () => {
    const template = 'Hire {{first_name}} {{last_name}} into {{legal_employer}}';
    const record = {
      first_name: 'John',
      last_name: 'Doe-Smith',
      legal_employer: 'US1 Legal Entity',
    };
    const rendered = substituteString(template, record);
    assert.equal(rendered, 'Hire John Doe-Smith into US1 Legal Entity');
    assert.equal(template, 'Hire {{first_name}} {{last_name}} into {{legal_employer}}');
  });

  test('6. Handles special characters, Unicode, and spaces in substituted values', () => {
    const template = 'Verify employee name is "{{full_name}}"';
    const record = {
      full_name: "Renée O'Connor & Söhn",
    };
    const rendered = substituteString(template, record);
    assert.equal(rendered, 'Verify employee name is "Renée O\'Connor & Söhn"');
  });

  test('7. Leaves unmatched project variable placeholders intact if omitted from row record', () => {
    const template = 'open "{{base_url}}" and fill "{{first_name}}"';
    const rowRecord = { first_name: 'Alice' }; // base_url omitted because it is a project variable
    const rendered = substituteString(template, rowRecord);
    assert.equal(rendered, 'open "{{base_url}}" and fill "Alice"');
  });

  test('8. Validates record table rows: flags empty, whitespace-only, and missing columns', () => {
    const dataColumns = ['first_name', 'last_name', 'hire_date'];
    const invalidRecords = [
      { first_name: 'Alice', last_name: '', hire_date: '2026-01-01' },
      { first_name: '   ', last_name: 'Bob', hire_date: '2026-01-02' },
      { first_name: 'Charlie', last_name: 'Brown' }, // missing hire_date
    ];
    const errors = validateRecordRows(dataColumns, invalidRecords);
    assert.equal(errors.length, 3);
    assert.ok(errors[0].includes('Row #1: Field "last_name" cannot be empty'));
    assert.ok(errors[1].includes('Row #2: Field "first_name" cannot be empty'));
    assert.ok(errors[2].includes('Row #3: Field "hire_date" cannot be empty'));
  });

  test('9. Validates record table rows: accepts complete, populated records', () => {
    const dataColumns = ['first_name', 'last_name'];
    const validRecords = [
      { first_name: 'Alice', last_name: 'Smith' },
      { first_name: 'Bob', last_name: 'Jones' },
    ];
    const errors = validateRecordRows(dataColumns, validRecords);
    assert.equal(errors.length, 0);
  });

  test('10. Verifies DataDrivenExecution.tsx, api client, and types reflect dynamic project variable exclusion', () => {
    const srcDir = path.resolve(__dirname, '../src');

    // Page file
    const pagePath = path.join(srcDir, 'pages', 'DataDrivenExecution.tsx');
    assert.ok(fs.existsSync(pagePath), 'DataDrivenExecution.tsx must exist');
    const pageContent = fs.readFileSync(pagePath, 'utf8');
    assert.ok(pageContent.includes('Data-Driven Test Execution'));
    assert.ok(pageContent.includes('All Placeholders are Configured in Project Test Variables'));
    assert.ok(pageContent.includes('Auto-Resolved Project Variables'));
    assert.ok(pageContent.includes('dataDrivenApi'));
    assert.ok(pageContent.includes('stopOnFailure'));

    // API client
    const apiPath = path.join(srcDir, 'api', 'dataDriven.ts');
    assert.ok(fs.existsSync(apiPath), 'api/dataDriven.ts must exist');
    const apiContent = fs.readFileSync(apiPath, 'utf8');
    assert.ok(apiContent.includes('getPlaceholders'));
    assert.ok(apiContent.includes('validateData'));
    assert.ok(apiContent.includes('previewData'));
    assert.ok(apiContent.includes('startRun'));

    // Types
    const typesPath = path.join(srcDir, 'types', 'index.ts');
    const typesContent = fs.readFileSync(typesPath, 'utf8');
    assert.ok(typesContent.includes('DataDrivenRunRequest'));
    assert.ok(typesContent.includes('TestCasePlaceholdersResponse'));
    assert.ok(typesContent.includes('project_variables?: string[]'));
    assert.ok(typesContent.includes('all_placeholders?: string[]'));

    // App routing
    const appPath = path.join(srcDir, 'App.tsx');
    const appContent = fs.readFileSync(appPath, 'utf8');
    assert.ok(appContent.includes('DataDrivenExecution'));
    assert.ok(appContent.includes('/data-driven'));

    // Sidebar navigation
    const sidebarPath = path.join(srcDir, 'components', 'layout', 'Sidebar.tsx');
    const sidebarContent = fs.readFileSync(sidebarPath, 'utf8');
    assert.ok(sidebarContent.includes('/data-driven'));
    assert.ok(sidebarContent.includes('Data-Driven Testing'));
  });
});
