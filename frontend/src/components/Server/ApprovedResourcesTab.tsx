import { useState } from 'react'
import {
  useServerModuleRequests,
  useServerNetworkRequests,
  useServerApprovedTools,
  useRevokeToolApproval,
  useRevokeModuleRequest,
  useRevokeNetworkRequest,
  useModuleRequestAction,
  useNetworkRequestAction,
  useDeleteModuleRequest,
  useDeleteNetworkRequest,
} from '../../api/approvals'
import { useAddAllowedHost, useRemoveAllowedHost } from '../../api/servers'
import { ConfirmModal } from '../ui'

interface ApprovedResourcesTabProps {
  serverId: string
}

const STATUS_BADGE: Record<string, { className: string; label: string }> = {
  approved: { className: 'bg-foam/10 text-foam', label: 'Approved' },
  pending: { className: 'bg-gold/10 text-gold', label: 'Pending' },
  pending_review: { className: 'bg-gold/10 text-gold', label: 'Pending' },
  rejected: { className: 'bg-love/10 text-love', label: 'Rejected' },
}

function StatusBadge({ status }: { status: string }) {
  const badge = STATUS_BADGE[status] ?? { className: 'bg-overlay text-subtle', label: status }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 text-xs font-medium rounded ${badge.className}`}>
      {badge.label}
    </span>
  )
}

function RevokeButton({
  label,
  onRevoke,
  isLoading,
}: {
  label: string
  onRevoke: () => void
  isLoading: boolean
}) {
  const [confirming, setConfirming] = useState(false)

  return (
    <>
      <button
        onClick={() => setConfirming(true)}
        disabled={isLoading}
        className="px-2.5 py-1 text-xs font-medium text-love bg-surface border border-love/20 rounded-lg hover:bg-love/10 transition-colors focus:outline-none focus:ring-2 focus:ring-love disabled:opacity-50"
      >
        Revoke
      </button>
      <ConfirmModal
        isOpen={confirming}
        title="Revoke Approval"
        message={`Are you sure you want to revoke "${label}"? It will be removed from the active configuration.`}
        confirmLabel="Revoke"
        destructive
        isLoading={isLoading}
        onConfirm={() => {
          onRevoke()
          setConfirming(false)
        }}
        onCancel={() => setConfirming(false)}
      />
    </>
  )
}

function RemoveHostButton({
  host,
  onRemove,
  isLoading,
}: {
  host: string
  onRemove: () => void
  isLoading: boolean
}) {
  const [confirming, setConfirming] = useState(false)

  return (
    <>
      <button
        onClick={() => setConfirming(true)}
        disabled={isLoading}
        className="px-2.5 py-1 text-xs font-medium text-love bg-surface border border-love/20 rounded-lg hover:bg-love/10 transition-colors focus:outline-none focus:ring-2 focus:ring-love disabled:opacity-50"
      >
        Remove
      </button>
      <ConfirmModal
        isOpen={confirming}
        title="Remove Host"
        message={`Are you sure you want to remove "${host}" from the allowlist?`}
        confirmLabel="Remove"
        destructive
        isLoading={isLoading}
        onConfirm={() => {
          onRemove()
          setConfirming(false)
        }}
        onCancel={() => setConfirming(false)}
      />
    </>
  )
}

export function ApprovedResourcesTab({ serverId }: ApprovedResourcesTabProps) {
  const { data: moduleData, isLoading: modulesLoading } = useServerModuleRequests(serverId, 'all')
  const { data: networkData, isLoading: networkLoading } = useServerNetworkRequests(serverId, 'all')
  const { data: toolsData, isLoading: toolsLoading } = useServerApprovedTools(serverId)

  const revokeToolMutation = useRevokeToolApproval()
  const revokeModuleMutation = useRevokeModuleRequest()
  const revokeNetworkMutation = useRevokeNetworkRequest()
  const moduleActionMutation = useModuleRequestAction()
  const networkActionMutation = useNetworkRequestAction()
  const deleteModuleMutation = useDeleteModuleRequest()
  const deleteNetworkMutation = useDeleteNetworkRequest()
  const addHostMutation = useAddAllowedHost()
  const removeHostMutation = useRemoveAllowedHost()

  const [error, setError] = useState<string | null>(null)
  const [showAddHost, setShowAddHost] = useState(false)
  const [newHost, setNewHost] = useState('')
  const [rejectModuleTarget, setRejectModuleTarget] = useState<{ id: string; name: string } | null>(null)
  const [rejectNetworkTarget, setRejectNetworkTarget] = useState<{ id: string; name: string } | null>(null)
  const [rejectReason, setRejectReason] = useState('')

  const handleWithError = (fn: () => Promise<unknown>) => {
    setError(null)
    fn().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : 'Operation failed')
    })
  }

  const handleAddHost = () => {
    const host = newHost.trim()
    if (!host) return
    setError(null)
    addHostMutation.mutate(
      { serverId, host },
      {
        onSuccess: () => {
          setNewHost('')
          setShowAddHost(false)
        },
        onError: (err: unknown) => {
          setError(err instanceof Error ? err.message : 'Failed to add host')
        },
      }
    )
  }

  const handleRemoveHost = (host: string) => {
    setError(null)
    removeHostMutation.mutate(
      { serverId, host },
      {
        onError: (err: unknown) => {
          setError(err instanceof Error ? err.message : 'Failed to remove host')
        },
      }
    )
  }

  if (modulesLoading || networkLoading || toolsLoading) {
    return (
      <div className="space-y-6">
        <div className="bg-surface rounded-lg shadow p-6">
          <div className="animate-pulse space-y-3">
            <div className="h-4 bg-hl-med rounded w-1/4" />
            <div className="h-10 bg-hl-med rounded" />
            <div className="h-10 bg-hl-med rounded" />
          </div>
        </div>
      </div>
    )
  }

  const modules = moduleData?.items ?? []
  const networkHosts = networkData?.items ?? []
  const approvedTools = toolsData?.items ?? []

  const pendingModules = modules.filter((m) => !m.status || m.status === 'pending')
  const approvedModules = modules.filter((m) => m.status === 'approved')
  const rejectedModules = modules.filter((m) => m.status === 'rejected')

  const pendingNetwork = networkHosts.filter((n) => !n.status || n.status === 'pending')
  const approvedNetwork = networkHosts.filter((n) => n.status === 'approved')
  const rejectedNetwork = networkHosts.filter((n) => n.status === 'rejected')

  return (
    <div className="space-y-6">
      {error && (
        <div className="p-3 bg-love/10 border border-love/20 rounded-md">
          <p className="text-sm text-love">{error}</p>
        </div>
      )}

      {/* Approved Tools */}
      <div className="bg-surface rounded-lg shadow">
        <div className="px-6 py-4 border-b border-hl-med">
          <h3 className="text-lg font-medium text-on-base">
            Approved Tools ({approvedTools.length})
          </h3>
          <p className="text-xs text-muted mt-0.5">
            Revoke to remove from the active sandbox and return to the review queue
          </p>
        </div>
        {approvedTools.length === 0 ? (
          <div className="px-6 py-8 text-center">
            <svg
              className="w-12 h-12 text-subtle mx-auto mb-3"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
              />
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
              />
            </svg>
            <p className="text-subtle">No approved tools for this server</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-hl-med">
                  <th className="px-6 py-3 text-left text-xs font-medium text-subtle uppercase tracking-wider">
                    Tool
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-subtle uppercase tracking-wider">
                    Approved By
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-subtle uppercase tracking-wider">
                    Approved
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-subtle uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hl-med">
                {approvedTools.map((tool) => (
                  <tr key={tool.id}>
                    <td className="px-6 py-3">
                      <div className="text-sm font-medium font-mono text-on-base">{tool.name}</div>
                      {tool.description && (
                        <div className="text-xs text-muted mt-0.5 truncate max-w-xs">
                          {tool.description}
                        </div>
                      )}
                    </td>
                    <td className="px-6 py-3 text-sm text-subtle">
                      {tool.approved_by ?? '—'}
                    </td>
                    <td className="px-6 py-3 text-sm text-subtle">
                      {tool.approved_at
                        ? new Date(tool.approved_at).toLocaleDateString([], {
                            month: 'short',
                            day: 'numeric',
                            year: 'numeric',
                          })
                        : '—'}
                    </td>
                    <td className="px-6 py-3 text-right">
                      <RevokeButton
                        label={tool.name}
                        isLoading={revokeToolMutation.isPending}
                        onRevoke={() =>
                          handleWithError(() =>
                            revokeToolMutation.mutateAsync(tool.id)
                          )
                        }
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modules */}
      <div className="bg-surface rounded-lg shadow">
        <div className="px-6 py-4 border-b border-hl-med">
          <h3 className="text-lg font-medium text-on-base">
            Modules ({modules.length})
          </h3>
          <p className="text-xs text-muted mt-0.5">
            Python modules allowed for import in the sandbox
          </p>
        </div>
        {modules.length === 0 ? (
          <div className="px-6 py-8 text-center">
            <svg
              className="w-12 h-12 text-subtle mx-auto mb-3"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"
              />
            </svg>
            <p className="text-subtle">No module requests for this server</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-hl-med">
                  <th className="px-6 py-3 text-left text-xs font-medium text-subtle uppercase tracking-wider">
                    Module
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-subtle uppercase tracking-wider">
                    Tool
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-subtle uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-subtle uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hl-med">
                {/* Pending first */}
                {pendingModules.map((mod) => (
                  <tr key={mod.id}>
                    <td className="px-6 py-3">
                      <span className="text-sm font-mono text-on-base">{mod.module_name}</span>
                      {mod.justification && (
                        <p className="text-xs text-muted mt-0.5 truncate max-w-xs">{mod.justification}</p>
                      )}
                    </td>
                    <td className="px-6 py-3 text-sm text-subtle">
                      {mod.source === 'admin' ? (
                        <span className="inline-flex items-center px-2 py-0.5 text-xs rounded-full bg-iris/10 text-iris border border-iris/20">Admin</span>
                      ) : (
                        mod.tool_name ?? '—'
                      )}
                    </td>
                    <td className="px-6 py-3"><StatusBadge status={mod.status} /></td>
                    <td className="px-6 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => handleWithError(() => moduleActionMutation.mutateAsync({ requestId: mod.id, action: 'approve' }))}
                          disabled={moduleActionMutation.isPending}
                          className="px-2.5 py-1 text-xs font-medium text-foam bg-surface border border-foam/20 rounded-lg hover:bg-foam/10 transition-colors focus:outline-none focus:ring-2 focus:ring-foam disabled:opacity-50"
                        >
                          Approve
                        </button>
                        <button
                          onClick={() => setRejectModuleTarget({ id: mod.id, name: mod.module_name })}
                          disabled={moduleActionMutation.isPending}
                          className="px-2.5 py-1 text-xs font-medium text-gold bg-surface border border-gold/20 rounded-lg hover:bg-gold/10 transition-colors focus:outline-none focus:ring-2 focus:ring-gold disabled:opacity-50"
                        >
                          Reject
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {/* Approved */}
                {approvedModules.map((mod) => (
                  <tr key={mod.id}>
                    <td className="px-6 py-3">
                      <span className="text-sm font-mono text-on-base">{mod.module_name}</span>
                    </td>
                    <td className="px-6 py-3 text-sm text-subtle">
                      {mod.source === 'admin' ? (
                        <span className="inline-flex items-center px-2 py-0.5 text-xs rounded-full bg-iris/10 text-iris border border-iris/20">Admin</span>
                      ) : (
                        mod.tool_name ?? '—'
                      )}
                    </td>
                    <td className="px-6 py-3"><StatusBadge status={mod.status} /></td>
                    <td className="px-6 py-3 text-right">
                      <RevokeButton
                        label={mod.module_name}
                        isLoading={revokeModuleMutation.isPending}
                        onRevoke={() =>
                          handleWithError(() =>
                            revokeModuleMutation.mutateAsync(mod.id)
                          )
                        }
                      />
                    </td>
                  </tr>
                ))}
                {/* Rejected */}
                {rejectedModules.map((mod) => (
                  <tr key={mod.id}>
                    <td className="px-6 py-3">
                      <span className="text-sm font-mono text-on-base">{mod.module_name}</span>
                      {mod.rejection_reason && (
                        <p className="text-xs text-love mt-0.5 truncate max-w-xs">{mod.rejection_reason}</p>
                      )}
                    </td>
                    <td className="px-6 py-3 text-sm text-subtle">
                      {mod.source === 'admin' ? (
                        <span className="inline-flex items-center px-2 py-0.5 text-xs rounded-full bg-iris/10 text-iris border border-iris/20">Admin</span>
                      ) : (
                        mod.tool_name ?? '—'
                      )}
                    </td>
                    <td className="px-6 py-3"><StatusBadge status={mod.status} /></td>
                    <td className="px-6 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => handleWithError(() => moduleActionMutation.mutateAsync({ requestId: mod.id, action: 'approve' }))}
                          disabled={moduleActionMutation.isPending}
                          className="px-2.5 py-1 text-xs font-medium text-foam bg-surface border border-foam/20 rounded-lg hover:bg-foam/10 transition-colors focus:outline-none focus:ring-2 focus:ring-foam disabled:opacity-50"
                        >
                          Approve
                        </button>
                        <button
                          onClick={() => handleWithError(() => deleteModuleMutation.mutateAsync(mod.id))}
                          disabled={deleteModuleMutation.isPending}
                          className="px-2.5 py-1 text-xs font-medium text-love bg-surface border border-love/20 rounded-lg hover:bg-love/10 transition-colors focus:outline-none focus:ring-2 focus:ring-love disabled:opacity-50"
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Network Access */}
      <div className="bg-surface rounded-lg shadow">
        <div className="px-6 py-4 border-b border-hl-med flex items-start justify-between">
          <div>
            <h3 className="text-lg font-medium text-on-base">
              Network Access ({networkHosts.length})
            </h3>
            <p className="text-xs text-muted mt-0.5">
              Hosts allowed to be reached from the sandbox
            </p>
          </div>
          {!showAddHost && (
            <button
              onClick={() => setShowAddHost(true)}
              className="px-3 py-1.5 text-xs font-medium text-iris bg-surface border border-iris/20 rounded-lg hover:bg-iris/10 transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
            >
              Add Host
            </button>
          )}
        </div>

        {/* Add Host inline form */}
        {showAddHost && (
          <div className="px-6 py-3 border-b border-hl-med bg-overlay/30">
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={newHost}
                onChange={(e) => setNewHost(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleAddHost()
                  if (e.key === 'Escape') {
                    setShowAddHost(false)
                    setNewHost('')
                  }
                }}
                placeholder="e.g. api.github.com"
                autoFocus
                className="flex-1 px-3 py-1.5 text-sm font-mono bg-surface border border-hl-med rounded-lg text-on-base placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
              />
              <button
                onClick={handleAddHost}
                disabled={!newHost.trim() || addHostMutation.isPending}
                className="px-3 py-1.5 text-xs font-medium text-white bg-iris rounded-lg hover:bg-iris/90 transition-colors focus:outline-none focus:ring-2 focus:ring-iris disabled:opacity-50"
              >
                {addHostMutation.isPending ? 'Adding...' : 'Add'}
              </button>
              <button
                onClick={() => {
                  setShowAddHost(false)
                  setNewHost('')
                }}
                className="px-3 py-1.5 text-xs font-medium text-subtle bg-surface border border-hl-med rounded-lg hover:bg-overlay transition-colors focus:outline-none focus:ring-2 focus:ring-subtle"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {networkHosts.length === 0 && !showAddHost ? (
          <div className="px-6 py-8 text-center">
            <svg
              className="w-12 h-12 text-subtle mx-auto mb-3"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9"
              />
            </svg>
            <p className="text-subtle">No network access configured for this server</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-hl-med">
                  <th className="px-6 py-3 text-left text-xs font-medium text-subtle uppercase tracking-wider">
                    Host
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-subtle uppercase tracking-wider">
                    Port
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-subtle uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-subtle uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hl-med">
                {/* Pending first */}
                {pendingNetwork.map((req) => (
                  <tr key={req.id}>
                    <td className="px-6 py-3">
                      <span className="text-sm font-mono text-on-base">{req.host}</span>
                      {req.justification && (
                        <p className="text-xs text-muted mt-0.5 truncate max-w-xs">{req.justification}</p>
                      )}
                    </td>
                    <td className="px-6 py-3 text-sm text-subtle">{req.port ?? 'Any'}</td>
                    <td className="px-6 py-3"><StatusBadge status={req.status} /></td>
                    <td className="px-6 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => handleWithError(() => networkActionMutation.mutateAsync({ requestId: req.id, action: 'approve' }))}
                          disabled={networkActionMutation.isPending}
                          className="px-2.5 py-1 text-xs font-medium text-foam bg-surface border border-foam/20 rounded-lg hover:bg-foam/10 transition-colors focus:outline-none focus:ring-2 focus:ring-foam disabled:opacity-50"
                        >
                          Approve
                        </button>
                        <button
                          onClick={() => setRejectNetworkTarget({ id: req.id, name: `${req.host}${req.port ? `:${req.port}` : ''}` })}
                          disabled={networkActionMutation.isPending}
                          className="px-2.5 py-1 text-xs font-medium text-gold bg-surface border border-gold/20 rounded-lg hover:bg-gold/10 transition-colors focus:outline-none focus:ring-2 focus:ring-gold disabled:opacity-50"
                        >
                          Reject
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {/* Approved */}
                {approvedNetwork.map((req) => (
                  <tr key={req.id}>
                    <td className="px-6 py-3 text-sm font-mono text-on-base">{req.host}</td>
                    <td className="px-6 py-3 text-sm text-subtle">{req.port ?? 'Any'}</td>
                    <td className="px-6 py-3"><StatusBadge status={req.status} /></td>
                    <td className="px-6 py-3 text-right">
                      {req.source === 'admin' ? (
                        <RemoveHostButton
                          host={req.host}
                          isLoading={removeHostMutation.isPending}
                          onRemove={() => handleRemoveHost(req.host)}
                        />
                      ) : (
                        <RevokeButton
                          label={req.host}
                          isLoading={revokeNetworkMutation.isPending}
                          onRevoke={() =>
                            handleWithError(() =>
                              revokeNetworkMutation.mutateAsync(req.id)
                            )
                          }
                        />
                      )}
                    </td>
                  </tr>
                ))}
                {/* Rejected */}
                {rejectedNetwork.map((req) => (
                  <tr key={req.id}>
                    <td className="px-6 py-3">
                      <span className="text-sm font-mono text-on-base">{req.host}</span>
                      {req.rejection_reason && (
                        <p className="text-xs text-love mt-0.5 truncate max-w-xs">{req.rejection_reason}</p>
                      )}
                    </td>
                    <td className="px-6 py-3 text-sm text-subtle">{req.port ?? 'Any'}</td>
                    <td className="px-6 py-3"><StatusBadge status={req.status} /></td>
                    <td className="px-6 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => handleWithError(() => networkActionMutation.mutateAsync({ requestId: req.id, action: 'approve' }))}
                          disabled={networkActionMutation.isPending}
                          className="px-2.5 py-1 text-xs font-medium text-foam bg-surface border border-foam/20 rounded-lg hover:bg-foam/10 transition-colors focus:outline-none focus:ring-2 focus:ring-foam disabled:opacity-50"
                        >
                          Approve
                        </button>
                        <button
                          onClick={() => handleWithError(() => deleteNetworkMutation.mutateAsync(req.id))}
                          disabled={deleteNetworkMutation.isPending}
                          className="px-2.5 py-1 text-xs font-medium text-love bg-surface border border-love/20 rounded-lg hover:bg-love/10 transition-colors focus:outline-none focus:ring-2 focus:ring-love disabled:opacity-50"
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Module Reject Modal */}
      {rejectModuleTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-base/50" role="dialog" aria-modal="true" onClick={() => { setRejectModuleTarget(null); setRejectReason('') }}>
          <div className="w-full max-w-md rounded-lg bg-surface p-6 shadow-xl mx-4" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-medium text-on-base">Reject: {rejectModuleTarget.name}</h3>
            <p className="mt-1 text-sm text-subtle">Provide a reason for the rejection (optional).</p>
            <textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              className="mt-4 w-full rounded-lg border border-hl-med p-2 text-sm bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
              rows={3}
              placeholder="Reason (optional)..."
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => { setRejectModuleTarget(null); setRejectReason('') }}
                className="rounded-lg border border-hl-med px-3 py-1.5 text-sm font-medium text-on-base hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  await moduleActionMutation.mutateAsync({ requestId: rejectModuleTarget.id, action: 'reject', reason: rejectReason.trim() || undefined })
                  setRejectModuleTarget(null)
                  setRejectReason('')
                }}
                disabled={moduleActionMutation.isPending}
                className="rounded-lg bg-gold px-3 py-1.5 text-sm font-medium text-base hover:bg-gold/80 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gold"
              >
                Reject
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Network Reject Modal */}
      {rejectNetworkTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-base/50" role="dialog" aria-modal="true" onClick={() => { setRejectNetworkTarget(null); setRejectReason('') }}>
          <div className="w-full max-w-md rounded-lg bg-surface p-6 shadow-xl mx-4" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-medium text-on-base">Reject: {rejectNetworkTarget.name}</h3>
            <p className="mt-1 text-sm text-subtle">Provide a reason for the rejection (optional).</p>
            <textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              className="mt-4 w-full rounded-lg border border-hl-med p-2 text-sm bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
              rows={3}
              placeholder="Reason (optional)..."
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => { setRejectNetworkTarget(null); setRejectReason('') }}
                className="rounded-lg border border-hl-med px-3 py-1.5 text-sm font-medium text-on-base hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  await networkActionMutation.mutateAsync({ requestId: rejectNetworkTarget.id, action: 'reject', reason: rejectReason.trim() || undefined })
                  setRejectNetworkTarget(null)
                  setRejectReason('')
                }}
                disabled={networkActionMutation.isPending}
                className="rounded-lg bg-gold px-3 py-1.5 text-sm font-medium text-base hover:bg-gold/80 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gold"
              >
                Reject
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
