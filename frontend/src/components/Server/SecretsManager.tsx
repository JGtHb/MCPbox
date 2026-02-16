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
        className="fixed inset-0 bg-gray-500 bg-opacity-75"
        aria-hidden="true"
        onClick={onCancel}
      />
      <div className="fixed inset-0 flex items-center justify-center p-4" onClick={onCancel}>
        <div
          className="relative bg-white rounded-lg shadow-xl max-w-md w-full p-6"
          onClick={(e) => e.stopPropagation()}
        >
          <h3 id="set-value-title" className="text-lg font-medium text-gray-900 mb-1">
            Set Secret Value
          </h3>
          <p className="text-sm text-gray-500 mb-4">
            Set the value for <span className="font-mono font-medium">{secret.key_name}</span>
          </p>
          {secret.description && (
            <p className="text-xs text-gray-400 mb-4">{secret.description}</p>
          )}

          <form onSubmit={handleSubmit}>
            <div className="mb-4">
              <label htmlFor="secret-value" className="block text-sm font-medium text-gray-700 mb-1">
                Value
              </label>
              <input
                id="secret-value"
                type="password"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder="Enter secret value..."
                className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 font-mono text-sm"
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
                className="flex-1 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isLoading || !value.trim()}
                className="flex-1 px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50"
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
        className="fixed inset-0 bg-gray-500 bg-opacity-75"
        aria-hidden="true"
        onClick={onCancel}
      />
      <div className="fixed inset-0 flex items-center justify-center p-4" onClick={onCancel}>
        <div
          className="relative bg-white rounded-lg shadow-xl max-w-md w-full p-6"
          onClick={(e) => e.stopPropagation()}
        >
          <h3 id="create-secret-title" className="text-lg font-medium text-gray-900 mb-4">
            Create Secret
          </h3>

          <form onSubmit={handleSubmit}>
            <div className="mb-4">
              <label htmlFor="key-name" className="block text-sm font-medium text-gray-700 mb-1">
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
                className={`w-full px-3 py-2 border rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 font-mono text-sm ${
                  keyError ? 'border-red-300' : 'border-gray-300'
                }`}
                autoFocus
                autoComplete="off"
              />
              {keyError && (
                <p className="mt-1 text-xs text-red-600">{keyError}</p>
              )}
              <p className="mt-1 text-xs text-gray-400">
                Uppercase letters, numbers, underscores. Access in tools via{' '}
                <code className="bg-gray-100 px-1 rounded">secrets[&quot;KEY_NAME&quot;]</code>
              </p>
            </div>
            <div className="mb-4">
              <label htmlFor="description" className="block text-sm font-medium text-gray-700 mb-1">
                Description <span className="text-gray-400">(optional)</span>
              </label>
              <input
                id="description"
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="e.g. TheirStack API key for job search"
                className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
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
                className="flex-1 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isLoading || !keyName.trim()}
                className="flex-1 px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50"
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
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-medium text-gray-900">
          Secrets ({secrets.length})
        </h3>
        <button
          onClick={() => {
            setMutationError(null)
            setShowCreateModal(true)
          }}
          className="px-3 py-1.5 text-sm font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded-md hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
        >
          + Add Secret
        </button>
      </div>

      {mutationError && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md">
          <p className="text-sm text-red-700">{mutationError}</p>
        </div>
      )}

      {isLoading ? (
        <div className="text-sm text-gray-500 py-4 text-center">
          Loading secrets...
        </div>
      ) : error ? (
        <div className="text-sm text-red-500 py-4 text-center">
          Failed to load secrets
        </div>
      ) : secrets.length === 0 ? (
        <div className="text-center py-6">
          <svg
            className="w-10 h-10 text-gray-300 mx-auto mb-3"
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
          <p className="text-gray-500 text-sm mb-1">No secrets configured</p>
          <p className="text-xs text-gray-400">
            LLMs create secret placeholders via <code className="bg-gray-100 px-1 rounded">mcpbox_create_server_secret</code>.
            <br />
            You can also add secrets manually above.
          </p>
        </div>
      ) : (
        <div className="divide-y divide-gray-100">
          {secrets.map((secret) => (
            <div
              key={secret.id}
              className="flex items-center justify-between py-3"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm font-medium text-gray-900">
                    {secret.key_name}
                  </span>
                  <span
                    className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                      secret.has_value
                        ? 'bg-green-100 text-green-700'
                        : 'bg-yellow-100 text-yellow-700'
                    }`}
                  >
                    {secret.has_value ? 'Set' : 'Not Set'}
                  </span>
                </div>
                {secret.description && (
                  <p className="text-xs text-gray-400 mt-0.5 truncate">
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
                  className="px-2.5 py-1 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-blue-500"
                >
                  {secret.has_value ? 'Update' : 'Set Value'}
                </button>
                <button
                  onClick={() => {
                    setMutationError(null)
                    setDeleteTarget(secret)
                  }}
                  className="px-2.5 py-1 text-xs font-medium text-red-700 bg-white border border-red-200 rounded hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-red-500"
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
