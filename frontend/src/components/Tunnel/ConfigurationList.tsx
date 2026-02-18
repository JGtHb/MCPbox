import { useState } from 'react'
import {
  useTunnelConfigurations,
  useActivateTunnelConfiguration,
  useDeleteTunnelConfiguration,
  TunnelConfigurationListItem,
} from '../../api/tunnel'

interface ConfigurationListProps {
  onEdit: (config: TunnelConfigurationListItem) => void
  onCreateNew: () => void
}

export function ConfigurationList({ onEdit, onCreateNew }: ConfigurationListProps) {
  const [page, setPage] = useState(1)
  const { data, isLoading } = useTunnelConfigurations(page)
  const activateMutation = useActivateTunnelConfiguration()
  const deleteMutation = useDeleteTunnelConfiguration()

  const handleActivate = async (id: string) => {
    await activateMutation.mutateAsync(id)
  }

  const handleDelete = async (config: TunnelConfigurationListItem) => {
    if (confirm(`Are you sure you want to delete "${config.name}"?`)) {
      await deleteMutation.mutateAsync(config.id)
    }
  }

  if (isLoading) {
    return (
      <div className="animate-pulse space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-16 bg-hl-med rounded-lg" />
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Configuration list */}
      {data && data.items.length > 0 ? (
        <div className="space-y-2">
          {data.items.map((config) => (
            <div
              key={config.id}
              className={`p-4 rounded-lg border transition-colors ${
                config.is_active
                  ? 'bg-iris/10 border-iris/30'
                  : 'bg-surface border-hl-med hover:border-hl-high'
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <h4 className="font-medium text-on-base">
                      {config.name}
                    </h4>
                    {config.is_active && (
                      <span className="px-2 py-0.5 text-xs bg-iris/10 text-iris rounded-full">
                        Active
                      </span>
                    )}
                  </div>
                  {config.description && (
                    <p className="text-sm text-muted mt-1">
                      {config.description}
                    </p>
                  )}
                  {config.public_url && (
                    <p className="text-sm font-mono text-subtle mt-1">
                      {config.public_url}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2 ml-4">
                  {!config.is_active && (
                    <button
                      onClick={() => handleActivate(config.id)}
                      disabled={activateMutation.isPending}
                      className="px-3 py-1.5 text-sm bg-iris/10 hover:bg-iris/20 text-iris rounded-lg transition-colors disabled:opacity-50"
                    >
                      Activate
                    </button>
                  )}
                  <button
                    onClick={() => onEdit(config)}
                    className="px-3 py-1.5 text-sm bg-hl-low hover:bg-hl-med text-subtle rounded-lg transition-colors"
                  >
                    Edit
                  </button>
                  {!config.is_active && (
                    <button
                      onClick={() => handleDelete(config)}
                      disabled={deleteMutation.isPending}
                      className="px-3 py-1.5 text-sm text-love hover:bg-love/10 rounded-lg transition-colors disabled:opacity-50"
                    >
                      Delete
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-8 text-subtle">
          <p>No saved configurations yet.</p>
          <p className="text-sm mt-1">
            Create a configuration to connect to Claude via Cloudflare MCP Server Portals.
          </p>
          <button
            onClick={onCreateNew}
            className="mt-4 px-4 py-2 bg-iris hover:bg-iris/80 text-base rounded-lg transition-colors"
          >
            Create Configuration
          </button>
        </div>
      )}

      {/* Pagination */}
      {data && data.pages > 1 && (
        <div className="flex justify-center gap-2 mt-4">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1 text-sm border border-hl-med rounded disabled:opacity-50"
          >
            Previous
          </button>
          <span className="px-3 py-1 text-sm text-subtle">
            Page {page} of {data.pages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(data.pages, p + 1))}
            disabled={page === data.pages}
            className="px-3 py-1 text-sm border border-hl-med rounded disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
