// Centralized API configuration - shared by auth.ts and client.ts
// This module has NO dependencies on other API modules to avoid circular imports

// IMPORTANT: VITE_API_URL must be set at build time for production builds
const getApiUrl = (): string => {
  const url = import.meta.env.VITE_API_URL
  if (!url) {
    // In development, fall back to localhost only if explicitly in dev mode
    if (import.meta.env.DEV) {
      return 'http://localhost:8000'
    }
    // In production, throw a clear error instead of silently using localhost
    throw new Error(
      'VITE_API_URL environment variable is not set. ' +
        'This must be configured at build time for production deployments.'
    )
  }
  return url
}

export const API_URL = getApiUrl()
