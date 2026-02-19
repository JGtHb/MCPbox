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
    debug: 'bg-overlay text-subtle',
    info: 'bg-pine/10 text-pine',
    warning: 'bg-gold/10 text-gold',
    error: 'bg-love/10 text-love',
  }
  return classes[level] || 'bg-overlay text-on-base'
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
    <div className="bg-base min-h-full">
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
        <div className="bg-surface rounded-lg shadow mb-6">
          <div className="border-b border-hl-med">
            <nav className="flex -mb-px">
              <button
                onClick={() => setActiveTab('executions')}
                className={`px-4 sm:px-6 py-3 text-sm font-medium border-b-2 transition-colors focus:outline-none focus:ring-2 focus:ring-iris focus:ring-inset ${
                  activeTab === 'executions'
                    ? 'border-rose text-rose'
                    : 'border-transparent text-subtle hover:text-on-base hover:border-hl-high'
                }`}
              >
                Execution History
                {logsData && (
                  <span className="ml-2 text-xs font-normal text-muted">
                    ({logsData.total})
                  </span>
                )}
              </button>
              <button
                onClick={() => setActiveTab('protocol')}
                className={`px-4 sm:px-6 py-3 text-sm font-medium border-b-2 transition-colors focus:outline-none focus:ring-2 focus:ring-iris focus:ring-inset ${
                  activeTab === 'protocol'
                    ? 'border-rose text-rose'
                    : 'border-transparent text-subtle hover:text-on-base hover:border-hl-high'
                }`}
              >
                Protocol Logs
                {protoData && (
                  <span className="ml-2 text-xs font-normal text-muted">
                    ({protoData.total})
                  </span>
                )}
              </button>

              {/* Live indicator */}
              <div className="ml-auto flex items-center pr-4">
                <span className="flex items-center gap-1.5">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      connected ? 'bg-foam animate-pulse' : 'bg-muted'
                    }`}
                  />
                  <span className="text-xs text-subtle">
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
              <div className="px-4 py-3 border-b border-hl-med">
                <div className="flex flex-wrap items-center gap-3 sm:gap-4">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-on-base hidden sm:inline">
                      Tool:
                    </span>
                    <input
                      type="text"
                      value={toolNameFilter}
                      onChange={(e) => handleToolNameChange(e.target.value)}
                      placeholder="Filter by tool name..."
                      className="px-3 py-1 text-sm border border-hl-med rounded-lg bg-surface text-on-base w-48 focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
                    />
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-on-base hidden sm:inline">
                      Status:
                    </span>
                    <div className="flex rounded-lg overflow-hidden border border-hl-med">
                      {(['all', 'success', 'failure'] as SuccessFilter[]).map((f) => (
                        <button
                          key={f}
                          onClick={() => handleSuccessFilterChange(f)}
                          className={`px-3 py-1 text-sm ${
                            successFilter === f
                              ? 'bg-rose text-base'
                              : 'bg-surface text-on-base hover:bg-hl-low'
                          }`}
                        >
                          {f === 'all' ? 'All' : f === 'success' ? 'Success' : 'Failed'}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 ml-auto">
                    <span className="text-sm text-subtle hidden sm:inline">
                      Show:
                    </span>
                    <select
                      value={execPageSize}
                      onChange={(e) => handleExecPageSizeChange(Number(e.target.value))}
                      className="px-2 py-1 text-sm border border-hl-med rounded-lg bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
                    >
                      {PAGE_SIZE_OPTIONS.map((size) => (
                        <option key={size} value={size}>
                          {size}
                        </option>
                      ))}
                    </select>
                    <span className="text-sm text-subtle hidden sm:inline">
                      per page
                    </span>
                  </div>
                </div>
              </div>

              {/* Execution Logs List */}
              {logsLoading ? (
                <div className="p-8 text-center text-subtle">
                  Loading execution logs...
                </div>
              ) : !logsData || logsData.items.length === 0 ? (
                <div className="p-8 text-center">
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
                      d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"
                    />
                  </svg>
                  <p className="text-subtle mb-1">No executions yet</p>
                  <p className="text-xs text-muted">
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
                    <div className="flex items-center justify-between px-4 py-3 border-t border-hl-med text-sm">
                      <button
                        onClick={() => setExecPage((p) => Math.max(1, p - 1))}
                        disabled={execPage <= 1}
                        className="px-3 py-1 border border-hl-med rounded-lg text-on-base disabled:opacity-50 disabled:cursor-not-allowed hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
                      >
                        Previous
                      </button>
                      <span className="text-subtle">
                        Page {execPage} of {logsData.pages}
                      </span>
                      <button
                        onClick={() => setExecPage((p) => Math.min(logsData.pages, p + 1))}
                        disabled={execPage >= logsData.pages}
                        className="px-3 py-1 border border-hl-med rounded-lg text-on-base disabled:opacity-50 disabled:cursor-not-allowed hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
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
              <div className="px-4 py-3 border-b border-hl-med">
                <div className="flex flex-wrap items-center gap-3 sm:gap-4">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-on-base hidden sm:inline">
                      Type:
                    </span>
                    <select
                      value={logTypeFilter}
                      onChange={(e) => handleLogTypeChange(e.target.value)}
                      className="px-2 py-1 text-sm border border-hl-med rounded-lg bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
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
                    <span className="text-sm font-medium text-on-base hidden sm:inline">
                      Level:
                    </span>
                    <select
                      value={levelFilter}
                      onChange={(e) => handleLevelChange(e.target.value)}
                      className="px-2 py-1 text-sm border border-hl-med rounded-lg bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
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
                      className="px-3 py-1 text-sm border border-hl-med rounded-lg bg-surface text-on-base w-full max-w-xs focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
                    />
                  </div>

                  <div className="flex items-center gap-2 ml-auto">
                    <span className="text-sm text-subtle hidden sm:inline">
                      Show:
                    </span>
                    <select
                      value={protoPageSize}
                      onChange={(e) => handleProtoPageSizeChange(Number(e.target.value))}
                      className="px-2 py-1 text-sm border border-hl-med rounded-lg bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
                    >
                      {PAGE_SIZE_OPTIONS.map((size) => (
                        <option key={size} value={size}>
                          {size}
                        </option>
                      ))}
                    </select>
                    <span className="text-sm text-subtle hidden sm:inline">
                      per page
                    </span>
                  </div>
                </div>
              </div>

              {/* Protocol Logs List */}
              {protoLoading ? (
                <div className="p-8 text-center text-subtle">
                  Loading protocol logs...
                </div>
              ) : !protoData || protoData.items.length === 0 ? (
                <div className="p-8 text-center">
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
                      d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
                    />
                  </svg>
                  <p className="text-subtle mb-1">No protocol logs found</p>
                  <p className="text-xs text-muted">
                    Protocol activity will be recorded here as MCP interactions occur
                  </p>
                </div>
              ) : (
                <>
                  <div className="divide-y divide-hl-low">
                    {protoData.items.map((log) => (
                      <ProtocolLogEntry key={log.id} log={log} />
                    ))}
                  </div>

                  {protoData.pages > 1 && (
                    <div className="flex items-center justify-between px-4 py-3 border-t border-hl-med text-sm">
                      <button
                        onClick={() => setProtoPage((p) => Math.max(1, p - 1))}
                        disabled={protoPage <= 1}
                        className="px-3 py-1 border border-hl-med rounded-lg text-on-base disabled:opacity-50 disabled:cursor-not-allowed hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
                      >
                        Previous
                      </button>
                      <span className="text-subtle">
                        Page {protoPage} of {protoData.pages}
                      </span>
                      <button
                        onClick={() => setProtoPage((p) => Math.min(protoData.pages, p + 1))}
                        disabled={protoPage >= protoData.pages}
                        className="px-3 py-1 border border-hl-med rounded-lg text-on-base disabled:opacity-50 disabled:cursor-not-allowed hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
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
    blue: 'text-pine',
    green: 'text-foam',
    red: 'text-love',
    gray: 'text-subtle',
  }

  return (
    <div className="bg-surface rounded-lg shadow p-3 sm:p-4">
      <p className="text-xs sm:text-sm text-subtle">{title}</p>
      {loading ? (
        <div className="h-8 bg-hl-low rounded animate-pulse mt-1" />
      ) : (
        <>
          <p className={`text-xl sm:text-2xl font-bold ${colorClasses[color]}`}>{value}</p>
          {subtitle && <p className="text-xs text-muted mt-1">{subtitle}</p>}
        </>
      )}
    </div>
  )
}

function ProtocolLogEntry({ log }: { log: ActivityLog }) {
  const [expanded, setExpanded] = useState(false)

  const typeStyles: Record<string, string> = {
    mcp_request: 'border-l-pine',
    mcp_response: 'border-l-foam',
    error: 'border-l-love',
    alert: 'border-l-gold',
    audit: 'border-l-iris',
    network: 'border-l-iris',
    system: 'border-l-muted',
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
      className={`px-4 py-2.5 border-l-4 cursor-pointer hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-inset focus:ring-iris ${
        typeStyles[log.log_type] || 'border-l-muted'
      }`}
      onClick={() => setExpanded(!expanded)}
      role="button"
      tabIndex={0}
      aria-expanded={expanded}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          setExpanded(!expanded)
        }
      }}
    >
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted font-mono w-28 flex-shrink-0">
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
        <span className="flex-1 text-xs text-on-base truncate">
          {log.message}
        </span>
        {log.duration_ms != null && (
          <span className="text-xs text-muted font-mono flex-shrink-0">
            {log.duration_ms}ms
          </span>
        )}
        <svg
          className={`w-3.5 h-3.5 text-muted transition-transform flex-shrink-0 ${
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
          <pre className="text-xs bg-overlay text-on-base p-3 rounded overflow-x-auto max-h-48">
            {JSON.stringify(log.details, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
