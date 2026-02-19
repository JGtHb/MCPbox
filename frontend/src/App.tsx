import { useState, useEffect } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router-dom'
import { ErrorBoundary } from './components/ui'
import { LoadingSpinner } from './components/shared'
import { AuthProvider } from './contexts'
import { queryClient } from './lib/queryClient'
import { router } from './routes'
import { getAuthStatus, validateSession, logout as authLogout, tokens } from './api/auth'
import { Login, Setup } from './pages'

type AuthState = 'loading' | 'setup' | 'login' | 'authenticated' | 'error'

function AppContent() {
  const [authState, setAuthState] = useState<AuthState>('loading')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    checkAuthStatus()
  }, [])

  const checkAuthStatus = async () => {
    try {
      // First, check if setup is required
      const status = await getAuthStatus()

      if (status.setup_required) {
        setAuthState('setup')
        return
      }

      // Setup is complete, check if we have valid tokens
      if (tokens.hasTokens()) {
        const isValid = await validateSession()
        if (isValid) {
          setAuthState('authenticated')
          return
        }
        // Tokens are invalid, clear them
        tokens.clearTokens()
      }

      // Need to login
      setAuthState('login')
    } catch (err) {
      setError('Unable to connect to server. Please check your connection.')
      setAuthState('error')
      console.error('Failed to check auth status:', err)
    }
  }

  const handleSetupComplete = () => {
    // After setup, show login page
    setAuthState('login')
  }

  const handleLogin = () => {
    setAuthState('authenticated')
  }

  const handleLogout = async () => {
    await authLogout()
    setAuthState('login')
  }

  if (authState === 'loading') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-base">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (authState === 'error') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-base px-4">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-on-base mb-4">
            Connection Error
          </h1>
          <p className="text-subtle mb-6">{error}</p>
          <button
            onClick={() => {
              setError(null)
              setAuthState('loading')
              checkAuthStatus()
            }}
            className="px-4 py-2 bg-rose text-base rounded-lg text-sm font-medium hover:bg-rose/80 transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  if (authState === 'setup') {
    return <Setup onSetupComplete={handleSetupComplete} />
  }

  if (authState === 'login') {
    return <Login onLogin={handleLogin} />
  }

  return (
    <AuthProvider isAuthenticated={true} onLogout={handleLogout}>
      <RouterProvider router={router} />
    </AuthProvider>
  )
}

function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AppContent />
      </QueryClientProvider>
    </ErrorBoundary>
  )
}

export default App
