import { useState, useMemo } from 'react'
import { Header } from '../components/Layout'
import {
  useActivityStats,
  useActivityStream,
  ActivityLog,
  getLogTypeLabel,
  getLogTypeBadgeClasses,
} from '../api/activity'

type Period = '1h' | '6h' | '24h' | '7d'
type LogType = 'all' | 'mcp_request' | 'mcp_response' | 'error' | 'alert' | 'audit'
type Level = 'all' | 'debug' | 'info' | 'warning' | 'error'

export function Activity() {
  const [period, setPeriod] = useState<Period>('1h')
  const [selectedType, setSelectedType] = useState<LogType>('all')
  const [selectedLevel, setSelectedLevel] = useState<Level>('all')
  const [paused, setPaused] = useState(false)

  const { data: stats, isLoading: statsLoading } = useActivityStats(period)

  const {
    logs,
    connected,
    error: wsError,
    clearLogs,
  } = useActivityStream({
    log_types: selectedType !== 'all' ? [selectedType] : undefined,
    levels: selectedLevel !== 'all' ? [selectedLevel] : undefined,
    maxLogs: 500,
    enabled: !paused,
  })

  // Filter logs based on current selection
  const filteredLogs = useMemo(() => {
    return logs.filter((log) => {
      if (selectedType !== 'all' && log.log_type !== selectedType) return false
      if (selectedLevel !== 'all' && log.level !== selectedLevel) return false
      return true
    })
  }, [logs, selectedType, selectedLevel])

  return (
    <div className="dark:bg-gray-900 min-h-full">
      <Header title="Activity Monitor" />
      <div className="p-4 sm:p-6">
        {/* Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4 mb-6">
          <StatCard
            title="Total Requests"
            value={stats?.total ?? 0}
            subtitle={`${stats?.requests_per_minute?.toFixed(1) ?? '0'}/min`}
            loading={statsLoading}
          />
          <StatCard
            title="Errors"
            value={stats?.errors ?? 0}
            subtitle={stats?.total ? `${((stats.errors / stats.total) * 100).toFixed(1)}%` : '0%'}
            loading={statsLoading}
            color="red"
          />
          <StatCard
            title="Avg Duration"
            value={`${stats?.avg_duration_ms?.toFixed(0) ?? 0}ms`}
            loading={statsLoading}
          />
          <StatCard
            title="Connection"
            value={connected ? 'Live' : 'Disconnected'}
            subtitle={`${filteredLogs.length} logs`}
            color={connected ? 'green' : 'gray'}
          />
        </div>

        {/* Period Selector */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 mb-6">
          <div className="flex flex-wrap items-center gap-3 sm:gap-4">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300 hidden sm:inline">Stats Period:</span>
              <div className="flex rounded-lg overflow-hidden border border-gray-300 dark:border-gray-600">
                {(['1h', '6h', '24h', '7d'] as Period[]).map((p) => (
                  <button
                    key={p}
                    onClick={() => setPeriod(p)}
                    className={`px-3 py-1 text-sm ${
                      period === p
                        ? 'bg-blue-600 text-white'
                        : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600'
                    }`}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300 hidden sm:inline">Type:</span>
              <select
                value={selectedType}
                onChange={(e) => setSelectedType(e.target.value as LogType)}
                className="px-3 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
              >
                <option value="all">All Types</option>
                <option value="mcp_request">MCP Request</option>
                <option value="mcp_response">MCP Response</option>
                <option value="error">Error</option>
                <option value="alert">Alert</option>
                <option value="audit">Audit</option>
              </select>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300 hidden sm:inline">Level:</span>
              <select
                value={selectedLevel}
                onChange={(e) => setSelectedLevel(e.target.value as Level)}
                className="px-3 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
              >
                <option value="all">All Levels</option>
                <option value="debug">Debug</option>
                <option value="info">Info</option>
                <option value="warning">Warning</option>
                <option value="error">Error</option>
              </select>
            </div>

            <div className="flex-1" />

            <button
              onClick={() => setPaused(!paused)}
              className={`px-3 py-1 text-sm rounded-lg transition-colors ${
                paused
                  ? 'bg-green-600 text-white hover:bg-green-700'
                  : 'bg-yellow-500 text-white hover:bg-yellow-600'
              }`}
            >
              {paused ? 'Resume' : 'Pause'}
            </button>

            <button
              onClick={clearLogs}
              className="px-3 py-1 text-sm bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
            >
              Clear
            </button>
          </div>
        </div>

        {/* WebSocket Error */}
        {wsError && (
          <div className="mb-6 p-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg">
            <p className="text-sm text-red-800 dark:text-red-300">{wsError}</p>
          </div>
        )}

        {/* Activity Type Breakdown */}
        {stats && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 mb-6">
            <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">Activity by Type</h3>
            <div className="flex gap-4 flex-wrap">
              {Object.entries(stats.by_type).map(([type, count]) => (
                <div key={type} className="flex items-center gap-2">
                  <span
                    className={`px-2 py-1 text-xs rounded-full ${getLogTypeBadgeClasses(type)}`}
                  >
                    {getLogTypeLabel(type)}
                  </span>
                  <span className="text-sm font-medium text-gray-900 dark:text-white">{count}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Live Log Stream */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow">
          <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <h3 className="font-medium text-gray-900 dark:text-white">Live Activity Stream</h3>
              {connected && !paused && (
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                  <span className="text-xs text-gray-500 dark:text-gray-400">Live</span>
                </span>
              )}
              {paused && (
                <span className="text-xs text-yellow-600 bg-yellow-100 dark:bg-yellow-900/50 dark:text-yellow-300 px-2 py-0.5 rounded">
                  Paused
                </span>
              )}
            </div>
            <span className="text-sm text-gray-500 dark:text-gray-400">{filteredLogs.length} entries</span>
          </div>

          <div className="divide-y divide-gray-100 dark:divide-gray-700 max-h-[600px] overflow-y-auto">
            {filteredLogs.length === 0 ? (
              <div className="p-8 text-center text-gray-500 dark:text-gray-400">
                {connected ? 'Waiting for activity...' : 'Connect to see live activity'}
              </div>
            ) : (
              filteredLogs.map((log) => <LogEntry key={log.id} log={log} />)
            )}
          </div>
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

interface LogEntryProps {
  log: ActivityLog
}

function LogEntry({ log }: LogEntryProps) {
  const [expanded, setExpanded] = useState(false)

  const levelStyles = {
    debug: 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300',
    info: 'bg-blue-100 dark:bg-blue-900/50 text-blue-700 dark:text-blue-300',
    warning: 'bg-yellow-100 dark:bg-yellow-900/50 text-yellow-700 dark:text-yellow-300',
    error: 'bg-red-100 dark:bg-red-900/50 text-red-700 dark:text-red-300',
  }

  const typeStyles: Record<string, string> = {
    mcp_request: 'bg-blue-50 dark:bg-blue-900/20 border-l-blue-400',
    mcp_response: 'bg-green-50 dark:bg-green-900/20 border-l-green-400',
    error: 'bg-red-50 dark:bg-red-900/20 border-l-red-400',
    alert: 'bg-yellow-50 dark:bg-yellow-900/20 border-l-yellow-400',
    network: 'bg-purple-50 dark:bg-purple-900/20 border-l-purple-400',
    system: 'bg-gray-50 dark:bg-gray-900/20 border-l-gray-400',
    audit: 'bg-indigo-50 dark:bg-indigo-900/20 border-l-indigo-400',
  }

  const timestamp = new Date(log.created_at).toLocaleTimeString()

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      setExpanded(!expanded)
    }
  }

  return (
    <div
      className={`px-4 py-3 border-l-4 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors ${
        typeStyles[log.log_type] || 'bg-white dark:bg-gray-800 border-l-gray-300'
      }`}
      onClick={() => setExpanded(!expanded)}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={0}
      aria-expanded={expanded}
      aria-label={`${log.level} log: ${log.message.substring(0, 50)}${log.message.length > 50 ? '...' : ''}`}
    >
      <div className="flex items-start gap-2 sm:gap-3 flex-wrap sm:flex-nowrap">
        <span className="text-xs text-gray-400 dark:text-gray-500 font-mono w-16 sm:w-20 flex-shrink-0">{timestamp}</span>

        <span
          className={`px-2 py-0.5 text-xs rounded-full font-medium ${levelStyles[log.level] || 'bg-gray-100 dark:bg-gray-700'}`}
        >
          {log.level}
        </span>

        <span className="text-xs text-gray-500 dark:text-gray-400 px-2 py-0.5 bg-gray-100 dark:bg-gray-700 rounded hidden sm:inline">
          {getLogTypeLabel(log.log_type)}
        </span>

        <span className="flex-1 text-sm text-gray-900 dark:text-gray-100 truncate w-full sm:w-auto">{log.message}</span>

        {log.duration_ms && (
          <span className="text-xs text-gray-500 dark:text-gray-400 font-mono hidden sm:inline">{log.duration_ms}ms</span>
        )}

        {log.request_id && (
          <span className="text-xs text-gray-400 dark:text-gray-500 font-mono hidden sm:inline">[{log.request_id}]</span>
        )}
      </div>

      {expanded && log.details && (
        <div className="mt-3 sm:ml-20">
          <pre className="text-xs bg-gray-800 text-gray-100 p-3 rounded-lg overflow-x-auto">
            {JSON.stringify(log.details, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
