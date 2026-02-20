import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ServerDetail } from '../../api/servers'
import { useDeleteServer, useUpdateServer } from '../../api/servers'
import { useCopyToClipboard } from '../../hooks/useCopyToClipboard'
import { ConfirmModal } from '../ui'

interface SettingsTabProps {
  server: ServerDetail
}

export function SettingsTab({ server }: SettingsTabProps) {
  const navigate = useNavigate()
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const deleteMutation = useDeleteServer()
  const updateMutation = useUpdateServer()
  const { copied: idCopied, copy: copyId } = useCopyToClipboard()

  // Inline edit state
  const [editingField, setEditingField] = useState<'name' | 'description' | null>(null)
  const [editValue, setEditValue] = useState('')
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null)

  const isRunning = server.status === 'running'

  useEffect(() => {
    if (editingField && inputRef.current) {
      inputRef.current.focus()
      if (inputRef.current instanceof HTMLInputElement) {
        inputRef.current.select()
      }
    }
  }, [editingField])

  const startEdit = (field: 'name' | 'description') => {
    setEditingField(field)
    setEditValue(field === 'name' ? server.name : server.description || '')
  }

  const cancelEdit = () => {
    setEditingField(null)
    setEditValue('')
  }

  const saveEdit = () => {
    if (!editingField) return

    const trimmed = editValue.trim()

    // Validate name is not empty
    if (editingField === 'name' && !trimmed) return

    // Skip if unchanged
    const currentValue = editingField === 'name' ? server.name : (server.description || '')
    if (trimmed === currentValue) {
      cancelEdit()
      return
    }

    updateMutation.mutate(
      {
        id: server.id,
        data: { [editingField]: editingField === 'description' && !trimmed ? null : trimmed },
      },
      { onSuccess: () => cancelEdit() },
    )
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && editingField === 'name') {
      e.preventDefault()
      saveEdit()
    }
    if (e.key === 'Enter' && e.metaKey && editingField === 'description') {
      e.preventDefault()
      saveEdit()
    }
    if (e.key === 'Escape') {
      cancelEdit()
    }
  }

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

          {/* Name (editable) */}
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-subtle">Name</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-on-base">
              {editingField === 'name' ? (
                <div className="flex items-center gap-2">
                  <input
                    ref={inputRef as React.RefObject<HTMLInputElement>}
                    type="text"
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onKeyDown={handleKeyDown}
                    onBlur={cancelEdit}
                    maxLength={255}
                    className="w-48 px-2 py-1 text-sm border border-hl-med rounded-lg bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
                    aria-label="Server name"
                  />
                  <button
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={saveEdit}
                    disabled={updateMutation.isPending || !editValue.trim()}
                    className="text-xs text-foam hover:text-foam/80 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-iris rounded-md"
                  >
                    {updateMutation.isPending ? 'Saving...' : 'Save'}
                  </button>
                  <button
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={cancelEdit}
                    className="text-xs text-muted hover:text-subtle transition-colors focus:outline-none focus:ring-2 focus:ring-iris rounded-md"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <span className="group flex items-center gap-2">
                  {server.name}
                  <button
                    onClick={() => startEdit('name')}
                    className="text-xs text-pine hover:text-pine/80 opacity-0 group-hover:opacity-100 transition-all focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-iris rounded-md"
                    aria-label="Edit server name"
                  >
                    Edit
                  </button>
                </span>
              )}
            </dd>
          </div>

          {/* Description (editable) */}
          <div className="sm:flex sm:justify-between sm:items-start">
            <dt className="text-sm font-medium text-subtle">Description</dt>
            <dd className="mt-1 sm:mt-0 text-sm text-on-base">
              {editingField === 'description' ? (
                <div className="flex flex-col gap-2">
                  <textarea
                    ref={inputRef as React.RefObject<HTMLTextAreaElement>}
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onKeyDown={handleKeyDown}
                    onBlur={cancelEdit}
                    rows={3}
                    maxLength={2000}
                    className="w-64 px-2 py-1 text-sm border border-hl-med rounded-lg bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris resize-y"
                    aria-label="Server description"
                  />
                  <div className="flex items-center gap-2">
                    <button
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={saveEdit}
                      disabled={updateMutation.isPending}
                      className="text-xs text-foam hover:text-foam/80 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-iris rounded-md"
                    >
                      {updateMutation.isPending ? 'Saving...' : 'Save'}
                    </button>
                    <button
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={cancelEdit}
                      className="text-xs text-muted hover:text-subtle transition-colors focus:outline-none focus:ring-2 focus:ring-iris rounded-md"
                    >
                      Cancel
                    </button>
                    <span className="text-xs text-muted">Cmd+Enter to save</span>
                  </div>
                </div>
              ) : (
                <span className="group flex items-center gap-2">
                  {server.description || <span className="text-muted italic">No description</span>}
                  <button
                    onClick={() => startEdit('description')}
                    className="text-xs text-pine hover:text-pine/80 opacity-0 group-hover:opacity-100 transition-all focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-iris rounded-md"
                    aria-label="Edit server description"
                  >
                    Edit
                  </button>
                </span>
              )}
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
