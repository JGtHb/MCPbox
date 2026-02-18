import { useState, useCallback } from 'react'
import { useTools, useUpdateToolEnabled, useRenameTool, useDeleteTool, useUpdateToolDescription, type ToolListItem } from '../../api/tools'
import { ToolExecutionLogs } from './ToolExecutionLogs'

const APPROVAL_COLORS: Record<string, string> = {
  draft: 'bg-overlay text-subtle',
  pending_review: 'bg-gold/10 text-gold',
  approved: 'bg-foam/10 text-foam',
  rejected: 'bg-love/10 text-love',
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
    className: 'bg-iris/10 text-iris',
  },
  mcp_passthrough: {
    label: 'External',
    className: 'bg-pine/10 text-pine',
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
      <div className="bg-surface rounded-lg shadow p-6">
        <div className="animate-pulse space-y-3">
          <div className="h-4 bg-hl-med rounded w-1/4" />
          <div className="h-10 bg-hl-med rounded" />
          <div className="h-10 bg-hl-med rounded" />
        </div>
      </div>
    )
  }

  if (!tools || tools.length === 0) {
    return (
      <div className="bg-surface rounded-lg shadow p-6">
        <div className="text-center py-8">
          <svg
            className="w-12 h-12 text-subtle mx-auto mb-3"
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
          <p className="text-subtle mb-1">No tools defined</p>
          <p className="text-xs text-muted">
            Create tools using the <code className="bg-hl-low px-1 rounded">mcpbox_create_tool</code> MCP command
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-surface rounded-lg shadow">
      <div className="px-6 py-4 border-b border-hl-med">
        <h3 className="text-lg font-medium text-on-base">
          Tools ({tools.length})
        </h3>
      </div>
      <ul className="divide-y divide-hl-med" role="list">
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-base/50" role="dialog" aria-modal="true" aria-labelledby="delete-tool-title" onClick={() => setDeleteTarget(null)}>
          <div
            className="bg-surface rounded-lg shadow-xl p-6 w-full max-w-md mx-4"
            onClick={e => e.stopPropagation()}
          >
            <h3 id="delete-tool-title" className="text-lg font-medium text-on-base mb-2">Delete Tool</h3>
            <p className="text-sm text-subtle mb-4">
              Are you sure you want to delete <span className="font-mono font-medium text-on-base">{deleteTarget.name}</span>? This action cannot be undone.
            </p>
            {deleteTool.isError && (
              <p className="mb-4 text-sm text-love">
                {deleteTool.error instanceof Error ? deleteTool.error.message : 'Delete failed'}
              </p>
            )}
            <div className="flex items-center gap-3 justify-end">
              <button
                type="button"
                onClick={() => setDeleteTarget(null)}
                className="px-4 py-2 text-sm font-medium text-subtle bg-surface border border-hl-med rounded-lg hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
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
                className="px-4 py-2 bg-love text-base text-sm font-medium rounded-lg hover:bg-love/80 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-love"
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
            aria-expanded={isExpanded}
            className="flex items-center gap-3 min-w-0 flex-1 text-left hover:bg-hl-low rounded px-1 py-1 -ml-1 transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
          >
            <span className={`px-2 py-0.5 text-xs font-medium rounded flex-shrink-0 ${badge.className}`}>
              {badge.label}
            </span>
            <div className="min-w-0 flex-1">
              <span className="text-on-base font-medium truncate block">{tool.name}</span>
              {tool.description ? (
                <span className="text-xs text-subtle truncate block">{tool.description}</span>
              ) : (
                <span className="text-xs text-muted italic truncate block">No description</span>
              )}
              {isExternal && tool.external_tool_name && tool.external_tool_name !== tool.name && (
                <span className="text-xs text-muted truncate block">
                  from: {tool.external_tool_name}
                </span>
              )}
            </div>
            <span
              className={`px-2 py-0.5 text-xs font-medium rounded flex-shrink-0 ${APPROVAL_COLORS[tool.approval_status] || 'bg-overlay text-subtle'}`}
            >
              {APPROVAL_LABELS[tool.approval_status] || tool.approval_status}
            </span>
            <svg
              className={`w-4 h-4 text-muted transition-transform flex-shrink-0 ${
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
              className="p-1 text-muted hover:text-subtle hover:bg-hl-low rounded transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
              aria-label="Rename tool"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
              </svg>
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); onDelete() }}
              className="p-1 text-muted hover:text-love hover:bg-love/10 rounded transition-colors focus:outline-none focus:ring-2 focus:ring-love"
              aria-label="Delete tool"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
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
              <div className="w-9 h-5 bg-hl-med peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-iris rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-surface after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-surface after:border-hl-med after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-iris peer-disabled:opacity-50" />
              <span className="ml-2 text-xs text-subtle">
                {!isApproved ? 'Not approved' : tool.enabled ? 'Enabled' : 'Disabled'}
              </span>
            </label>
          </div>
        </div>
      </div>
      {isExpanded && (
        <div className="px-6 pb-4">
          <div className="ml-2 pl-4 border-l-2 border-hl-med space-y-4">
            {/* Editable Description */}
            <ToolDescription toolId={tool.id} description={tool.description} />
            {/* Code Viewer */}
            {tool.python_code && (
              <ToolCodeViewer code={tool.python_code} />
            )}
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
        <label className="block text-xs font-medium text-on-base">
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
          className="w-full px-3 py-2 text-sm border border-hl-med rounded-lg bg-surface text-on-base placeholder-muted focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
          autoFocus
        />
        <div className="flex items-center gap-2">
          <button
            onClick={handleSave}
            disabled={updateDescription.isPending}
            className="px-2.5 py-1 text-xs font-medium bg-iris text-base rounded-lg hover:bg-iris/80 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
          >
            {updateDescription.isPending ? 'Saving...' : 'Save'}
          </button>
          <button
            onClick={handleCancel}
            className="px-2.5 py-1 text-xs font-medium text-subtle hover:text-on-base rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
          >
            Cancel
          </button>
          <span className="text-xs text-muted ml-auto">
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
          <label className="block text-xs font-medium text-on-base mb-1">
            Description
          </label>
          {description ? (
            <p className="text-sm text-subtle whitespace-pre-wrap">{description}</p>
          ) : (
            <p className="text-sm text-muted italic">
              No description. Add one to help LLMs understand when and how to use this tool.
            </p>
          )}
        </div>
        <button
          onClick={() => { setValue(description || ''); setIsEditing(true) }}
          className="p-1 text-muted hover:text-iris rounded opacity-0 group-hover/desc:opacity-100 transition-opacity mt-4 focus:outline-none focus:ring-2 focus:ring-iris focus:opacity-100"
          aria-label="Edit description"
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-base/50" role="dialog" aria-modal="true" aria-labelledby="rename-tool-title" onClick={onClose}>
      <div
        className="bg-surface rounded-lg shadow-xl p-6 w-full max-w-md mx-4"
        onClick={e => e.stopPropagation()}
      >
        <h3 id="rename-tool-title" className="text-lg font-medium text-on-base mb-4">Rename Tool</h3>
        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <label className="block text-sm font-medium text-on-base mb-1">
              Tool Name
            </label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value.toLowerCase())}
              pattern="^[a-z][a-z0-9_]*$"
              className="w-full px-3 py-2 border border-hl-med rounded-lg text-sm bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
              autoFocus
            />
            <p className="mt-1 text-xs text-subtle">
              Lowercase letters, numbers, and underscores. Must start with a letter.
            </p>
          </div>
          {isExternal && tool.external_tool_name && (
            <div className="mb-4 p-3 bg-pine/10 rounded-md">
              <p className="text-xs text-pine">
                External source name: <span className="font-mono font-medium">{tool.external_tool_name}</span>
              </p>
              <p className="text-xs text-pine mt-1">
                Renaming only changes the local name. Tool execution still uses the original external name.
              </p>
            </div>
          )}
          {error && (
            <p className="mb-4 text-sm text-love">{error}</p>
          )}
          <div className="flex items-center gap-3 justify-end">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-subtle bg-surface border border-hl-med rounded-lg hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!isValid || renameMutation.isPending}
              className="px-4 py-2 bg-iris text-base text-sm font-medium rounded-lg hover:bg-iris/80 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
            >
              {renameMutation.isPending ? 'Renaming...' : 'Rename'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}


// --- Tool Code Viewer ---

interface ToolCodeViewerProps {
  code: string
}

function ToolCodeViewer({ code }: ToolCodeViewerProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Fallback for older browsers
      const textarea = document.createElement('textarea')
      textarea.value = code
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }, [code])

  return (
    <div>
      <button
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        className="flex items-center gap-2 text-xs font-medium text-on-base hover:text-on-base transition-colors focus:outline-none focus:ring-2 focus:ring-iris rounded"
      >
        <svg
          className={`w-3 h-3 transition-transform ${isOpen ? 'rotate-90' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        Code
      </button>
      {isOpen && (
        <div className="mt-2 relative">
          <button
            onClick={handleCopy}
            className="absolute top-2 right-2 px-2 py-1 text-xs font-medium text-subtle hover:text-on-base bg-surface border border-hl-med rounded-md shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
            aria-label="Copy code"
          >
            {copied ? 'Copied!' : 'Copy'}
          </button>
          <pre className="font-mono text-sm bg-hl-low border border-hl-med rounded-md p-4 overflow-x-auto whitespace-pre-wrap text-on-base">
            {code}
          </pre>
        </div>
      )}
    </div>
  )
}
