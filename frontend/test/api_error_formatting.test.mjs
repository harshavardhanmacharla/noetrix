import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { formatApiErrorMessage } from '../src/api/client.ts';

describe('API Error Message Formatter (Pydantic / FastAPI formatting)', () => {
  test('1. Single Pydantic validation error formats into "field: message"', () => {
    const pydanticError = [
      {
        type: 'value_error',
        loc: ['body', 'email'],
        msg: 'value is not a valid email address',
        input: 'invalid-email',
      },
    ];
    const result = formatApiErrorMessage(pydanticError);
    assert.equal(result, 'email: value is not a valid email address');
    assert.ok(!result.includes('[object Object]'));
  });

  test('2. Multiple Pydantic validation errors format and join with commas', () => {
    const pydanticErrors = [
      {
        type: 'string_too_short',
        loc: ['body', 'name'],
        msg: 'String should have at least 1 character',
        input: '',
      },
      {
        type: 'string_pattern_mismatch',
        loc: ['body', 'slug'],
        msg: 'String should match pattern "^[a-z0-9-]+$"',
        input: 'Invalid Slug!',
      },
    ];
    const result = formatApiErrorMessage(pydanticErrors);
    assert.equal(
      result,
      'name: String should have at least 1 character, slug: String should match pattern "^[a-z0-9-]+$"'
    );
    assert.ok(!result.includes('[object Object]'));
  });

  test('3. Strips query and header prefixes from loc path', () => {
    const queryError = [
      {
        loc: ['query', 'page'],
        msg: 'Input should be greater than 0',
      },
    ];
    const result = formatApiErrorMessage(queryError);
    assert.equal(result, 'page: Input should be greater than 0');
  });

  test('4. Formats deeply nested field paths and array indexes accurately', () => {
    const nestedError = [
      {
        loc: ['body', 'members', 0, 'role'],
        msg: 'Input should be "owner", "admin" or "member"',
      },
    ];
    const result = formatApiErrorMessage(nestedError);
    assert.equal(result, 'members.0.role: Input should be "owner", "admin" or "member"');
  });

  test('5. Handles Pydantic error item without loc', () => {
    const generalError = [
      {
        msg: 'Malformed JSON payload in request body',
      },
    ];
    const result = formatApiErrorMessage(generalError);
    assert.equal(result, 'Malformed JSON payload in request body');
  });

  test('6. Formats array of plain string errors', () => {
    const stringArray = ['User not found', 'Insufficient permissions'];
    const result = formatApiErrorMessage(stringArray);
    assert.equal(result, 'User not found, Insufficient permissions');
  });

  test('7. Handles plain string details directly', () => {
    const plainString = 'Organization with slug "acme-corp" already exists.';
    const result = formatApiErrorMessage(plainString);
    assert.equal(result, plainString);
  });

  test('8. Whitespace-only string returns fallback', () => {
    const result = formatApiErrorMessage('   ', 'Custom Fallback');
    assert.equal(result, 'Custom Fallback');
  });

  test('9. Single object error format (non-array)', () => {
    const singleObj = {
      loc: ['body', 'role'],
      msg: 'Invalid role assignment',
    };
    const result = formatApiErrorMessage(singleObj);
    assert.equal(result, 'role: Invalid role assignment');
  });

  test('10. Single object with detail or message property', () => {
    assert.equal(formatApiErrorMessage({ detail: 'Token has expired' }), 'Token has expired');
    assert.equal(formatApiErrorMessage({ message: 'Network timeout' }), 'Network timeout');
  });

  test('11. Null, undefined, and empty arrays safely return fallback', () => {
    assert.equal(formatApiErrorMessage(null, 'Fallback'), 'Fallback');
    assert.equal(formatApiErrorMessage(undefined, 'Fallback'), 'Fallback');
    assert.equal(formatApiErrorMessage([], 'Fallback'), 'Fallback');
  });

  test('12. Guarantees [object Object] is never returned across malformed shapes', () => {
    const malformedCases = [
      {},
      { unknownField: 123 },
      [{ unknownField: 123 }],
      [{}],
      [{ loc: null, msg: null }],
    ];

    for (const testCase of malformedCases) {
      const result = formatApiErrorMessage(testCase);
      assert.ok(
        !result.includes('[object Object]'),
        `Expected result to not contain "[object Object]", got: "${result}"`
      );
    }
  });
});
