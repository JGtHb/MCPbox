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

export function Approvals() {
  const [activeTab, setActiveTab] = useState<TabType>('tools')
  const { data: stats, isLoading: statsLoading } = useApprovalStats()

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Approval Queue</h1>
        <p className="mt-1 text-sm text-gray-500">
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
      <div className="border-b border-gray-200">
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
          ? 'border-blue-500 bg-blue-50'
          : 'border-gray-200 bg-white hover:border-gray-300'
      }`}
    >
      <p className="text-sm font-medium text-gray-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-gray-900">
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
          ? 'border-blue-500 text-blue-600'
          : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
      }`}
    >
      {label}
      {count > 0 && (
        <span
          className={`ml-2 rounded-full px-2.5 py-0.5 text-xs font-medium ${
            active ? 'bg-blue-100 text-blue-600' : 'bg-gray-100 text-gray-600'
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
  const { data, isLoading, error } = usePendingTools(1, 20, debouncedSearch || undefined)
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

  const toggleSelectAll = () => {
    if (!data?.items) return
    if (selectedIds.size === data.items.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(data.items.map((t) => t.id)))
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
      <div className="text-center py-8 text-red-600">
        Error loading pending tools: {error instanceof Error ? error.message : 'Unknown error'}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Search Input */}
      <div className="flex items-center gap-2">
        <input
          type="text"
          placeholder="Search by tool name, description, or server..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm placeholder-gray-400 focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
        />
        {searchQuery && (
          <button
            onClick={() => setSearchQuery('')}
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            Clear
          </button>
        )}
      </div>

      {/* Bulk Action Toolbar */}
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-purple-200 bg-purple-50 px-4 py-2">
          <span className="text-sm font-medium text-purple-700">
            {selectedIds.size} selected
          </span>
          <button
            onClick={handleBulkApprove}
            disabled={bulkAction.isPending}
            className="rounded bg-green-600 px-3 py-1 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            Approve All
          </button>
          <button
            onClick={() => setShowBulkRejectModal(true)}
            disabled={bulkAction.isPending}
            className="rounded bg-amber-600 px-3 py-1 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
          >
            Request Revision All
          </button>
          <button
            onClick={() => setSelectedIds(new Set())}
            className="text-sm text-purple-600 hover:text-purple-800"
          >
            Clear
          </button>
        </div>
      )}

      {isLoading ? (
        <div className="text-center py-8 text-gray-500">Loading...</div>
      ) : !data?.items.length ? (
        <div className="text-center py-8 text-gray-500">
          {debouncedSearch ? 'No tools match your search' : 'No tools pending approval'}
        </div>
      ) : (
        <>
        {/* Select All */}
        <div className="flex items-center gap-2 py-2">
          <input
            type="checkbox"
            checked={selectedIds.size === data.items.length && data.items.length > 0}
            onChange={toggleSelectAll}
            className="h-4 w-4 rounded border-gray-300 text-purple-600 focus:ring-purple-500"
          />
          <span className="text-sm text-gray-600">Select all ({data.items.length})</span>
        </div>
        {data.items.map((tool) => (
        <div
          key={tool.id}
          className={`rounded-lg border bg-white p-4 shadow-sm ${selectedIds.has(tool.id) ? 'border-purple-400 ring-1 ring-purple-200' : 'border-gray-200'}`}
        >
          <div className="flex items-start gap-3">
            <input
              type="checkbox"
              checked={selectedIds.has(tool.id)}
              onChange={() => toggleSelection(tool.id)}
              className="mt-1 h-4 w-4 rounded border-gray-300 text-purple-600 focus:ring-purple-500"
            />
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <h3 className="text-lg font-medium text-gray-900">{tool.name}</h3>
                <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                  {tool.server_name}
                </span>
                <span className="rounded px-2 py-0.5 text-xs bg-purple-100 text-purple-700">
                  Python
                </span>
              </div>
              {tool.description && (
                <p className="mt-1 text-sm text-gray-600">{tool.description}</p>
              )}
              {tool.created_by && (
                <p className="mt-1 text-xs text-gray-400">
                  Created by: {tool.created_by}
                </p>
              )}
              {tool.publish_notes && (
                <div className="mt-2 rounded bg-yellow-50 p-2 text-sm text-yellow-800">
                  <strong>Notes:</strong> {tool.publish_notes}
                </div>
              )}
              {tool.python_code && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-sm text-blue-600 hover:text-blue-800">
                    View Code
                  </summary>
                  <pre className="mt-2 max-h-64 overflow-auto rounded bg-gray-900 p-3 text-xs text-gray-100">
                    {tool.python_code}
                  </pre>
                </details>
              )}
            </div>
            <div className="ml-4 flex gap-2">
              <button
                onClick={() => handleApprove(tool.id)}
                disabled={toolAction.isPending}
                className="rounded bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
              >
                Approve
              </button>
              <button
                onClick={() => {
                  setSelectedTool(tool)
                  setShowRejectModal(true)
                }}
                disabled={toolAction.isPending}
                className="rounded bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
              >
                Request Revision
              </button>
            </div>
          </div>
        </div>
      ))}
        </>
      )}

      {/* Revision Request Modal */}
      {showRejectModal && selectedTool && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            <h3 className="text-lg font-medium text-gray-900">
              Request Revision: {selectedTool.name}
            </h3>
            <p className="mt-1 text-sm text-gray-500">
              Provide feedback to help the LLM improve this tool.
            </p>
            <textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              className="mt-4 w-full rounded border border-gray-300 p-2 text-sm"
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
                className="rounded border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleReject}
                disabled={!rejectReason.trim() || toolAction.isPending}
                className="rounded bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
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
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            <h3 className="text-lg font-medium text-gray-900">
              Request Revision for {selectedIds.size} Tools
            </h3>
            <p className="mt-1 text-sm text-gray-500">
              Provide feedback that will be applied to all selected tools.
            </p>
            <textarea
              value={bulkRejectReason}
              onChange={(e) => setBulkRejectReason(e.target.value)}
              className="mt-4 w-full rounded border border-gray-300 p-2 text-sm"
              rows={4}
              placeholder="What needs to be improved..."
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowBulkRejectModal(false)
                  setBulkRejectReason('')
                }}
                className="rounded border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleBulkReject}
                disabled={!bulkRejectReason.trim() || bulkAction.isPending}
                className="rounded bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
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
      return 'bg-red-600 text-white'
    case 'HIGH':
      return 'bg-red-100 text-red-800'
    case 'MEDIUM':
      return 'bg-yellow-100 text-yellow-800'
    case 'LOW':
      return 'bg-gray-100 text-gray-700'
    default:
      return 'bg-gray-100 text-gray-600'
  }
}

// OpenSSF Scorecard color (0-10 scale)
function scorecardColor(score: number): string {
  if (score >= 7) return 'text-green-700'
  if (score >= 4) return 'text-yellow-700'
  return 'text-red-700'
}

// PyPI Info Display Component
function PyPIInfoDisplay({ info, moduleName }: { info: PyPIPackageInfo | null; moduleName: string }) {
  const [vulnsExpanded, setVulnsExpanded] = useState(false)

  if (!info) {
    return (
      <div className="mt-3 rounded border border-gray-200 bg-gray-50 p-3 text-sm text-gray-500">
        Loading package info...
      </div>
    )
  }

  if (info.error) {
    return (
      <div className="mt-3 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-600">
        Error loading package info: {info.error}
      </div>
    )
  }

  // Stdlib module - safe, no install needed
  if (info.is_stdlib) {
    return (
      <div className="mt-3 rounded border border-green-200 bg-green-50 p-3">
        <div className="flex items-center gap-2">
          <span className="rounded bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">
            Python Stdlib
          </span>
          <span className="text-sm text-green-700">
            Built-in module - no installation required
          </span>
        </div>
      </div>
    )
  }

  const hasVulns = info.vulnerability_count > 0
  const borderColor = hasVulns ? 'border-red-300' : 'border-blue-200'
  const bgColor = hasVulns ? 'bg-red-50' : 'bg-blue-50'

  // Third-party package
  return (
    <div className={`mt-3 rounded border ${borderColor} ${bgColor} p-3`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">
          PyPI Package
        </span>
        {moduleName !== info.package_name && info.package_name && (
          <span className="text-xs text-gray-500">
            installs as <code className="font-mono">{info.package_name}</code>
          </span>
        )}
        {info.is_installed ? (
          <span className="rounded bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
            Installed v{info.installed_version}
          </span>
        ) : (
          <span className="rounded bg-yellow-100 px-2 py-0.5 text-xs font-medium text-yellow-700">
            Not installed
          </span>
        )}
        {info.latest_version && (
          <span className="text-xs text-gray-500">
            Latest: v{info.latest_version}
          </span>
        )}
      </div>

      {info.summary && (
        <p className="mt-2 text-sm text-gray-700">{info.summary}</p>
      )}

      <div className="mt-2 flex flex-wrap gap-3 text-xs text-gray-500">
        {info.author && <span>Author: {info.author}</span>}
        {info.license && <span>License: {info.license}</span>}
        {info.home_page && (
          <a
            href={info.home_page}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:underline"
          >
            Project Homepage
          </a>
        )}
      </div>

      {/* Security section */}
      <div className="mt-3 border-t border-gray-200 pt-3">
        <div className="flex flex-wrap items-center gap-3">
          {/* Vulnerability badge */}
          {hasVulns ? (
            <button
              onClick={() => setVulnsExpanded(!vulnsExpanded)}
              className="flex items-center gap-1 rounded bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800 hover:bg-red-200"
            >
              {info.vulnerability_count} known {info.vulnerability_count === 1 ? 'vulnerability' : 'vulnerabilities'}
              <span className="ml-1">{vulnsExpanded ? '\u25B2' : '\u25BC'}</span>
            </button>
          ) : (
            <span className="rounded bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
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
            <span className="text-xs text-gray-500">
              {info.dependency_count} {info.dependency_count === 1 ? 'dependency' : 'dependencies'}
            </span>
          )}

          {/* Source repo link */}
          {info.source_repo && (
            <a
              href={`https://${info.source_repo}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-600 hover:underline"
            >
              Source
            </a>
          )}
        </div>

        {/* Expanded vulnerability list */}
        {vulnsExpanded && info.vulnerabilities && info.vulnerabilities.length > 0 && (
          <div className="mt-2 space-y-2">
            {info.vulnerabilities.map((vuln) => (
              <div key={vuln.id} className="rounded border border-red-200 bg-white p-2 text-xs">
                <div className="flex items-center gap-2">
                  <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${severityColor(vuln.severity)}`}>
                    {vuln.severity || 'UNKNOWN'}
                  </span>
                  {vuln.link ? (
                    <a
                      href={vuln.link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-mono text-blue-600 hover:underline"
                    >
                      {vuln.id}
                    </a>
                  ) : (
                    <span className="font-mono">{vuln.id}</span>
                  )}
                  {vuln.fixed_version && (
                    <span className="text-gray-500">
                      Fixed in v{vuln.fixed_version}
                    </span>
                  )}
                </div>
                <p className="mt-1 text-gray-600">{vuln.summary}</p>
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
  const { data, isLoading, error } = usePendingModuleRequests(1, 20, debouncedSearch || undefined)
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

  const toggleSelectAll = () => {
    if (!data?.items) return
    if (selectedIds.size === data.items.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(data.items.map((r) => r.id)))
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
      <div className="text-center py-8 text-red-600">
        Error loading module requests: {error instanceof Error ? error.message : 'Unknown error'}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Search Input */}
      <div className="flex items-center gap-2">
        <input
          type="text"
          placeholder="Search by module name or justification..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm placeholder-gray-400 focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
        />
        {searchQuery && (
          <button
            onClick={() => setSearchQuery('')}
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            Clear
          </button>
        )}
      </div>

      {/* Bulk Action Toolbar */}
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-purple-200 bg-purple-50 px-4 py-2">
          <span className="text-sm font-medium text-purple-700">
            {selectedIds.size} selected
          </span>
          <button
            onClick={handleBulkApprove}
            disabled={bulkAction.isPending}
            className="rounded bg-green-600 px-3 py-1 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            Approve All
          </button>
          <button
            onClick={() => setShowBulkRejectModal(true)}
            disabled={bulkAction.isPending}
            className="rounded bg-amber-600 px-3 py-1 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
          >
            Request Revision All
          </button>
          <button
            onClick={() => setSelectedIds(new Set())}
            className="text-sm text-purple-600 hover:text-purple-800"
          >
            Clear
          </button>
        </div>
      )}

      {isLoading ? (
        <div className="text-center py-8 text-gray-500">Loading...</div>
      ) : !data?.items.length ? (
        <div className="text-center py-8 text-gray-500">
          {debouncedSearch ? 'No module requests match your search' : 'No module requests pending approval'}
        </div>
      ) : (
        <>
        {/* Select All */}
        <div className="flex items-center gap-2 py-2">
          <input
            type="checkbox"
            checked={selectedIds.size === data.items.length && data.items.length > 0}
            onChange={toggleSelectAll}
            className="h-4 w-4 rounded border-gray-300 text-purple-600 focus:ring-purple-500"
          />
          <span className="text-sm text-gray-600">Select all ({data.items.length})</span>
        </div>
        {data.items.map((req) => (
        <div
          key={req.id}
          className={`rounded-lg border bg-white p-4 shadow-sm ${selectedIds.has(req.id) ? 'border-purple-400 ring-1 ring-purple-200' : 'border-gray-200'}`}
        >
          <div className="flex items-start gap-3">
            <input
              type="checkbox"
              checked={selectedIds.has(req.id)}
              onChange={() => toggleSelection(req.id)}
              className="mt-1 h-4 w-4 rounded border-gray-300 text-purple-600 focus:ring-purple-500"
            />
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <code className="rounded bg-purple-100 px-2 py-0.5 text-sm font-medium text-purple-800">
                  {req.module_name}
                </code>
                <span className="text-sm text-gray-500">for</span>
                <span className="text-sm font-medium text-gray-700">
                  {req.server_name}.{req.tool_name}
                </span>
              </div>
              <p className="mt-2 text-sm text-gray-600">{req.justification}</p>
              {req.requested_by && (
                <p className="mt-1 text-xs text-gray-400">
                  Requested by: {req.requested_by}
                </p>
              )}

              {/* PyPI Info Section */}
              <PyPIInfoDisplay info={req.pypi_info} moduleName={req.module_name} />
            </div>
            <div className="ml-4 flex gap-2">
              <button
                onClick={() => handleApprove(req.id)}
                disabled={moduleAction.isPending}
                className="rounded bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
              >
                Approve
              </button>
              <button
                onClick={() => {
                  setSelectedRequest(req)
                  setShowRejectModal(true)
                }}
                disabled={moduleAction.isPending}
                className="rounded bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
              >
                Request Revision
              </button>
            </div>
          </div>
        </div>
      ))}
        </>
      )}

      {/* Revision Request Modal */}
      {showRejectModal && selectedRequest && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            <h3 className="text-lg font-medium text-gray-900">
              Request Revision: {selectedRequest.module_name}
            </h3>
            <p className="mt-1 text-sm text-gray-500">
              Provide feedback to help the LLM find a better alternative.
            </p>
            <textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              className="mt-4 w-full rounded border border-gray-300 p-2 text-sm"
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
                className="rounded border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleReject}
                disabled={!rejectReason.trim() || moduleAction.isPending}
                className="rounded bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
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
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            <h3 className="text-lg font-medium text-gray-900">
              Request Revision for {selectedIds.size} Module Requests
            </h3>
            <p className="mt-1 text-sm text-gray-500">
              Provide feedback that will be applied to all selected requests.
            </p>
            <textarea
              value={bulkRejectReason}
              onChange={(e) => setBulkRejectReason(e.target.value)}
              className="mt-4 w-full rounded border border-gray-300 p-2 text-sm"
              rows={4}
              placeholder="What needs to be changed..."
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowBulkRejectModal(false)
                  setBulkRejectReason('')
                }}
                className="rounded border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleBulkReject}
                disabled={!bulkRejectReason.trim() || bulkAction.isPending}
                className="rounded bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
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
  const { data, isLoading, error } = usePendingNetworkRequests(1, 20, debouncedSearch || undefined)
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
    if (selectedIds.size === data.items.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(data.items.map((r) => r.id)))
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
    return <div className="text-center py-8 text-gray-500">Loading...</div>
  }

  if (error) {
    return (
      <div className="text-center py-8 text-red-600">
        Error loading network requests:{' '}
        {error instanceof Error ? error.message : 'Unknown error'}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Search Input */}
      <div className="relative">
        <input
          type="text"
          placeholder="Search by host, justification, or server/tool name..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full rounded-lg border border-gray-300 px-4 py-2 pl-10 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        <svg
          className="absolute left-3 top-2.5 h-4 w-4 text-gray-400"
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

      {/* Bulk Action Toolbar */}
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-blue-200 bg-blue-50 px-4 py-2">
          <span className="text-sm font-medium text-blue-700">
            {selectedIds.size} selected
          </span>
          <button
            onClick={handleBulkApprove}
            disabled={bulkAction.isPending}
            className="rounded bg-green-600 px-3 py-1 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            Approve All
          </button>
          <button
            onClick={() => setShowBulkRejectModal(true)}
            disabled={bulkAction.isPending}
            className="rounded bg-amber-600 px-3 py-1 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
          >
            Request Revision All
          </button>
          <button
            onClick={() => setSelectedIds(new Set())}
            className="text-sm text-blue-600 hover:text-blue-800"
          >
            Clear
          </button>
        </div>
      )}

      {!data?.items.length ? (
        <div className="text-center py-8 text-gray-500">
          {debouncedSearch
            ? `No network access requests matching "${debouncedSearch}"`
            : 'No network access requests pending approval'}
        </div>
      ) : (
        <>
        {/* Select All */}
        <div className="flex items-center gap-2 py-2">
          <input
            type="checkbox"
            checked={selectedIds.size === data.items.length && data.items.length > 0}
            onChange={toggleSelectAll}
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          <span className="text-sm text-gray-600">Select all ({data.items.length})</span>
        </div>
        {data.items.map((req) => (
        <div
          key={req.id}
          className={`rounded-lg border bg-white p-4 shadow-sm ${selectedIds.has(req.id) ? 'border-blue-400 ring-1 ring-blue-200' : 'border-gray-200'}`}
        >
          <div className="flex items-start gap-3">
            <input
              type="checkbox"
              checked={selectedIds.has(req.id)}
              onChange={() => toggleSelection(req.id)}
              className="mt-1 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <code className="rounded bg-blue-100 px-2 py-0.5 text-sm font-medium text-blue-800">
                  {req.host}
                  {req.port ? `:${req.port}` : ''}
                </code>
                <span className="text-sm text-gray-500">for</span>
                <span className="text-sm font-medium text-gray-700">
                  {req.server_name}.{req.tool_name}
                </span>
              </div>
              <p className="mt-2 text-sm text-gray-600">{req.justification}</p>
              {req.requested_by && (
                <p className="mt-1 text-xs text-gray-400">
                  Requested by: {req.requested_by}
                </p>
              )}
            </div>
            <div className="ml-4 flex gap-2">
              <button
                onClick={() => handleApprove(req.id)}
                disabled={networkAction.isPending}
                className="rounded bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
              >
                Approve
              </button>
              <button
                onClick={() => {
                  setSelectedRequest(req)
                  setShowRejectModal(true)
                }}
                disabled={networkAction.isPending}
                className="rounded bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
              >
                Request Revision
              </button>
            </div>
          </div>
        </div>
      ))}
        </>
      )}

      {/* Revision Request Modal */}
      {showRejectModal && selectedRequest && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            <h3 className="text-lg font-medium text-gray-900">
              Request Revision: {selectedRequest.host}
            </h3>
            <p className="mt-1 text-sm text-gray-500">
              Provide feedback to help the LLM find a better approach.
            </p>
            <textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              className="mt-4 w-full rounded border border-gray-300 p-2 text-sm"
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
                className="rounded border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleReject}
                disabled={!rejectReason.trim() || networkAction.isPending}
                className="rounded bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
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
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            <h3 className="text-lg font-medium text-gray-900">
              Request Revision for {selectedIds.size} Network Requests
            </h3>
            <p className="mt-1 text-sm text-gray-500">
              Provide feedback that will be applied to all selected requests.
            </p>
            <textarea
              value={bulkRejectReason}
              onChange={(e) => setBulkRejectReason(e.target.value)}
              className="mt-4 w-full rounded border border-gray-300 p-2 text-sm"
              rows={4}
              placeholder="What needs to be changed..."
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowBulkRejectModal(false)
                  setBulkRejectReason('')
                }}
                className="rounded border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleBulkReject}
                disabled={!bulkRejectReason.trim() || bulkAction.isPending}
                className="rounded bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
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
