import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Header } from '../components/Layout'
import { ConfirmModal } from '../components/ui'
import { useCloudflareStatus, useTeardown } from '../api/cloudflare'

export function Tunnel() {
  const { data: cloudflareStatus, isLoading } = useCloudflareStatus()
  const teardownMutation = useTeardown()

  const [copySuccess, setCopySuccess] = useState<string | null>(null)
  const [showTeardownConfirm, setShowTeardownConfirm] = useState(false)

  const handleCopy = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopySuccess(label)
      setTimeout(() => setCopySuccess(null), 2000)
    } catch {
      // Clipboard API not available - ignore silently
    }
  }

  const handleTeardown = () => {
    if (!cloudflareStatus?.config_id) return
    setShowTeardownConfirm(true)
  }

  const confirmTeardown = async () => {
    if (!cloudflareStatus?.config_id) return
    setShowTeardownConfirm(false)
    try {
      await teardownMutation.mutateAsync(cloudflareStatus.config_id)
    } catch {
      // Error handled by mutation
    }
  }

  // Check if wizard setup is complete
  const isWizardActive = cloudflareStatus?.status === 'active' && cloudflareStatus?.completed_step === 5
  const isWizardInProgress = cloudflareStatus?.config_id && !isWizardActive

  if (isLoading) {
    return (
      <div className="min-h-full">
        <Header title="Remote Access" />
        <div className="p-4 sm:p-6 max-w-4xl flex items-center justify-center min-h-[400px]">
          <div className="animate-spin h-8 w-8 border-4 border-iris border-t-transparent rounded-full" />
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-full">
      <Header title="Remote Access" />
      <div className="p-4 sm:p-6 max-w-4xl mx-auto">

        {/* Wizard Complete - Show active status */}
        {isWizardActive && (
          <>
            {/* Status Card */}
            <div className="bg-surface rounded-lg shadow p-4 sm:p-6 mb-6">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-3 h-3 rounded-full bg-foam"></div>
                  <span className="text-lg font-medium text-on-base">
                    Remote Access Configured
                  </span>
                </div>
              </div>

              <div className="space-y-4">
                {/* Worker URL */}
                {cloudflareStatus?.worker_url && (
                  <div>
                    <label className="block text-sm font-medium text-subtle mb-2">
                      MCP Endpoint URL
                    </label>
                    <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                      <input
                        type="text"
                        readOnly
                        value={`${cloudflareStatus.worker_url}/mcp`}
                        className="flex-1 px-3 py-2 bg-hl-low border border-hl-med rounded-lg text-sm font-mono text-on-base"
                      />
                      <button
                        onClick={() => handleCopy(`${cloudflareStatus.worker_url}/mcp`, 'worker')}
                        className="px-4 py-2 bg-iris hover:bg-iris/80 text-base rounded-lg text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
                      >
                        {copySuccess === 'worker' ? 'Copied!' : 'Copy URL'}
                      </button>
                    </div>
                  </div>
                )}

                {/* Configuration summary */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-4 border-t border-hl-med">
                  <div className="text-center p-3 bg-hl-low rounded-lg">
                    <div className="text-xs text-muted uppercase tracking-wide">Tunnel</div>
                    <div className="text-sm font-medium text-on-base mt-1">
                      {cloudflareStatus?.tunnel_name || 'Configured'}
                    </div>
                  </div>
                  <div className="text-center p-3 bg-hl-low rounded-lg">
                    <div className="text-xs text-muted uppercase tracking-wide">Worker</div>
                    <div className="text-sm font-medium text-on-base mt-1">
                      {cloudflareStatus?.worker_name || 'Deployed'}
                    </div>
                  </div>
                  <div className="text-center p-3 bg-hl-low rounded-lg">
                    <div className="text-xs text-muted uppercase tracking-wide">Security</div>
                    <div className="text-sm font-medium text-foam mt-1">
                      JWT Verified
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* How to use */}
            <div className="bg-surface rounded-lg shadow p-4 sm:p-6 mb-6">
              <h3 className="text-lg font-medium text-on-base mb-4">How to Connect</h3>
              <div className="space-y-4 text-sm text-subtle">
                <ol className="list-decimal list-inside space-y-2">
                  <li>Open your MCP client (Claude, ChatGPT, Cursor, etc.) and go to Settings</li>
                  <li>Navigate to Integrations or MCP Servers</li>
                  <li>Add your Worker URL: <code className="bg-hl-low px-2 py-0.5 rounded font-mono text-xs">{cloudflareStatus?.worker_url}/mcp</code></li>
                  <li>Authenticate when prompted (OAuth handled by the Worker)</li>
                  <li>Your MCPbox tools will appear in the client</li>
                </ol>
                <p className="mt-3 text-xs text-muted">
                  If you just completed the setup wizard, it may take a few minutes for Cloudflare
                  to propagate your configuration. Wait and retry if you see a connection error.
                </p>
              </div>
            </div>

            {/* Management actions */}
            <div className="bg-surface rounded-lg shadow p-4 sm:p-6">
              <h3 className="text-lg font-medium text-on-base mb-4">Management</h3>
              <div className="flex flex-wrap gap-3">
                <Link
                  to="/tunnel/setup"
                  className="px-4 py-2 bg-hl-low hover:bg-hl-med text-subtle rounded-lg text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
                >
                  View Setup Details
                </Link>
                <a
                  href="https://one.dash.cloudflare.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="px-4 py-2 bg-hl-low hover:bg-hl-med text-subtle rounded-lg text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
                >
                  Cloudflare Dashboard
                </a>
                <button
                  onClick={handleTeardown}
                  disabled={teardownMutation.isPending}
                  className="px-4 py-2 bg-love/10 hover:bg-love/20 text-love rounded-lg text-sm font-medium transition-colors disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-love"
                >
                  {teardownMutation.isPending ? 'Removing...' : 'Remove Setup'}
                </button>
              </div>
              {teardownMutation.error && (
                <p className="mt-3 text-sm text-love">
                  {teardownMutation.error instanceof Error ? teardownMutation.error.message : 'Failed to remove setup'}
                </p>
              )}
            </div>
          </>
        )}

        {/* Wizard in progress */}
        {isWizardInProgress && (
          <div className="bg-surface rounded-lg shadow p-4 sm:p-6 mb-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <div className="flex items-center gap-3 mb-2">
                  <div className="w-3 h-3 rounded-full bg-gold animate-pulse"></div>
                  <span className="text-lg font-medium text-on-base">
                    Setup In Progress
                  </span>
                </div>
                <p className="text-sm text-subtle">
                  Step {cloudflareStatus?.completed_step} of 5 completed
                </p>
              </div>
              <Link
                to="/tunnel/setup"
                className="px-4 py-2 bg-iris text-base rounded-lg hover:bg-iris/80 transition-colors text-sm font-medium focus:outline-none focus:ring-2 focus:ring-iris"
              >
                Continue Setup
              </Link>
            </div>
          </div>
        )}

        {/* No setup - show getting started */}
        {!cloudflareStatus?.config_id && (
          <>
            {/* Hero card */}
            <div className="bg-gradient-to-br from-rose to-rose/80 rounded-lg shadow p-6 sm:p-8 mb-6 text-base">
              <h2 className="text-2xl font-bold mb-3">Enable Remote Access</h2>
              <p className="text-base/70 mb-6">
                Use your MCPbox tools from any MCP client, anywhere. The setup wizard will
                configure a secure Cloudflare tunnel with Zero Trust authentication.
              </p>
              <Link
                to="/tunnel/setup"
                className="inline-block px-6 py-3 bg-base text-iris font-medium rounded-lg hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-base"
              >
                Start Setup Wizard
              </Link>
            </div>

            {/* What you'll get */}
            <div className="bg-surface rounded-lg shadow p-4 sm:p-6 mb-6">
              <h3 className="text-lg font-medium text-on-base mb-4">What the Wizard Configures</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="p-4 bg-hl-low rounded-lg">
                  <h4 className="font-medium text-on-base mb-2">Cloudflare Tunnel</h4>
                  <p className="text-sm text-subtle">
                    Secure outbound connection from your network - no exposed ports needed.
                  </p>
                </div>
                <div className="p-4 bg-hl-low rounded-lg">
                  <h4 className="font-medium text-on-base mb-2">Workers VPC</h4>
                  <p className="text-sm text-subtle">
                    Private network routing so your tunnel has no public URL.
                  </p>
                </div>
                <div className="p-4 bg-hl-low rounded-lg">
                  <h4 className="font-medium text-on-base mb-2">OIDC Authentication</h4>
                  <p className="text-sm text-subtle">
                    OAuth 2.1 authentication via Cloudflare Access for secure MCP client access.
                  </p>
                </div>
              </div>
            </div>

            {/* Requirements */}
            <div className="bg-surface rounded-lg shadow p-4 sm:p-6">
              <h3 className="text-lg font-medium text-on-base mb-4">Requirements</h3>
              <ul className="space-y-2 text-sm text-subtle">
                <li className="flex items-start gap-2">
                  <span className="text-foam mt-0.5">&#10003;</span>
                  <span>Cloudflare account (free tier works)</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-foam mt-0.5">&#10003;</span>
                  <span>API token with required permissions (wizard will guide you)</span>
                </li>
              </ul>
            </div>
          </>
        )}

      </div>

      <ConfirmModal
        isOpen={showTeardownConfirm}
        title="Remove Cloudflare Setup"
        message="Are you sure you want to remove all Cloudflare resources? This will delete the tunnel, worker, and OIDC configuration."
        confirmLabel="Remove Setup"
        destructive
        isLoading={teardownMutation.isPending}
        onConfirm={confirmTeardown}
        onCancel={() => setShowTeardownConfirm(false)}
      />
    </div>
  )
}
