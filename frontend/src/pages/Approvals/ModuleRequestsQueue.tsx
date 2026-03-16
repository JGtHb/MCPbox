import React, { useState } from 'react'
import {
  usePendingModuleRequests,
  useModuleRequestAction,
  useBulkModuleRequestAction,
  useRevokeModuleRequest,
  useDeleteModuleRequest,
  ModuleRequestQueueItem,
} from '../../api/approvals'
import { ConfirmModal } from '../../components/ui'
import { StatusBadge, formatDate, isPendingStatus } from './shared'
import { PyPIInfoDisplay } from './PyPIInfoDisplay'

export function ModuleRequestsQueue() {
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const { data, isLoading, error } = usePendingModuleRequests(1, 100, debouncedSearch || undefined, 'all')
  const moduleAction = useModuleRequestAction()
  const bulkAction = useBulkModuleRequestAction()
  const revokeAction = useRevokeModuleRequest()
  const deleteAction = useDeleteModuleRequest()
  const [selectedRequest, setSelectedRequest] = useState<ModuleRequestQueueItem | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [showRejectModal, setShowRejectModal] = useState(false)
  const [revokeTarget, setRevokeTarget] = useState<ModuleRequestQueueItem | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ModuleRequestQueueItem | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [showBulkRejectModal, setShowBulkRejectModal] = useState(false)
  const [bulkRejectReason, setBulkRejectReason] = useState('')

  React.useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchQuery), 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  const pendingItems = data?.items.filter((r) => isPendingStatus(r.status)) ?? []
  const approvedItems = data?.items.filter((r) => r.status === 'approved') ?? []
  const rejectedItems = data?.items.filter((r) => r.status === 'rejected') ?? []

  const toggleSelection = (id: string) => {
    const newSet = new Set(selectedIds)
    if (newSet.has(id)) { newSet.delete(id) } else { newSet.add(id) }
    setSelectedIds(newSet)
  }

  const toggleSelectAll = () => {
    setSelectedIds(
      selectedIds.size === pendingItems.length && pendingItems.length > 0
        ? new Set()
        : new Set(pendingItems.map((r) => r.id))
    )
  }

  const handleApprove = async (requestId: string) => {
    await moduleAction.mutateAsync({ requestId, action: 'approve' })
    selectedIds.delete(requestId)
    setSelectedIds(new Set(selectedIds))
  }

  const handleReject = async () => {
    if (selectedRequest) {
      await moduleAction.mutateAsync({ requestId: selectedRequest.id, action: 'reject', reason: rejectReason.trim() || undefined })
      selectedIds.delete(selectedRequest.id)
      setSelectedIds(new Set(selectedIds))
      setShowRejectModal(false)
      setRejectReason('')
      setSelectedRequest(null)
    }
  }

  const handleBulkApprove = async () => {
    if (selectedIds.size === 0) return
    await bulkAction.mutateAsync({ requestIds: Array.from(selectedIds), action: 'approve' })
    setSelectedIds(new Set())
  }

  const handleBulkReject = async () => {
    if (selectedIds.size === 0) return
    await bulkAction.mutateAsync({ requestIds: Array.from(selectedIds), action: 'reject', reason: bulkRejectReason.trim() || undefined })
    setSelectedIds(new Set())
    setShowBulkRejectModal(false)
    setBulkRejectReason('')
  }

  if (error) {
    return (
      <div className="text-center py-8 text-love">
        Error loading module requests: {error instanceof Error ? error.message : 'Unknown error'}
      </div>
    )
  }

  const ModuleCard = ({ req, isPending }: { req: ModuleRequestQueueItem; isPending: boolean }) => (
    <div className={`rounded-lg border p-4 shadow-sm ${
      isPending && selectedIds.has(req.id)
        ? 'border-iris bg-surface ring-1 ring-iris/30'
        : 'border-hl-med bg-surface'
    }`}>
      <div className="flex items-start gap-3">
        {isPending ? (
          <input
            type="checkbox"
            checked={selectedIds.has(req.id)}
            onChange={() => toggleSelection(req.id)}
            className="mt-1 h-4 w-4 rounded border-hl-med text-iris focus:ring-iris"
          />
        ) : (
          <div className="mt-1 h-4 w-4" />
        )}
        <div className="flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <code className="rounded bg-iris/10 px-2 py-0.5 text-sm font-medium text-iris">{req.module_name}</code>
            <span className="text-sm text-subtle">for</span>
            <span className="text-sm font-medium text-on-base">
              {req.tool_name ? `${req.server_name ?? 'Global'}.${req.tool_name}` : req.server_name ?? 'Global'}
            </span>
            {req.source === 'admin' && (
              <span className="inline-flex items-center px-2 py-0.5 text-xs rounded-full bg-iris/10 text-iris border border-iris/20">Admin</span>
            )}
            <StatusBadge status={req.status} />
          </div>
          <p className="mt-2 text-sm text-subtle">{req.justification}</p>
          {req.requested_by && <p className="mt-1 text-xs text-muted">Requested by: {req.requested_by}</p>}
          {req.status === 'approved' && req.reviewed_at && (
            <p className="mt-1 text-xs text-foam">
              Approved{req.reviewed_by ? ` by ${req.reviewed_by}` : ''} on {formatDate(req.reviewed_at)}
            </p>
          )}
          {req.status === 'rejected' && req.rejection_reason && (
            <div className="mt-2 rounded bg-love/10 p-2 text-sm text-love">
              <strong>Rejection reason:</strong> {req.rejection_reason}
            </div>
          )}
          <PyPIInfoDisplay info={req.pypi_info} moduleName={req.module_name} />
        </div>
        <div className="ml-4 flex gap-2 shrink-0">
          {isPending ? (
            <>
              <button
                onClick={() => handleApprove(req.id)}
                disabled={moduleAction.isPending}
                className="rounded-lg bg-foam px-3 py-1.5 text-sm font-medium text-base hover:bg-foam/80 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-foam"
              >
                Approve
              </button>
              <button
                onClick={() => { setSelectedRequest(req); setShowRejectModal(true) }}
                disabled={moduleAction.isPending}
                className="rounded-lg bg-gold px-3 py-1.5 text-sm font-medium text-base hover:bg-gold/80 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gold"
              >
                Reject
              </button>
            </>
          ) : req.status === 'approved' ? (
            <button
              onClick={() => setRevokeTarget(req)}
              disabled={revokeAction.isPending}
              className="px-2.5 py-1 text-xs font-medium text-love bg-surface border border-love/20 rounded-lg hover:bg-love/10 transition-colors focus:outline-none focus:ring-2 focus:ring-love disabled:opacity-50"
            >
              Revoke
            </button>
          ) : (
            <>
              <button
                onClick={() => handleApprove(req.id)}
                disabled={moduleAction.isPending}
                className="rounded-lg bg-foam px-3 py-1.5 text-sm font-medium text-base hover:bg-foam/80 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-foam"
              >
                Approve
              </button>
              <button
                onClick={() => setDeleteTarget(req)}
                disabled={deleteAction.isPending}
                className="px-2.5 py-1 text-xs font-medium text-love bg-surface border border-love/20 rounded-lg hover:bg-love/10 transition-colors focus:outline-none focus:ring-2 focus:ring-love disabled:opacity-50"
              >
                Delete
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )

  return (
    <div className="space-y-4">
      {/* Search */}
      <div className="flex items-center gap-2">
        <input
          type="text"
          placeholder="Search by module name or justification..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="flex-1 rounded-lg border border-hl-med px-3 py-2 text-sm placeholder-muted bg-surface text-on-base focus:border-iris focus:outline-none focus:ring-2 focus:ring-iris"
        />
        {searchQuery && (
          <button onClick={() => setSearchQuery('')} className="text-sm text-subtle hover:text-on-base">
            Clear
          </button>
        )}
      </div>

      {/* Bulk Action Toolbar */}
      {selectedIds.size > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-rose/30 bg-rose/10 px-4 py-2">
          <span className="text-sm font-medium text-rose">{selectedIds.size} selected</span>
          <button
            onClick={handleBulkApprove}
            disabled={bulkAction.isPending}
            className="rounded-lg bg-foam px-3 py-1 text-sm font-medium text-base hover:bg-foam/80 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-foam"
          >
            Approve All
          </button>
          <button
            onClick={() => setShowBulkRejectModal(true)}
            disabled={bulkAction.isPending}
            className="rounded-lg bg-gold px-3 py-1 text-sm font-medium text-base hover:bg-gold/80 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gold"
          >
            Reject All
          </button>
          <button onClick={() => setSelectedIds(new Set())} className="text-sm text-rose hover:text-rose/80">
            Clear
          </button>
        </div>
      )}

      {isLoading ? (
        <div className="text-center py-8 text-subtle">Loading...</div>
      ) : (
        <>
          {/* Pending section */}
          {pendingItems.length === 0 && !debouncedSearch ? (
            <div className="text-center py-8">
              <svg className="w-12 h-12 text-muted mx-auto mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
              </svg>
              <p className="text-subtle mb-1">No module requests pending approval</p>
              <p className="text-xs text-muted">Module import requests will appear here</p>
            </div>
          ) : pendingItems.length === 0 && debouncedSearch ? null : (
            <>
              {pendingItems.length > 0 && (
                <div className="flex items-center gap-2 py-1">
                  <input
                    type="checkbox"
                    checked={selectedIds.size === pendingItems.length}
                    onChange={toggleSelectAll}
                    className="h-4 w-4 rounded border-hl-med text-iris focus:ring-iris"
                  />
                  <span className="text-sm text-subtle">Select all pending ({pendingItems.length})</span>
                </div>
              )}
              {pendingItems.map((req) => <ModuleCard key={req.id} req={req} isPending={true} />)}
            </>
          )}

          {/* Approved section */}
          {approvedItems.length > 0 && (
            <div className="mt-6">
              <div className="flex items-center gap-3 mb-3">
                <h3 className="text-sm font-medium text-subtle uppercase tracking-wide">
                  Approved ({approvedItems.length})
                </h3>
                <div className="flex-1 h-px bg-hl-med" />
              </div>
              <div className="space-y-3">
                {approvedItems.map((req) => <ModuleCard key={req.id} req={req} isPending={false} />)}
              </div>
            </div>
          )}

          {/* Rejected section */}
          {rejectedItems.length > 0 && (
            <div className="mt-6">
              <div className="flex items-center gap-3 mb-3">
                <h3 className="text-sm font-medium text-subtle uppercase tracking-wide">
                  Rejected ({rejectedItems.length})
                </h3>
                <div className="flex-1 h-px bg-hl-med" />
              </div>
              <div className="space-y-3">
                {rejectedItems.map((req) => <ModuleCard key={req.id} req={req} isPending={false} />)}
              </div>
            </div>
          )}

          {debouncedSearch && pendingItems.length === 0 && approvedItems.length === 0 && rejectedItems.length === 0 && (
            <div className="text-center py-8">
              <p className="text-subtle">No module requests match your search</p>
              <p className="text-xs text-muted mt-1">Try a different search term</p>
            </div>
          )}
        </>
      )}

      {/* Reject Modal */}
      {showRejectModal && selectedRequest && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-base/50" role="dialog" aria-modal="true">
          <div className="w-full max-w-md rounded-lg bg-surface p-6 shadow-xl">
            <h3 className="text-lg font-medium text-on-base">Reject: {selectedRequest.module_name}</h3>
            <p className="mt-1 text-sm text-subtle">Optionally provide a reason for the rejection.</p>
            <textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              className="mt-4 w-full rounded-lg border border-hl-med p-2 text-sm bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
              rows={4}
              placeholder="Reason (optional)..."
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => { setShowRejectModal(false); setRejectReason(''); setSelectedRequest(null) }}
                className="rounded-lg border border-hl-med px-3 py-1.5 text-sm font-medium text-on-base hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
              >
                Cancel
              </button>
              <button
                onClick={handleReject}
                disabled={moduleAction.isPending}
                className="rounded-lg bg-gold px-3 py-1.5 text-sm font-medium text-base hover:bg-gold/80 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gold"
              >
                Reject
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bulk Reject Modal */}
      {showBulkRejectModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-base/50" role="dialog" aria-modal="true">
          <div className="w-full max-w-md rounded-lg bg-surface p-6 shadow-xl">
            <h3 className="text-lg font-medium text-on-base">Reject {selectedIds.size} Module Requests</h3>
            <p className="mt-1 text-sm text-subtle">Optionally provide a reason that will be applied to all selected requests.</p>
            <textarea
              value={bulkRejectReason}
              onChange={(e) => setBulkRejectReason(e.target.value)}
              className="mt-4 w-full rounded-lg border border-hl-med p-2 text-sm bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
              rows={4}
              placeholder="Reason (optional)..."
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => { setShowBulkRejectModal(false); setBulkRejectReason('') }}
                className="rounded-lg border border-hl-med px-3 py-1.5 text-sm font-medium text-on-base hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
              >
                Cancel
              </button>
              <button
                onClick={handleBulkReject}
                disabled={bulkAction.isPending}
                className="rounded-lg bg-gold px-3 py-1.5 text-sm font-medium text-base hover:bg-gold/80 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gold"
              >
                Reject All
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Revoke Confirmation */}
      <ConfirmModal
        isOpen={!!revokeTarget}
        title="Revoke Module Approval"
        message={`Revoke "${revokeTarget?.module_name ?? ''}"? It will be removed from the global module whitelist. You can re-approve or delete it later.`}
        confirmLabel="Revoke"
        destructive
        isLoading={revokeAction.isPending}
        onConfirm={async () => { await revokeAction.mutateAsync(revokeTarget!.id); setRevokeTarget(null) }}
        onCancel={() => setRevokeTarget(null)}
      />

      {/* Delete Confirmation */}
      <ConfirmModal
        isOpen={!!deleteTarget}
        title="Delete Module Request"
        message={`Permanently delete the request for "${deleteTarget?.module_name ?? ''}"? This cannot be undone. The LLM will be able to re-request this module.`}
        confirmLabel="Delete"
        destructive
        isLoading={deleteAction.isPending}
        onConfirm={async () => { await deleteAction.mutateAsync(deleteTarget!.id); setDeleteTarget(null) }}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}
