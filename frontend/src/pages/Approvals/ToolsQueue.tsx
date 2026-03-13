import React, { useState } from 'react'
import {
  usePendingTools,
  useToolAction,
  useBulkToolAction,
  useRevokeToolApproval,
  ToolApprovalQueueItem,
} from '../../api/approvals'
import { ConfirmModal } from '../../components/ui'
import { StatusBadge, formatDate, isPendingStatus } from './shared'

export function ToolsQueue() {
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const { data, isLoading, error } = usePendingTools(1, 100, debouncedSearch || undefined, 'all')
  const toolAction = useToolAction()
  const bulkAction = useBulkToolAction()
  const revokeAction = useRevokeToolApproval()
  const [selectedTool, setSelectedTool] = useState<ToolApprovalQueueItem | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [showRejectModal, setShowRejectModal] = useState(false)
  const [revokeTarget, setRevokeTarget] = useState<ToolApprovalQueueItem | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [showBulkRejectModal, setShowBulkRejectModal] = useState(false)
  const [bulkRejectReason, setBulkRejectReason] = useState('')

  React.useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchQuery), 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  const pendingItems = data?.items.filter((t) => isPendingStatus(t.approval_status)) ?? []
  const approvedItems = data?.items.filter((t) => t.approval_status === 'approved') ?? []
  const draftOrRejectedItems = data?.items.filter(
    (t) => t.approval_status === 'draft' || t.approval_status === 'rejected'
  ) ?? []

  const handleSubmitForReview = async (toolId: string) => {
    await toolAction.mutateAsync({ toolId, action: 'submit_for_review' })
  }

  const handleApprove = async (toolId: string) => {
    await toolAction.mutateAsync({ toolId, action: 'approve' })
    selectedIds.delete(toolId)
    setSelectedIds(new Set(selectedIds))
  }

  const handleReject = async () => {
    if (selectedTool) {
      await toolAction.mutateAsync({ toolId: selectedTool.id, action: 'reject', reason: rejectReason.trim() || undefined })
      selectedIds.delete(selectedTool.id)
      setSelectedIds(new Set(selectedIds))
      setShowRejectModal(false)
      setRejectReason('')
      setSelectedTool(null)
    }
  }

  const toggleSelection = (id: string) => {
    const newSet = new Set(selectedIds)
    if (newSet.has(id)) { newSet.delete(id) } else { newSet.add(id) }
    setSelectedIds(newSet)
  }

  const toggleSelectAll = () => {
    setSelectedIds(
      selectedIds.size === pendingItems.length && pendingItems.length > 0
        ? new Set()
        : new Set(pendingItems.map((t) => t.id))
    )
  }

  const handleBulkApprove = async () => {
    if (selectedIds.size === 0) return
    await bulkAction.mutateAsync({ toolIds: Array.from(selectedIds), action: 'approve' })
    setSelectedIds(new Set())
  }

  const handleBulkReject = async () => {
    if (selectedIds.size === 0) return
    await bulkAction.mutateAsync({ toolIds: Array.from(selectedIds), action: 'reject', reason: bulkRejectReason.trim() || undefined })
    setSelectedIds(new Set())
    setShowBulkRejectModal(false)
    setBulkRejectReason('')
  }

  if (error) {
    return (
      <div className="text-center py-8 text-love">
        Error loading tools: {error instanceof Error ? error.message : 'Unknown error'}
      </div>
    )
  }

  const ToolCard = ({ tool, isPending }: { tool: ToolApprovalQueueItem; isPending: boolean }) => (
    <div
      className={`rounded-lg border p-4 shadow-sm ${
        isPending && selectedIds.has(tool.id)
          ? 'border-iris bg-surface ring-1 ring-iris/30'
          : 'border-hl-med bg-surface'
      }`}
    >
      <div className="flex items-start gap-3">
        {isPending ? (
          <input
            type="checkbox"
            checked={selectedIds.has(tool.id)}
            onChange={() => toggleSelection(tool.id)}
            className="mt-1 h-4 w-4 rounded border-hl-med text-iris focus:ring-iris"
          />
        ) : (
          <div className="mt-1 h-4 w-4" />
        )}
        <div className="flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-lg font-medium text-on-base">{tool.name}</h3>
            <span className="rounded bg-overlay px-2 py-0.5 text-xs text-subtle">{tool.server_name}</span>
            <span className="rounded px-2 py-0.5 text-xs bg-iris/10 text-iris">Python</span>
            {tool.approval_status && <StatusBadge status={tool.approval_status} />}
          </div>
          {tool.description && <p className="mt-1 text-sm text-subtle">{tool.description}</p>}
          {tool.created_by && <p className="mt-1 text-xs text-muted">Created by: {tool.created_by}</p>}
          {tool.approval_status === 'approved' && tool.approved_at && (
            <p className="mt-1 text-xs text-foam">
              Approved{tool.approved_by ? ` by ${tool.approved_by}` : ''} on {formatDate(tool.approved_at)}
            </p>
          )}
          {tool.approval_status === 'rejected' && tool.rejection_reason && (
            <div className="mt-2 rounded bg-love/10 p-2 text-sm text-love">
              <strong>Rejection reason:</strong> {tool.rejection_reason}
            </div>
          )}
          {tool.publish_notes && (
            <div className="mt-2 rounded bg-gold/10 p-2 text-sm text-gold">
              <strong>Notes:</strong> {tool.publish_notes}
            </div>
          )}
          {tool.python_code && (
            <details className="mt-2">
              <summary className="cursor-pointer text-sm text-pine hover:underline">View Code</summary>
              <pre className="mt-2 max-h-64 overflow-auto rounded bg-overlay p-3 text-xs text-on-base">
                {tool.python_code}
              </pre>
            </details>
          )}
        </div>
        <div className="ml-4 flex gap-2 shrink-0">
          {isPending ? (
            <>
              <button
                onClick={() => handleApprove(tool.id)}
                disabled={toolAction.isPending}
                className="rounded-lg bg-foam px-3 py-1.5 text-sm font-medium text-base hover:bg-foam/80 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-foam"
              >
                Approve
              </button>
              <button
                onClick={() => { setSelectedTool(tool); setShowRejectModal(true) }}
                disabled={toolAction.isPending}
                className="rounded-lg bg-gold px-3 py-1.5 text-sm font-medium text-base hover:bg-gold/80 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-gold"
              >
                Reject
              </button>
            </>
          ) : tool.approval_status === 'draft' || tool.approval_status === 'rejected' ? (
            <>
              <button
                onClick={() => handleApprove(tool.id)}
                disabled={toolAction.isPending}
                className="rounded-lg bg-foam px-3 py-1.5 text-sm font-medium text-base hover:bg-foam/80 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-foam"
              >
                Approve
              </button>
              <button
                onClick={() => handleSubmitForReview(tool.id)}
                disabled={toolAction.isPending}
                className="rounded-lg border border-iris/30 px-3 py-1.5 text-sm font-medium text-iris hover:bg-iris/10 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
              >
                Submit for Review
              </button>
            </>
          ) : (
            <button
              onClick={() => setRevokeTarget(tool)}
              disabled={revokeAction.isPending}
              className="px-2.5 py-1 text-xs font-medium text-love bg-surface border border-love/20 rounded-lg hover:bg-love/10 transition-colors focus:outline-none focus:ring-2 focus:ring-love disabled:opacity-50"
            >
              Revoke
            </button>
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
          placeholder="Search by tool name, description, or server..."
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
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <p className="text-subtle mb-1">No tools pending approval</p>
              <p className="text-xs text-muted">Tool approval requests will appear here</p>
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
              {pendingItems.map((tool) => <ToolCard key={tool.id} tool={tool} isPending={true} />)}
            </>
          )}

          {/* Draft / Rejected section */}
          {draftOrRejectedItems.length > 0 && (
            <div className="mt-6">
              <div className="flex items-center gap-3 mb-3">
                <h3 className="text-sm font-medium text-subtle uppercase tracking-wide">
                  Needs Submission ({draftOrRejectedItems.length})
                </h3>
                <div className="flex-1 h-px bg-hl-med" />
              </div>
              <div className="space-y-3">
                {draftOrRejectedItems.map((tool) => <ToolCard key={tool.id} tool={tool} isPending={false} />)}
              </div>
            </div>
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
                {approvedItems.map((tool) => <ToolCard key={tool.id} tool={tool} isPending={false} />)}
              </div>
            </div>
          )}

          {debouncedSearch && pendingItems.length === 0 && approvedItems.length === 0 && draftOrRejectedItems.length === 0 && (
            <div className="text-center py-8">
              <p className="text-subtle">No tools match your search</p>
              <p className="text-xs text-muted mt-1">Try a different search term</p>
            </div>
          )}
        </>
      )}

      {/* Reject Modal */}
      {showRejectModal && selectedTool && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-base/50" role="dialog" aria-modal="true">
          <div className="w-full max-w-md rounded-lg bg-surface p-6 shadow-xl">
            <h3 className="text-lg font-medium text-on-base">Reject: {selectedTool.name}</h3>
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
                onClick={() => { setShowRejectModal(false); setRejectReason(''); setSelectedTool(null) }}
                className="rounded-lg border border-hl-med px-3 py-1.5 text-sm font-medium text-on-base hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
              >
                Cancel
              </button>
              <button
                onClick={handleReject}
                disabled={toolAction.isPending}
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
            <h3 className="text-lg font-medium text-on-base">Reject {selectedIds.size} Tools</h3>
            <p className="mt-1 text-sm text-subtle">Optionally provide a reason that will be applied to all selected tools.</p>
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
        title="Revoke Tool Approval"
        message={`Revoke "${revokeTarget?.name ?? ''}"? It will be removed from the active sandbox and placed back in the pending review queue.`}
        confirmLabel="Revoke"
        destructive
        isLoading={revokeAction.isPending}
        onConfirm={async () => { await revokeAction.mutateAsync(revokeTarget!.id); setRevokeTarget(null) }}
        onCancel={() => setRevokeTarget(null)}
      />
    </div>
  )
}
