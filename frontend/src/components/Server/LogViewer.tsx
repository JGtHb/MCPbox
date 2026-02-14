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
      <div className="bg-gray-900 text-gray-400 rounded-lg p-4 text-center">
        Start the server to view logs
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="bg-gray-900 text-gray-400 rounded-lg p-4 text-center animate-pulse">
        Loading logs...
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-gray-900 text-red-400 rounded-lg p-4">
        <p>Failed to load logs</p>
        <button
          onClick={() => refetch()}
          className="mt-2 text-sm text-blue-400 hover:text-blue-300"
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="bg-gray-900 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700">
        <span className="text-sm font-medium text-gray-300">Container Logs</span>
        <div className="flex items-center space-x-4">
          <label className="flex items-center space-x-2 text-sm text-gray-400">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              className="rounded border-gray-600 bg-gray-700 text-blue-500 focus:ring-blue-500"
            />
            <span>Auto-scroll</span>
          </label>
          <button
            onClick={() => refetch()}
            className="text-sm text-gray-400 hover:text-gray-300"
          >
            Refresh
          </button>
        </div>
      </div>
      <pre
        ref={containerRef}
        className="p-4 text-sm text-gray-300 font-mono overflow-auto max-h-96 whitespace-pre-wrap"
      >
        {data?.logs || 'No logs available'}
      </pre>
    </div>
  )
}
