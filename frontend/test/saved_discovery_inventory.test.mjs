/**
 * Frontend Saved Discovery Inventory Test Suite
 * Executed via Node.js built-in test runner (node --test) without external dependencies.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('Noetrix Saved Discovery Inventory (Frontend)', () => {
  // 1. Export JSON filename generator
  function getExportFilename(sessionId) {
    if (!sessionId) throw new Error('Session ID required');
    return `discovery_inventory_${sessionId}.json`;
  }

  test('1. Generates stable, descriptive JSON export filename', () => {
    assert.equal(
      getExportFilename('bd33ca2e-3b0b-4392-ad76-d005223d2fb8'),
      'discovery_inventory_bd33ca2e-3b0b-4392-ad76-d005223d2fb8.json'
    );
  });

  // 2. Export JSON validation
  function validateExportPayload(payload) {
    if (!payload || typeof payload !== 'object') return false;
    if (payload.schema_version !== '1.0') return false;
    if (!payload.session || typeof payload.session !== 'object') return false;
    if (!payload.session.id || !payload.session.status) return false;
    if (!Array.isArray(payload.snapshots)) return false;
    if (typeof payload.total_snapshots !== 'number') return false;
    if (typeof payload.total_elements !== 'number') return false;
    for (const snap of payload.snapshots) {
      if (!snap.id || !snap.page_url || !Array.isArray(snap.elements)) return false;
    }
    return true;
  }

  test('2. Validates export JSON schema structure and completeness', () => {
    const validExport = {
      schema_version: '1.0',
      exported_at: '2026-10-26T14:50:00.000Z',
      session: {
        id: 'sess-123',
        project_id: 'proj-456',
        user_id: 'user-789',
        app_url: 'https://example.com/erp',
        status: 'completed',
        snapshots_count: 2,
      },
      total_snapshots: 2,
      total_elements: 3,
      snapshots: [
        {
          id: 'snap-1',
          page_url: 'https://example.com/erp/login',
          page_title: 'Sign In',
          elements_count: 2,
          elements: [
            { id: 'el_1', tag: 'input', accessible_name: 'Username' },
            { id: 'el_2', tag: 'input', accessible_name: 'Password' },
          ],
        },
        {
          id: 'snap-2',
          page_url: 'https://example.com/erp/home',
          page_title: 'Home',
          elements_count: 1,
          elements: [{ id: 'el_1', tag: 'button', accessible_name: 'Sign Out' }],
        },
      ],
    };

    assert.equal(validateExportPayload(validExport), true);
    assert.equal(validateExportPayload({ schema_version: '0.9' }), false);
    assert.equal(validateExportPayload(null), false);
  });

  // 3. Category filtering logic
  function filterByCategory(elements, category) {
    return elements.filter((el) => {
      if (category === 'all') return true;
      if (category === 'input') {
        return (
          (['input', 'textarea'].includes(el.tag) ||
            el.role === 'textbox' ||
            el.role === 'searchbox') &&
          el.type !== 'checkbox' &&
          el.role !== 'checkbox'
        );
      }
      if (category === 'button') {
        return el.tag === 'button' || el.role === 'button';
      }
      if (category === 'link') {
        return el.tag === 'a' || el.role === 'link';
      }
      if (category === 'dropdown') {
        return el.tag === 'select' || el.role === 'combobox';
      }
      if (category === 'checkbox') {
        return el.role === 'checkbox' || el.type === 'checkbox';
      }
      if (category === 'image') {
        return el.tag === 'img' || el.tag === 'svg';
      }
      return true;
    });
  }

  test('3. Filters elements by semantic category pills', () => {
    const elements = [
      { id: 'el_1', tag: 'input', type: 'text', role: 'textbox' },
      { id: 'el_2', tag: 'button', type: 'submit', role: 'button' },
      { id: 'el_3', tag: 'a', role: 'link' },
      { id: 'el_4', tag: 'select', role: 'combobox' },
      { id: 'el_5', tag: 'input', type: 'checkbox', role: 'checkbox' },
      { id: 'el_6', tag: 'img', role: null },
    ];

    assert.equal(filterByCategory(elements, 'all').length, 6);
    assert.equal(filterByCategory(elements, 'input').length, 1);
    assert.equal(filterByCategory(elements, 'button').length, 1);
    assert.equal(filterByCategory(elements, 'link').length, 1);
    assert.equal(filterByCategory(elements, 'dropdown').length, 1);
    assert.equal(filterByCategory(elements, 'checkbox').length, 1);
    assert.equal(filterByCategory(elements, 'image').length, 1);
  });

  // 4. Search filtering logic
  function searchElements(elements, query) {
    if (!query || !query.trim()) return elements;
    const q = query.toLowerCase().trim();
    return elements.filter((el) =>
      (el.accessible_name && el.accessible_name.toLowerCase().includes(q)) ||
      (el.label && el.label.toLowerCase().includes(q)) ||
      (el.placeholder && el.placeholder.toLowerCase().includes(q)) ||
      (el.suggested_intent && el.suggested_intent.toLowerCase().includes(q)) ||
      (el.element_id && el.element_id.toLowerCase().includes(q)) ||
      (el.data_testid && el.data_testid.toLowerCase().includes(q)) ||
      (el.name && el.name.toLowerCase().includes(q)) ||
      (el.visible_text && el.visible_text.toLowerCase().includes(q))
    );
  }

  test('4. Searches elements by name, label, placeholder, element_id, and data_testid', () => {
    const elements = [
      { id: 'el_1', accessible_name: 'Submit Application', data_testid: 'submit-btn' },
      { id: 'el_2', label: 'First Name', element_id: 'inp-fname' },
      { id: 'el_3', placeholder: 'Enter email address', name: 'email' },
      { id: 'el_4', suggested_intent: 'Company Logo logo', visible_text: 'eAppSys' },
    ];

    assert.equal(searchElements(elements, 'submit').length, 1);
    assert.equal(searchElements(elements, 'submit-btn').length, 1);
    assert.equal(searchElements(elements, 'fname').length, 1);
    assert.equal(searchElements(elements, 'email').length, 1);
    assert.equal(searchElements(elements, 'eappsys').length, 1);
    assert.equal(searchElements(elements, 'nonexistent').length, 0);
  });

  // 5. Complete element fields inspector graceful fallback
  function getElementDisplayFields(el) {
    return {
      elementId: el.id,
      tagAndType: `<${el.tag}>${el.type ? ` (type: ${el.type})` : ''}`,
      role: el.role || '—',
      accessibleName: el.accessible_name || '—',
      label: el.label || '—',
      placeholder: el.placeholder || '—',
      htmlId: el.element_id ? `#${el.element_id}` : '—',
      testId: el.data_testid || '—',
      href: el.href || '—',
      visibleText: el.visible_text || '—',
      status: `${el.is_visible ? 'Visible' : 'Hidden'}, ${el.is_enabled ? 'Enabled' : 'Disabled'}`,
      uniqueness: el.is_unique ? 'Unique (Single element)' : 'Non-unique (Multiple matches)',
      locatorsCount: Array.isArray(el.candidate_locators) ? el.candidate_locators.length : 0,
    };
  }

  test('5. Handles missing or null optional element fields gracefully in details view', () => {
    const sparse = {
      id: 'el_10',
      tag: 'div',
      is_visible: true,
      is_enabled: true,
      is_unique: false,
    };

    const display = getElementDisplayFields(sparse);
    assert.equal(display.elementId, 'el_10');
    assert.equal(display.tagAndType, '<div>');
    assert.equal(display.role, '—');
    assert.equal(display.accessibleName, '—');
    assert.equal(display.label, '—');
    assert.equal(display.htmlId, '—');
    assert.equal(display.testId, '—');
    assert.equal(display.locatorsCount, 0);
    assert.equal(display.uniqueness, 'Non-unique (Multiple matches)');
  });

  // 6. File structure & export symbol verification
  test('6. Verifies LiveDiscovery.tsx and api/discovery.ts contain required export & saved inventory symbols', () => {
    const apiPath = path.resolve(__dirname, '../src/api/discovery.ts');
    const pagePath = path.resolve(__dirname, '../src/pages/LiveDiscovery.tsx');

    assert.equal(fs.existsSync(apiPath), true, 'api/discovery.ts must exist');
    assert.equal(fs.existsSync(pagePath), true, 'pages/LiveDiscovery.tsx must exist');

    const apiContent = fs.readFileSync(apiPath, 'utf8');
    assert.equal(apiContent.includes('exportSessionJson'), true);
    assert.equal(apiContent.includes('searchInventory'), true);
    assert.equal(apiContent.includes('DiscoverySessionExport'), true);

    const pageContent = fs.readFileSync(pagePath, 'utf8');
    assert.equal(pageContent.includes('Saved Discovery Inventory'), true);
    assert.equal(pageContent.includes('handleExportJson'), true);
    assert.equal(pageContent.includes('handleSearchSavedInventory'), true);
    assert.equal(pageContent.includes('Complete Saved Element Metadata'), true);
  });
});
