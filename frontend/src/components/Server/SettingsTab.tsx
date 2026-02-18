import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ServerDetail } from '../../api/servers'
import { useDeleteServer } from '../../api/servers'
import { useCopyToClipboard } from '../../hooks/useCopyToClipboard'
import { ConfirmModal } from '../ui'

interface SettingsTabProps {
  server: ServerDetail
}

export function SettingsTab({ server }: SettingsTabProps) {
  const navigate = useNavigate()
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const deleteMutation = useDeleteServer()
  const { copied: idCopied, copy: copyId } = useCopyToClipboard()

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
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
        <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Configuration</h3>
        <dl className="space-y-4">
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-gray-500 dark:text-gray-400">Server ID</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-gray-900 dark:text-white font-mono flex items-center gap-2">
              {server.id}
              <button
                onClick={() => copyId(server.id)}
                className="text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 transition-colors"
              >
                {idCopied ? 'Copied' : 'Copy'}
              </button>
            </dd>
          </div>
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-gray-500 dark:text-gray-400">Name</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-gray-900 dark:text-white">{server.name}</dd>
          </div>
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-gray-500 dark:text-gray-400">Description</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-gray-900 dark:text-white">
              {server.description || <span className="text-gray-400 dark:text-gray-500 italic">No description</span>}
            </dd>
          </div>
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-gray-500 dark:text-gray-400">Network Mode</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-gray-900 dark:text-white capitalize">{server.network_mode}</dd>
          </div>
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-gray-500 dark:text-gray-400">Default Timeout</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-gray-900 dark:text-white">{server.default_timeout_ms}ms</dd>
          </div>
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-gray-500 dark:text-gray-400">Created</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-gray-900 dark:text-white">
              {new Date(server.created_at).toLocaleString()}
            </dd>
          </div>
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-gray-500 dark:text-gray-400">Last Updated</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-gray-900 dark:text-white">
              {new Date(server.updated_at).toLocaleString()}
            </dd>
          </div>
        </dl>
        <p className="mt-4 text-xs text-gray-400 dark:text-gray-500">
          Server configuration is managed via MCP tools. Use{' '}
          <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">mcpbox_create_server</code> to create servers
          and <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">mcpbox_update_tool</code> to manage tools.
        </p>
      </div>

      {/* Danger Zone */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-red-200 dark:border-red-800">
        <div className="p-6">
          <h3 className="text-lg font-medium text-red-900 dark:text-red-300 mb-2">Danger Zone</h3>
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
            Deleting this server will permanently remove all associated tools, secrets,
            and execution logs. This action cannot be undone.
          </p>
          <button
            onClick={() => setShowDeleteConfirm(true)}
            disabled={isRunning || deleteMutation.isPending}
            className="px-4 py-2 text-sm font-medium text-red-700 dark:text-red-300 bg-white dark:bg-gray-800 border border-red-300 dark:border-red-700 rounded-md hover:bg-red-50 dark:hover:bg-red-900/30 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 dark:focus:ring-offset-gray-800"
          >
            {deleteMutation.isPending ? 'Deleting...' : 'Delete Server'}
          </button>
          {isRunning && (
            <p className="mt-2 text-xs text-red-500 dark:text-red-400">
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
