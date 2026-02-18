import type { ServerDetail } from '../../api/servers'
import type { ContainerStatus } from '../../api/servers'
import { useServerExecutionLogs } from '../../api/executionLogs'
import { ServerControls } from './ServerControls'
import { STATUS_COLORS, STATUS_LABELS, type ServerStatus } from '../../lib/constants'

interface OverviewTabProps {
  server: ServerDetail
  serverStatus: ContainerStatus | undefined
  toolCount: number
}

export function OverviewTab({ server, serverStatus, toolCount }: OverviewTabProps) {
  const isRunning = server.status === 'running'
  const hasTools = toolCount > 0
  const statusKey = server.status as ServerStatus
  const { data: executionLogs } = useServerExecutionLogs(server.id, 1, 20)

  return (
    <div className="space-y-6">
      {/* Status and Controls */}
      <div className="bg-surface rounded-lg shadow p-6">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center space-x-3 mb-2">
              <span
                className={`px-3 py-1 text-sm font-medium rounded-full ${STATUS_COLORS[statusKey] || 'bg-overlay text-subtle'}`}
                role="status"
              >
                {STATUS_LABELS[statusKey] || server.status}
              </span>
              {serverStatus && serverStatus.registered_tools > 0 && (
                <span className="text-sm text-subtle">
                  {serverStatus.registered_tools} tools registered
                </span>
              )}
            </div>
            {server.description && (
              <p className="text-subtle">{server.description}</p>
            )}
          </div>
          <ServerControls
            serverId={server.id}
            status={server.status}
            hasTools={hasTools}
          />
        </div>
      </div>

      {/* Info Grid */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="bg-surface rounded-lg shadow p-6">
          <h3 className="text-sm font-medium text-subtle mb-1">Status</h3>
          <p className="text-2xl font-semibold text-on-base capitalize">{server.status}</p>
        </div>
        <div className="bg-surface rounded-lg shadow p-6">
          <h3 className="text-sm font-medium text-subtle mb-1">Tools</h3>
          <p className="text-2xl font-semibold text-on-base">{toolCount}</p>
        </div>
        <div className="bg-surface rounded-lg shadow p-6">
          <h3 className="text-sm font-medium text-subtle mb-1">Registered</h3>
          <p className="text-2xl font-semibold text-on-base">
            {isRunning ? (serverStatus?.registered_tools ?? 0) : '-'}
          </p>
        </div>
        <div className="bg-surface rounded-lg shadow p-6">
          <h3 className="text-sm font-medium text-subtle mb-1">Recent Executions</h3>
          <p className="text-2xl font-semibold text-on-base">
            {executionLogs?.total ?? 0}
          </p>
        </div>
      </div>

      {/* Server Info */}
      <div className="bg-surface rounded-lg shadow p-6">
        <h3 className="text-lg font-medium text-on-base mb-4">Server Info</h3>
        <dl className="space-y-3">
          <div className="flex justify-between">
            <dt className="text-subtle">Network Mode</dt>
            <dd className="text-on-base capitalize">{server.network_mode}</dd>
          </div>
          {server.network_mode === 'allowlist' && server.allowed_hosts && server.allowed_hosts.length > 0 && (
            <div className="flex justify-between">
              <dt className="text-subtle">Allowed Hosts</dt>
              <dd className="text-on-base text-right">
                <div className="flex flex-wrap justify-end gap-1">
                  {server.allowed_hosts.map((host) => (
                    <span
                      key={host}
                      className="inline-block px-2 py-0.5 text-xs font-mono bg-overlay rounded"
                    >
                      {host}
                    </span>
                  ))}
                </div>
              </dd>
            </div>
          )}
          <div className="flex justify-between">
            <dt className="text-subtle">Default Timeout</dt>
            <dd className="text-on-base">{server.default_timeout_ms}ms</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-subtle">Created</dt>
            <dd className="text-on-base">
              {new Date(server.created_at).toLocaleDateString()}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-subtle">Updated</dt>
            <dd className="text-on-base">
              {new Date(server.updated_at).toLocaleDateString()}
            </dd>
          </div>
        </dl>
      </div>
    </div>
  )
}
