/**
 * Authentication API functions
 */

import { API_URL } from './config'

// Token storage keys
const ACCESS_TOKEN_KEY = 'mcpbox_access_token'
const REFRESH_TOKEN_KEY = 'mcpbox_refresh_token'

export interface AuthStatus {
  setup_required: boolean
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface UserInfo {
  id: string
  username: string
  is_active: boolean
  last_login_at: string | null
  created_at: string
}

export interface SetupResponse {
  message: string
  username: string
}

/**
 * Token management
 */
export const tokens = {
  getAccessToken(): string | null {
    return localStorage.getItem(ACCESS_TOKEN_KEY)
  },

  getRefreshToken(): string | null {
    return localStorage.getItem(REFRESH_TOKEN_KEY)
  },

  setTokens(accessToken: string, refreshToken: string): void {
    localStorage.setItem(ACCESS_TOKEN_KEY, accessToken)
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken)
  },

  clearTokens(): void {
    localStorage.removeItem(ACCESS_TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
  },

  hasTokens(): boolean {
    return !!localStorage.getItem(ACCESS_TOKEN_KEY) && !!localStorage.getItem(REFRESH_TOKEN_KEY)
  },
}

/**
 * Check auth status (is setup required?)
 */
export async function getAuthStatus(): Promise<AuthStatus> {
  const response = await fetch(`${API_URL}/auth/status`)
  if (!response.ok) {
    throw new Error('Failed to check auth status')
  }
  return response.json()
}

/**
 * Setup initial admin user
 */
export async function setupAdmin(username: string, password: string): Promise<SetupResponse> {
  const response = await fetch(`${API_URL}/auth/setup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Setup failed' }))
    throw new Error(error.detail || 'Setup failed')
  }

  return response.json()
}

/**
 * Login and get tokens
 */
export async function login(username: string, password: string): Promise<TokenResponse> {
  const response = await fetch(`${API_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Login failed' }))
    throw new Error(error.detail || 'Login failed')
  }

  const tokenResponse: TokenResponse = await response.json()
  tokens.setTokens(tokenResponse.access_token, tokenResponse.refresh_token)
  return tokenResponse
}

/**
 * Refresh tokens
 */
export async function refreshTokens(): Promise<TokenResponse> {
  const refreshToken = tokens.getRefreshToken()
  if (!refreshToken) {
    throw new Error('No refresh token available')
  }

  const response = await fetch(`${API_URL}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })

  if (!response.ok) {
    // Clear tokens on refresh failure
    tokens.clearTokens()
    throw new Error('Session expired. Please login again.')
  }

  const tokenResponse: TokenResponse = await response.json()
  tokens.setTokens(tokenResponse.access_token, tokenResponse.refresh_token)
  return tokenResponse
}

/**
 * Logout
 */
export async function logout(): Promise<void> {
  const accessToken = tokens.getAccessToken()

  // Try to call logout endpoint (best effort)
  if (accessToken) {
    try {
      await fetch(`${API_URL}/auth/logout`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${accessToken}`,
        },
      })
    } catch {
      // Ignore errors - we'll clear tokens regardless
    }
  }

  tokens.clearTokens()
}

/**
 * Get current user info
 */
export async function getCurrentUser(): Promise<UserInfo> {
  const accessToken = tokens.getAccessToken()
  if (!accessToken) {
    throw new Error('Not authenticated')
  }

  const response = await fetch(`${API_URL}/auth/me`, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
  })

  if (!response.ok) {
    if (response.status === 401) {
      // Try to refresh and retry
      await refreshTokens()
      return getCurrentUser()
    }
    throw new Error('Failed to get user info')
  }

  return response.json()
}

/**
 * Change password
 */
export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  const accessToken = tokens.getAccessToken()
  if (!accessToken) {
    throw new Error('Not authenticated')
  }

  const response = await fetch(`${API_URL}/auth/change-password`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Password change failed' }))
    throw new Error(error.detail || 'Password change failed')
  }

  // Clear tokens - user must re-login after password change
  tokens.clearTokens()
}

/**
 * Validate that stored tokens are still valid
 */
export async function validateSession(): Promise<boolean> {
  if (!tokens.hasTokens()) {
    return false
  }

  try {
    await getCurrentUser()
    return true
  } catch {
    return false
  }
}
