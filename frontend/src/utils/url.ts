export interface SafeUrlResult {
  display: string;
  href?: string;
}

/**
 * Safely parse and format an application URL for display without throwing exceptions.
 * Handles valid URLs, scheme-less URLs (e.g. 'localhost:3000'), and malformed inputs.
 * Preserves the original URL without mutating or saving it.
 */
export function getSafeUrlDisplay(rawUrl?: string | null): SafeUrlResult | null {
  if (!rawUrl || typeof rawUrl !== 'string') {
    return null;
  }
  const trimmed = rawUrl.trim();
  if (!trimmed) {
    return null;
  }

  // 1. Valid absolute URL with http: or https: protocol
  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return {
        display: parsed.hostname || trimmed,
        href: trimmed,
      };
    }
  } catch {
    // Continue to scheme-less fallback
  }

  // 2. Scheme-less addresses like "localhost:3000" or "internal.test.net/app"
  try {
    if (!trimmed.includes(' ') && !trimmed.startsWith('/')) {
      const withScheme = new URL(`http://${trimmed}`);
      if (withScheme.hostname) {
        return {
          display: withScheme.hostname,
          href: `http://${trimmed}`,
        };
      }
    }
  } catch {
    // Malformed input fallback
  }

  // 3. Malformed URL fallback (safe non-link display, no runtime crash)
  return {
    display: trimmed,
    href: undefined,
  };
}
