import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ServerDetail } from '../../api/servers'
import { useDeleteServer } from '../../api/servers'
import { ConfirmModal } from '../ui'

interface SettingsTabProps {
  server: ServerDetail
}

export function SettingsTab({ server }: SettingsTabProps) {
  const navigate = useNavigate()
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const deleteMutation = useDeleteServer()

  const isRunning = server.status === 'running'

  const handleDeleteConfirm = () => {
    deleteMutation.mutate(server.id, {
      onSuccess: () => {
        setShowDeleteConfirm(false)
        navigate('/servers')
      },
    })
  }

  return (
    <div className="space-y-6">
      {/* Server Configuration */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-medium text-gray-900 mb-4">Configuration</h3>
        <dl className="space-y-4">
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-gray-500">Server ID</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-gray-900 font-mono">{server.id}</dd>
          </div>
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-gray-500">Name</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-gray-900">{server.name}</dd>
          </div>
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-gray-500">Description</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-gray-900">
              {server.description || <span className="text-gray-400 italic">No description</span>}
            </dd>
          </div>
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-gray-500">Network Mode</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-gray-900 capitalize">{server.network_mode}</dd>
          </div>
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-gray-500">Default Timeout</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-gray-900">{server.default_timeout_ms}ms</dd>
          </div>
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-gray-500">Helper Code</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-gray-900">
              {server.helper_code ? (
                <span className="text-green-600">Configured</span>
              ) : (
                <span className="text-gray-400 italic">None</span>
              )}
            </dd>
          </div>
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-gray-500">Created</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-gray-900">
              {new Date(server.created_at).toLocaleString()}
            </dd>
          </div>
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-gray-500">Last Updated</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-gray-900">
              {new Date(server.updated_at).toLocaleString()}
            </dd>
          </div>
        </dl>
        <p className="mt-4 text-xs text-gray-400">
          Server configuration is managed via MCP tools. Use{' '}
          <code className="bg-gray-100 px-1 rounded">mcpbox_create_server</code> to create servers
          and <code className="bg-gray-100 px-1 rounded">mcpbox_update_tool</code> to manage tools.
        </p>
      </div>

      {/* Danger Zone */}
      <div className="bg-white rounded-lg shadow border border-red-200">
        <div className="p-6">
          <h3 className="text-lg font-medium text-red-900 mb-2">Danger Zone</h3>
          <p className="text-sm text-gray-600 mb-4">
            Deleting this server will permanently remove all associated tools, secrets,
            and execution logs. This action cannot be undone.
          </p>
          <button
            onClick={() => setShowDeleteConfirm(true)}
            disabled={isRunning || deleteMutation.isPending}
            className="px-4 py-2 text-sm font-medium text-red-700 bg-white border border-red-300 rounded-md hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500"
          >
            {deleteMutation.isPending ? 'Deleting...' : 'Delete Server'}
          </button>
          {isRunning && (
            <p className="mt-2 text-xs text-red-500">
              Stop the server before deleting it.
            </p>
          )}
        </div>
      </div>

      {/* Delete Confirmation Modal */}
      <ConfirmModal
        isOpen={showDeleteConfirm}
        title="Delete Server"
        message="Are you sure you want to delete this server? This action cannot be undone and will remove all associated tools, secrets, and execution logs."
        confirmLabel="Delete"
        destructive
        isLoading={deleteMutation.isPending}
        onConfirm={handleDeleteConfirm}
        onCancel={() => setShowDeleteConfirm(false)}
      />
    </div>
  )
}
