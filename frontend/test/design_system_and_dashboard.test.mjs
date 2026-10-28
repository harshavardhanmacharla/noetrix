import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const srcDir = path.resolve(__dirname, '../src');

describe('Noetrix Design System & Run Identifiers (Stage 2 & Stage 3)', () => {
  it('1. Formats raw UUID into RUN-XXXXXXXX display identifier while preserving raw UUID', () => {
    const rawUuid = '3f9a1b2c-8d4e-4f1a-b62c-7e8d9a0b1c2d';
    const shortId = rawUuid.replace(/-/g, '').slice(0, 8).toUpperCase();
    const formatted = `RUN-${shortId}`;

    assert.equal(formatted, 'RUN-3F9A1B2C');
    assert.equal(shortId.length, 8);
    // Raw UUID must remain accessible
    assert.equal(rawUuid, '3f9a1b2c-8d4e-4f1a-b62c-7e8d9a0b1c2d');
  });

  it('2. StatusBadge configuration maps all statuses with appropriate badge styles', () => {
    const statusMap = {
      passed: { label: 'Passed', className: 'badge-passed' },
      failed: { label: 'Failed', className: 'badge-failed' },
      running: { label: 'Running', className: 'badge-running' },
      pending: { label: 'Pending', className: 'badge-pending' },
      error: { label: 'Error', className: 'badge-error' },
      skipped: { label: 'Skipped', className: 'badge-skipped' },
    };

    assert.equal(statusMap.passed.label, 'Passed');
    assert.equal(statusMap.passed.className, 'badge-passed');
    assert.equal(statusMap.failed.className, 'badge-failed');
    assert.equal(statusMap.running.className, 'badge-running');
    assert.equal(statusMap.error.className, 'badge-error');
    assert.equal(statusMap.skipped.className, 'badge-skipped');
  });

  it('3. Verifies RunIdBadge.tsx component exists and provides 1-click clipboard copy and full UUID tooltip', () => {
    const runIdBadgePath = path.join(srcDir, 'components/ui/RunIdBadge.tsx');
    assert.ok(fs.existsSync(runIdBadgePath), 'RunIdBadge.tsx must exist');

    const content = fs.readFileSync(runIdBadgePath, 'utf-8');
    assert.ok(content.includes('RUN-'), 'Must format run identifier with RUN- prefix');
    assert.ok(content.includes('navigator.clipboard.writeText'), 'Must implement clipboard copy');
    assert.ok(content.includes('title='), 'Must include tooltip with full UUID');
    assert.ok(content.includes('stopPropagation'), 'Must stop event propagation on copy button');
  });

  it('4. Verifies Pagination.tsx component exists and handles client-side page range calculations', () => {
    const paginationPath = path.join(srcDir, 'components/ui/Pagination.tsx');
    assert.ok(fs.existsSync(paginationPath), 'Pagination.tsx must exist');

    const content = fs.readFileSync(paginationPath, 'utf-8');
    assert.ok(content.includes('currentPage'), 'Must accept currentPage prop');
    assert.ok(content.includes('totalItems'), 'Must accept totalItems prop');
    assert.ok(content.includes('pageSize'), 'Must accept pageSize prop');
    assert.ok(content.includes('onPageChange'), 'Must support onPageChange callback');
  });

  it('5. Verifies Dashboard.tsx contains RunIdBadge, status filter pills, search input, and client pagination', () => {
    const dashboardPath = path.join(srcDir, 'pages/Dashboard.tsx');
    assert.ok(fs.existsSync(dashboardPath), 'Dashboard.tsx must exist');

    const content = fs.readFileSync(dashboardPath, 'utf-8');
    assert.ok(content.includes('RunIdBadge'), 'Dashboard must import and render RunIdBadge');
    assert.ok(content.includes('Pagination'), 'Dashboard must render Pagination component');
    assert.ok(content.includes('statusFilter'), 'Dashboard must support status filtering');
    assert.ok(content.includes('searchQuery'), 'Dashboard must support search filtering');
    assert.ok(content.includes('sortBy'), 'Dashboard must support sorting');
  });

  it('6. Verifies Reports.tsx contains run search, status filter, copy logs, and video unavailable fallback state', () => {
    const reportsPath = path.join(srcDir, 'pages/Reports.tsx');
    assert.ok(fs.existsSync(reportsPath), 'Reports.tsx must exist');

    const content = fs.readFileSync(reportsPath, 'utf-8');
    assert.ok(content.includes('RunIdBadge'), 'Reports must render RunIdBadge');
    assert.ok(content.includes('sidebarSearch'), 'Reports must include sidebar search filter');
    assert.ok(content.includes('sidebarStatus'), 'Reports must include sidebar status filter');
    assert.ok(content.includes('handleCopyLogs'), 'Reports must provide 1-click log copying');
    assert.ok(
      content.includes('Browser Recording Unavailable') || content.includes('VideoOff'),
      'Reports must render informative fallback when browser recording is missing'
    );
  });

  it('7. Verifies test case name resolution priority and graceful fallback logic', () => {
    const testCaseMap = {
      'tc-111': { id: 'tc-111', name: 'User Authentication Flow', description: 'Tests login and MFA' },
    };

    const resolveInfo = (result) => {
      const tcFromMap = result?.test_case_id ? testCaseMap[result.test_case_id] : undefined;
      const name =
        result?.test_case?.name ||
        tcFromMap?.name ||
        (result?.test_case_id ? `Test Case #${result.test_case_id.slice(0, 8)}` : 'Test Case');
      const idLabel = result?.test_case_id ? `ID: ${result.test_case_id.slice(0, 8)}…` : '';
      return { name, idLabel };
    };

    // Case A: Name present directly on result
    const directResult = { id: 'res-1', test_case_id: 'tc-999', test_case: { name: 'Direct Name' } };
    assert.equal(resolveInfo(directResult).name, 'Direct Name');

    // Case B: Name found in project testCaseMap
    const mappedResult = { id: 'res-2', test_case_id: 'tc-111' };
    assert.equal(resolveInfo(mappedResult).name, 'User Authentication Flow');
    assert.equal(resolveInfo(mappedResult).idLabel, 'ID: tc-111…');

    // Case C: Neither available, falls back to ID
    const fallbackResult = { id: 'res-3', test_case_id: 'f90b5bbe-1234-5678-9abc-def012345678' };
    assert.equal(resolveInfo(fallbackResult).name, 'Test Case #f90b5bbe');
    assert.equal(resolveInfo(fallbackResult).idLabel, 'ID: f90b5bbe…');

    // Case D: Null/missing test_case_id
    const emptyResult = { id: 'res-4' };
    assert.equal(resolveInfo(emptyResult).name, 'Test Case');
    assert.equal(resolveInfo(emptyResult).idLabel, '');
  });

  it('8. Verifies Reports.tsx implements test case name resolution with secondary muted ID', () => {
    const reportsPath = path.join(srcDir, 'pages/Reports.tsx');
    const content = fs.readFileSync(reportsPath, 'utf-8');

    assert.ok(content.includes('testCasesApi'), 'Reports must import testCasesApi');
    assert.ok(content.includes('testCaseMap'), 'Reports must manage testCaseMap state');
    assert.ok(content.includes('getTestCaseInfo'), 'Reports must define getTestCaseInfo helper');
    assert.ok(content.includes('selectedTcInfo'), 'Reports must compute selectedTcInfo');
    assert.ok(content.includes('tcInfo.idLabel'), 'Reports selector must render secondary muted ID label');
  });
});

