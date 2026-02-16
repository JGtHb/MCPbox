import { useState } from 'react'
import { useTools, useUpdateToolEnabled, type ToolListItem } from '../../api/tools'
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

interface ToolsTabProps {
  serverId: string
}

export function ToolsTab({ serverId }: ToolsTabProps) {
  const { data: tools, isLoading } = useTools(serverId)
  const updateEnabled = useUpdateToolEnabled()
  const [expandedToolId, setExpandedToolId] = useState<string | null>(null)

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
            isUpdating={updateEnabled.isPending}
          />
        ))}
      </ul>
    </div>
  )
}

interface ToolRowProps {
  tool: ToolListItem
  serverId: string
  isExpanded: boolean
  onToggle: () => void
  onToggleEnabled: (enabled: boolean) => void
  isUpdating: boolean
}

function ToolRow({ tool, isExpanded, onToggle, onToggleEnabled, isUpdating }: ToolRowProps) {
  const isApproved = tool.approval_status === 'approved'

  return (
    <li>
      <div className="px-6 py-3">
        <div className="flex items-center justify-between">
          <button
            onClick={onToggle}
            className="flex items-center gap-3 min-w-0 flex-1 text-left hover:bg-gray-50 dark:hover:bg-gray-700 rounded px-1 py-1 -ml-1"
          >
            <span className="px-2 py-0.5 text-xs font-medium rounded bg-purple-100 dark:bg-purple-900/50 text-purple-800 dark:text-purple-300">
              Python
            </span>
            <span className="text-gray-900 dark:text-white font-medium truncate">{tool.name}</span>
            <span
              className={`px-2 py-0.5 text-xs font-medium rounded ${APPROVAL_COLORS[tool.approval_status] || 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300'}`}
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
            {tool.description && (
              <span className="text-xs text-gray-400 dark:text-gray-500 truncate max-w-[200px] hidden lg:inline" title={tool.description}>
                {tool.description}
              </span>
            )}
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
          <div className="ml-2 pl-4 border-l-2 border-gray-200 dark:border-gray-700">
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
