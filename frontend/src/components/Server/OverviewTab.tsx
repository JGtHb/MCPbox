import { Link } from 'react-router-dom'
import type { ServerDetail } from '../../api/servers'
import type { ContainerStatus } from '../../api/servers'
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

  return (
    <div className="space-y-6">
      {/* Status and Controls */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center space-x-3 mb-2">
              <span
                className={`px-3 py-1 text-sm font-medium rounded-full ${STATUS_COLORS[statusKey] || 'bg-gray-100 text-gray-800'}`}
                role="status"
              >
                {STATUS_LABELS[statusKey] || server.status}
              </span>
              {serverStatus && serverStatus.registered_tools > 0 && (
                <span className="text-sm text-gray-500">
                  {serverStatus.registered_tools} tools registered
                </span>
              )}
            </div>
            {server.description && (
              <p className="text-gray-600">{server.description}</p>
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
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-sm font-medium text-gray-500 mb-1">Status</h3>
          <p className="text-2xl font-semibold text-gray-900 capitalize">{server.status}</p>
        </div>
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-sm font-medium text-gray-500 mb-1">Tools</h3>
          <p className="text-2xl font-semibold text-gray-900">{toolCount}</p>
        </div>
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-sm font-medium text-gray-500 mb-1">Registered</h3>
          <p className="text-2xl font-semibold text-gray-900">
            {isRunning ? (serverStatus?.registered_tools ?? 0) : '-'}
          </p>
        </div>
      </div>

      {/* Server Info */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-medium text-gray-900 mb-4">Server Info</h3>
        <dl className="space-y-3">
          <div className="flex justify-between">
            <dt className="text-gray-500">Network Mode</dt>
            <dd className="text-gray-900 capitalize">{server.network_mode}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-500">Default Timeout</dt>
            <dd className="text-gray-900">{server.default_timeout_ms}ms</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-500">Created</dt>
            <dd className="text-gray-900">
              {new Date(server.created_at).toLocaleDateString()}
            </dd>
          </div>
        </dl>
      </div>

      {/* Activity Tip */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <div className="flex items-start">
          <svg
            className="w-5 h-5 text-blue-500 mt-0.5 mr-3 flex-shrink-0"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <div>
            <h4 className="text-sm font-medium text-blue-800">
              View Activity Logs
            </h4>
            <p className="text-sm text-blue-700 mt-1">
              Monitor requests and responses for this server in the{' '}
              <Link to="/activity" className="underline focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 rounded">
                Activity dashboard
              </Link>
              .
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
