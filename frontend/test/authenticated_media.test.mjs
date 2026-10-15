/**
 * Authenticated Media Loading & Lifecycle Test Suite
 * Tests authenticated blob fetching, authorization headers, 401/404 error states,
 * and URL.revokeObjectURL cleanup.
 */
import { test, describe, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

describe('Authenticated Media Loading & Lifecycle', () => {
  let mockApiClient;
  let inMemoryToken;
  let revokedUrls;
  let createdUrls;

  beforeEach(() => {
    inMemoryToken = 'test-bearer-token-xyz';
    revokedUrls = [];
    createdUrls = [];

    // Mock ObjectURL registry
    globalThis.URL.createObjectURL = (blob) => {
      const url = `blob:http://localhost:5173/${Math.random().toString(36).slice(2)}`;
      createdUrls.push(url);
      return url;
    };

    globalThis.URL.revokeObjectURL = (url) => {
      revokedUrls.push(url);
    };

    // Mock client simulating axios interceptors and withCredentials
    mockApiClient = {
      get: async (url, config = {}) => {
        const headers = { ...config.headers };
        if (inMemoryToken && !headers.Authorization) {
          headers.Authorization = `Bearer ${inMemoryToken}`;
        }

        const requestSnapshot = {
          url,
          headers,
          withCredentials: config.withCredentials ?? true,
          responseType: config.responseType,
        };

        if (url.includes('unauthorized')) {
          const err = new Error('Authentication credentials were not provided.');
          err.status = 401;
          err.request = requestSnapshot;
          throw err;
        }

        if (url.includes('missing-artifact')) {
          const err = new Error('Artifact file not found.');
          err.status = 404;
          err.request = requestSnapshot;
          throw err;
        }

        // Return a mock binary Blob
        const blob = new Blob(['mock-binary-media-data'], { type: 'image/png' });
        return {
          data: blob,
          status: 200,
          request: requestSnapshot,
        };
      },
    };
  });

  // Simulated media loader controller mirroring AuthenticatedImage/AuthenticatedVideo lifecycle
  class MediaLoaderController {
    constructor(client) {
      this.client = client;
      this.blobUrl = null;
      this.loading = false;
      this.error = null;
      this.isMounted = true;
    }

    async loadMedia({ id, path }) {
      if (!id && !path) {
        this.blobUrl = null;
        this.loading = false;
        this.error = null;
        return;
      }

      this.loading = true;
      this.error = null;

      const endpoint = id
        ? `/api/artifacts/${id}`
        : `/api/artifacts/file?path=${encodeURIComponent(path)}`;

      try {
        const res = await this.client.get(endpoint, {
          responseType: 'blob',
          withCredentials: true,
        });

        if (this.isMounted) {
          if (this.blobUrl) {
            URL.revokeObjectURL(this.blobUrl);
          }
          this.blobUrl = URL.createObjectURL(res.data);
          this.loading = false;
          return res.request;
        }
      } catch (err) {
        if (this.isMounted) {
          this.error = err.message || 'Failed to load media';
          this.loading = false;
          return err.request;
        }
      }
    }

    unmount() {
      this.isMounted = false;
      if (this.blobUrl) {
        URL.revokeObjectURL(this.blobUrl);
        this.blobUrl = null;
      }
    }
  }

  test('1. Authenticated media request sends Bearer token, withCredentials, and responseType blob', async () => {
    const controller = new MediaLoaderController(mockApiClient);
    const request = await controller.loadMedia({ id: 'art-001' });

    assert.equal(controller.loading, false);
    assert.equal(controller.error, null);
    assert.match(controller.blobUrl, /^blob:/);
    assert.equal(request.headers.Authorization, 'Bearer test-bearer-token-xyz');
    assert.equal(request.withCredentials, true);
    assert.equal(request.responseType, 'blob');

    controller.unmount();
  });

  test('2. Authenticated media request by path encodes relative path properly', async () => {
    const controller = new MediaLoaderController(mockApiClient);
    const request = await controller.loadMedia({ path: 'runs/run-123/screenshot.png' });

    assert.equal(request.url, '/api/artifacts/file?path=runs%2Frun-123%2Fscreenshot.png');
    assert.equal(request.headers.Authorization, 'Bearer test-bearer-token-xyz');
    assert.match(controller.blobUrl, /^blob:/);

    controller.unmount();
  });

  test('3. Unauthorized (401) response sets clean error state without crashing', async () => {
    const controller = new MediaLoaderController(mockApiClient);
    await controller.loadMedia({ id: 'unauthorized-artifact' });

    assert.equal(controller.loading, false);
    assert.equal(controller.blobUrl, null);
    assert.match(controller.error, /Authentication credentials were not provided/);

    controller.unmount();
  });

  test('4. Non-existent artifact (404) response captures error state for graceful UI rendering', async () => {
    const controller = new MediaLoaderController(mockApiClient);
    await controller.loadMedia({ path: 'missing-artifact.png' });

    assert.equal(controller.loading, false);
    assert.equal(controller.blobUrl, null);
    assert.match(controller.error, /Artifact file not found/);

    controller.unmount();
  });

  test('5. Lifecycle cleanup revokes Object URL on unmount', async () => {
    const controller = new MediaLoaderController(mockApiClient);
    await controller.loadMedia({ id: 'art-002' });

    const activeBlob = controller.blobUrl;
    assert.notEqual(activeBlob, null);
    assert.equal(revokedUrls.includes(activeBlob), false);

    controller.unmount();
    assert.equal(revokedUrls.includes(activeBlob), true);
    assert.equal(controller.blobUrl, null);
  });

  test('6. Changing media source revokes previous Object URL', async () => {
    const controller = new MediaLoaderController(mockApiClient);
    await controller.loadMedia({ id: 'art-first' });
    const firstUrl = controller.blobUrl;

    await controller.loadMedia({ id: 'art-second' });
    const secondUrl = controller.blobUrl;

    assert.notEqual(firstUrl, secondUrl);
    assert.equal(revokedUrls.includes(firstUrl), true);
    assert.equal(revokedUrls.includes(secondUrl), false);

    controller.unmount();
    assert.equal(revokedUrls.includes(secondUrl), true);
  });

  test('7. Empty artifact and path does not trigger network call and clears state', async () => {
    const controller = new MediaLoaderController(mockApiClient);
    await controller.loadMedia({});

    assert.equal(controller.loading, false);
    assert.equal(controller.blobUrl, null);
    assert.equal(controller.error, null);
    assert.equal(createdUrls.length, 0);

    controller.unmount();
  });
});
