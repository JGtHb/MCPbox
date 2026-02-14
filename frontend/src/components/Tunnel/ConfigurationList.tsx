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
          <div key={i} className="h-16 bg-gray-100 dark:bg-gray-700 rounded-lg" />
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
                  ? 'bg-purple-50 dark:bg-purple-900/30 border-purple-200 dark:border-purple-700'
                  : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <h4 className="font-medium text-gray-900 dark:text-white">
                      {config.name}
                    </h4>
                    {config.is_active && (
                      <span className="px-2 py-0.5 text-xs bg-purple-100 dark:bg-purple-800 text-purple-700 dark:text-purple-300 rounded-full">
                        Active
                      </span>
                    )}
                  </div>
                  {config.description && (
                    <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                      {config.description}
                    </p>
                  )}
                  {config.public_url && (
                    <p className="text-sm font-mono text-gray-600 dark:text-gray-300 mt-1">
                      {config.public_url}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2 ml-4">
                  {!config.is_active && (
                    <button
                      onClick={() => handleActivate(config.id)}
                      disabled={activateMutation.isPending}
                      className="px-3 py-1.5 text-sm bg-purple-100 dark:bg-purple-900/50 hover:bg-purple-200 dark:hover:bg-purple-800 text-purple-700 dark:text-purple-300 rounded-lg transition-colors disabled:opacity-50"
                    >
                      Activate
                    </button>
                  )}
                  <button
                    onClick={() => onEdit(config)}
                    className="px-3 py-1.5 text-sm bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-300 rounded-lg transition-colors"
                  >
                    Edit
                  </button>
                  {!config.is_active && (
                    <button
                      onClick={() => handleDelete(config)}
                      disabled={deleteMutation.isPending}
                      className="px-3 py-1.5 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30 rounded-lg transition-colors disabled:opacity-50"
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
        <div className="text-center py-8 text-gray-500 dark:text-gray-400">
          <p>No saved configurations yet.</p>
          <p className="text-sm mt-1">
            Create a configuration to connect to Claude via Cloudflare MCP Server Portals.
          </p>
          <button
            onClick={onCreateNew}
            className="mt-4 px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg transition-colors"
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
            className="px-3 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded disabled:opacity-50"
          >
            Previous
          </button>
          <span className="px-3 py-1 text-sm text-gray-600 dark:text-gray-400">
            Page {page} of {data.pages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(data.pages, p + 1))}
            disabled={page === data.pages}
            className="px-3 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
