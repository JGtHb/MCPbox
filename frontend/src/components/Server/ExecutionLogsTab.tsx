import { useState } from 'react'
import { useServerExecutionLogs, type ExecutionLog } from '../../api/executionLogs'

export function formatDuration(ms: number | null): string {
  if (ms === null) return '-'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

export function formatTime(iso: string): string {
  const date = new Date(iso)
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function LogDetail({ log }: { log: ExecutionLog }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/50 text-left"
      >
        <div className="flex items-center gap-3 min-w-0">
          <span
            className={`inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold ${
              log.success
                ? 'bg-green-100 dark:bg-green-900/50 text-green-700 dark:text-green-300'
                : 'bg-red-100 dark:bg-red-900/50 text-red-700 dark:text-red-300'
            }`}
          >
            {log.success ? '\u2713' : '\u2717'}
          </span>
          <span className="px-2 py-0.5 text-xs font-medium rounded bg-purple-100 dark:bg-purple-900/50 text-purple-800 dark:text-purple-300 whitespace-nowrap">
            {log.tool_name}
          </span>
          <span className="text-sm text-gray-500 dark:text-gray-400 whitespace-nowrap">
            {formatTime(log.created_at)}
          </span>
          <span className="text-sm text-gray-700 dark:text-gray-300 font-mono">
            {formatDuration(log.duration_ms)}
          </span>
          {log.executed_by && (
            <span className="text-xs text-gray-400 dark:text-gray-500 truncate hidden sm:inline">
              by {log.executed_by}
            </span>
          )}
          {log.error && (
            <span className="text-xs text-red-600 dark:text-red-400 truncate ml-2 hidden md:inline">
              {log.error.slice(0, 60)}
            </span>
          )}
        </div>
        <svg
          className={`w-4 h-4 text-gray-400 dark:text-gray-500 transition-transform flex-shrink-0 ${
            expanded ? 'rotate-180' : ''
          }`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M19 9l-7 7-7-7"
          />
        </svg>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-gray-100 dark:border-gray-700">
          {log.input_args && Object.keys(log.input_args).length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase mb-1">
                Input Arguments
              </h4>
              <pre className="text-xs bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 p-2 rounded overflow-x-auto max-h-40">
                {JSON.stringify(log.input_args, null, 2)}
              </pre>
            </div>
          )}

          {log.error && (
            <div>
              <h4 className="text-xs font-semibold text-red-500 dark:text-red-400 uppercase mb-1">
                Error
              </h4>
              <pre className="text-xs bg-red-50 dark:bg-red-900/30 text-red-800 dark:text-red-300 p-2 rounded overflow-x-auto max-h-40 whitespace-pre-wrap">
                {log.error}
              </pre>
            </div>
          )}

          {log.result !== null && log.result !== undefined && (
            <div>
              <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase mb-1">
                Result
              </h4>
              <pre className="text-xs bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 p-2 rounded overflow-x-auto max-h-40">
                {typeof log.result === 'string'
                  ? log.result
                  : JSON.stringify(log.result, null, 2)}
              </pre>
            </div>
          )}

          {log.stdout && (
            <div>
              <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase mb-1">
                Stdout
              </h4>
              <pre className="text-xs bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 p-2 rounded overflow-x-auto max-h-40 whitespace-pre-wrap">
                {log.stdout}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

interface ExecutionLogsTabProps {
  serverId: string
}

export function ExecutionLogsTab({ serverId }: ExecutionLogsTabProps) {
  const [page, setPage] = useState(1)
  const { data, isLoading, error } = useServerExecutionLogs(serverId, page, 20)

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
        <div className="text-sm text-gray-500 dark:text-gray-400 py-4 text-center">
          Loading execution logs...
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
        <div className="text-sm text-red-500 dark:text-red-400 py-4 text-center">
          Failed to load execution logs
        </div>
      </div>
    )
  }

  if (!data || data.items.length === 0) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
        <div className="text-center py-8">
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
          <p className="text-gray-500 dark:text-gray-400 mb-1">No execution logs yet</p>
          <p className="text-xs text-gray-400 dark:text-gray-500">
            Logs will appear here when tools are executed
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-medium text-gray-900 dark:text-white">
          Execution Logs ({data.total})
        </h3>
      </div>

      <div className="space-y-2">
        {data.items.map((log) => (
          <LogDetail key={log.id} log={log} />
        ))}
      </div>

      {data.pages > 1 && (
        <div className="flex items-center justify-between mt-4 text-sm">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="px-3 py-1 border border-gray-300 dark:border-gray-600 rounded text-gray-700 dark:text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 dark:hover:bg-gray-700"
          >
            Previous
          </button>
          <span className="text-gray-500 dark:text-gray-400">
            Page {page} of {data.pages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(data.pages, p + 1))}
            disabled={page >= data.pages}
            className="px-3 py-1 border border-gray-300 dark:border-gray-600 rounded text-gray-700 dark:text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 dark:hover:bg-gray-700"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
