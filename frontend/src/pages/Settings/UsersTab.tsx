import { useState, useEffect } from 'react'
import {
  useCloudflareStatus,
  useUpdateAccessPolicy,
  useWorkerConfig,
  useUpdateWorkerConfig,
  AccessPolicyType,
  AccessPolicyConfig,
} from '../../api/cloudflare'

// =============================================================================
// Allowed Origins Section (inside Users tab)
// =============================================================================

function AllowedOriginsSection({ configId }: { configId: string | null }) {
  const { data: workerConfig, isLoading } = useWorkerConfig(configId)
  const updateConfig = useUpdateWorkerConfig()

  const [corsOrigins, setCorsOrigins] = useState<string[]>([])
  const [redirectUris, setRedirectUris] = useState<string[]>([])
  const [newCorsOrigin, setNewCorsOrigin] = useState('')
  const [newRedirectUri, setNewRedirectUri] = useState('')
  const [originError, setOriginError] = useState<string | null>(null)
  const [redirectError, setRedirectError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [initialized, setInitialized] = useState(false)

  useEffect(() => {
    if (workerConfig && !initialized) {
      setCorsOrigins(workerConfig.allowed_cors_origins || [])
      setRedirectUris(workerConfig.allowed_redirect_uris || [])
      setInitialized(true)
    }
  }, [workerConfig, initialized])

  if (!configId) return null

  const validateOrigin = (origin: string): string | null => {
    origin = origin.trim().replace(/\/+$/, '')
    if (!origin) return null
    if (!/^https?:\/\/[a-zA-Z0-9]/.test(origin)) {
      return 'Must be a valid HTTP(S) origin (e.g., https://example.com)'
    }
    if (origin.startsWith('http://') && !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin)) {
      return 'Non-localhost origins must use HTTPS'
    }
    return null
  }

  const validateRedirectUri = (uri: string): string | null => {
    uri = uri.trim()
    if (!uri) return null
    if (!/^https?:\/\/[a-zA-Z0-9]/.test(uri)) {
      return 'Must start with http:// or https://'
    }
    if (uri.startsWith('http://') && !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?\//.test(uri)) {
      return 'Non-localhost URIs must use HTTPS'
    }
    return null
  }

  const handleAddCorsOrigin = () => {
    const origin = newCorsOrigin.trim().replace(/\/+$/, '')
    setOriginError(null)
    if (!origin) return

    const error = validateOrigin(origin)
    if (error) { setOriginError(error); return }
    if (corsOrigins.includes(origin)) { setOriginError('Already in list'); return }

    setCorsOrigins([...corsOrigins, origin])
    setNewCorsOrigin('')
  }

  const handleAddRedirectUri = () => {
    const uri = newRedirectUri.trim()
    setRedirectError(null)
    if (!uri) return

    const error = validateRedirectUri(uri)
    if (error) { setRedirectError(error); return }
    if (redirectUris.includes(uri)) { setRedirectError('Already in list'); return }

    setRedirectUris([...redirectUris, uri])
    setNewRedirectUri('')
  }

  const handleSaveOrigins = async () => {
    if (!configId) return
    setSaveError(null)
    setSaveSuccess(null)

    try {
      const result = await updateConfig.mutateAsync({
        configId,
        corsOrigins,
        redirectUris,
      })
      setSaveSuccess(
        result.kv_synced
          ? 'Origins updated and synced to Worker'
          : 'Origins saved (Worker KV sync unavailable)'
      )
      setTimeout(() => setSaveSuccess(null), 4000)
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : 'Failed to update origins')
    }
  }

  if (isLoading) {
    return (
      <div className="mt-8 pt-6 border-t border-hl-med">
        <div className="animate-pulse space-y-3">
          <div className="h-6 bg-hl-low rounded w-40"></div>
          <div className="h-4 bg-hl-low rounded w-80"></div>
        </div>
      </div>
    )
  }

  return (
    <div className="mt-8 pt-6 border-t border-hl-med">
      <div className="mb-4">
        <h3 className="text-lg font-medium text-on-base">Allowed Origins</h3>
        <p className="text-sm text-subtle mt-1">
          Additional CORS origins and OAuth redirect URIs for custom MCP clients.
          Built-in origins (Claude, ChatGPT, OpenAI, Cloudflare, localhost) are always included.
        </p>
      </div>

      {/* CORS Origins */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-on-base mb-2">
          CORS Origins
        </label>
        <p className="text-xs text-muted mb-2">
          Additional origins allowed to make cross-origin requests to the Worker.
        </p>
        <div className="flex gap-2 mb-2">
          <input
            type="text"
            value={newCorsOrigin}
            onChange={(e) => { setNewCorsOrigin(e.target.value); setOriginError(null) }}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleAddCorsOrigin() } }}
            placeholder="https://my-mcp-client.example.com"
            className="flex-1 max-w-md px-3 py-2 text-sm border border-hl-med rounded-lg focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris bg-surface text-on-base"
          />
          <button
            onClick={handleAddCorsOrigin}
            disabled={!newCorsOrigin.trim()}
            className="px-4 py-2 text-sm font-medium text-base bg-iris hover:bg-iris/80 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
          >
            Add
          </button>
        </div>
        {originError && <div className="text-sm text-love mb-2">{originError}</div>}
        {corsOrigins.length > 0 && (
          <div className="border border-hl-med rounded-lg divide-y divide-hl-low max-h-40 overflow-y-auto">
            {corsOrigins.map((origin) => (
              <div key={origin} className="flex items-center justify-between px-3 py-2 hover:bg-hl-low">
                <span className="text-sm text-on-base font-mono">{origin}</span>
                <button
                  onClick={() => setCorsOrigins(corsOrigins.filter((o) => o !== origin))}
                  className="p-1 text-muted hover:text-love hover:bg-love/10 rounded transition-colors focus:outline-none focus:ring-2 focus:ring-love"
                  aria-label={`Remove ${origin}`}
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Redirect URIs */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-on-base mb-2">
          OAuth Redirect URI Prefixes
        </label>
        <p className="text-xs text-muted mb-2">
          URI prefixes allowed for OAuth client redirect URIs. The Worker accepts any redirect URI starting with these prefixes.
        </p>
        <div className="flex gap-2 mb-2">
          <input
            type="text"
            value={newRedirectUri}
            onChange={(e) => { setNewRedirectUri(e.target.value); setRedirectError(null) }}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleAddRedirectUri() } }}
            placeholder="https://my-mcp-client.example.com/"
            className="flex-1 max-w-md px-3 py-2 text-sm border border-hl-med rounded-lg focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris bg-surface text-on-base"
          />
          <button
            onClick={handleAddRedirectUri}
            disabled={!newRedirectUri.trim()}
            className="px-4 py-2 text-sm font-medium text-base bg-iris hover:bg-iris/80 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
          >
            Add
          </button>
        </div>
        {redirectError && <div className="text-sm text-love mb-2">{redirectError}</div>}
        {redirectUris.length > 0 && (
          <div className="border border-hl-med rounded-lg divide-y divide-hl-low max-h-40 overflow-y-auto">
            {redirectUris.map((uri) => (
              <div key={uri} className="flex items-center justify-between px-3 py-2 hover:bg-hl-low">
                <span className="text-sm text-on-base font-mono">{uri}</span>
                <button
                  onClick={() => setRedirectUris(redirectUris.filter((u) => u !== uri))}
                  className="p-1 text-muted hover:text-love hover:bg-love/10 rounded transition-colors focus:outline-none focus:ring-2 focus:ring-love"
                  aria-label={`Remove ${uri}`}
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Save button */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSaveOrigins}
          disabled={updateConfig.isPending}
          className="px-4 py-2 bg-iris text-base rounded-lg text-sm font-medium hover:bg-iris/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
        >
          {updateConfig.isPending ? 'Saving...' : 'Save Origins'}
        </button>
        {saveSuccess && <span className="text-sm text-foam">{saveSuccess}</span>}
      </div>

      {saveError && (
        <div className="mt-4 p-3 rounded-lg bg-love/10 text-love border border-love/30">
          {saveError}
        </div>
      )}

      <p className="mt-4 text-xs text-subtle">
        Built-in origins (Claude, ChatGPT, OpenAI, Cloudflare, localhost) are always allowed. These are additional origins for other MCP clients.
      </p>
    </div>
  )
}

// =============================================================================
// Users Tab Component
// =============================================================================

export function UsersTab() {
  const { data: cfStatus, isLoading: statusLoading } = useCloudflareStatus()
  const updateAccessPolicy = useUpdateAccessPolicy()

  const [policyType, setPolicyType] = useState<AccessPolicyType>('everyone')
  const [emails, setEmails] = useState<string[]>([])
  const [emailDomain, setEmailDomain] = useState('')
  const [newEmail, setNewEmail] = useState('')
  const [emailError, setEmailError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [initialized, setInitialized] = useState(false)

  // Initialize local state from server data
  useEffect(() => {
    if (cfStatus && !initialized) {
      if (cfStatus.access_policy_type) {
        setPolicyType(cfStatus.access_policy_type as AccessPolicyType)
      }
      if (cfStatus.access_policy_emails) {
        setEmails(cfStatus.access_policy_emails)
      }
      if (cfStatus.access_policy_email_domain) {
        setEmailDomain(cfStatus.access_policy_email_domain)
      }
      setInitialized(true)
    }
  }, [cfStatus, initialized])

  const isConfigured = cfStatus?.config_id != null

  const handleAddEmail = () => {
    const email = newEmail.trim().toLowerCase()
    setEmailError(null)

    if (!email) return

    // Basic email validation
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setEmailError('Please enter a valid email address')
      return
    }

    if (emails.includes(email)) {
      setEmailError('This email is already in the list')
      return
    }

    setEmails([...emails, email])
    setNewEmail('')
  }

  const handleRemoveEmail = (emailToRemove: string) => {
    setEmails(emails.filter((e) => e !== emailToRemove))
  }

  const handleEmailKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleAddEmail()
    }
  }

  const handleSave = async () => {
    setSaveError(null)
    setSaveSuccess(null)

    if (!cfStatus?.config_id) return

    const accessPolicy: AccessPolicyConfig = {
      policy_type: policyType,
      emails: policyType === 'emails' ? emails : [],
      email_domain: policyType === 'email_domain' ? emailDomain : null,
    }

    try {
      const result = await updateAccessPolicy.mutateAsync({
        configId: cfStatus.config_id,
        accessPolicy,
      })
      setSaveSuccess(result.message || 'Access policy updated successfully')
      setTimeout(() => setSaveSuccess(null), 4000)
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : 'Failed to update access policy')
    }
  }

  if (statusLoading) {
    return (
      <div className="bg-surface rounded-lg shadow p-6">
        <div className="animate-pulse space-y-3">
          <div className="h-6 bg-hl-low rounded w-48"></div>
          <div className="h-4 bg-hl-low rounded w-96"></div>
          <div className="h-32 bg-hl-low rounded"></div>
        </div>
      </div>
    )
  }

  if (!isConfigured) {
    return (
      <div className="bg-surface rounded-lg shadow p-6">
        <h3 className="text-lg font-medium text-on-base mb-4">Approved Users</h3>
        <div className="p-4 rounded-lg bg-hl-low border border-hl-med">
          <p className="text-sm text-subtle">
            Remote access is not configured. Set up Cloudflare tunnel first.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-surface rounded-lg shadow p-6">
      <div className="mb-4">
        <h3 className="text-lg font-medium text-on-base">Approved Users</h3>
        <p className="text-sm text-subtle mt-1">
          Controls who can access MCPbox remotely via the Cloudflare tunnel. Changes are synced to the Cloudflare Access Policy.
        </p>
      </div>

      {/* Policy type radio group */}
      <div className="space-y-3 mb-6">
        <label className="block text-sm font-medium text-on-base">
          Access Policy Type
        </label>
        <div className="space-y-2">
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="radio"
              name="policyType"
              value="everyone"
              checked={policyType === 'everyone'}
              onChange={() => setPolicyType('everyone')}
              className="text-iris focus:ring-iris"
            />
            <span className="text-sm text-on-base">Everyone</span>
          </label>
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="radio"
              name="policyType"
              value="emails"
              checked={policyType === 'emails'}
              onChange={() => setPolicyType('emails')}
              className="text-iris focus:ring-iris"
            />
            <span className="text-sm text-on-base">Specific Emails</span>
          </label>
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="radio"
              name="policyType"
              value="email_domain"
              checked={policyType === 'email_domain'}
              onChange={() => setPolicyType('email_domain')}
              className="text-iris focus:ring-iris"
            />
            <span className="text-sm text-on-base">Email Domain</span>
          </label>
        </div>
      </div>

      {/* Everyone warning */}
      {policyType === 'everyone' && (
        <div className="mb-6 p-3 rounded-lg bg-gold/10 border border-gold/30">
          <div className="flex items-start gap-2">
            <svg className="w-5 h-5 text-gold flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <p className="text-sm text-gold">
              Anyone with the URL can access MCPbox remotely. This is not recommended for production use.
            </p>
          </div>
        </div>
      )}

      {/* Specific emails management */}
      {policyType === 'emails' && (
        <div className="mb-6 space-y-4">
          <div className="flex gap-2">
            <input
              type="email"
              value={newEmail}
              onChange={(e) => {
                setNewEmail(e.target.value)
                setEmailError(null)
              }}
              onKeyPress={handleEmailKeyPress}
              placeholder="user@example.com"
              className="flex-1 max-w-sm px-3 py-2 text-sm border border-hl-med rounded-lg focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris bg-surface text-on-base"
            />
            <button
              onClick={handleAddEmail}
              disabled={!newEmail.trim()}
              className="px-4 py-2 text-sm font-medium text-base bg-iris hover:bg-iris/80 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
            >
              Add
            </button>
          </div>

          {emailError && (
            <div className="text-sm text-love">
              {emailError}
            </div>
          )}

          {emails.length > 0 ? (
            <div className="border border-hl-med rounded-lg divide-y divide-hl-low max-h-60 overflow-y-auto">
              {emails.map((email) => (
                <div
                  key={email}
                  className="flex items-center justify-between px-3 py-2 hover:bg-hl-low"
                >
                  <span className="text-sm text-on-base">{email}</span>
                  <button
                    onClick={() => handleRemoveEmail(email)}
                    className="p-1 text-muted hover:text-love hover:bg-love/10 rounded transition-colors focus:outline-none focus:ring-2 focus:ring-love"
                    aria-label={`Remove ${email}`}
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div className="p-4 text-center text-sm text-subtle border border-hl-med rounded-lg">
              No approved emails. Add email addresses above.
            </div>
          )}
        </div>
      )}

      {/* Email domain input */}
      {policyType === 'email_domain' && (
        <div className="mb-6 space-y-2">
          <label className="block text-sm font-medium text-on-base">
            Allowed Domain
          </label>
          <input
            type="text"
            value={emailDomain}
            onChange={(e) => setEmailDomain(e.target.value.trim())}
            placeholder="company.com"
            className="w-full max-w-sm px-3 py-2 text-sm border border-hl-med rounded-lg focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris bg-surface text-on-base"
          />
          <p className="text-xs text-subtle">
            Any email address ending in @{emailDomain || 'domain.com'} will be allowed access.
          </p>
        </div>
      )}

      {/* Save button */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={updateAccessPolicy.isPending}
          className="px-4 py-2 bg-iris text-base rounded-lg text-sm font-medium hover:bg-iris/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
        >
          {updateAccessPolicy.isPending ? 'Saving...' : 'Save Changes'}
        </button>

        {saveSuccess && (
          <span className="text-sm text-foam">{saveSuccess}</span>
        )}
      </div>

      {saveError && (
        <div className="mt-4 p-3 rounded-lg bg-love/10 text-love border border-love/30">
          {saveError}
        </div>
      )}

      {/* Sync note */}
      <div className="mt-6 pt-4 border-t border-hl-med">
        <p className="text-xs text-subtle">
          Changes are synced to the Cloudflare Access Policy on the OIDC application. The Access Policy is the source of truth for email enforcement.
        </p>
      </div>

      {/* Allowed Origins section */}
      <AllowedOriginsSection configId={cfStatus?.config_id ?? null} />
    </div>
  )
}
