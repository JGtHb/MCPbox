import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Header } from '../components/Layout'
import { useCloudflareStatus, useSyncTools, useTeardown } from '../api/cloudflare'

export function Tunnel() {
  const { data: cloudflareStatus, isLoading } = useCloudflareStatus()
  const teardownMutation = useTeardown()
  const syncToolsMutation = useSyncTools()

  const [copySuccess, setCopySuccess] = useState<string | null>(null)

  const handleCopy = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopySuccess(label)
      setTimeout(() => setCopySuccess(null), 2000)
    } catch {
      // Clipboard API not available - ignore silently
    }
  }

  const handleTeardown = async () => {
    if (!cloudflareStatus?.config_id) return
    if (!confirm('Are you sure you want to remove all Cloudflare resources? This will delete the tunnel, worker, and portal.')) {
      return
    }
    try {
      await teardownMutation.mutateAsync(cloudflareStatus.config_id)
    } catch {
      // Error handled by mutation
    }
  }

  // Check if wizard setup is complete
  const isWizardActive = cloudflareStatus?.status === 'active' && cloudflareStatus?.completed_step === 7
  const isWizardInProgress = cloudflareStatus?.config_id && !isWizardActive

  if (isLoading) {
    return (
      <div className="dark:bg-gray-900 min-h-full">
        <Header title="Remote Access" />
        <div className="p-4 sm:p-6 max-w-4xl flex items-center justify-center min-h-[400px]">
          <div className="animate-spin h-8 w-8 border-4 border-purple-500 border-t-transparent rounded-full" />
        </div>
      </div>
    )
  }

  return (
    <div className="dark:bg-gray-900 min-h-full">
      <Header title="Remote Access" />
      <div className="p-4 sm:p-6 max-w-4xl mx-auto">

        {/* Wizard Complete - Show active status */}
        {isWizardActive && (
          <>
            {/* Status Card */}
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 sm:p-6 mb-6">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-3 h-3 rounded-full bg-green-500"></div>
                  <span className="text-lg font-medium text-gray-900 dark:text-white">
                    Remote Access Configured
                  </span>
                </div>
              </div>

              <div className="space-y-4">
                {/* Portal URL */}
                {cloudflareStatus?.mcp_portal_hostname && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                      MCP Portal URL (use this in Claude Web)
                    </label>
                    <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                      <input
                        type="text"
                        readOnly
                        value={`https://${cloudflareStatus.mcp_portal_hostname}/mcp`}
                        className="flex-1 px-3 py-2 bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-sm font-mono text-gray-900 dark:text-gray-100"
                      />
                      <button
                        onClick={() => handleCopy(`https://${cloudflareStatus.mcp_portal_hostname}/mcp`, 'portal')}
                        className="px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg text-sm transition-colors"
                      >
                        {copySuccess === 'portal' ? 'Copied!' : 'Copy URL'}
                      </button>
                    </div>
                  </div>
                )}

                {/* Configuration summary */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-4 border-t border-gray-200 dark:border-gray-700">
                  <div className="text-center p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
                    <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide">Tunnel</div>
                    <div className="text-sm font-medium text-gray-900 dark:text-white mt-1">
                      {cloudflareStatus?.tunnel_name || 'Configured'}
                    </div>
                  </div>
                  <div className="text-center p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
                    <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide">Worker</div>
                    <div className="text-sm font-medium text-gray-900 dark:text-white mt-1">
                      {cloudflareStatus?.worker_name || 'Deployed'}
                    </div>
                  </div>
                  <div className="text-center p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
                    <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide">Security</div>
                    <div className="text-sm font-medium text-green-600 dark:text-green-400 mt-1">
                      JWT Verified
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* How to use */}
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 sm:p-6 mb-6">
              <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">How to Connect Claude Web</h3>
              <div className="space-y-4 text-sm text-gray-600 dark:text-gray-400">
                <ol className="list-decimal list-inside space-y-2">
                  <li>Go to <a href="https://claude.ai" target="_blank" rel="noopener noreferrer" className="text-purple-600 dark:text-purple-400 hover:underline">claude.ai</a> and open Settings</li>
                  <li>Navigate to Integrations or MCP Servers</li>
                  <li>Add your MCP Portal URL: <code className="bg-gray-100 dark:bg-gray-700 px-2 py-0.5 rounded font-mono text-xs">https://{cloudflareStatus?.mcp_portal_hostname}/mcp</code></li>
                  <li>Authenticate when prompted (Cloudflare handles OAuth)</li>
                  <li>Your MCPbox tools will appear in Claude</li>
                </ol>
                <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">
                  If you just completed the setup wizard, it may take a few minutes for Cloudflare
                  to propagate your configuration. Wait and retry if you see a connection error.
                </p>
              </div>
            </div>

            {/* Management actions */}
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 sm:p-6">
              <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Management</h3>
              <div className="flex flex-wrap gap-3">
                <Link
                  to="/tunnel/setup"
                  className="px-4 py-2 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-300 rounded-lg text-sm transition-colors"
                >
                  View Setup Details
                </Link>
                <a
                  href="https://one.dash.cloudflare.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="px-4 py-2 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-300 rounded-lg text-sm transition-colors"
                >
                  Cloudflare Dashboard
                </a>
                <button
                  onClick={() => cloudflareStatus?.config_id && syncToolsMutation.mutate(cloudflareStatus.config_id)}
                  disabled={syncToolsMutation.isPending || !cloudflareStatus?.config_id}
                  className="px-4 py-2 bg-purple-100 dark:bg-purple-900/30 hover:bg-purple-200 dark:hover:bg-purple-900/50 text-purple-700 dark:text-purple-300 rounded-lg text-sm transition-colors"
                >
                  {syncToolsMutation.isPending ? 'Syncing...' : 'Sync Tools'}
                </button>
                <button
                  onClick={handleTeardown}
                  disabled={teardownMutation.isPending}
                  className="px-4 py-2 bg-red-100 dark:bg-red-900/30 hover:bg-red-200 dark:hover:bg-red-900/50 text-red-700 dark:text-red-300 rounded-lg text-sm transition-colors"
                >
                  {teardownMutation.isPending ? 'Removing...' : 'Remove Setup'}
                </button>
              </div>
              {syncToolsMutation.isSuccess && (
                <p className="mt-3 text-sm text-green-600 dark:text-green-400">
                  {syncToolsMutation.data?.message || 'Tools synced successfully'}
                </p>
              )}
              {syncToolsMutation.error && (
                <p className="mt-3 text-sm text-red-600 dark:text-red-400">
                  {syncToolsMutation.error instanceof Error ? syncToolsMutation.error.message : 'Failed to sync tools'}
                </p>
              )}
              {teardownMutation.error && (
                <p className="mt-3 text-sm text-red-600 dark:text-red-400">
                  {teardownMutation.error instanceof Error ? teardownMutation.error.message : 'Failed to remove setup'}
                </p>
              )}
            </div>
          </>
        )}

        {/* Wizard in progress */}
        {isWizardInProgress && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 sm:p-6 mb-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <div className="flex items-center gap-3 mb-2">
                  <div className="w-3 h-3 rounded-full bg-yellow-500 animate-pulse"></div>
                  <span className="text-lg font-medium text-gray-900 dark:text-white">
                    Setup In Progress
                  </span>
                </div>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  Step {cloudflareStatus?.completed_step} of 7 completed
                </p>
              </div>
              <Link
                to="/tunnel/setup"
                className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors text-sm"
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
            <div className="bg-gradient-to-br from-purple-600 to-purple-800 rounded-lg shadow p-6 sm:p-8 mb-6 text-white">
              <h2 className="text-2xl font-bold mb-3">Enable Remote Access</h2>
              <p className="text-purple-100 mb-6">
                Connect Claude Web to your MCPbox tools from anywhere. The setup wizard will
                configure a secure Cloudflare tunnel with Zero Trust authentication.
              </p>
              <Link
                to="/tunnel/setup"
                className="inline-block px-6 py-3 bg-white text-purple-700 font-medium rounded-lg hover:bg-purple-50 transition-colors"
              >
                Start Setup Wizard
              </Link>
            </div>

            {/* What you'll get */}
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 sm:p-6 mb-6">
              <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">What the Wizard Configures</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
                  <h4 className="font-medium text-gray-900 dark:text-white mb-2">Cloudflare Tunnel</h4>
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    Secure outbound connection from your network - no exposed ports needed.
                  </p>
                </div>
                <div className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
                  <h4 className="font-medium text-gray-900 dark:text-white mb-2">Workers VPC</h4>
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    Private network routing so your tunnel has no public URL.
                  </p>
                </div>
                <div className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
                  <h4 className="font-medium text-gray-900 dark:text-white mb-2">MCP Portal</h4>
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    OAuth authentication for Claude Web users on your custom domain.
                  </p>
                </div>
                <div className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
                  <h4 className="font-medium text-gray-900 dark:text-white mb-2">JWT Verification</h4>
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    Cryptographic verification that requests come through the portal.
                  </p>
                </div>
              </div>
            </div>

            {/* Requirements */}
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 sm:p-6">
              <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Requirements</h3>
              <ul className="space-y-2 text-sm text-gray-600 dark:text-gray-400">
                <li className="flex items-start gap-2">
                  <span className="text-green-500 mt-0.5">✓</span>
                  <span>Cloudflare account (free tier works)</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-green-500 mt-0.5">✓</span>
                  <span>Domain added to Cloudflare (for the MCP Portal hostname)</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-green-500 mt-0.5">✓</span>
                  <span>API token with required permissions (wizard will guide you)</span>
                </li>
              </ul>
            </div>
          </>
        )}

      </div>
    </div>
  )
}
