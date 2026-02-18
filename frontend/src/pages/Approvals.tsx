import React, { useState } from 'react'
import {
  useApprovalStats,
  usePendingTools,
  usePendingModuleRequests,
  usePendingNetworkRequests,
  useToolAction,
  useModuleRequestAction,
  useNetworkRequestAction,
  useBulkToolAction,
  useBulkModuleRequestAction,
  useBulkNetworkRequestAction,
  ToolApprovalQueueItem,
  ModuleRequestQueueItem,
  NetworkAccessRequestQueueItem,
  PyPIPackageInfo,
} from '../api/approvals'

type TabType = 'tools' | 'modules' | 'network'

// Status badge component for approval items
function StatusBadge({ status }: { status: string }) {
  switch (status) {
    case 'approved':
      return (
        <span className="inline-flex items-center rounded-full bg-foam/10 px-2.5 py-0.5 text-xs font-medium text-foam">
          Approved
        </span>
      )
    case 'rejected':
      return (
        <span className="inline-flex items-center rounded-full bg-love/10 px-2.5 py-0.5 text-xs font-medium text-love">
          Rejected
        </span>
      )
    case 'pending_review':
    case 'pending':
      return (
        <span className="inline-flex items-center rounded-full bg-gold/10 px-2.5 py-0.5 text-xs font-medium text-gold">
          Pending
        </span>
      )
    default:
      return (
        <span className="inline-flex items-center rounded-full bg-overlay px-2.5 py-0.5 text-xs font-medium text-subtle">
          {status}
        </span>
      )
  }
}

// Format a date string for display
function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })
}

// Check if a status is pending (actionable)
function isPendingStatus(status?: string): boolean {
  return !status || status === 'pending_review' || status === 'pending'
}

// Show History toggle component
function ShowHistoryToggle({
  showHistory,
  onChange,
}: {
  showHistory: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2">
      <input
        type="checkbox"
        checked={showHistory}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-hl-med text-iris focus:ring-iris"
      />
      <span className="text-sm text-subtle">Show history</span>
    </label>
  )
}

export function Approvals() {
  const [activeTab, setActiveTab] = useState<TabType>('tools')
  const { data: stats, isLoading: statsLoading } = useApprovalStats()

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold text-on-base">Approval Queue</h1>
        <p className="mt-1 text-sm text-subtle">
          Review and approve tool publishing requests, module whitelist requests, and network
          access requests.
        </p>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard
          label="Pending Tools"
          value={stats?.pending_tools ?? 0}
          loading={statsLoading}
          onClick={() => setActiveTab('tools')}
          active={activeTab === 'tools'}
        />
        <StatCard
          label="Module Requests"
          value={stats?.pending_module_requests ?? 0}
          loading={statsLoading}
          onClick={() => setActiveTab('modules')}
          active={activeTab === 'modules'}
        />
        <StatCard
          label="Network Requests"
          value={stats?.pending_network_requests ?? 0}
          loading={statsLoading}
          onClick={() => setActiveTab('network')}
          active={activeTab === 'network'}
        />
      </div>

      {/* Tabs */}
      <div className="border-b border-hl-med">
        <nav className="-mb-px flex space-x-8">
          <TabButton
            label="Tools"
            count={stats?.pending_tools ?? 0}
            active={activeTab === 'tools'}
            onClick={() => setActiveTab('tools')}
          />
          <TabButton
            label="Module Requests"
            count={stats?.pending_module_requests ?? 0}
            active={activeTab === 'modules'}
            onClick={() => setActiveTab('modules')}
          />
          <TabButton
            label="Network Requests"
            count={stats?.pending_network_requests ?? 0}
            active={activeTab === 'network'}
            onClick={() => setActiveTab('network')}
          />
        </nav>
      </div>

      {/* Tab Content */}
      <div className="mt-4">
        {activeTab === 'tools' && <ToolsQueue />}
        {activeTab === 'modules' && <ModuleRequestsQueue />}
        {activeTab === 'network' && <NetworkRequestsQueue />}
      </div>
    </div>
  )
}

// Stats Card Component
function StatCard({
  label,
  value,
  loading,
  onClick,
  active,
}: {
  label: string
  value: number
  loading: boolean
  onClick: () => void
  active: boolean
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-lg border p-4 text-left transition-colors ${
        active
          ? 'border-iris bg-iris/10'
          : 'border-hl-med bg-surface hover:border-hl-high'
      }`}
    >
      <p className="text-sm font-medium text-subtle">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-on-base">
        {loading ? '...' : value}
      </p>
    </button>
  )
}

// Tab Button Component
function TabButton({
  label,
  count,
  active,
  onClick,
}: {
  label: string
  count: number
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium ${
        active
          ? 'border-iris text-iris'
          : 'border-transparent text-subtle hover:border-hl-high hover:text-on-base'
      }`}
    >
      {label}
      {count > 0 && (
        <span
          className={`ml-2 rounded-full px-2.5 py-0.5 text-xs font-medium ${
            active ? 'bg-iris/10 text-iris' : 'bg-hl-low text-subtle'
          }`}
        >
          {count}
        </span>
      )}
    </button>
  )
}

// Tools Queue Component
function ToolsQueue() {
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [showHistory, setShowHistory] = useState(false)
  const statusFilter = showHistory ? 'all' : undefined
  const { data, isLoading, error } = usePendingTools(1, 20, debouncedSearch || undefined, statusFilter)
  const toolAction = useToolAction()
  const bulkAction = useBulkToolAction()
  const [selectedTool, setSelectedTool] = useState<ToolApprovalQueueItem | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [showRejectModal, setShowRejectModal] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [showBulkRejectModal, setShowBulkRejectModal] = useState(false)
  const [bulkRejectReason, setBulkRejectReason] = useState('')

  // Debounce search input
  React.useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  const handleApprove = async (toolId: string) => {
    await toolAction.mutateAsync({ toolId, action: 'approve' })
    selectedIds.delete(toolId)
    setSelectedIds(new Set(selectedIds))
  }

  const handleReject = async () => {
    if (selectedTool && rejectReason.trim()) {
      await toolAction.mutateAsync({
        toolId: selectedTool.id,
        action: 'reject',
        reason: rejectReason,
      })
      selectedIds.delete(selectedTool.id)
      setSelectedIds(new Set(selectedIds))
      setShowRejectModal(false)
      setRejectReason('')
      setSelectedTool(null)
    }
  }

  const toggleSelection = (id: string) => {
    const newSet = new Set(selectedIds)
    if (newSet.has(id)) {
      newSet.delete(id)
    } else {
      newSet.add(id)
    }
    setSelectedIds(newSet)
  }

  const pendingItems = data?.items.filter((t) => isPendingStatus(t.approval_status)) ?? []

  const toggleSelectAll = () => {
    if (!data?.items) return
    const selectableItems = pendingItems
    if (selectedIds.size === selectableItems.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(selectableItems.map((t) => t.id)))
    }
  }

  const handleBulkApprove = async () => {
    if (selectedIds.size === 0) return
    await bulkAction.mutateAsync({ toolIds: Array.from(selectedIds), action: 'approve' })
    setSelectedIds(new Set())
  }

  const handleBulkReject = async () => {
    if (selectedIds.size === 0 || !bulkRejectReason.trim()) return
    await bulkAction.mutateAsync({
      toolIds: Array.from(selectedIds),
      action: 'reject',
      reason: bulkRejectReason,
    })
    setSelectedIds(new Set())
    setShowBulkRejectModal(false)
    setBulkRejectReason('')
  }

  if (error) {
    return (
      <div className="text-center py-8 text-love">
        Error loading pending tools: {error instanceof Error ? error.message : 'Unknown error'}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Search Input and Show History Toggle */}
      <div className="flex items-center gap-2">
        <input
          type="text"
          placeholder="Search by tool name, description, or server..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="flex-1 rounded-md border border-hl-med px-3 py-2 text-sm placeholder-muted focus:border-iris focus:outline-none focus:ring-1 focus:ring-iris"
        />
        {searchQuery && (
          <button
            onClick={() => setSearchQuery('')}
            className="text-sm text-subtle hover:text-on-base"
          >
            Clear
          </button>
        )}
        <ShowHistoryToggle showHistory={showHistory} onChange={(v) => { setShowHistory(v); setSelectedIds(new Set()) }} />
      </div>

      {/* Bulk Action Toolbar */}
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-iris/30 bg-iris/10 px-4 py-2">
          <span className="text-sm font-medium text-iris">
            {selectedIds.size} selected
          </span>
          <button
            onClick={handleBulkApprove}
            disabled={bulkAction.isPending}
            className="rounded bg-foam px-3 py-1 text-sm font-medium text-base hover:bg-foam/80 disabled:opacity-50"
          >
            Approve All
          </button>
          <button
            onClick={() => setShowBulkRejectModal(true)}
            disabled={bulkAction.isPending}
            className="rounded bg-gold px-3 py-1 text-sm font-medium text-base hover:bg-gold/80 disabled:opacity-50"
          >
            Request Revision All
          </button>
          <button
            onClick={() => setSelectedIds(new Set())}
            className="text-sm text-iris hover:text-iris/80"
          >
            Clear
          </button>
        </div>
      )}

      {isLoading ? (
        <div className="text-center py-8 text-subtle">Loading...</div>
      ) : !data?.items.length ? (
        <div className="text-center py-8 text-subtle">
          {debouncedSearch
            ? 'No tools match your search'
            : showHistory
              ? 'No approval history found'
              : 'No tools pending approval'}
        </div>
      ) : (
        <>
        {/* Select All (only count pending items) */}
        {pendingItems.length > 0 && (
        <div className="flex items-center gap-2 py-2">
          <input
            type="checkbox"
            checked={selectedIds.size === pendingItems.length && pendingItems.length > 0}
            onChange={toggleSelectAll}
            className="h-4 w-4 rounded border-hl-med text-iris focus:ring-iris"
          />
          <span className="text-sm text-subtle">Select all pending ({pendingItems.length})</span>
        </div>
        )}
        {data.items.map((tool) => {
          const toolIsPending = isPendingStatus(tool.approval_status)
          return (
        <div
          key={tool.id}
          className={`rounded-lg border p-4 shadow-sm ${
            !toolIsPending
              ? 'border-hl-med bg-hl-low'
              : selectedIds.has(tool.id)
                ? 'border-iris bg-surface ring-1 ring-iris/30'
                : 'border-hl-med bg-surface'
          }`}
        >
          <div className="flex items-start gap-3">
            {toolIsPending ? (
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
              <div className="flex items-center gap-2">
                <h3 className="text-lg font-medium text-on-base">{tool.name}</h3>
                <span className="rounded bg-overlay px-2 py-0.5 text-xs text-subtle">
                  {tool.server_name}
                </span>
                <span className="rounded px-2 py-0.5 text-xs bg-iris/10 text-iris">
                  Python
                </span>
                {tool.approval_status && (
                  <StatusBadge status={tool.approval_status} />
                )}
              </div>
              {tool.description && (
                <p className="mt-1 text-sm text-subtle">{tool.description}</p>
              )}
              {tool.created_by && (
                <p className="mt-1 text-xs text-muted">
                  Created by: {tool.created_by}
                </p>
              )}
              {/* Show approval/rejection details for historical items */}
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
                  <summary className="cursor-pointer text-sm text-pine hover:underline">
                    View Code
                  </summary>
                  <pre className="mt-2 max-h-64 overflow-auto rounded bg-overlay p-3 text-xs text-on-base">
                    {tool.python_code}
                  </pre>
                </details>
              )}
            </div>
            {toolIsPending && (
            <div className="ml-4 flex gap-2">
              <button
                onClick={() => handleApprove(tool.id)}
                disabled={toolAction.isPending}
                className="rounded bg-foam px-3 py-1.5 text-sm font-medium text-base hover:bg-foam/80 disabled:opacity-50"
              >
                Approve
              </button>
              <button
                onClick={() => {
                  setSelectedTool(tool)
                  setShowRejectModal(true)
                }}
                disabled={toolAction.isPending}
                className="rounded bg-gold px-3 py-1.5 text-sm font-medium text-base hover:bg-gold/80 disabled:opacity-50"
              >
                Request Revision
              </button>
            </div>
            )}
          </div>
        </div>
          )
      })}
        </>
      )}

      {/* Revision Request Modal */}
      {showRejectModal && selectedTool && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-md rounded-lg bg-surface p-6 shadow-xl">
            <h3 className="text-lg font-medium text-on-base">
              Request Revision: {selectedTool.name}
            </h3>
            <p className="mt-1 text-sm text-subtle">
              Provide feedback to help the LLM improve this tool.
            </p>
            <textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              className="mt-4 w-full rounded border border-hl-med p-2 text-sm"
              rows={4}
              placeholder="What needs to be improved..."
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowRejectModal(false)
                  setRejectReason('')
                  setSelectedTool(null)
                }}
                className="rounded border border-hl-med px-3 py-1.5 text-sm font-medium text-on-base hover:bg-hl-low"
              >
                Cancel
              </button>
              <button
                onClick={handleReject}
                disabled={!rejectReason.trim() || toolAction.isPending}
                className="rounded bg-gold px-3 py-1.5 text-sm font-medium text-base hover:bg-gold/80 disabled:opacity-50"
              >
                Request Revision
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bulk Revision Request Modal */}
      {showBulkRejectModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-md rounded-lg bg-surface p-6 shadow-xl">
            <h3 className="text-lg font-medium text-on-base">
              Request Revision for {selectedIds.size} Tools
            </h3>
            <p className="mt-1 text-sm text-subtle">
              Provide feedback that will be applied to all selected tools.
            </p>
            <textarea
              value={bulkRejectReason}
              onChange={(e) => setBulkRejectReason(e.target.value)}
              className="mt-4 w-full rounded border border-hl-med p-2 text-sm"
              rows={4}
              placeholder="What needs to be improved..."
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowBulkRejectModal(false)
                  setBulkRejectReason('')
                }}
                className="rounded border border-hl-med px-3 py-1.5 text-sm font-medium text-on-base hover:bg-hl-low"
              >
                Cancel
              </button>
              <button
                onClick={handleBulkReject}
                disabled={!bulkRejectReason.trim() || bulkAction.isPending}
                className="rounded bg-gold px-3 py-1.5 text-sm font-medium text-base hover:bg-gold/80 disabled:opacity-50"
              >
                Request Revision All
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// Severity badge colors
function severityColor(severity: string | null): string {
  switch (severity?.toUpperCase()) {
    case 'CRITICAL':
      return 'bg-love text-base'
    case 'HIGH':
      return 'bg-love/10 text-love'
    case 'MEDIUM':
      return 'bg-gold/10 text-gold'
    case 'LOW':
      return 'bg-hl-low text-on-base'
    default:
      return 'bg-hl-low text-subtle'
  }
}

// OpenSSF Scorecard color (0-10 scale)
function scorecardColor(score: number): string {
  if (score >= 7) return 'text-foam'
  if (score >= 4) return 'text-gold'
  return 'text-love'
}

// PyPI Info Display Component
function PyPIInfoDisplay({ info, moduleName }: { info: PyPIPackageInfo | null; moduleName: string }) {
  const [vulnsExpanded, setVulnsExpanded] = useState(false)

  if (!info) {
    return (
      <div className="mt-3 rounded border border-hl-med bg-hl-low p-3 text-sm text-subtle">
        Loading package info...
      </div>
    )
  }

  if (info.error) {
    return (
      <div className="mt-3 rounded border border-love/30 bg-love/10 p-3 text-sm text-love">
        Error loading package info: {info.error}
      </div>
    )
  }

  // Stdlib module - safe, no install needed
  if (info.is_stdlib) {
    return (
      <div className="mt-3 rounded border border-foam/30 bg-foam/10 p-3">
        <div className="flex items-center gap-2">
          <span className="rounded bg-foam/10 px-2 py-0.5 text-xs font-medium text-foam">
            Python Stdlib
          </span>
          <span className="text-sm text-foam">
            Built-in module - no installation required
          </span>
        </div>
      </div>
    )
  }

  const hasVulns = info.vulnerability_count > 0
  const borderColor = hasVulns ? 'border-love/40' : 'border-pine/30'
  const bgColor = hasVulns ? 'bg-love/10' : 'bg-pine/10'

  // Third-party package
  return (
    <div className={`mt-3 rounded border ${borderColor} ${bgColor} p-3`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded bg-pine/10 px-2 py-0.5 text-xs font-medium text-pine">
          PyPI Package
        </span>
        {moduleName !== info.package_name && info.package_name && (
          <span className="text-xs text-subtle">
            installs as <code className="font-mono">{info.package_name}</code>
          </span>
        )}
        {info.is_installed ? (
          <span className="rounded bg-foam/10 px-2 py-0.5 text-xs font-medium text-foam">
            Installed v{info.installed_version}
          </span>
        ) : (
          <span className="rounded bg-gold/10 px-2 py-0.5 text-xs font-medium text-gold">
            Not installed
          </span>
        )}
        {info.latest_version && (
          <span className="text-xs text-subtle">
            Latest: v{info.latest_version}
          </span>
        )}
      </div>

      {info.summary && (
        <p className="mt-2 text-sm text-on-base">{info.summary}</p>
      )}

      <div className="mt-2 flex flex-wrap gap-3 text-xs text-subtle">
        {info.author && <span>Author: {info.author}</span>}
        {info.license && <span>License: {info.license}</span>}
        {info.home_page && (
          <a
            href={info.home_page}
            target="_blank"
            rel="noopener noreferrer"
            className="text-pine hover:underline"
          >
            Project Homepage
          </a>
        )}
      </div>

      {/* Security section */}
      <div className="mt-3 border-t border-hl-med pt-3">
        <div className="flex flex-wrap items-center gap-3">
          {/* Vulnerability badge */}
          {hasVulns ? (
            <button
              onClick={() => setVulnsExpanded(!vulnsExpanded)}
              className="flex items-center gap-1 rounded bg-love/10 px-2 py-0.5 text-xs font-medium text-love hover:bg-love/20"
            >
              {info.vulnerability_count} known {info.vulnerability_count === 1 ? 'vulnerability' : 'vulnerabilities'}
              <span className="ml-1">{vulnsExpanded ? '\u25B2' : '\u25BC'}</span>
            </button>
          ) : (
            <span className="rounded bg-foam/10 px-2 py-0.5 text-xs font-medium text-foam">
              No known vulnerabilities
            </span>
          )}

          {/* OpenSSF Scorecard */}
          {info.scorecard_score !== null && (
            <span className={`text-xs font-medium ${scorecardColor(info.scorecard_score)}`}>
              OpenSSF Score: {info.scorecard_score.toFixed(1)}/10
            </span>
          )}

          {/* Dependency count */}
          {info.dependency_count !== null && (
            <span className="text-xs text-subtle">
              {info.dependency_count} {info.dependency_count === 1 ? 'dependency' : 'dependencies'}
            </span>
          )}

          {/* Source repo link */}
          {info.source_repo && (
            <a
              href={`https://${info.source_repo}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-pine hover:underline"
            >
              Source
            </a>
          )}
        </div>

        {/* Expanded vulnerability list */}
        {vulnsExpanded && info.vulnerabilities && info.vulnerabilities.length > 0 && (
          <div className="mt-2 space-y-2">
            {info.vulnerabilities.map((vuln) => (
              <div key={vuln.id} className="rounded border border-love/30 bg-surface p-2 text-xs">
                <div className="flex items-center gap-2">
                  <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${severityColor(vuln.severity)}`}>
                    {vuln.severity || 'UNKNOWN'}
                  </span>
                  {vuln.link ? (
                    <a
                      href={vuln.link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-mono text-pine hover:underline"
                    >
                      {vuln.id}
                    </a>
                  ) : (
                    <span className="font-mono">{vuln.id}</span>
                  )}
                  {vuln.fixed_version && (
                    <span className="text-subtle">
                      Fixed in v{vuln.fixed_version}
                    </span>
                  )}
                </div>
                <p className="mt-1 text-subtle">{vuln.summary}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// Module Requests Queue Component
function ModuleRequestsQueue() {
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [showHistory, setShowHistory] = useState(false)
  const statusFilter = showHistory ? 'all' : undefined
  const { data, isLoading, error } = usePendingModuleRequests(1, 20, debouncedSearch || undefined, statusFilter)
  const moduleAction = useModuleRequestAction()
  const bulkAction = useBulkModuleRequestAction()
  const [selectedRequest, setSelectedRequest] = useState<ModuleRequestQueueItem | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [showRejectModal, setShowRejectModal] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [showBulkRejectModal, setShowBulkRejectModal] = useState(false)
  const [bulkRejectReason, setBulkRejectReason] = useState('')

  // Debounce search input
  React.useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  const toggleSelection = (id: string) => {
    const newSet = new Set(selectedIds)
    if (newSet.has(id)) {
      newSet.delete(id)
    } else {
      newSet.add(id)
    }
    setSelectedIds(newSet)
  }

  const pendingItems = data?.items.filter((r) => isPendingStatus(r.status)) ?? []

  const toggleSelectAll = () => {
    if (!data?.items) return
    const selectableItems = pendingItems
    if (selectedIds.size === selectableItems.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(selectableItems.map((r) => r.id)))
    }
  }

  const handleApprove = async (requestId: string) => {
    await moduleAction.mutateAsync({ requestId, action: 'approve' })
    selectedIds.delete(requestId)
    setSelectedIds(new Set(selectedIds))
  }

  const handleReject = async () => {
    if (selectedRequest && rejectReason.trim()) {
      await moduleAction.mutateAsync({
        requestId: selectedRequest.id,
        action: 'reject',
        reason: rejectReason,
      })
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
    if (selectedIds.size === 0 || !bulkRejectReason.trim()) return
    await bulkAction.mutateAsync({
      requestIds: Array.from(selectedIds),
      action: 'reject',
      reason: bulkRejectReason,
    })
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

  return (
    <div className="space-y-4">
      {/* Search Input and Show History Toggle */}
      <div className="flex items-center gap-2">
        <input
          type="text"
          placeholder="Search by module name or justification..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="flex-1 rounded-md border border-hl-med px-3 py-2 text-sm placeholder-muted focus:border-iris focus:outline-none focus:ring-1 focus:ring-iris"
        />
        {searchQuery && (
          <button
            onClick={() => setSearchQuery('')}
            className="text-sm text-subtle hover:text-on-base"
          >
            Clear
          </button>
        )}
        <ShowHistoryToggle showHistory={showHistory} onChange={(v) => { setShowHistory(v); setSelectedIds(new Set()) }} />
      </div>

      {/* Bulk Action Toolbar */}
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-iris/30 bg-iris/10 px-4 py-2">
          <span className="text-sm font-medium text-iris">
            {selectedIds.size} selected
          </span>
          <button
            onClick={handleBulkApprove}
            disabled={bulkAction.isPending}
            className="rounded bg-foam px-3 py-1 text-sm font-medium text-base hover:bg-foam/80 disabled:opacity-50"
          >
            Approve All
          </button>
          <button
            onClick={() => setShowBulkRejectModal(true)}
            disabled={bulkAction.isPending}
            className="rounded bg-gold px-3 py-1 text-sm font-medium text-base hover:bg-gold/80 disabled:opacity-50"
          >
            Request Revision All
          </button>
          <button
            onClick={() => setSelectedIds(new Set())}
            className="text-sm text-iris hover:text-iris/80"
          >
            Clear
          </button>
        </div>
      )}

      {isLoading ? (
        <div className="text-center py-8 text-subtle">Loading...</div>
      ) : !data?.items.length ? (
        <div className="text-center py-8 text-subtle">
          {debouncedSearch
            ? 'No module requests match your search'
            : showHistory
              ? 'No module request history found'
              : 'No module requests pending approval'}
        </div>
      ) : (
        <>
        {/* Select All (only count pending items) */}
        {pendingItems.length > 0 && (
        <div className="flex items-center gap-2 py-2">
          <input
            type="checkbox"
            checked={selectedIds.size === pendingItems.length && pendingItems.length > 0}
            onChange={toggleSelectAll}
            className="h-4 w-4 rounded border-hl-med text-iris focus:ring-iris"
          />
          <span className="text-sm text-subtle">Select all pending ({pendingItems.length})</span>
        </div>
        )}
        {data.items.map((req) => {
          const reqIsPending = isPendingStatus(req.status)
          return (
        <div
          key={req.id}
          className={`rounded-lg border p-4 shadow-sm ${
            !reqIsPending
              ? 'border-hl-med bg-hl-low'
              : selectedIds.has(req.id)
                ? 'border-iris bg-surface ring-1 ring-iris/30'
                : 'border-hl-med bg-surface'
          }`}
        >
          <div className="flex items-start gap-3">
            {reqIsPending ? (
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
              <div className="flex items-center gap-2">
                <code className="rounded bg-iris/10 px-2 py-0.5 text-sm font-medium text-iris">
                  {req.module_name}
                </code>
                <span className="text-sm text-subtle">for</span>
                <span className="text-sm font-medium text-on-base">
                  {req.server_name}.{req.tool_name}
                </span>
                <StatusBadge status={req.status} />
              </div>
              <p className="mt-2 text-sm text-subtle">{req.justification}</p>
              {req.requested_by && (
                <p className="mt-1 text-xs text-muted">
                  Requested by: {req.requested_by}
                </p>
              )}
              {/* Show approval/rejection details for historical items */}
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

              {/* PyPI Info Section */}
              <PyPIInfoDisplay info={req.pypi_info} moduleName={req.module_name} />
            </div>
            {reqIsPending && (
            <div className="ml-4 flex gap-2">
              <button
                onClick={() => handleApprove(req.id)}
                disabled={moduleAction.isPending}
                className="rounded bg-foam px-3 py-1.5 text-sm font-medium text-base hover:bg-foam/80 disabled:opacity-50"
              >
                Approve
              </button>
              <button
                onClick={() => {
                  setSelectedRequest(req)
                  setShowRejectModal(true)
                }}
                disabled={moduleAction.isPending}
                className="rounded bg-gold px-3 py-1.5 text-sm font-medium text-base hover:bg-gold/80 disabled:opacity-50"
              >
                Request Revision
              </button>
            </div>
            )}
          </div>
        </div>
          )
      })}
        </>
      )}

      {/* Revision Request Modal */}
      {showRejectModal && selectedRequest && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-md rounded-lg bg-surface p-6 shadow-xl">
            <h3 className="text-lg font-medium text-on-base">
              Request Revision: {selectedRequest.module_name}
            </h3>
            <p className="mt-1 text-sm text-subtle">
              Provide feedback to help the LLM find a better alternative.
            </p>
            <textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              className="mt-4 w-full rounded border border-hl-med p-2 text-sm"
              rows={4}
              placeholder="What needs to be changed..."
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowRejectModal(false)
                  setRejectReason('')
                  setSelectedRequest(null)
                }}
                className="rounded border border-hl-med px-3 py-1.5 text-sm font-medium text-on-base hover:bg-hl-low"
              >
                Cancel
              </button>
              <button
                onClick={handleReject}
                disabled={!rejectReason.trim() || moduleAction.isPending}
                className="rounded bg-gold px-3 py-1.5 text-sm font-medium text-base hover:bg-gold/80 disabled:opacity-50"
              >
                Request Revision
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bulk Revision Request Modal */}
      {showBulkRejectModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-md rounded-lg bg-surface p-6 shadow-xl">
            <h3 className="text-lg font-medium text-on-base">
              Request Revision for {selectedIds.size} Module Requests
            </h3>
            <p className="mt-1 text-sm text-subtle">
              Provide feedback that will be applied to all selected requests.
            </p>
            <textarea
              value={bulkRejectReason}
              onChange={(e) => setBulkRejectReason(e.target.value)}
              className="mt-4 w-full rounded border border-hl-med p-2 text-sm"
              rows={4}
              placeholder="What needs to be changed..."
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowBulkRejectModal(false)
                  setBulkRejectReason('')
                }}
                className="rounded border border-hl-med px-3 py-1.5 text-sm font-medium text-on-base hover:bg-hl-low"
              >
                Cancel
              </button>
              <button
                onClick={handleBulkReject}
                disabled={!bulkRejectReason.trim() || bulkAction.isPending}
                className="rounded bg-gold px-3 py-1.5 text-sm font-medium text-base hover:bg-gold/80 disabled:opacity-50"
              >
                Request Revision All
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// Network Requests Queue Component
function NetworkRequestsQueue() {
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [showHistory, setShowHistory] = useState(false)
  const statusFilter = showHistory ? 'all' : undefined
  const { data, isLoading, error } = usePendingNetworkRequests(1, 20, debouncedSearch || undefined, statusFilter)
  const networkAction = useNetworkRequestAction()
  const [selectedRequest, setSelectedRequest] =
    useState<NetworkAccessRequestQueueItem | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [showRejectModal, setShowRejectModal] = useState(false)
  const bulkAction = useBulkNetworkRequestAction()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [showBulkRejectModal, setShowBulkRejectModal] = useState(false)
  const [bulkRejectReason, setBulkRejectReason] = useState('')

  // Debounce search input
  React.useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  const pendingItems = data?.items.filter((r) => isPendingStatus(r.status)) ?? []

  const toggleSelection = (id: string) => {
    const newSet = new Set(selectedIds)
    if (newSet.has(id)) {
      newSet.delete(id)
    } else {
      newSet.add(id)
    }
    setSelectedIds(newSet)
  }

  const toggleSelectAll = () => {
    if (!data?.items) return
    const selectableItems = pendingItems
    if (selectedIds.size === selectableItems.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(selectableItems.map((r) => r.id)))
    }
  }

  const handleApprove = async (requestId: string) => {
    await networkAction.mutateAsync({ requestId, action: 'approve' })
    selectedIds.delete(requestId)
    setSelectedIds(new Set(selectedIds))
  }

  const handleReject = async () => {
    if (selectedRequest && rejectReason.trim()) {
      await networkAction.mutateAsync({
        requestId: selectedRequest.id,
        action: 'reject',
        reason: rejectReason,
      })
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
    if (selectedIds.size === 0 || !bulkRejectReason.trim()) return
    await bulkAction.mutateAsync({
      requestIds: Array.from(selectedIds),
      action: 'reject',
      reason: bulkRejectReason,
    })
    setSelectedIds(new Set())
    setShowBulkRejectModal(false)
    setBulkRejectReason('')
  }

  if (isLoading) {
    return <div className="text-center py-8 text-subtle">Loading...</div>
  }

  if (error) {
    return (
      <div className="text-center py-8 text-love">
        Error loading network requests:{' '}
        {error instanceof Error ? error.message : 'Unknown error'}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Search Input and Show History Toggle */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <input
            type="text"
            placeholder="Search by host, justification, or server/tool name..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-lg border border-hl-med px-4 py-2 pl-10 text-sm focus:border-iris focus:outline-none focus:ring-1 focus:ring-iris"
          />
          <svg
            className="absolute left-3 top-2.5 h-4 w-4 text-muted"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
        </div>
        <ShowHistoryToggle showHistory={showHistory} onChange={(v) => { setShowHistory(v); setSelectedIds(new Set()) }} />
      </div>

      {/* Bulk Action Toolbar */}
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-iris/30 bg-iris/10 px-4 py-2">
          <span className="text-sm font-medium text-iris">
            {selectedIds.size} selected
          </span>
          <button
            onClick={handleBulkApprove}
            disabled={bulkAction.isPending}
            className="rounded bg-foam px-3 py-1 text-sm font-medium text-base hover:bg-foam/80 disabled:opacity-50"
          >
            Approve All
          </button>
          <button
            onClick={() => setShowBulkRejectModal(true)}
            disabled={bulkAction.isPending}
            className="rounded bg-gold px-3 py-1 text-sm font-medium text-base hover:bg-gold/80 disabled:opacity-50"
          >
            Request Revision All
          </button>
          <button
            onClick={() => setSelectedIds(new Set())}
            className="text-sm text-iris hover:text-iris/80"
          >
            Clear
          </button>
        </div>
      )}

      {!data?.items.length ? (
        <div className="text-center py-8 text-subtle">
          {debouncedSearch
            ? `No network access requests matching "${debouncedSearch}"`
            : showHistory
              ? 'No network request history found'
              : 'No network access requests pending approval'}
        </div>
      ) : (
        <>
        {/* Select All (only count pending items) */}
        {pendingItems.length > 0 && (
        <div className="flex items-center gap-2 py-2">
          <input
            type="checkbox"
            checked={selectedIds.size === pendingItems.length && pendingItems.length > 0}
            onChange={toggleSelectAll}
            className="h-4 w-4 rounded border-hl-med text-iris focus:ring-iris"
          />
          <span className="text-sm text-subtle">Select all pending ({pendingItems.length})</span>
        </div>
        )}
        {data.items.map((req) => {
          const reqIsPending = isPendingStatus(req.status)
          return (
        <div
          key={req.id}
          className={`rounded-lg border p-4 shadow-sm ${
            !reqIsPending
              ? 'border-hl-med bg-hl-low'
              : selectedIds.has(req.id)
                ? 'border-iris bg-surface ring-1 ring-iris/30'
                : 'border-hl-med bg-surface'
          }`}
        >
          <div className="flex items-start gap-3">
            {reqIsPending ? (
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
              <div className="flex items-center gap-2">
                <code className="rounded bg-pine/10 px-2 py-0.5 text-sm font-medium text-pine">
                  {req.host}
                  {req.port ? `:${req.port}` : ''}
                </code>
                <span className="text-sm text-subtle">for</span>
                <span className="text-sm font-medium text-on-base">
                  {req.server_name}.{req.tool_name}
                </span>
                <StatusBadge status={req.status} />
              </div>
              <p className="mt-2 text-sm text-subtle">{req.justification}</p>
              {req.requested_by && (
                <p className="mt-1 text-xs text-muted">
                  Requested by: {req.requested_by}
                </p>
              )}
              {/* Show approval/rejection details for historical items */}
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
            </div>
            {reqIsPending && (
            <div className="ml-4 flex gap-2">
              <button
                onClick={() => handleApprove(req.id)}
                disabled={networkAction.isPending}
                className="rounded bg-foam px-3 py-1.5 text-sm font-medium text-base hover:bg-foam/80 disabled:opacity-50"
              >
                Approve
              </button>
              <button
                onClick={() => {
                  setSelectedRequest(req)
                  setShowRejectModal(true)
                }}
                disabled={networkAction.isPending}
                className="rounded bg-gold px-3 py-1.5 text-sm font-medium text-base hover:bg-gold/80 disabled:opacity-50"
              >
                Request Revision
              </button>
            </div>
            )}
          </div>
        </div>
          )
      })}
        </>
      )}

      {/* Revision Request Modal */}
      {showRejectModal && selectedRequest && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-md rounded-lg bg-surface p-6 shadow-xl">
            <h3 className="text-lg font-medium text-on-base">
              Request Revision: {selectedRequest.host}
            </h3>
            <p className="mt-1 text-sm text-subtle">
              Provide feedback to help the LLM find a better approach.
            </p>
            <textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              className="mt-4 w-full rounded border border-hl-med p-2 text-sm"
              rows={4}
              placeholder="What needs to be changed..."
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowRejectModal(false)
                  setRejectReason('')
                  setSelectedRequest(null)
                }}
                className="rounded border border-hl-med px-3 py-1.5 text-sm font-medium text-on-base hover:bg-hl-low"
              >
                Cancel
              </button>
              <button
                onClick={handleReject}
                disabled={!rejectReason.trim() || networkAction.isPending}
                className="rounded bg-gold px-3 py-1.5 text-sm font-medium text-base hover:bg-gold/80 disabled:opacity-50"
              >
                Request Revision
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bulk Revision Request Modal */}
      {showBulkRejectModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-md rounded-lg bg-surface p-6 shadow-xl">
            <h3 className="text-lg font-medium text-on-base">
              Request Revision for {selectedIds.size} Network Requests
            </h3>
            <p className="mt-1 text-sm text-subtle">
              Provide feedback that will be applied to all selected requests.
            </p>
            <textarea
              value={bulkRejectReason}
              onChange={(e) => setBulkRejectReason(e.target.value)}
              className="mt-4 w-full rounded border border-hl-med p-2 text-sm"
              rows={4}
              placeholder="What needs to be changed..."
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowBulkRejectModal(false)
                  setBulkRejectReason('')
                }}
                className="rounded border border-hl-med px-3 py-1.5 text-sm font-medium text-on-base hover:bg-hl-low"
              >
                Cancel
              </button>
              <button
                onClick={handleBulkReject}
                disabled={!bulkRejectReason.trim() || bulkAction.isPending}
                className="rounded bg-gold px-3 py-1.5 text-sm font-medium text-base hover:bg-gold/80 disabled:opacity-50"
              >
                Request Revision All
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Approvals
