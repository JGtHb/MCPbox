import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'

interface LogViewerProps {
  serverId: string
  enabled?: boolean
}

interface LogsResponse {
  server_id: string
  logs: string
  tail: number
}

async function fetchLogs(serverId: string): Promise<LogsResponse> {
  return api.get<LogsResponse>(`/api/servers/${serverId}/logs?tail=200`)
}

export function LogViewer({ serverId, enabled = true }: LogViewerProps) {
  const containerRef = useRef<HTMLPreElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['logs', serverId],
    queryFn: () => fetchLogs(serverId),
    enabled,
    refetchInterval: enabled ? 3000 : false, // Poll every 3 seconds when enabled
  })

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [data?.logs, autoScroll])

  if (!enabled) {
    return (
      <div className="bg-base text-muted rounded-lg p-4 text-center">
        Start the server to view logs
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="bg-base text-muted rounded-lg p-4 text-center animate-pulse">
        Loading logs...
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-base text-love rounded-lg p-4">
        <p>Failed to load logs</p>
        <button
          onClick={() => refetch()}
          className="mt-2 text-sm text-pine hover:text-pine/80 transition-colors rounded-md focus:outline-none focus:ring-2 focus:ring-iris"
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="bg-base rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 bg-overlay border-b border-hl-med">
        <span className="text-sm font-medium text-subtle">Container Logs</span>
        <div className="flex items-center space-x-4">
          <label className="flex items-center space-x-2 text-sm text-muted">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              className="rounded border-hl-med bg-hl-med text-iris focus:ring-iris"
            />
            <span>Auto-scroll</span>
          </label>
          <button
            onClick={() => refetch()}
            className="text-sm text-muted hover:text-subtle transition-colors rounded-md focus:outline-none focus:ring-2 focus:ring-iris"
          >
            Refresh
          </button>
        </div>
      </div>
      <pre
        ref={containerRef}
        className="p-4 text-sm text-subtle font-mono overflow-auto max-h-96 whitespace-pre-wrap"
      >
        {data?.logs || 'No logs available'}
      </pre>
    </div>
  )
}
