import { useEffect, useState } from 'react'
import { exchangeOAuthCode } from '../api/externalMcpSources'

/**
 * OAuth callback page - handles the redirect from the external auth server.
 *
 * This page runs inside the popup window opened by ExternalSourcesTab.
 * It reads the authorization code and state from the URL, exchanges them
 * for tokens via the backend, and then closes the popup.
 */
export function OAuthCallback() {
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading')
  const [errorMessage, setErrorMessage] = useState('')

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')
    const state = params.get('state')
    const error = params.get('error')
    const errorDescription = params.get('error_description')

    if (error) {
      setStatus('error')
      setErrorMessage(errorDescription || error)
      return
    }

    if (!code || !state) {
      setStatus('error')
      setErrorMessage('Missing authorization code or state parameter.')
      return
    }

    exchangeOAuthCode(state, code)
      .then(() => {
        setStatus('success')
        // Auto-close popup after brief delay
        setTimeout(() => window.close(), 1500)
      })
      .catch(err => {
        setStatus('error')
        setErrorMessage(err instanceof Error ? err.message : 'Token exchange failed')
      })
  }, [])

  return (
    <div className="min-h-screen flex items-center justify-center bg-base">
      <div className="max-w-sm w-full bg-surface rounded-lg shadow-sm p-8 text-center">
        {status === 'loading' && (
          <>
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-iris mx-auto" />
            <p className="mt-4 text-sm text-subtle">Completing authentication...</p>
          </>
        )}

        {status === 'success' && (
          <>
            <div className="mx-auto h-10 w-10 rounded-full bg-foam/10 flex items-center justify-center">
              <svg className="h-6 w-6 text-foam" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <p className="mt-4 text-sm font-medium text-on-base">Authentication successful!</p>
            <p className="mt-1 text-xs text-subtle">This window will close automatically.</p>
          </>
        )}

        {status === 'error' && (
          <>
            <div className="mx-auto h-10 w-10 rounded-full bg-love/10 flex items-center justify-center">
              <svg className="h-6 w-6 text-love" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
            <p className="mt-4 text-sm font-medium text-on-base">Authentication failed</p>
            <p className="mt-1 text-xs text-love">{errorMessage}</p>
            <button
              onClick={() => window.close()}
              className="mt-4 px-4 py-2 bg-hl-low text-sm font-medium text-subtle rounded-md hover:bg-hl-med"
            >
              Close
            </button>
          </>
        )}
      </div>
    </div>
  )
}
