// Centralized API configuration - shared by auth.ts and client.ts
// This module has NO dependencies on other API modules to avoid circular imports

// All API calls use same-origin relative paths (e.g. /api/servers, /auth/status).
// Nginx reverse-proxies /api/*, /auth/*, and /health to the backend container.
// This works both locally (localhost:3000 → backend:8000) and behind a
// reverse proxy like Traefik (single domain, no CORS needed).
export const API_URL = ''
