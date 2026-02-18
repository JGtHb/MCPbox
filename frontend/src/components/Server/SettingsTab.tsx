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
      <div className="bg-surface rounded-lg shadow p-6">
        <h3 className="text-lg font-medium text-on-base mb-4">Configuration</h3>
        <dl className="space-y-4">
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-subtle">Server ID</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-on-base font-mono flex items-center gap-2">
              {server.id}
              <button
                onClick={() => copyId(server.id)}
                className="text-xs text-pine hover:text-pine/80 transition-colors rounded-md focus:outline-none focus:ring-2 focus:ring-iris"
                aria-label="Copy server ID"
              >
                {idCopied ? 'Copied' : 'Copy'}
              </button>
            </dd>
          </div>
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-subtle">Name</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-on-base">{server.name}</dd>
          </div>
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-subtle">Description</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-on-base">
              {server.description || <span className="text-muted italic">No description</span>}
            </dd>
          </div>
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-subtle">Network Mode</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-on-base capitalize">{server.network_mode}</dd>
          </div>
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-subtle">Default Timeout</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-on-base">{server.default_timeout_ms}ms</dd>
          </div>
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-subtle">Created</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-on-base">
              {new Date(server.created_at).toLocaleString()}
            </dd>
          </div>
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-subtle">Last Updated</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-on-base">
              {new Date(server.updated_at).toLocaleString()}
            </dd>
          </div>
        </dl>
        <p className="mt-4 text-xs text-subtle">
          Server configuration is managed via MCP tools. Use{' '}
          <code className="bg-overlay px-1 rounded">mcpbox_create_server</code> to create servers
          and <code className="bg-overlay px-1 rounded">mcpbox_update_tool</code> to manage tools.
        </p>
      </div>

      {/* Danger Zone */}
      <div className="bg-surface rounded-lg shadow border border-love/30">
        <div className="p-6">
          <h3 className="text-lg font-medium text-love mb-2">Danger Zone</h3>
          <p className="text-sm text-subtle mb-4">
            Deleting this server will permanently remove all associated tools, secrets,
            and execution logs. This action cannot be undone.
          </p>
          <button
            onClick={() => setShowDeleteConfirm(true)}
            disabled={isRunning || deleteMutation.isPending}
            className="px-4 py-2 text-sm font-medium text-love bg-surface border border-love/40 rounded-lg hover:bg-love/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-love"
          >
            {deleteMutation.isPending ? 'Deleting...' : 'Delete Server'}
          </button>
          {isRunning && (
            <p className="mt-2 text-xs text-love">
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
