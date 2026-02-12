// Base API client with timeout, retry, and JWT authentication support

import { tokens, refreshTokens } from './auth'
import { API_URL } from './config'

export { API_URL }

// Default timeout in milliseconds
const DEFAULT_TIMEOUT = 30000

// Retry configuration
const RETRY_CONFIG = {
  maxRetries: 2,
  baseDelay: 1000,
  maxDelay: 10000,
  retryableStatuses: [502, 503, 504, 429],
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public data?: unknown
  ) {
    // Extract detail message if available
    let message = `API Error: ${status} ${statusText}`
    if (data && typeof data === 'object' && 'detail' in data) {
      const detail = (data as { detail: unknown }).detail
      // Handle structured detail objects (e.g., 409 Conflict with message + existing_resources)
      if (detail && typeof detail === 'object' && 'message' in (detail as Record<string, unknown>)) {
        message = String((detail as { message: unknown }).message)
      } else {
        message = String(detail)
      }
    }
    super(message)
    this.name = 'ApiError'
  }

  get isTimeout(): boolean {
    return this.status === 408 || this.statusText === 'Request Timeout'
  }

  get isNetworkError(): boolean {
    return this.status === 0
  }

  get isServerError(): boolean {
    return this.status >= 500
  }

  get isUnauthorized(): boolean {
    return this.status === 401
  }

  get isConflict(): boolean {
    return this.status === 409
  }

  get conflicts(): Array<{ resource_type: string; name: string; id: string }> | null {
    if (this.status !== 409 || !this.data) return null
    const detail = (this.data as Record<string, unknown>)?.detail
    if (detail && typeof detail === 'object') {
      return ((detail as Record<string, unknown>).existing_resources as Array<{
        resource_type: string
        name: string
        id: string
      }>) ?? null
    }
    return null
  }

  get isRetryable(): boolean {
    return RETRY_CONFIG.retryableStatuses.includes(this.status) || this.isNetworkError
  }
}

export class TimeoutError extends Error {
  constructor(public timeout: number) {
    super(`Request timed out after ${timeout}ms`)
    this.name = 'TimeoutError'
  }
}

export class NetworkError extends Error {
  constructor(message: string, public originalError?: Error) {
    super(message)
    this.name = 'NetworkError'
  }
}

/**
 * Fetch with timeout support
 */
async function fetchWithTimeout(
  url: string,
  options: RequestInit,
  timeout: number = DEFAULT_TIMEOUT
): Promise<Response> {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeout)

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    })
    return response
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new TimeoutError(timeout)
    }
    throw error
  } finally {
    clearTimeout(timeoutId)
  }
}

/**
 * Calculate exponential backoff delay with jitter
 */
function calculateBackoff(attempt: number): number {
  const delay = RETRY_CONFIG.baseDelay * Math.pow(2, attempt)
  const jitter = delay * (0.5 + Math.random() * 0.5)
  return Math.min(jitter, RETRY_CONFIG.maxDelay)
}

/**
 * Sleep for specified milliseconds
 */
function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const data = await response.json().catch(() => null)
    throw new ApiError(response.status, response.statusText, data)
  }
  return response.json()
}

interface RequestOptions {
  timeout?: number
  retries?: number
  retryDelay?: number
  skipAuth?: boolean // Skip adding auth header (for auth endpoints)
}

// Global auth expiry callback - set by AuthProvider to handle session expiry
let onAuthExpired: (() => void) | null = null

/**
 * Register a callback for when authentication expires and cannot be refreshed.
 * Called by AuthProvider to redirect to login instead of showing generic errors.
 */
export function setAuthExpiredHandler(handler: (() => void) | null) {
  onAuthExpired = handler
}

// Flag to prevent multiple simultaneous refresh attempts
let isRefreshing = false
let refreshPromise: Promise<void> | null = null

/**
 * Attempt to refresh tokens if we have a refresh token
 */
async function tryRefreshTokens(): Promise<boolean> {
  if (!tokens.getRefreshToken()) {
    return false
  }

  // If already refreshing, wait for that to complete
  if (isRefreshing && refreshPromise) {
    try {
      await refreshPromise
      return true
    } catch {
      return false
    }
  }

  isRefreshing = true
  refreshPromise = (async () => {
    try {
      await refreshTokens()
    } finally {
      isRefreshing = false
      refreshPromise = null
    }
  })()

  try {
    await refreshPromise
    return true
  } catch {
    return false
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  options: RequestOptions = {}
): Promise<T> {
  const timeout = options.timeout ?? DEFAULT_TIMEOUT
  const maxRetries = options.retries ?? RETRY_CONFIG.maxRetries
  const skipAuth = options.skipAuth ?? false

  let lastError: Error | null = null
  let hasTriedRefresh = false

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      // Build headers including JWT token if available
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      }

      // Include JWT access token if available and not skipping auth
      if (!skipAuth) {
        const accessToken = tokens.getAccessToken()
        if (accessToken) {
          headers['Authorization'] = `Bearer ${accessToken}`
        }
      }

      const response = await fetchWithTimeout(
        `${API_URL}${path}`,
        {
          method,
          headers,
          body: body ? JSON.stringify(body) : undefined,
        },
        timeout
      )

      // Handle 401 Unauthorized - try to refresh tokens once
      if (response.status === 401 && !skipAuth && !hasTriedRefresh) {
        hasTriedRefresh = true
        const refreshed = await tryRefreshTokens()
        if (refreshed) {
          // Retry the request with new token
          continue
        }
        // Refresh failed - notify auth handler and throw
        if (onAuthExpired) {
          onAuthExpired()
        }
        const data = await response.json().catch(() => null)
        throw new ApiError(response.status, response.statusText, data)
      }

      return await handleResponse<T>(response)
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error))

      // Don't retry 401 errors after refresh attempt
      if (error instanceof ApiError && error.isUnauthorized) {
        throw error
      }

      // Determine if we should retry
      const isRetryable =
        error instanceof TimeoutError ||
        (error instanceof ApiError && error.isRetryable) ||
        (error instanceof TypeError) // Network errors

      if (isRetryable && attempt < maxRetries) {
        const delay = calculateBackoff(attempt)
        // Retry silently - no console logging in production
        await sleep(delay)
        continue
      }

      // Transform errors for better messages
      if (error instanceof TypeError && error.message.includes('fetch')) {
        throw new NetworkError(
          'Unable to connect to server. Please check your connection.',
          error
        )
      }

      throw error
    }
  }

  // Should not reach here, but just in case
  throw lastError || new Error('Request failed after retries')
}

export const api = {
  async get<T>(path: string, options?: RequestOptions): Promise<T> {
    return request<T>('GET', path, undefined, options)
  },

  async post<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return request<T>('POST', path, body, options)
  },

  async put<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return request<T>('PUT', path, body, options)
  },

  async patch<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return request<T>('PATCH', path, body, options)
  },

  async delete<T>(path: string, options?: RequestOptions): Promise<T> {
    return request<T>('DELETE', path, undefined, options)
  },
}
