import { useState } from 'react'
import {
  useTunnelConfigurations,
  useActivateTunnelConfiguration,
  useDeleteTunnelConfiguration,
  TunnelConfigurationListItem,
} from '../../api/tunnel'
import { ConfirmModal } from '../ui'

interface ConfigurationListProps {
  onEdit: (config: TunnelConfigurationListItem) => void
  onCreateNew: () => void
}

export function ConfigurationList({ onEdit, onCreateNew }: ConfigurationListProps) {
  const [page, setPage] = useState(1)
  const { data, isLoading } = useTunnelConfigurations(page)
  const activateMutation = useActivateTunnelConfiguration()
  const deleteMutation = useDeleteTunnelConfiguration()
  const [deleteTarget, setDeleteTarget] = useState<TunnelConfigurationListItem | null>(null)

  const handleActivate = async (id: string) => {
    await activateMutation.mutateAsync(id)
  }

  const handleDelete = (config: TunnelConfigurationListItem) => {
    setDeleteTarget(config)
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setDeleteTarget(null)
    await deleteMutation.mutateAsync(deleteTarget.id)
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
                      className="px-3 py-1.5 text-sm font-medium bg-iris/10 hover:bg-iris/20 text-iris rounded-lg transition-colors disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-iris"
                    >
                      Activate
                    </button>
                  )}
                  <button
                    onClick={() => onEdit(config)}
                    className="px-3 py-1.5 text-sm font-medium bg-hl-low hover:bg-hl-med text-subtle rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
                  >
                    Edit
                  </button>
                  {!config.is_active && (
                    <button
                      onClick={() => handleDelete(config)}
                      disabled={deleteMutation.isPending}
                      className="px-3 py-1.5 text-sm font-medium text-love hover:bg-love/10 rounded-lg transition-colors disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-love"
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
        <div className="text-center py-8">
          <svg className="w-12 h-12 text-muted mx-auto mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
          </svg>
          <p className="text-subtle mb-1">No saved configurations yet</p>
          <p className="text-xs text-muted">
            Create a configuration to connect to Claude via Cloudflare MCP Server Portals.
          </p>
          <button
            onClick={onCreateNew}
            className="mt-4 px-4 py-2 bg-iris hover:bg-iris/80 text-base rounded-lg text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
          >
            Create Configuration
          </button>
        </div>
      )}

      <ConfirmModal
        isOpen={deleteTarget !== null}
        title="Delete Configuration"
        message={`Are you sure you want to delete "${deleteTarget?.name}"?`}
        confirmLabel="Delete"
        destructive
        isLoading={deleteMutation.isPending}
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />

      {/* Pagination */}
      {data && data.pages > 1 && (
        <div className="flex justify-center gap-2 mt-4">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1 text-sm border border-hl-med rounded-lg text-on-base disabled:opacity-50 disabled:cursor-not-allowed hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
          >
            Previous
          </button>
          <span className="px-3 py-1 text-sm text-subtle">
            Page {page} of {data.pages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(data.pages, p + 1))}
            disabled={page === data.pages}
            className="px-3 py-1 text-sm border border-hl-med rounded-lg text-on-base disabled:opacity-50 disabled:cursor-not-allowed hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
