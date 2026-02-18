import { useState } from 'react'
import { useToolExecutionLogs, type ExecutionLog } from '../../api/executionLogs'

interface ToolExecutionLogsProps {
  toolId: string
  toolName: string
}

function formatDuration(ms: number | null): string {
  if (ms === null) return '-'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatTime(iso: string): string {
  const date = new Date(iso)
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function LogDetail({ log }: { log: ExecutionLog }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="border border-hl-med rounded-lg mb-2 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-hl-low text-left"
      >
        <div className="flex items-center gap-3 min-w-0">
          <span
            className={`inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold ${
              log.success
                ? 'bg-foam/10 text-foam'
                : 'bg-love/10 text-love'
            }`}
          >
            {log.success ? '\u2713' : '\u2717'}
          </span>
          <span className="text-sm text-subtle whitespace-nowrap">
            {formatTime(log.created_at)}
          </span>
          <span className="text-sm text-on-base font-mono truncate">
            {formatDuration(log.duration_ms)}
          </span>
          {log.executed_by && (
            <span className="text-xs text-muted truncate">
              by {log.executed_by}
            </span>
          )}
          {log.error && (
            <span className="text-xs text-love truncate ml-2">
              {log.error.slice(0, 80)}
            </span>
          )}
        </div>
        <svg
          className={`w-4 h-4 text-muted transition-transform ${
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
        <div className="px-4 pb-4 space-y-3 border-t border-hl-med">
          {log.input_args && Object.keys(log.input_args).length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-subtle uppercase mb-1">
                Input Arguments
              </h4>
              <pre className="text-xs bg-hl-low p-2 rounded overflow-x-auto max-h-40">
                {JSON.stringify(log.input_args, null, 2)}
              </pre>
            </div>
          )}

          {log.error && (
            <div>
              <h4 className="text-xs font-semibold text-love uppercase mb-1">
                Error
              </h4>
              <pre className="text-xs bg-love/10 text-love p-2 rounded overflow-x-auto max-h-40 whitespace-pre-wrap">
                {log.error}
              </pre>
            </div>
          )}

          {log.result !== null && log.result !== undefined && (
            <div>
              <h4 className="text-xs font-semibold text-subtle uppercase mb-1">
                Result
              </h4>
              <pre className="text-xs bg-hl-low p-2 rounded overflow-x-auto max-h-40">
                {typeof log.result === 'string'
                  ? log.result
                  : JSON.stringify(log.result, null, 2)}
              </pre>
            </div>
          )}

          {log.stdout && (
            <div>
              <h4 className="text-xs font-semibold text-subtle uppercase mb-1">
                Stdout
              </h4>
              <pre className="text-xs bg-hl-low p-2 rounded overflow-x-auto max-h-40 whitespace-pre-wrap">
                {log.stdout}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function ToolExecutionLogs({ toolId, toolName }: ToolExecutionLogsProps) {
  const [page, setPage] = useState(1)
  const { data, isLoading, error } = useToolExecutionLogs(toolId, page, 20)

  if (isLoading) {
    return (
      <div className="text-sm text-subtle py-4 text-center">
        Loading execution logs...
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-sm text-love py-4 text-center">
        Failed to load execution logs
      </div>
    )
  }

  if (!data || data.items.length === 0) {
    return (
      <div className="text-sm text-subtle py-4 text-center">
        No execution logs yet for {toolName}
      </div>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-medium text-on-base">
          Execution Logs ({data.total})
        </h4>
      </div>

      <div className="space-y-0">
        {data.items.map((log) => (
          <LogDetail key={log.id} log={log} />
        ))}
      </div>

      {data.pages > 1 && (
        <div className="flex items-center justify-between mt-4 text-sm">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="px-3 py-1 border rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-hl-low"
          >
            Previous
          </button>
          <span className="text-subtle">
            Page {page} of {data.pages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(data.pages, p + 1))}
            disabled={page >= data.pages}
            className="px-3 py-1 border rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-hl-low"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
