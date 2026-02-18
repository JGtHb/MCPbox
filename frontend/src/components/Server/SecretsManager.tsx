import { useState } from 'react'
import {
  useSecrets,
  useCreateSecret,
  useSetSecretValue,
  useDeleteSecret,
  type Secret,
} from '../../api/serverSecrets'
import { ConfirmModal } from '../ui'

interface SecretsManagerProps {
  serverId: string
}

function SetValueModal({
  isOpen,
  secret,
  onSubmit,
  onCancel,
  isLoading,
}: {
  isOpen: boolean
  secret: Secret | null
  onSubmit: (value: string) => void
  onCancel: () => void
  isLoading: boolean
}) {
  const [value, setValue] = useState('')

  if (!isOpen || !secret) return null

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (value.trim()) {
      onSubmit(value)
      setValue('')
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 overflow-y-auto"
      role="dialog"
      aria-modal="true"
      aria-labelledby="set-value-title"
    >
      <div
        className="fixed inset-0 bg-base/75"
        aria-hidden="true"
        onClick={onCancel}
      />
      <div className="fixed inset-0 flex items-center justify-center p-4" onClick={onCancel}>
        <div
          className="relative bg-surface rounded-lg shadow-xl max-w-md w-full p-6"
          onClick={(e) => e.stopPropagation()}
        >
          <h3 id="set-value-title" className="text-lg font-medium text-on-base mb-1">
            Set Secret Value
          </h3>
          <p className="text-sm text-subtle mb-4">
            Set the value for <span className="font-mono font-medium">{secret.key_name}</span>
          </p>
          {secret.description && (
            <p className="text-xs text-muted mb-4">{secret.description}</p>
          )}

          <form onSubmit={handleSubmit}>
            <div className="mb-4">
              <label htmlFor="secret-value" className="block text-sm font-medium text-on-base mb-1">
                Value
              </label>
              <input
                id="secret-value"
                type="password"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder="Enter secret value..."
                className="w-full px-3 py-2 border border-hl-med rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris font-mono text-sm"
                autoFocus
                autoComplete="off"
              />
            </div>
            <div className="flex space-x-3">
              <button
                type="button"
                onClick={() => {
                  setValue('')
                  onCancel()
                }}
                disabled={isLoading}
                className="flex-1 px-4 py-2 text-sm font-medium text-on-base bg-surface border border-hl-med rounded-md hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isLoading || !value.trim()}
                className="flex-1 px-4 py-2 text-sm font-medium text-base bg-iris rounded-md hover:bg-iris/80 transition-colors focus:outline-none focus:ring-2 focus:ring-iris disabled:opacity-50"
              >
                {isLoading ? 'Setting...' : secret.has_value ? 'Update Value' : 'Set Value'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

function CreateSecretModal({
  isOpen,
  onSubmit,
  onCancel,
  isLoading,
}: {
  isOpen: boolean
  onSubmit: (keyName: string, description: string) => void
  onCancel: () => void
  isLoading: boolean
}) {
  const [keyName, setKeyName] = useState('')
  const [description, setDescription] = useState('')
  const [keyError, setKeyError] = useState('')

  if (!isOpen) return null

  const validateKeyName = (name: string): boolean => {
    if (!name) {
      setKeyError('Key name is required')
      return false
    }
    if (!/^[A-Z][A-Z0-9_]*$/.test(name)) {
      setKeyError('Must start with uppercase letter, only A-Z, 0-9, and underscores')
      return false
    }
    setKeyError('')
    return true
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (validateKeyName(keyName)) {
      onSubmit(keyName, description)
      setKeyName('')
      setDescription('')
      setKeyError('')
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 overflow-y-auto"
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-secret-title"
    >
      <div
        className="fixed inset-0 bg-base/75"
        aria-hidden="true"
        onClick={onCancel}
      />
      <div className="fixed inset-0 flex items-center justify-center p-4" onClick={onCancel}>
        <div
          className="relative bg-surface rounded-lg shadow-xl max-w-md w-full p-6"
          onClick={(e) => e.stopPropagation()}
        >
          <h3 id="create-secret-title" className="text-lg font-medium text-on-base mb-4">
            Create Secret
          </h3>

          <form onSubmit={handleSubmit}>
            <div className="mb-4">
              <label htmlFor="key-name" className="block text-sm font-medium text-on-base mb-1">
                Key Name
              </label>
              <input
                id="key-name"
                type="text"
                value={keyName}
                onChange={(e) => {
                  setKeyName(e.target.value.toUpperCase())
                  if (keyError) validateKeyName(e.target.value.toUpperCase())
                }}
                placeholder="e.g. API_KEY"
                className={`w-full px-3 py-2 border rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris font-mono text-sm ${
                  keyError ? 'border-love' : 'border-hl-med'
                }`}
                autoFocus
                autoComplete="off"
              />
              {keyError && (
                <p className="mt-1 text-xs text-love">{keyError}</p>
              )}
              <p className="mt-1 text-xs text-muted">
                Uppercase letters, numbers, underscores. Access in tools via{' '}
                <code className="bg-hl-low px-1 rounded">secrets[&quot;KEY_NAME&quot;]</code>
              </p>
            </div>
            <div className="mb-4">
              <label htmlFor="description" className="block text-sm font-medium text-on-base mb-1">
                Description <span className="text-muted">(optional)</span>
              </label>
              <input
                id="description"
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="e.g. TheirStack API key for job search"
                className="w-full px-3 py-2 border border-hl-med rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris text-sm"
              />
            </div>
            <div className="flex space-x-3">
              <button
                type="button"
                onClick={() => {
                  setKeyName('')
                  setDescription('')
                  setKeyError('')
                  onCancel()
                }}
                disabled={isLoading}
                className="flex-1 px-4 py-2 text-sm font-medium text-on-base bg-surface border border-hl-med rounded-md hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isLoading || !keyName.trim()}
                className="flex-1 px-4 py-2 text-sm font-medium text-base bg-iris rounded-md hover:bg-iris/80 transition-colors focus:outline-none focus:ring-2 focus:ring-iris disabled:opacity-50"
              >
                {isLoading ? 'Creating...' : 'Create'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

export function SecretsManager({ serverId }: SecretsManagerProps) {
  const { data, isLoading, error } = useSecrets(serverId)
  const createMutation = useCreateSecret()
  const setValueMutation = useSetSecretValue()
  const deleteMutation = useDeleteSecret()

  const [showCreateModal, setShowCreateModal] = useState(false)
  const [selectedSecret, setSelectedSecret] = useState<Secret | null>(null)
  const [showSetValueModal, setShowSetValueModal] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<Secret | null>(null)
  const [mutationError, setMutationError] = useState<string | null>(null)

  const handleCreate = (keyName: string, description: string) => {
    setMutationError(null)
    createMutation.mutate(
      { server_id: serverId, key_name: keyName, description: description || undefined },
      {
        onSuccess: () => setShowCreateModal(false),
        onError: (err) => setMutationError(err instanceof Error ? err.message : 'Failed to create secret'),
      }
    )
  }

  const handleSetValue = (value: string) => {
    if (!selectedSecret) return
    setMutationError(null)
    setValueMutation.mutate(
      { server_id: serverId, key_name: selectedSecret.key_name, value },
      {
        onSuccess: () => {
          setShowSetValueModal(false)
          setSelectedSecret(null)
        },
        onError: (err) => setMutationError(err instanceof Error ? err.message : 'Failed to set value'),
      }
    )
  }

  const handleDelete = () => {
    if (!deleteTarget) return
    setMutationError(null)
    deleteMutation.mutate(
      { serverId, keyName: deleteTarget.key_name },
      {
        onSuccess: () => {
          setDeleteTarget(null)
        },
        onError: (err) => setMutationError(err instanceof Error ? err.message : 'Failed to delete secret'),
      }
    )
  }

  const secrets = data?.items || []

  return (
    <div className="bg-surface rounded-lg shadow p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-medium text-on-base">
          Secrets ({secrets.length})
        </h3>
        <button
          onClick={() => {
            setMutationError(null)
            setShowCreateModal(true)
          }}
          className="px-3 py-1.5 text-sm font-medium text-iris bg-iris/10 border border-iris rounded-md hover:bg-iris/20 transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
        >
          + Add Secret
        </button>
      </div>

      {mutationError && (
        <div className="mb-4 p-3 bg-love/10 border border-love/20 rounded-md">
          <p className="text-sm text-love">{mutationError}</p>
        </div>
      )}

      {isLoading ? (
        <div className="text-sm text-subtle py-4 text-center">
          Loading secrets...
        </div>
      ) : error ? (
        <div className="text-sm text-love py-4 text-center">
          Failed to load secrets
        </div>
      ) : secrets.length === 0 ? (
        <div className="text-center py-6">
          <svg
            className="w-10 h-10 text-muted mx-auto mb-3"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"
            />
          </svg>
          <p className="text-subtle text-sm mb-1">No secrets configured</p>
          <p className="text-xs text-muted">
            LLMs create secret placeholders via <code className="bg-hl-low px-1 rounded">mcpbox_create_server_secret</code>.
            <br />
            You can also add secrets manually above.
          </p>
        </div>
      ) : (
        <div className="divide-y divide-hl-med">
          {secrets.map((secret) => (
            <div
              key={secret.id}
              className="flex items-center justify-between py-3"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm font-medium text-on-base">
                    {secret.key_name}
                  </span>
                  <span
                    className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                      secret.has_value
                        ? 'bg-foam/10 text-foam'
                        : 'bg-gold/10 text-gold'
                    }`}
                  >
                    {secret.has_value ? 'Set' : 'Not Set'}
                  </span>
                </div>
                {secret.description && (
                  <p className="text-xs text-muted mt-0.5 truncate">
                    {secret.description}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2 ml-4">
                <button
                  onClick={() => {
                    setMutationError(null)
                    setSelectedSecret(secret)
                    setShowSetValueModal(true)
                  }}
                  className="px-2.5 py-1 text-xs font-medium text-on-base bg-surface border border-hl-med rounded-lg hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
                >
                  {secret.has_value ? 'Update' : 'Set Value'}
                </button>
                <button
                  onClick={() => {
                    setMutationError(null)
                    setDeleteTarget(secret)
                  }}
                  className="px-2.5 py-1 text-xs font-medium text-love bg-surface border border-love/20 rounded-lg hover:bg-love/10 transition-colors focus:outline-none focus:ring-2 focus:ring-love"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create Secret Modal */}
      <CreateSecretModal
        isOpen={showCreateModal}
        onSubmit={handleCreate}
        onCancel={() => setShowCreateModal(false)}
        isLoading={createMutation.isPending}
      />

      {/* Set Value Modal */}
      <SetValueModal
        isOpen={showSetValueModal}
        secret={selectedSecret}
        onSubmit={handleSetValue}
        onCancel={() => {
          setShowSetValueModal(false)
          setSelectedSecret(null)
        }}
        isLoading={setValueMutation.isPending}
      />

      {/* Delete Confirmation Modal */}
      <ConfirmModal
        isOpen={!!deleteTarget}
        title="Delete Secret"
        message={`Are you sure you want to delete the secret "${deleteTarget?.key_name}"? Tools using this secret will fail until a new value is provided.`}
        confirmLabel="Delete"
        destructive
        isLoading={deleteMutation.isPending}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}
