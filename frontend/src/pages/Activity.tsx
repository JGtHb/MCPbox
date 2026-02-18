import { useState, useMemo } from 'react'
import { Header } from '../components/Layout'
import {
  useAllExecutionLogs,
  useExecutionStats,
  type AllExecutionLogsParams,
} from '../api/executionLogs'
import { LogDetail, formatDuration } from '../components/Server/ExecutionLogsTab'
import {
  useActivityStream,
  useActivityLogs,
  ActivityLog,
  getLogTypeLabel,
  getLogTypeBadgeClasses,
  type ActivityLogsParams,
} from '../api/activity'

type SuccessFilter = 'all' | 'success' | 'failure'
type ActiveTab = 'executions' | 'protocol'

const PAGE_SIZE_OPTIONS = [10, 20, 50] as const

function getLevelBadgeClasses(level: string): string {
  const classes: Record<string, string> = {
    debug: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
    info: 'bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-300',
    warning: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/50 dark:text-yellow-300',
    error: 'bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-300',
  }
  return classes[level] || 'bg-gray-100 text-gray-800'
}

function getLevelLabel(level: string): string {
  const labels: Record<string, string> = {
    debug: 'Debug',
    info: 'Info',
    warning: 'Warning',
    error: 'Error',
  }
  return labels[level] || level
}

export function Activity() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('executions')

  // Execution history state
  const [execPage, setExecPage] = useState(1)
  const [execPageSize, setExecPageSize] = useState(20)
  const [toolNameFilter, setToolNameFilter] = useState('')
  const [successFilter, setSuccessFilter] = useState<SuccessFilter>('all')

  // Protocol logs state
  const [protoPage, setProtoPage] = useState(1)
  const [protoPageSize, setProtoPageSize] = useState(20)
  const [logTypeFilter, setLogTypeFilter] = useState('')
  const [levelFilter, setLevelFilter] = useState('')
  const [searchFilter, setSearchFilter] = useState('')

  // Execution stats
  const { data: stats, isLoading: statsLoading } = useExecutionStats(24)

  // Build execution log query params
  const execParams: AllExecutionLogsParams = useMemo(
    () => ({
      page: execPage,
      pageSize: execPageSize,
      toolName: toolNameFilter || undefined,
      success: successFilter === 'all' ? undefined : successFilter === 'success',
    }),
    [execPage, execPageSize, toolNameFilter, successFilter]
  )

  const { data: logsData, isLoading: logsLoading } = useAllExecutionLogs(execParams)

  // Build protocol log query params
  const protoParams: ActivityLogsParams = useMemo(
    () => ({
      page: protoPage,
      pageSize: protoPageSize,
      logType: logTypeFilter || undefined,
      level: levelFilter || undefined,
      search: searchFilter || undefined,
    }),
    [protoPage, protoPageSize, logTypeFilter, levelFilter, searchFilter]
  )

  const { data: protoData, isLoading: protoLoading } = useActivityLogs(protoParams)

  // WebSocket for live indicator only
  const { connected } = useActivityStream({
    maxLogs: 1,
  })

  // Reset page when execution filters change
  const handleToolNameChange = (value: string) => {
    setToolNameFilter(value)
    setExecPage(1)
  }

  const handleSuccessFilterChange = (value: SuccessFilter) => {
    setSuccessFilter(value)
    setExecPage(1)
  }

  const handleExecPageSizeChange = (value: number) => {
    setExecPageSize(value)
    setExecPage(1)
  }

  // Reset page when protocol filters change
  const handleLogTypeChange = (value: string) => {
    setLogTypeFilter(value)
    setProtoPage(1)
  }

  const handleLevelChange = (value: string) => {
    setLevelFilter(value)
    setProtoPage(1)
  }

  const handleSearchChange = (value: string) => {
    setSearchFilter(value)
    setProtoPage(1)
  }

  const handleProtoPageSizeChange = (value: number) => {
    setProtoPageSize(value)
    setProtoPage(1)
  }

  const successRate =
    stats && stats.total_executions > 0
      ? ((stats.successful / stats.total_executions) * 100).toFixed(1)
      : '0'

  return (
    <div className="dark:bg-gray-900 min-h-full">
      <Header title="Activity" />
      <div className="p-4 sm:p-6">
        {/* Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4 mb-6">
          <StatCard
            title="Total Executions"
            value={stats?.total_executions ?? 0}
            subtitle={`${stats?.period_executions ?? 0} in last 24h`}
            loading={statsLoading}
          />
          <StatCard
            title="Success Rate"
            value={`${successRate}%`}
            subtitle={`${stats?.failed ?? 0} failed`}
            loading={statsLoading}
            color={stats && stats.failed > 0 ? 'red' : 'green'}
          />
          <StatCard
            title="Avg Duration"
            value={stats?.avg_duration_ms != null ? formatDuration(Math.round(stats.avg_duration_ms)) : '-'}
            loading={statsLoading}
          />
          <StatCard
            title="Active Tools"
            value={stats?.unique_tools ?? 0}
            subtitle={`${stats?.unique_users ?? 0} users`}
            loading={statsLoading}
          />
        </div>

        {/* Tabs */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow mb-6">
          <div className="border-b border-gray-200 dark:border-gray-700">
            <nav className="flex -mb-px">
              <button
                onClick={() => setActiveTab('executions')}
                className={`px-4 sm:px-6 py-3 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === 'executions'
                    ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                    : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'
                }`}
              >
                Execution History
                {logsData && (
                  <span className="ml-2 text-xs font-normal text-gray-400 dark:text-gray-500">
                    ({logsData.total})
                  </span>
                )}
              </button>
              <button
                onClick={() => setActiveTab('protocol')}
                className={`px-4 sm:px-6 py-3 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === 'protocol'
                    ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                    : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'
                }`}
              >
                Protocol Logs
                {protoData && (
                  <span className="ml-2 text-xs font-normal text-gray-400 dark:text-gray-500">
                    ({protoData.total})
                  </span>
                )}
              </button>

              {/* Live indicator */}
              <div className="ml-auto flex items-center pr-4">
                <span className="flex items-center gap-1.5">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      connected ? 'bg-green-500 animate-pulse' : 'bg-gray-400'
                    }`}
                  />
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    {connected ? 'Live' : 'Offline'}
                  </span>
                </span>
              </div>
            </nav>
          </div>

          {/* Execution History Tab */}
          {activeTab === 'executions' && (
            <div>
              {/* Execution Filters */}
              <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700">
                <div className="flex flex-wrap items-center gap-3 sm:gap-4">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300 hidden sm:inline">
                      Tool:
                    </span>
                    <input
                      type="text"
                      value={toolNameFilter}
                      onChange={(e) => handleToolNameChange(e.target.value)}
                      placeholder="Filter by tool name..."
                      className="px-3 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 w-48"
                    />
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300 hidden sm:inline">
                      Status:
                    </span>
                    <div className="flex rounded-lg overflow-hidden border border-gray-300 dark:border-gray-600">
                      {(['all', 'success', 'failure'] as SuccessFilter[]).map((f) => (
                        <button
                          key={f}
                          onClick={() => handleSuccessFilterChange(f)}
                          className={`px-3 py-1 text-sm ${
                            successFilter === f
                              ? 'bg-blue-600 text-white'
                              : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600'
                          }`}
                        >
                          {f === 'all' ? 'All' : f === 'success' ? 'Success' : 'Failed'}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 ml-auto">
                    <span className="text-sm text-gray-500 dark:text-gray-400 hidden sm:inline">
                      Show:
                    </span>
                    <select
                      value={execPageSize}
                      onChange={(e) => handleExecPageSizeChange(Number(e.target.value))}
                      className="px-2 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                    >
                      {PAGE_SIZE_OPTIONS.map((size) => (
                        <option key={size} value={size}>
                          {size}
                        </option>
                      ))}
                    </select>
                    <span className="text-sm text-gray-500 dark:text-gray-400 hidden sm:inline">
                      per page
                    </span>
                  </div>
                </div>
              </div>

              {/* Execution Logs List */}
              {logsLoading ? (
                <div className="p-8 text-center text-gray-500 dark:text-gray-400">
                  Loading execution logs...
                </div>
              ) : !logsData || logsData.items.length === 0 ? (
                <div className="p-8 text-center">
                  <svg
                    className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-3"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.5}
                      d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"
                    />
                  </svg>
                  <p className="text-gray-500 dark:text-gray-400 mb-1">No executions yet</p>
                  <p className="text-xs text-gray-400 dark:text-gray-500">
                    Tool executions will appear here when tools are called
                  </p>
                </div>
              ) : (
                <>
                  <div className="p-4 space-y-2">
                    {logsData.items.map((log) => (
                      <LogDetail key={log.id} log={log} />
                    ))}
                  </div>

                  {logsData.pages > 1 && (
                    <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 dark:border-gray-700 text-sm">
                      <button
                        onClick={() => setExecPage((p) => Math.max(1, p - 1))}
                        disabled={execPage <= 1}
                        className="px-3 py-1 border border-gray-300 dark:border-gray-600 rounded text-gray-700 dark:text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 dark:hover:bg-gray-700"
                      >
                        Previous
                      </button>
                      <span className="text-gray-500 dark:text-gray-400">
                        Page {execPage} of {logsData.pages}
                      </span>
                      <button
                        onClick={() => setExecPage((p) => Math.min(logsData.pages, p + 1))}
                        disabled={execPage >= logsData.pages}
                        className="px-3 py-1 border border-gray-300 dark:border-gray-600 rounded text-gray-700 dark:text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 dark:hover:bg-gray-700"
                      >
                        Next
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* Protocol Logs Tab */}
          {activeTab === 'protocol' && (
            <div>
              {/* Protocol Filters */}
              <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700">
                <div className="flex flex-wrap items-center gap-3 sm:gap-4">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300 hidden sm:inline">
                      Type:
                    </span>
                    <select
                      value={logTypeFilter}
                      onChange={(e) => handleLogTypeChange(e.target.value)}
                      className="px-2 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                    >
                      <option value="">All</option>
                      <option value="mcp_request">MCP Request</option>
                      <option value="mcp_response">MCP Response</option>
                      <option value="network">Network</option>
                      <option value="alert">Alert</option>
                      <option value="error">Error</option>
                      <option value="system">System</option>
                      <option value="audit">Audit</option>
                    </select>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300 hidden sm:inline">
                      Level:
                    </span>
                    <select
                      value={levelFilter}
                      onChange={(e) => handleLevelChange(e.target.value)}
                      className="px-2 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                    >
                      <option value="">All</option>
                      <option value="debug">Debug</option>
                      <option value="info">Info</option>
                      <option value="warning">Warning</option>
                      <option value="error">Error</option>
                    </select>
                  </div>

                  <div className="flex items-center gap-2 flex-1 min-w-[200px]">
                    <input
                      type="text"
                      value={searchFilter}
                      onChange={(e) => handleSearchChange(e.target.value)}
                      placeholder="Search logs..."
                      className="px-3 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 w-full max-w-xs"
                    />
                  </div>

                  <div className="flex items-center gap-2 ml-auto">
                    <span className="text-sm text-gray-500 dark:text-gray-400 hidden sm:inline">
                      Show:
                    </span>
                    <select
                      value={protoPageSize}
                      onChange={(e) => handleProtoPageSizeChange(Number(e.target.value))}
                      className="px-2 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                    >
                      {PAGE_SIZE_OPTIONS.map((size) => (
                        <option key={size} value={size}>
                          {size}
                        </option>
                      ))}
                    </select>
                    <span className="text-sm text-gray-500 dark:text-gray-400 hidden sm:inline">
                      per page
                    </span>
                  </div>
                </div>
              </div>

              {/* Protocol Logs List */}
              {protoLoading ? (
                <div className="p-8 text-center text-gray-500 dark:text-gray-400">
                  Loading protocol logs...
                </div>
              ) : !protoData || protoData.items.length === 0 ? (
                <div className="p-8 text-center">
                  <svg
                    className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-3"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.5}
                      d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
                    />
                  </svg>
                  <p className="text-gray-500 dark:text-gray-400 mb-1">No protocol logs found</p>
                  <p className="text-xs text-gray-400 dark:text-gray-500">
                    Protocol activity will be recorded here as MCP interactions occur
                  </p>
                </div>
              ) : (
                <>
                  <div className="divide-y divide-gray-100 dark:divide-gray-700">
                    {protoData.items.map((log) => (
                      <ProtocolLogEntry key={log.id} log={log} />
                    ))}
                  </div>

                  {protoData.pages > 1 && (
                    <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 dark:border-gray-700 text-sm">
                      <button
                        onClick={() => setProtoPage((p) => Math.max(1, p - 1))}
                        disabled={protoPage <= 1}
                        className="px-3 py-1 border border-gray-300 dark:border-gray-600 rounded text-gray-700 dark:text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 dark:hover:bg-gray-700"
                      >
                        Previous
                      </button>
                      <span className="text-gray-500 dark:text-gray-400">
                        Page {protoPage} of {protoData.pages}
                      </span>
                      <button
                        onClick={() => setProtoPage((p) => Math.min(protoData.pages, p + 1))}
                        disabled={protoPage >= protoData.pages}
                        className="px-3 py-1 border border-gray-300 dark:border-gray-600 rounded text-gray-700 dark:text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 dark:hover:bg-gray-700"
                      >
                        Next
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

interface StatCardProps {
  title: string
  value: number | string
  subtitle?: string
  loading?: boolean
  color?: 'blue' | 'green' | 'red' | 'gray'
}

function StatCard({ title, value, subtitle, loading, color = 'blue' }: StatCardProps) {
  const colorClasses = {
    blue: 'text-blue-600 dark:text-blue-400',
    green: 'text-green-600 dark:text-green-400',
    red: 'text-red-600 dark:text-red-400',
    gray: 'text-gray-600 dark:text-gray-400',
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-3 sm:p-4">
      <p className="text-xs sm:text-sm text-gray-500 dark:text-gray-400">{title}</p>
      {loading ? (
        <div className="h-8 bg-gray-100 dark:bg-gray-700 rounded animate-pulse mt-1" />
      ) : (
        <>
          <p className={`text-xl sm:text-2xl font-bold ${colorClasses[color]}`}>{value}</p>
          {subtitle && <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">{subtitle}</p>}
        </>
      )}
    </div>
  )
}

function ProtocolLogEntry({ log }: { log: ActivityLog }) {
  const [expanded, setExpanded] = useState(false)

  const typeStyles: Record<string, string> = {
    mcp_request: 'border-l-blue-400',
    mcp_response: 'border-l-green-400',
    error: 'border-l-red-400',
    alert: 'border-l-yellow-400',
    audit: 'border-l-indigo-400',
    network: 'border-l-purple-400',
    system: 'border-l-gray-400',
  }

  const timestamp = new Date(log.created_at).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })

  return (
    <div
      className={`px-4 py-2.5 border-l-4 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors ${
        typeStyles[log.log_type] || 'border-l-gray-300'
      }`}
      onClick={() => setExpanded(!expanded)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          setExpanded(!expanded)
        }
      }}
    >
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-400 dark:text-gray-500 font-mono w-28 flex-shrink-0">
          {timestamp}
        </span>
        <span
          className={`px-1.5 py-0.5 text-xs rounded flex-shrink-0 ${getLogTypeBadgeClasses(log.log_type)}`}
        >
          {getLogTypeLabel(log.log_type)}
        </span>
        <span
          className={`px-1.5 py-0.5 text-xs rounded flex-shrink-0 ${getLevelBadgeClasses(log.level)}`}
        >
          {getLevelLabel(log.level)}
        </span>
        <span className="flex-1 text-xs text-gray-700 dark:text-gray-300 truncate">
          {log.message}
        </span>
        {log.duration_ms != null && (
          <span className="text-xs text-gray-400 dark:text-gray-500 font-mono flex-shrink-0">
            {log.duration_ms}ms
          </span>
        )}
        <svg
          className={`w-3.5 h-3.5 text-gray-400 dark:text-gray-500 transition-transform flex-shrink-0 ${
            expanded ? 'rotate-180' : ''
          }`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </div>

      {expanded && log.details && (
        <div className="mt-2 ml-28">
          <pre className="text-xs bg-gray-800 dark:bg-gray-900 text-gray-100 p-3 rounded overflow-x-auto max-h-48">
            {JSON.stringify(log.details, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
