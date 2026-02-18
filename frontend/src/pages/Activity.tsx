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
  ActivityLog,
  getLogTypeLabel,
  getLogTypeBadgeClasses,
} from '../api/activity'

type SuccessFilter = 'all' | 'success' | 'failure'

export function Activity() {
  const [page, setPage] = useState(1)
  const [toolNameFilter, setToolNameFilter] = useState('')
  const [successFilter, setSuccessFilter] = useState<SuccessFilter>('all')
  const [protocolExpanded, setProtocolExpanded] = useState(false)

  // Execution stats
  const { data: stats, isLoading: statsLoading } = useExecutionStats(24)

  // Build query params
  const params: AllExecutionLogsParams = useMemo(
    () => ({
      page,
      pageSize: 20,
      toolName: toolNameFilter || undefined,
      success: successFilter === 'all' ? undefined : successFilter === 'success',
    }),
    [page, toolNameFilter, successFilter]
  )

  const { data: logsData, isLoading: logsLoading } = useAllExecutionLogs(params)

  // Protocol log stream (always connected, displayed when expanded)
  const {
    logs: protocolLogs,
    connected,
    error: wsError,
    clearLogs,
  } = useActivityStream({
    maxLogs: 200,
  })

  // Reset page when filters change
  const handleToolNameChange = (value: string) => {
    setToolNameFilter(value)
    setPage(1)
  }

  const handleSuccessFilterChange = (value: SuccessFilter) => {
    setSuccessFilter(value)
    setPage(1)
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

        {/* Filters */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 mb-6">
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
          </div>
        </div>

        {/* Execution History */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow mb-6">
          <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
            <h3 className="font-medium text-gray-900 dark:text-white">
              Execution History
              {logsData && (
                <span className="text-sm font-normal text-gray-500 dark:text-gray-400 ml-2">
                  ({logsData.total})
                </span>
              )}
            </h3>
          </div>

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
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                    className="px-3 py-1 border border-gray-300 dark:border-gray-600 rounded text-gray-700 dark:text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 dark:hover:bg-gray-700"
                  >
                    Previous
                  </button>
                  <span className="text-gray-500 dark:text-gray-400">
                    Page {page} of {logsData.pages}
                  </span>
                  <button
                    onClick={() => setPage((p) => Math.min(logsData.pages, p + 1))}
                    disabled={page >= logsData.pages}
                    className="px-3 py-1 border border-gray-300 dark:border-gray-600 rounded text-gray-700 dark:text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 dark:hover:bg-gray-700"
                  >
                    Next
                  </button>
                </div>
              )}
            </>
          )}
        </div>

        {/* Protocol Logs (collapsible) */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow">
          <button
            onClick={() => setProtocolExpanded(!protocolExpanded)}
            className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors rounded-lg"
          >
            <div className="flex items-center gap-2">
              <h3 className="font-medium text-gray-900 dark:text-white">Protocol Logs</h3>
              <span className="text-xs text-gray-400 dark:text-gray-500">(Advanced)</span>
              {protocolExpanded && connected && (
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                  <span className="text-xs text-gray-500 dark:text-gray-400">Live</span>
                </span>
              )}
            </div>
            <svg
              className={`w-4 h-4 text-gray-400 dark:text-gray-500 transition-transform ${
                protocolExpanded ? 'rotate-180' : ''
              }`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {protocolExpanded && (
            <div className="border-t border-gray-200 dark:border-gray-700">
              {wsError && (
                <div className="mx-4 mt-3 p-3 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg">
                  <p className="text-sm text-red-800 dark:text-red-300">{wsError}</p>
                </div>
              )}

              <div className="px-4 py-2 flex items-center justify-between">
                <span className="text-sm text-gray-500 dark:text-gray-400">
                  {protocolLogs.length} entries
                </span>
                <button
                  onClick={clearLogs}
                  className="px-3 py-1 text-xs bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
                >
                  Clear
                </button>
              </div>

              <div className="divide-y divide-gray-100 dark:divide-gray-700 max-h-[400px] overflow-y-auto">
                {protocolLogs.length === 0 ? (
                  <div className="p-6 text-center text-gray-500 dark:text-gray-400 text-sm">
                    {connected ? 'Waiting for protocol activity...' : 'Connecting...'}
                  </div>
                ) : (
                  protocolLogs.map((log) => <ProtocolLogEntry key={log.id} log={log} />)
                )}
              </div>
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
  }

  const timestamp = new Date(log.created_at).toLocaleTimeString()

  return (
    <div
      className={`px-4 py-2 border-l-4 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors ${
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
        <span className="text-xs text-gray-400 dark:text-gray-500 font-mono w-16 flex-shrink-0">
          {timestamp}
        </span>
        <span
          className={`px-1.5 py-0.5 text-xs rounded ${getLogTypeBadgeClasses(log.log_type)}`}
        >
          {getLogTypeLabel(log.log_type)}
        </span>
        <span className="flex-1 text-xs text-gray-700 dark:text-gray-300 truncate">
          {log.message}
        </span>
        {log.duration_ms != null && (
          <span className="text-xs text-gray-400 dark:text-gray-500 font-mono">
            {log.duration_ms}ms
          </span>
        )}
      </div>

      {expanded && log.details && (
        <div className="mt-2 ml-16">
          <pre className="text-xs bg-gray-800 text-gray-100 p-2 rounded overflow-x-auto max-h-32">
            {JSON.stringify(log.details, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
