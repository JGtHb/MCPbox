import { useState } from 'react'
import { useTools, useUpdateToolEnabled, useRenameTool, useDeleteTool, useUpdateToolDescription, type ToolListItem } from '../../api/tools'
import { ToolExecutionLogs } from './ToolExecutionLogs'

const APPROVAL_COLORS: Record<string, string> = {
  draft: 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300',
  pending_review: 'bg-yellow-100 dark:bg-yellow-900/50 text-yellow-800 dark:text-yellow-300',
  approved: 'bg-green-100 dark:bg-green-900/50 text-green-700 dark:text-green-300',
  rejected: 'bg-red-100 dark:bg-red-900/50 text-red-700 dark:text-red-300',
}

const APPROVAL_LABELS: Record<string, string> = {
  draft: 'Draft',
  pending_review: 'Pending Review',
  approved: 'Approved',
  rejected: 'Rejected',
}

const TOOL_TYPE_BADGE: Record<string, { label: string; className: string }> = {
  python_code: {
    label: 'Python',
    className: 'bg-purple-100 dark:bg-purple-900/50 text-purple-800 dark:text-purple-300',
  },
  mcp_passthrough: {
    label: 'External',
    className: 'bg-blue-100 dark:bg-blue-900/50 text-blue-800 dark:text-blue-300',
  },
}

interface ToolsTabProps {
  serverId: string
}

export function ToolsTab({ serverId }: ToolsTabProps) {
  const { data: tools, isLoading } = useTools(serverId)
  const updateEnabled = useUpdateToolEnabled()
  const deleteTool = useDeleteTool()
  const [expandedToolId, setExpandedToolId] = useState<string | null>(null)
  const [renamingTool, setRenamingTool] = useState<ToolListItem | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ToolListItem | null>(null)

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
        <div className="animate-pulse space-y-3">
          <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/4" />
          <div className="h-10 bg-gray-200 dark:bg-gray-700 rounded" />
          <div className="h-10 bg-gray-200 dark:bg-gray-700 rounded" />
        </div>
      </div>
    )
  }

  if (!tools || tools.length === 0) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
        <div className="text-center py-8">
          <svg
            className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-3"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
            />
          </svg>
          <p className="text-gray-500 dark:text-gray-400 mb-1">No tools defined</p>
          <p className="text-xs text-gray-400 dark:text-gray-500">
            Create tools using the <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">mcpbox_create_tool</code> MCP command
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow">
      <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
        <h3 className="text-lg font-medium text-gray-900 dark:text-white">
          Tools ({tools.length})
        </h3>
      </div>
      <ul className="divide-y divide-gray-200 dark:divide-gray-700" role="list">
        {tools.map((tool) => (
          <ToolRow
            key={tool.id}
            tool={tool}
            serverId={serverId}
            isExpanded={expandedToolId === tool.id}
            onToggle={() =>
              setExpandedToolId(expandedToolId === tool.id ? null : tool.id)
            }
            onToggleEnabled={(enabled) =>
              updateEnabled.mutate({ toolId: tool.id, enabled })
            }
            onRename={() => setRenamingTool(tool)}
            onDelete={() => setDeleteTarget(tool)}
            isUpdating={updateEnabled.isPending}
          />
        ))}
      </ul>

      {/* Rename Tool Modal */}
      {renamingTool && (
        <RenameToolModal
          tool={renamingTool}
          onClose={() => setRenamingTool(null)}
        />
      )}

      {/* Delete Tool Confirm Modal */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setDeleteTarget(null)}>
          <div
            className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-md mx-4"
            onClick={e => e.stopPropagation()}
          >
            <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">Delete Tool</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
              Are you sure you want to delete <span className="font-mono font-medium text-gray-900 dark:text-white">{deleteTarget.name}</span>? This action cannot be undone.
            </p>
            {deleteTool.isError && (
              <p className="mb-4 text-sm text-red-600 dark:text-red-400">
                {deleteTool.error instanceof Error ? deleteTool.error.message : 'Delete failed'}
              </p>
            )}
            <div className="flex items-center gap-3 justify-end">
              <button
                type="button"
                onClick={() => setDeleteTarget(null)}
                className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={deleteTool.isPending}
                onClick={() => {
                  deleteTool.mutate(deleteTarget.id, {
                    onSuccess: () => setDeleteTarget(null),
                  })
                }}
                className="px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-md hover:bg-red-700 disabled:opacity-50"
              >
                {deleteTool.isPending ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

interface ToolRowProps {
  tool: ToolListItem
  serverId: string
  isExpanded: boolean
  onToggle: () => void
  onToggleEnabled: (enabled: boolean) => void
  onRename: () => void
  onDelete: () => void
  isUpdating: boolean
}

function ToolRow({ tool, isExpanded, onToggle, onToggleEnabled, onRename, onDelete, isUpdating }: ToolRowProps) {
  const isApproved = tool.approval_status === 'approved'
  const badge = TOOL_TYPE_BADGE[tool.tool_type] || TOOL_TYPE_BADGE.python_code
  const isExternal = tool.tool_type === 'mcp_passthrough'

  return (
    <li>
      <div className="px-6 py-3">
        <div className="flex items-center justify-between">
          <button
            onClick={onToggle}
            className="flex items-center gap-3 min-w-0 flex-1 text-left hover:bg-gray-50 dark:hover:bg-gray-700 rounded px-1 py-1 -ml-1"
          >
            <span className={`px-2 py-0.5 text-xs font-medium rounded flex-shrink-0 ${badge.className}`}>
              {badge.label}
            </span>
            <div className="min-w-0 flex-1">
              <span className="text-gray-900 dark:text-white font-medium truncate block">{tool.name}</span>
              {tool.description ? (
                <span className="text-xs text-gray-500 dark:text-gray-400 truncate block">{tool.description}</span>
              ) : (
                <span className="text-xs text-gray-400 dark:text-gray-500 italic truncate block">No description</span>
              )}
              {isExternal && tool.external_tool_name && tool.external_tool_name !== tool.name && (
                <span className="text-xs text-gray-400 dark:text-gray-500 truncate block">
                  from: {tool.external_tool_name}
                </span>
              )}
            </div>
            <span
              className={`px-2 py-0.5 text-xs font-medium rounded flex-shrink-0 ${APPROVAL_COLORS[tool.approval_status] || 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300'}`}
            >
              {APPROVAL_LABELS[tool.approval_status] || tool.approval_status}
            </span>
            <svg
              className={`w-4 h-4 text-gray-400 dark:text-gray-500 transition-transform flex-shrink-0 ${
                isExpanded ? 'rotate-180' : ''
              }`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M19 9l-7 7-7-7"
              />
            </svg>
          </button>
          <div className="flex items-center gap-3 ml-3">
            <button
              onClick={(e) => { e.stopPropagation(); onRename() }}
              className="p-1 text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300 rounded"
              title="Rename tool"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
              </svg>
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); onDelete() }}
              className="p-1 text-gray-400 hover:text-red-500 dark:text-gray-500 dark:hover:text-red-400 rounded"
              title="Delete tool"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
            <label
              className={`relative inline-flex items-center ${isApproved ? 'cursor-pointer' : 'cursor-not-allowed'}`}
              title={isApproved ? undefined : 'Tool must be approved before it can be enabled'}
            >
              <input
                type="checkbox"
                checked={tool.enabled}
                onChange={(e) => onToggleEnabled(e.target.checked)}
                disabled={isUpdating || !isApproved}
                className="sr-only peer"
              />
              <div className="w-9 h-5 bg-gray-200 dark:bg-gray-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-indigo-300 dark:peer-focus:ring-indigo-600 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-600 peer-disabled:opacity-50" />
              <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">
                {!isApproved ? 'Not approved' : tool.enabled ? 'Enabled' : 'Disabled'}
              </span>
            </label>
          </div>
        </div>
      </div>
      {isExpanded && (
        <div className="px-6 pb-4">
          <div className="ml-2 pl-4 border-l-2 border-gray-200 dark:border-gray-700 space-y-4">
            {/* Editable Description */}
            <ToolDescription toolId={tool.id} description={tool.description} />
            {/* Execution Logs */}
            <ToolExecutionLogs
              toolId={tool.id}
              toolName={tool.name}
            />
          </div>
        </div>
      )}
    </li>
  )
}


// --- Inline Editable Description ---

interface ToolDescriptionProps {
  toolId: string
  description: string | null
}

function ToolDescription({ toolId, description }: ToolDescriptionProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [value, setValue] = useState(description || '')
  const updateDescription = useUpdateToolDescription()

  const handleSave = async () => {
    const trimmed = value.trim()
    const newDesc = trimmed || null
    if (newDesc !== description) {
      try {
        await updateDescription.mutateAsync({ toolId, description: newDesc })
      } catch {
        // Revert on error
        setValue(description || '')
      }
    }
    setIsEditing(false)
  }

  const handleCancel = () => {
    setValue(description || '')
    setIsEditing(false)
  }

  if (isEditing) {
    return (
      <div className="space-y-2">
        <label className="block text-xs font-medium text-gray-700 dark:text-gray-300">
          Description
        </label>
        <textarea
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Escape') handleCancel()
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSave()
          }}
          rows={3}
          maxLength={2000}
          placeholder="Describe what this tool does, when to use it, and what it returns..."
          className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-indigo-500 focus:border-indigo-500"
          autoFocus
        />
        <div className="flex items-center gap-2">
          <button
            onClick={handleSave}
            disabled={updateDescription.isPending}
            className="px-3 py-1 text-xs font-medium bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            {updateDescription.isPending ? 'Saving...' : 'Save'}
          </button>
          <button
            onClick={handleCancel}
            className="px-3 py-1 text-xs font-medium text-gray-600 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200"
          >
            Cancel
          </button>
          <span className="text-xs text-gray-400 dark:text-gray-500 ml-auto">
            {value.length}/2000
          </span>
        </div>
      </div>
    )
  }

  return (
    <div className="group/desc">
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
            Description
          </label>
          {description ? (
            <p className="text-sm text-gray-600 dark:text-gray-400 whitespace-pre-wrap">{description}</p>
          ) : (
            <p className="text-sm text-gray-400 dark:text-gray-500 italic">
              No description. Add one to help LLMs understand when and how to use this tool.
            </p>
          )}
        </div>
        <button
          onClick={() => { setValue(description || ''); setIsEditing(true) }}
          className="p-1 text-gray-400 hover:text-indigo-600 dark:text-gray-500 dark:hover:text-indigo-400 rounded opacity-0 group-hover/desc:opacity-100 transition-opacity mt-4"
          title="Edit description"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
          </svg>
        </button>
      </div>
    </div>
  )
}


// --- Rename Tool Modal ---

interface RenameToolModalProps {
  tool: ToolListItem
  onClose: () => void
}

function RenameToolModal({ tool, onClose }: RenameToolModalProps) {
  const [name, setName] = useState(tool.name)
  const [error, setError] = useState<string | null>(null)
  const renameMutation = useRenameTool()
  const isExternal = tool.tool_type === 'mcp_passthrough'

  const isValid = /^[a-z][a-z0-9_]*$/.test(name) && name !== tool.name

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!isValid) return
    setError(null)
    try {
      await renameMutation.mutateAsync({ toolId: tool.id, name })
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Rename failed')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-md mx-4"
        onClick={e => e.stopPropagation()}
      >
        <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Rename Tool</h3>
        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Tool Name
            </label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value.toLowerCase())}
              pattern="^[a-z][a-z0-9_]*$"
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-indigo-500 focus:border-indigo-500"
              autoFocus
            />
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              Lowercase letters, numbers, and underscores. Must start with a letter.
            </p>
          </div>
          {isExternal && tool.external_tool_name && (
            <div className="mb-4 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-md">
              <p className="text-xs text-blue-700 dark:text-blue-300">
                External source name: <span className="font-mono font-medium">{tool.external_tool_name}</span>
              </p>
              <p className="text-xs text-blue-600 dark:text-blue-400 mt-1">
                Renaming only changes the local name. Tool execution still uses the original external name.
              </p>
            </div>
          )}
          {error && (
            <p className="mb-4 text-sm text-red-600 dark:text-red-400">{error}</p>
          )}
          <div className="flex items-center gap-3 justify-end">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!isValid || renameMutation.isPending}
              className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700 disabled:opacity-50"
            >
              {renameMutation.isPending ? 'Renaming...' : 'Rename'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
