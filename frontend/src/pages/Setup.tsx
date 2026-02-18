import { useState } from 'react'
import { setupAdmin } from '../api/auth'

interface SetupProps {
  onSetupComplete: () => void
}

export function Setup({ onSetupComplete }: SetupProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const validateForm = (): string | null => {
    if (username.length < 3) {
      return 'Username must be at least 3 characters'
    }
    if (!/^[a-zA-Z][a-zA-Z0-9_]*$/.test(username)) {
      return 'Username must start with a letter and contain only letters, numbers, and underscores'
    }
    if (password.length < 12) {
      return 'Password must be at least 12 characters'
    }
    if (password !== confirmPassword) {
      return 'Passwords do not match'
    }
    return null
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    const validationError = validateForm()
    if (validationError) {
      setError(validationError)
      return
    }

    setIsLoading(true)

    try {
      await setupAdmin(username, password)
      onSetupComplete()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Setup failed')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-base px-4">
      <div className="max-w-md w-full space-y-8">
        <div className="text-center">
          <h1 className="text-3xl font-bold text-on-base">MCPbox Setup</h1>
          <p className="mt-2 text-subtle">
            Create your admin account to get started
          </p>
        </div>

        <form onSubmit={handleSubmit} className="mt-8 space-y-6">
          <div className="space-y-4">
            <div>
              <label htmlFor="username" className="block text-sm font-medium text-on-base mb-1">
                Username
              </label>
              <input
                id="username"
                name="username"
                type="text"
                autoComplete="username"
                required
                className="appearance-none rounded-lg relative block w-full px-3 py-3 border border-hl-med placeholder-muted text-on-base bg-surface focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris sm:text-sm"
                placeholder="admin"
                value={username}
                onChange={e => setUsername(e.target.value)}
                disabled={isLoading}
              />
              <p className="mt-1 text-xs text-muted">
                3-50 characters, letters, numbers, and underscores
              </p>
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-on-base mb-1">
                Password
              </label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="new-password"
                required
                className="appearance-none rounded-lg relative block w-full px-3 py-3 border border-hl-med placeholder-muted text-on-base bg-surface focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris sm:text-sm"
                placeholder="Enter password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                disabled={isLoading}
              />
              <p className="mt-1 text-xs text-muted">
                Minimum 12 characters
              </p>
            </div>

            <div>
              <label htmlFor="confirm-password" className="block text-sm font-medium text-on-base mb-1">
                Confirm Password
              </label>
              <input
                id="confirm-password"
                name="confirmPassword"
                type="password"
                autoComplete="new-password"
                required
                className="appearance-none rounded-lg relative block w-full px-3 py-3 border border-hl-med placeholder-muted text-on-base bg-surface focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris sm:text-sm"
                placeholder="Confirm password"
                value={confirmPassword}
                onChange={e => setConfirmPassword(e.target.value)}
                disabled={isLoading}
              />
            </div>
          </div>

          {error && (
            <div className="rounded-md bg-love/10 p-4">
              <div className="flex">
                <div className="flex-shrink-0">
                  <svg
                    className="h-5 w-5 text-love"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                    aria-hidden="true"
                  >
                    <path
                      fillRule="evenodd"
                      d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z"
                      clipRule="evenodd"
                    />
                  </svg>
                </div>
                <div className="ml-3">
                  <p className="text-sm text-love">{error}</p>
                </div>
              </div>
            </div>
          )}

          <div>
            <button
              type="submit"
              disabled={isLoading || !username || !password || !confirmPassword}
              className="group relative w-full flex justify-center py-3 px-4 border border-transparent text-sm font-medium rounded-lg text-base bg-iris hover:bg-iris/80 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-iris disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isLoading ? (
                <span className="flex items-center">
                  <svg
                    className="animate-spin -ml-1 mr-3 h-5 w-5 text-base"
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    />
                  </svg>
                  Creating account...
                </span>
              ) : (
                'Create Admin Account'
              )}
            </button>
          </div>
        </form>

        <div className="text-center text-sm text-muted">
          <p>
            This account will be used to access the MCPbox dashboard.
          </p>
        </div>
      </div>
    </div>
  )
}
