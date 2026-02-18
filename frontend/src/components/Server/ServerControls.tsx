import { useStartServer, useStopServer, useRestartServer } from '../../api/servers'

interface ServerControlsProps {
  serverId: string
  status: string
  hasTools: boolean
}

export function ServerControls({ serverId, status, hasTools }: ServerControlsProps) {
  const startMutation = useStartServer()
  const stopMutation = useStopServer()
  const restartMutation = useRestartServer()

  const isLoading = startMutation.isPending || stopMutation.isPending || restartMutation.isPending
  const isRunning = status === 'running'
  const canStart = (status === 'ready' || status === 'stopped' || status === 'imported') && hasTools

  // Get the current error from any failed mutation
  const error = startMutation.error || stopMutation.error || restartMutation.error
  const errorMessage = error instanceof Error ? error.message : error ? String(error) : null

  return (
    <div className="flex flex-col space-y-2">
      {errorMessage && (
        <div className="text-sm text-love bg-love/10 border border-love/20 rounded px-3 py-2">
          {errorMessage}
        </div>
      )}
      <div className="flex items-center space-x-3">
      {isRunning ? (
        <>
          <button
            onClick={() => stopMutation.mutate(serverId)}
            disabled={isLoading}
            className="inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-base bg-love hover:bg-love/80 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <svg className="w-4 h-4 mr-2" fill="currentColor" viewBox="0 0 24 24">
              <rect x="6" y="6" width="12" height="12" />
            </svg>
            {stopMutation.isPending ? 'Stopping...' : 'Stop'}
          </button>
          <button
            onClick={() => restartMutation.mutate(serverId)}
            disabled={isLoading}
            className="inline-flex items-center px-4 py-2 border border-hl-med rounded-md shadow-sm text-sm font-medium text-on-base bg-surface hover:bg-hl-low disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
            {restartMutation.isPending ? 'Restarting...' : 'Restart'}
          </button>
        </>
      ) : (
        <button
          onClick={() => startMutation.mutate(serverId)}
          disabled={isLoading || !canStart}
          className="inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-base bg-foam hover:bg-foam/80 disabled:opacity-50 disabled:cursor-not-allowed"
          title={!hasTools ? 'Add tools first' : undefined}
        >
          <svg className="w-4 h-4 mr-2" fill="currentColor" viewBox="0 0 24 24">
            <polygon points="5,3 19,12 5,21" />
          </svg>
          {startMutation.isPending ? 'Starting...' : 'Start'}
        </button>
      )}

      {!hasTools && status !== 'running' && (
        <span className="text-sm text-gold">
          Add tools first to enable starting
        </span>
      )}
      </div>
    </div>
  )
}
