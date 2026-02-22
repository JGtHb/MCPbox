// Centralized API configuration - shared by auth.ts and client.ts
// This module has NO dependencies on other API modules to avoid circular imports

// Runtime config is injected by docker-entrypoint.sh via /config.js
// which sets window.__MCPBOX_CONFIG__ before the React bundle loads.
// This allows changing MCPBOX_BACKEND_PORT without rebuilding the image.
interface MCPBoxConfig {
  API_URL: string
}

declare global {
  interface Window {
    __MCPBOX_CONFIG__?: MCPBoxConfig
  }
}

const getApiUrl = (): string => {
  // 1. Runtime injection (Docker container — set by docker-entrypoint.sh)
  if (window.__MCPBOX_CONFIG__?.API_URL) {
    return window.__MCPBOX_CONFIG__.API_URL
  }

  // 2. Build-time injection (VITE_API_URL — for non-Docker or legacy builds)
  const url = import.meta.env.VITE_API_URL
  if (url) {
    return url
  }

  // 3. Dev fallback
  if (import.meta.env.DEV) {
    return 'http://localhost:8000'
  }

  // In production without any config, throw a clear error
  throw new Error(
    'API URL is not configured. ' +
      'Ensure MCPBOX_BACKEND_PORT is set in .env for Docker deployments, ' +
      'or set VITE_API_URL at build time for non-Docker builds.'
  )
}

export const API_URL = getApiUrl()
