import { useState, useEffect } from 'react'
import {
  useCreateTunnelConfiguration,
  useUpdateTunnelConfiguration,
  TunnelConfigurationCreate,
  TunnelConfigurationUpdate,
  TunnelConfigurationListItem,
} from '../../api/tunnel'

interface ConfigurationFormProps {
  editConfig?: TunnelConfigurationListItem | null
  onClose: () => void
  onSuccess: () => void
}

export function ConfigurationForm({ editConfig, onClose, onSuccess }: ConfigurationFormProps) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [publicUrl, setPublicUrl] = useState('')
  const [tunnelToken, setTunnelToken] = useState('')
  const [showToken, setShowToken] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const createMutation = useCreateTunnelConfiguration()
  const updateMutation = useUpdateTunnelConfiguration()

  const isEditing = !!editConfig

  useEffect(() => {
    if (editConfig) {
      setName(editConfig.name)
      setDescription(editConfig.description || '')
      setPublicUrl(editConfig.public_url || '')
      setTunnelToken('')
    }
  }, [editConfig])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    try {
      if (isEditing) {
        const data: TunnelConfigurationUpdate = {
          name,
          description: description || undefined,
          public_url: publicUrl || undefined,
        }
        if (tunnelToken) {
          data.tunnel_token = tunnelToken
        }
        await updateMutation.mutateAsync({ id: editConfig!.id, data })
      } else {
        if (!tunnelToken) {
          setError('Tunnel token is required')
          return
        }
        const data: TunnelConfigurationCreate = {
          name,
          description: description || undefined,
          public_url: publicUrl || undefined,
          tunnel_token: tunnelToken,
        }
        await createMutation.mutateAsync(data)
      }
      onSuccess()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save configuration')
    }
  }

  const isPending = createMutation.isPending || updateMutation.isPending

  return (
    <div className="fixed inset-0 bg-base/50 flex items-center justify-center z-50 p-4">
      <div className="bg-surface rounded-lg shadow-xl p-4 sm:p-6 w-full max-w-lg">
        <h3 className="text-lg font-medium text-on-base mb-4">
          {isEditing ? 'Edit Configuration' : 'New Tunnel Configuration'}
        </h3>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-subtle mb-1">
              Configuration Name *
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Production, Development"
              required
              className="w-full px-3 py-2 border border-hl-med rounded-lg text-sm bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-subtle mb-1">
              Description
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional description"
              className="w-full px-3 py-2 border border-hl-med rounded-lg text-sm bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
            />
          </div>

          {/* Public URL */}
          <div>
            <label className="block text-sm font-medium text-subtle mb-1">
              Public URL / Custom Subdomain
            </label>
            <input
              type="text"
              value={publicUrl}
              onChange={(e) => setPublicUrl(e.target.value)}
              placeholder="e.g., mcpbox.example.com"
              className="w-full px-3 py-2 border border-hl-med rounded-lg text-sm bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
            />
            <p className="mt-1 text-xs text-muted">
              The hostname you configured in Cloudflare for this tunnel
            </p>
          </div>

          {/* Tunnel Token */}
          <div>
            <label className="block text-sm font-medium text-subtle mb-1">
              Tunnel Token {isEditing ? '(leave empty to keep current)' : '*'}
            </label>
            <div className="relative">
              <input
                type={showToken ? 'text' : 'password'}
                value={tunnelToken}
                onChange={(e) => setTunnelToken(e.target.value)}
                placeholder={isEditing ? 'Enter new token to update' : 'Paste your tunnel token'}
                required={!isEditing}
                className="w-full px-3 py-2 pr-16 border border-hl-med rounded-lg text-sm bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
              />
              <button
                type="button"
                onClick={() => setShowToken(!showToken)}
                aria-label="Toggle password visibility"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-muted hover:text-on-base rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
              >
                {showToken ? 'Hide' : 'Show'}
              </button>
            </div>
            <p className="mt-1 text-xs text-muted">
              Get this from{' '}
              <a
                href="https://one.dash.cloudflare.com/"
                target="_blank"
                rel="noopener noreferrer"
                className="text-pine hover:underline"
              >
                Cloudflare Zero Trust Dashboard
              </a>
              {' '}&rarr; Networks &rarr; Tunnels
            </p>
          </div>

          {/* Error */}
          {error && (
            <div className="p-3 bg-love/10 border border-love/20 rounded-lg">
              <p className="text-sm text-love">{error}</p>
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 border border-hl-med rounded-lg text-subtle hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isPending || !name}
              className="flex-1 px-4 py-2 bg-iris text-base rounded-lg hover:bg-iris/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
            >
              {isPending ? 'Saving...' : isEditing ? 'Update' : 'Create'}
            </button>
          </div>
        </form>

        {/* Setup help */}
        {!isEditing && (
          <div className="mt-6 pt-4 border-t border-hl-med">
            <h4 className="text-sm font-medium text-on-base mb-2">
              How to create a named tunnel
            </h4>
            <ol className="text-xs text-subtle space-y-1 list-decimal list-inside">
              <li>Go to Cloudflare Zero Trust Dashboard</li>
              <li>Navigate to Networks &rarr; Tunnels</li>
              <li>Click "Create a tunnel"</li>
              <li>Choose "Cloudflared" and give it a name</li>
              <li>Copy the tunnel token shown</li>
              <li>Add a public hostname (e.g., mcpbox.yourdomain.com)</li>
              <li>Set service to HTTP://localhost:8000</li>
            </ol>
          </div>
        )}
      </div>
    </div>
  )
}
