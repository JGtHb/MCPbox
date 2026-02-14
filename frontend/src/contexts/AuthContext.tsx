import { createContext, useContext, useEffect, useRef, ReactNode } from 'react'
import { refreshTokens, tokens } from '../api/auth'
import { setAuthExpiredHandler } from '../api/client'

// Refresh the access token 2 minutes before it expires (15 min default - 2 min = 13 min)
const TOKEN_REFRESH_INTERVAL_MS = 13 * 60 * 1000

interface AuthContextValue {
  /** Whether the user is currently authenticated */
  isAuthenticated: boolean
  /** Log the user out (clears API key and resets auth state) */
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

interface AuthProviderProps {
  children: ReactNode
  isAuthenticated: boolean
  onLogout: () => void
}

/**
 * Provider component for authentication context.
 * Wraps the app to provide logout functionality to nested components.
 * Proactively refreshes the access token before it expires.
 */
export function AuthProvider({ children, isAuthenticated, onLogout }: AuthProviderProps) {
  const onLogoutRef = useRef(onLogout)
  onLogoutRef.current = onLogout

  // Proactive token refresh - refresh before the access token expires
  useEffect(() => {
    if (!isAuthenticated || !tokens.hasTokens()) return

    const refresh = async () => {
      try {
        await refreshTokens()
      } catch {
        // Refresh token is invalid/expired - force re-login
        onLogoutRef.current()
      }
    }

    const intervalId = setInterval(refresh, TOKEN_REFRESH_INTERVAL_MS)

    return () => clearInterval(intervalId)
  }, [isAuthenticated])

  // Register global auth expiry handler so failed API refreshes redirect to login
  useEffect(() => {
    if (!isAuthenticated) return

    setAuthExpiredHandler(() => onLogoutRef.current())

    return () => setAuthExpiredHandler(null)
  }, [isAuthenticated])

  return (
    <AuthContext.Provider value={{ isAuthenticated, logout: onLogout }}>
      {children}
    </AuthContext.Provider>
  )
}

/**
 * Hook to access authentication context.
 * Must be used within an AuthProvider.
 *
 * @example
 * ```tsx
 * function LogoutButton() {
 *   const { logout } = useAuth()
 *   return <button onClick={logout}>Logout</button>
 * }
 * ```
 */
export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
