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
      className="block bg-white dark:bg-gray-800 rounded-lg shadow hover:shadow-md dark:shadow-gray-900/50 transition-shadow focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 dark:focus:ring-offset-gray-900"
    >
      <div className="p-4">
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <h3 className="text-lg font-medium text-gray-900 dark:text-white truncate">
              {server.name}
            </h3>
            {server.description && (
              <p className="mt-1 text-sm text-gray-500 dark:text-gray-400 line-clamp-2">
                {server.description}
              </p>
            )}
          </div>
          <span
            className={`ml-2 px-2 py-1 text-xs font-medium rounded-full ${STATUS_COLORS[statusKey] || 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'}`}
            role="status"
          >
            {STATUS_LABELS[statusKey] || server.status}
          </span>
        </div>

        {/* Show error message if mutation failed */}
        {(startMutation.error || stopMutation.error) && (
          <div className="mt-2 text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded px-2 py-1">
            {startMutation.error instanceof Error
              ? startMutation.error.message
              : stopMutation.error instanceof Error
                ? stopMutation.error.message
                : 'Operation failed'}
          </div>
        )}

        <div className="mt-4 flex items-center justify-between">
          <div className="flex items-center space-x-4 text-sm text-gray-500 dark:text-gray-400">
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
            <span className="text-gray-400 dark:text-gray-500" aria-hidden="true">|</span>
            <span className="capitalize">{server.network_mode}</span>
          </div>

          <div className="flex items-center space-x-2">
            {server.status === 'running' ? (
              <button
                onClick={handleStop}
                disabled={isLoading}
                aria-label={`Stop ${server.name}`}
                className="px-3 py-1 text-xs font-medium text-red-700 dark:text-red-300 bg-red-100 dark:bg-red-900/50 rounded hover:bg-red-200 dark:hover:bg-red-900/70 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 dark:focus:ring-offset-gray-800"
              >
                {stopMutation.isPending ? 'Stopping...' : 'Stop'}
              </button>
            ) : server.status === 'ready' || server.status === 'stopped' ? (
              <button
                onClick={handleStart}
                disabled={isLoading}
                aria-label={`Start ${server.name}`}
                className="px-3 py-1 text-xs font-medium text-green-700 dark:text-green-300 bg-green-100 dark:bg-green-900/50 rounded hover:bg-green-200 dark:hover:bg-green-900/70 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2 dark:focus:ring-offset-gray-800"
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
