import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { getSafeUrlDisplay } from '../src/utils/url.ts';

describe('Safe Project URL Display Utility', () => {
  test('1. Valid HTTPS URL parses and extracts hostname with external link href', () => {
    const raw = 'https://app.noetrix.internal/dashboard?tab=runs';
    const result = getSafeUrlDisplay(raw);

    assert.notEqual(result, null);
    assert.equal(result.display, 'app.noetrix.internal');
    assert.equal(result.href, raw);
  });

  test('2. Valid HTTP URL with custom port parses hostname', () => {
    const raw = 'http://localhost:8080/app';
    const result = getSafeUrlDisplay(raw);

    assert.notEqual(result, null);
    assert.equal(result.display, 'localhost');
    assert.equal(result.href, raw);
  });

  test('3. Scheme-less localhost:port address parses hostname and builds valid http href', () => {
    const raw = 'localhost:3000';
    const result = getSafeUrlDisplay(raw);

    assert.notEqual(result, null);
    assert.equal(result.display, 'localhost');
    assert.equal(result.href, 'http://localhost:3000');
  });

  test('4. Scheme-less domain address parses hostname and builds valid http href', () => {
    const raw = 'qa-staging.example.com/login';
    const result = getSafeUrlDisplay(raw);

    assert.notEqual(result, null);
    assert.equal(result.display, 'qa-staging.example.com');
    assert.equal(result.href, 'http://qa-staging.example.com/login');
  });

  test('5. Malformed URL does not throw and falls back to safe non-link display', () => {
    const malformed = 'http://invalid URL with spaces and % symbols';
    const result = getSafeUrlDisplay(malformed);

    assert.notEqual(result, null);
    assert.equal(result.display, malformed);
    assert.equal(result.href, undefined);
  });

  test('6. Completely invalid garbage input falls back safely without crashing', () => {
    const garbage = ':::not-a-valid-protocol:::';
    const result = getSafeUrlDisplay(garbage);

    assert.notEqual(result, null);
    assert.equal(result.display, garbage);
    assert.equal(result.href, undefined);
  });

  test('7. Empty string, whitespace, null, and undefined values return null', () => {
    assert.equal(getSafeUrlDisplay(''), null);
    assert.equal(getSafeUrlDisplay('   '), null);
    assert.equal(getSafeUrlDisplay(null), null);
    assert.equal(getSafeUrlDisplay(undefined), null);
  });

  test('8. Preserves original stored URL without mutating input string', () => {
    const original = '  https://noetrix.internal/test  ';
    const copy = String(original);
    const result = getSafeUrlDisplay(original);

    assert.equal(original, copy);
    assert.equal(result.href, 'https://noetrix.internal/test');
    assert.equal(result.display, 'noetrix.internal');
  });
});
