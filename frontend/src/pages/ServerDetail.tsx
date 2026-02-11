import { useState } from 'react'
import { Link, useParams, useNavigate } from 'react-router-dom'
import { Header } from '../components/Layout'
import { ServerControls } from '../components/Server'
import { ConfirmModal, LoadingCard } from '../components/ui'
import { useServer, useServerStatus, useDeleteServer } from '../api/servers'
import { useTools } from '../api/tools'
import { STATUS_COLORS, STATUS_LABELS, type ServerStatus } from '../lib/constants'

export function ServerDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  const { data: server, isLoading } = useServer(id || '')
  const { data: serverStatus } = useServerStatus(id || '', server?.status === 'running')
  const { data: tools } = useTools(id || '')
  const deleteMutation = useDeleteServer()

  const handleDeleteClick = () => {
    setShowDeleteConfirm(true)
  }

  const handleDeleteConfirm = () => {
    deleteMutation.mutate(id || '', {
      onSuccess: () => {
        setShowDeleteConfirm(false)
        navigate('/servers')
      },
    })
  }

  if (isLoading || !server) {
    return (
      <div>
        <Header title="Server Details" />
        <div className="p-6">
          <LoadingCard lines={3} />
        </div>
      </div>
    )
  }

  const isRunning = server.status === 'running'
  const hasTools = (tools?.length || 0) > 0
  const statusKey = server.status as ServerStatus

  return (
    <div>
      <Header
        title={server.name}
        action={
          <button
            onClick={handleDeleteClick}
            disabled={isRunning || deleteMutation.isPending}
            aria-label="Delete server"
            className="px-4 py-2 text-sm font-medium text-red-700 bg-white border border-red-300 rounded-md hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500"
          >
            {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
          </button>
        }
      />

      <div className="p-6 space-y-6">
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
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
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

          {/* Tools */}
          <div className="bg-white rounded-lg shadow p-6">
            <h3 className="text-lg font-medium text-gray-900 mb-4">
              Tools ({tools?.length || 0})
            </h3>
            {tools && tools.length > 0 ? (
              <ul className="divide-y divide-gray-200" role="list">
                {tools.map((tool) => (
                  <li key={tool.id} className="py-2 flex items-center justify-between">
                    <div className="flex items-center space-x-2">
                      <span className="px-2 py-0.5 text-xs font-medium rounded bg-purple-100 text-purple-800">
                        Python
                      </span>
                      <span className="text-gray-900">{tool.name}</span>
                    </div>
                    {!tool.enabled && (
                      <span className="text-xs text-gray-400">Disabled</span>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-center py-4">
                <p className="text-gray-500 mb-2">No tools defined</p>
                <p className="text-xs text-gray-400">
                  Create tools using mcpbox_create_tool MCP command
                </p>
              </div>
            )}
          </div>
        </div>

        {/* NOTE: Module configuration moved to global Settings page */}

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

      {/* Delete Confirmation Modal */}
      <ConfirmModal
        isOpen={showDeleteConfirm}
        title="Delete Server"
        message="Are you sure you want to delete this server? This action cannot be undone and will remove all associated tools."
        confirmLabel="Delete"
        destructive
        isLoading={deleteMutation.isPending}
        onConfirm={handleDeleteConfirm}
        onCancel={() => setShowDeleteConfirm(false)}
      />
    </div>
  )
}
