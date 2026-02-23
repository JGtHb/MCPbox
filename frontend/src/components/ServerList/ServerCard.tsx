import { Link } from 'react-router-dom'
import type { Server } from '../../api/servers'
import { useStartServer, useStopServer } from '../../api/servers'
import { STATUS_COLORS, STATUS_LABELS, type ServerStatus } from '../../lib/constants'

interface ServerCardProps {
  server: Server
}

export function ServerCard({ server }: ServerCardProps) {
  const startMutation = useStartServer()
  const stopMutation = useStopServer()

  const isLoading = startMutation.isPending || stopMutation.isPending
  const statusKey = server.status as ServerStatus

  const handleStart = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    startMutation.mutate(server.id)
  }

  const handleStop = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    stopMutation.mutate(server.id)
  }

  return (
    <Link
      to={`/servers/${server.id}`}
      className="block bg-surface rounded-lg shadow hover:shadow-md transition-shadow focus:outline-none focus:ring-2 focus:ring-iris focus:ring-offset-2"
    >
      <div className="p-4">
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <h3 className="text-lg font-medium text-on-base truncate">
              {server.name}
            </h3>
            {server.description && (
              <p className="mt-1 text-sm text-muted line-clamp-2">
                {server.description}
              </p>
            )}
          </div>
          <span
            className={`ml-2 px-2 py-1 text-xs font-medium rounded-full ${STATUS_COLORS[statusKey] || 'bg-overlay text-subtle'}`}
            role="status"
          >
            {STATUS_LABELS[statusKey] || server.status}
          </span>
        </div>

        {/* Show error message if mutation failed */}
        {(startMutation.error || stopMutation.error) && (
          <div className="mt-2 text-xs text-love bg-love/10 border border-love/20 rounded px-2 py-1">
            {startMutation.error instanceof Error
              ? startMutation.error.message
              : stopMutation.error instanceof Error
                ? stopMutation.error.message
                : 'Operation failed'}
          </div>
        )}

        <div className="mt-4 flex items-center justify-between">
          <div className="flex items-center space-x-4 text-sm text-muted">
            <span className="flex items-center">
              <svg
                className="w-4 h-4 mr-1"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 6h16M4 10h16M4 14h16M4 18h16"
                />
              </svg>
              <span aria-label={`${server.tool_count} tools`}>
                {server.tool_count} {server.tool_count === 1 ? 'tool' : 'tools'}
              </span>
            </span>
            <span className="text-muted" aria-hidden="true">|</span>
            <span>{server.allowed_hosts.length === 0 ? 'Isolated' : `${server.allowed_hosts.length} host(s)`}</span>
          </div>

          <div className="flex items-center space-x-2">
            {server.status === 'running' ? (
              <button
                onClick={handleStop}
                disabled={isLoading}
                aria-label={`Stop ${server.name}`}
                className="px-3 py-1 text-xs font-medium text-love bg-love/10 rounded hover:bg-love/20 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-love focus:ring-offset-2"
              >
                {stopMutation.isPending ? 'Stopping...' : 'Stop'}
              </button>
            ) : server.status === 'ready' || server.status === 'stopped' ? (
              <button
                onClick={handleStart}
                disabled={isLoading}
                aria-label={`Start ${server.name}`}
                className="px-3 py-1 text-xs font-medium text-foam bg-foam/10 rounded hover:bg-foam/20 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-foam focus:ring-offset-2"
              >
                {startMutation.isPending ? 'Starting...' : 'Start'}
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </Link>
  )
}
