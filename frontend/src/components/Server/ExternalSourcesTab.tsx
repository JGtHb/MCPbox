import { useState, useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  useExternalSources,
  useCreateExternalSource,
  useDeleteExternalSource,
  useRenameSource,
  useDiscoverTools,
  useImportTools,
  useCachedTools,
  useStartOAuth,
  externalSourceKeys,
  type ExternalMCPSource,
  type ExternalMCPSourceCreateInput,
  type DiscoveredTool,
} from '../../api/externalMcpSources'
import { ConfirmModal } from '../ui'

interface ExternalSourcesTabProps {
  serverId: string
  onImportSuccess?: (count: number) => void
}

const STATUS_COLORS: Record<string, string> = {
  active: 'bg-green-100 text-green-800',
  error: 'bg-red-100 text-red-800',
  disabled: 'bg-gray-100 text-gray-800',
}

function formatRelativeTime(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export function ExternalSourcesTab({ serverId, onImportSuccess }: ExternalSourcesTabProps) {
  const { data: sources, isLoading } = useExternalSources(serverId)
  const [showAddForm, setShowAddForm] = useState(false)
  const [expandedSourceId, setExpandedSourceId] = useState<string | null>(null)
  const [selectedTools, setSelectedTools] = useState<Set<string>>(new Set())
  const [oauthError, setOauthError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ExternalMCPSource | null>(null)

  const [renamingSourceId, setRenamingSourceId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')

  const queryClient = useQueryClient()
  const createSource = useCreateExternalSource(serverId)
  const deleteSource = useDeleteExternalSource(serverId)
  const renameSource = useRenameSource(serverId)
  const discoverTools = useDiscoverTools(serverId)
  const importToolsMutation = useImportTools(serverId)
  const startOAuth = useStartOAuth(serverId)

  // Fetch cached tools for the expanded source
  const { data: cachedToolsData, isLoading: isLoadingCached } = useCachedTools(expandedSourceId)
  const discoveredTools: DiscoveredTool[] = cachedToolsData?.tools || []

  const handleAddSource = async (data: ExternalMCPSourceCreateInput) => {
    await createSource.mutateAsync(data)
    setShowAddForm(false)
  }

  const handleDiscover = async (sourceId: string) => {
    setExpandedSourceId(sourceId)
    setSelectedTools(new Set())
    try {
      const result = await discoverTools.mutateAsync(sourceId)
      // Pre-select tools that haven't been imported yet
      setSelectedTools(new Set(result.tools.filter(t => !t.already_imported).map(t => t.name)))
    } catch {
      // Error handled by mutation
    }
  }

  const handleExpand = (sourceId: string) => {
    if (expandedSourceId === sourceId) {
      setExpandedSourceId(null)
      setSelectedTools(new Set())
    } else {
      setExpandedSourceId(sourceId)
      // Pre-select non-imported tools from cache
      const cached = queryClient.getQueryData<{ tools: DiscoveredTool[] }>(
        externalSourceKeys.discover(sourceId)
      )
      if (cached?.tools) {
        setSelectedTools(new Set(cached.tools.filter(t => !t.already_imported).map(t => t.name)))
      } else {
        setSelectedTools(new Set())
      }
    }
  }

  const handleImport = async () => {
    if (!expandedSourceId || selectedTools.size === 0) return
    try {
      const result = await importToolsMutation.mutateAsync({
        sourceId: expandedSourceId,
        toolNames: Array.from(selectedTools),
      })
      setSelectedTools(new Set())
      // Notify parent to switch to tools tab on success
      if (result.total_created > 0 && onImportSuccess) {
        onImportSuccess(result.total_created)
      }
    } catch {
      // Error handled by mutation
    }
  }

  const handleOAuthAuthenticate = useCallback(async (source: ExternalMCPSource) => {
    setOauthError(null)
    const callbackUrl = `${window.location.origin}/oauth/callback`

    try {
      const result = await startOAuth.mutateAsync({
        sourceId: source.id,
        callbackUrl,
      })

      // Open popup for OAuth
      const popup = window.open(
        result.auth_url,
        'mcpbox-oauth',
        'width=600,height=700,menubar=no,toolbar=no,location=yes,status=yes'
      )

      if (!popup) {
        setOauthError('Popup blocked. Please allow popups for this site.')
        return
      }

      // Poll for popup close
      const pollInterval = setInterval(() => {
        if (popup.closed) {
          clearInterval(pollInterval)
          // Refresh sources to check if auth succeeded
          queryClient.invalidateQueries({
            queryKey: externalSourceKeys.list(serverId),
          })
        }
      }, 500)
    } catch (err) {
      setOauthError(err instanceof Error ? err.message : 'OAuth flow failed')
    }
  }, [startOAuth, queryClient, serverId])

  const handleDelete = async () => {
    if (!deleteTarget) return
    try {
      await deleteSource.mutateAsync(deleteTarget.id)
      if (expandedSourceId === deleteTarget.id) {
        setExpandedSourceId(null)
      }
    } finally {
      setDeleteTarget(null)
    }
  }

  const toggleToolSelection = (name: string) => {
    setSelectedTools(prev => {
      const next = new Set(prev)
      if (next.has(name)) {
        next.delete(name)
      } else {
        next.add(name)
      }
      return next
    })
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="animate-pulse bg-gray-100 h-24 rounded-lg" />
      </div>
    )
  }

  const isExpanded = (sourceId: string) => expandedSourceId === sourceId
  const isDiscovering = (sourceId: string) =>
    discoverTools.isPending && discoverTools.variables === sourceId

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-medium text-gray-900">External MCP Sources</h3>
          <p className="mt-1 text-sm text-gray-500">
            Connect external MCP servers and import their tools into this server.
          </p>
        </div>
        <button
          onClick={() => setShowAddForm(true)}
          className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700"
        >
          Add Source
        </button>
      </div>

      {/* Global OAuth Error */}
      {oauthError && (
        <div className="p-3 bg-red-50 rounded-md">
          <p className="text-sm text-red-700">{oauthError}</p>
        </div>
      )}

      {/* Add Source Form */}
      {showAddForm && (
        <AddSourceForm
          onSubmit={handleAddSource}
          onCancel={() => setShowAddForm(false)}
          isLoading={createSource.isPending}
          error={createSource.error?.message}
        />
      )}

      {/* Sources List */}
      {sources && sources.length > 0 ? (
        <div className="space-y-4">
          {sources.map(source => (
            <div key={source.id} className="border border-gray-200 rounded-lg p-4">
              <div className="flex items-start justify-between">
                <div
                  className="flex-1 cursor-pointer"
                  onClick={() => source.tool_count > 0 ? handleExpand(source.id) : undefined}
                >
                  <div className="flex items-center gap-3">
                    {/* Expand/collapse arrow for sources with cached tools */}
                    {source.tool_count > 0 && (
                      <svg
                        className={`h-4 w-4 text-gray-400 transition-transform ${isExpanded(source.id) ? 'rotate-90' : ''}`}
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    )}
                    {renamingSourceId === source.id ? (
                      <form
                        className="flex items-center gap-1"
                        onSubmit={async (e) => {
                          e.preventDefault()
                          e.stopPropagation()
                          if (renameValue.trim() && renameValue.trim() !== source.name) {
                            await renameSource.mutateAsync({ sourceId: source.id, name: renameValue.trim() })
                          }
                          setRenamingSourceId(null)
                        }}
                        onClick={e => e.stopPropagation()}
                      >
                        <input
                          type="text"
                          value={renameValue}
                          onChange={e => setRenameValue(e.target.value)}
                          onKeyDown={e => { if (e.key === 'Escape') setRenamingSourceId(null) }}
                          className="px-2 py-0.5 text-sm font-medium border border-indigo-300 rounded focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 w-48"
                          autoFocus
                        />
                        <button type="submit" className="text-xs text-indigo-600 hover:text-indigo-800 font-medium">Save</button>
                        <button type="button" onClick={() => setRenamingSourceId(null)} className="text-xs text-gray-500 hover:text-gray-700">Cancel</button>
                      </form>
                    ) : (
                      <div className="flex items-center gap-1.5 group/name">
                        <h4 className="text-sm font-medium text-gray-900">{source.name}</h4>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            setRenamingSourceId(source.id)
                            setRenameValue(source.name)
                          }}
                          className="p-0.5 text-gray-300 hover:text-gray-500 opacity-0 group-hover/name:opacity-100 transition-opacity"
                          title="Rename source"
                        >
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                          </svg>
                        </button>
                      </div>
                    )}
                    <span className={`px-2 py-0.5 text-xs rounded-full ${STATUS_COLORS[source.status] || STATUS_COLORS.disabled}`}>
                      {source.status}
                    </span>
                    <span className="text-xs text-gray-500">
                      {source.transport_type === 'streamable_http' ? 'HTTP' : 'SSE'}
                    </span>
                    {source.auth_type === 'oauth' && (
                      <span className={`px-2 py-0.5 text-xs rounded-full ${
                        source.oauth_authenticated
                          ? 'bg-green-100 text-green-800'
                          : 'bg-yellow-100 text-yellow-800'
                      }`}>
                        {source.oauth_authenticated ? 'Authenticated' : 'Needs Auth'}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-sm text-gray-500 font-mono truncate">{source.url}</p>
                  <div className="mt-2 flex items-center gap-4 text-xs text-gray-500">
                    <span>Auth: {source.auth_type}</span>
                    {source.auth_type === 'oauth' && source.oauth_issuer && (
                      <span className="truncate max-w-xs" title={source.oauth_issuer}>
                        Issuer: {source.oauth_issuer}
                      </span>
                    )}
                    {source.auth_secret_name && (
                      <span>Secret: {source.auth_secret_name}</span>
                    )}
                    {source.tool_count > 0 ? (
                      <span>{source.tool_count} tools available</span>
                    ) : (
                      <span className="text-gray-400">Not yet discovered</span>
                    )}
                    {source.last_discovered_at && (
                      <span title={new Date(source.last_discovered_at).toLocaleString()}>
                        Discovered {formatRelativeTime(source.last_discovered_at)}
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2 ml-4">
                  {/* OAuth Authenticate button */}
                  {source.auth_type === 'oauth' && !source.oauth_authenticated && (
                    <button
                      onClick={() => handleOAuthAuthenticate(source)}
                      disabled={startOAuth.isPending}
                      className="px-3 py-1.5 text-sm font-medium text-amber-700 bg-amber-50 rounded-md hover:bg-amber-100 disabled:opacity-50"
                    >
                      {startOAuth.isPending ? 'Starting...' : 'Authenticate'}
                    </button>
                  )}
                  {/* Re-authenticate button for already-authenticated OAuth sources */}
                  {source.auth_type === 'oauth' && source.oauth_authenticated && (
                    <button
                      onClick={() => handleOAuthAuthenticate(source)}
                      disabled={startOAuth.isPending}
                      className="px-3 py-1.5 text-sm font-medium text-gray-600 bg-gray-50 rounded-md hover:bg-gray-100 disabled:opacity-50"
                      title="Re-authenticate if the token has expired"
                    >
                      Re-auth
                    </button>
                  )}
                  {/* Discover / Refresh button */}
                  {source.last_discovered_at ? (
                    <button
                      onClick={() => handleDiscover(source.id)}
                      disabled={isDiscovering(source.id)}
                      className="px-3 py-1.5 text-sm font-medium text-indigo-600 bg-indigo-50 rounded-md hover:bg-indigo-100 disabled:opacity-50 flex items-center gap-1.5"
                      title="Re-scan the external server for tool changes"
                    >
                      <svg className={`h-3.5 w-3.5 ${isDiscovering(source.id) ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                      </svg>
                      {isDiscovering(source.id) ? 'Refreshing...' : 'Refresh'}
                    </button>
                  ) : (
                    <button
                      onClick={() => handleDiscover(source.id)}
                      disabled={isDiscovering(source.id)}
                      className="px-3 py-1.5 text-sm font-medium text-indigo-600 bg-indigo-50 rounded-md hover:bg-indigo-100 disabled:opacity-50"
                    >
                      {isDiscovering(source.id) ? 'Discovering...' : 'Discover Tools'}
                    </button>
                  )}
                  <button
                    onClick={() => setDeleteTarget(source)}
                    disabled={deleteSource.isPending}
                    className="px-3 py-1.5 text-sm font-medium text-red-600 bg-red-50 rounded-md hover:bg-red-100 disabled:opacity-50"
                  >
                    Delete
                  </button>
                </div>
              </div>

              {/* Expanded Tool List (from cache or fresh discovery) */}
              {isExpanded(source.id) && (
                <div className="mt-4 border-t border-gray-200 pt-4">
                  {isLoadingCached ? (
                    <div className="py-4 text-center text-sm text-gray-500">Loading tools...</div>
                  ) : discoveredTools.length > 0 ? (
                    <>
                      {/* Conflict summary banner */}
                      {discoveredTools.some(t => t.already_imported) && (
                        <div className="mb-3 p-2 bg-yellow-50 border border-yellow-200 rounded-md">
                          <p className="text-xs text-yellow-800">
                            {discoveredTools.filter(t => t.already_imported).length} tool(s) have name conflicts
                            with existing tools in this server and were deselected.
                            You can still select them to re-import under the same name.
                          </p>
                        </div>
                      )}
                      <div className="flex items-center justify-between mb-3">
                        <h5 className="text-sm font-medium text-gray-700">
                          Available Tools ({discoveredTools.length})
                        </h5>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => setSelectedTools(new Set(discoveredTools.map(t => t.name)))}
                            className="text-xs text-indigo-600 hover:text-indigo-800"
                          >
                            Select All
                          </button>
                          <button
                            onClick={() => setSelectedTools(new Set())}
                            className="text-xs text-gray-500 hover:text-gray-700"
                          >
                            Deselect All
                          </button>
                        </div>
                      </div>
                      <div className="space-y-2 max-h-64 overflow-y-auto">
                        {discoveredTools.map(tool => (
                          <label
                            key={tool.name}
                            className="flex items-start gap-3 p-2 rounded hover:bg-gray-50 cursor-pointer"
                          >
                            <input
                              type="checkbox"
                              checked={selectedTools.has(tool.name)}
                              onChange={() => toggleToolSelection(tool.name)}
                              className="mt-0.5 h-4 w-4 rounded border-gray-300 text-indigo-600"
                            />
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-medium text-gray-900">{tool.name}</span>
                                {tool.already_imported && (
                                  <span className="px-1.5 py-0.5 text-xs bg-yellow-100 text-yellow-800 rounded">
                                    Name conflict
                                  </span>
                                )}
                              </div>
                              {tool.description && (
                                <p className="text-xs text-gray-500 truncate">{tool.description}</p>
                              )}
                            </div>
                          </label>
                        ))}
                      </div>
                      <div className="mt-3 flex items-center gap-3">
                        <button
                          onClick={handleImport}
                          disabled={selectedTools.size === 0 || importToolsMutation.isPending}
                          className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700 disabled:opacity-50"
                        >
                          {importToolsMutation.isPending
                            ? 'Importing...'
                            : `Import ${selectedTools.size} Tool${selectedTools.size !== 1 ? 's' : ''}`}
                        </button>
                        <button
                          onClick={() => {
                            setExpandedSourceId(null)
                            setSelectedTools(new Set())
                          }}
                          className="px-4 py-2 text-sm font-medium text-gray-700 hover:text-gray-900"
                        >
                          Collapse
                        </button>
                        {importToolsMutation.isSuccess && importToolsMutation.data && (
                          <span className="text-sm">
                            {importToolsMutation.data.total_created > 0 && (
                              <span className="text-green-600">
                                {importToolsMutation.data.total_created} imported successfully.
                              </span>
                            )}
                            {importToolsMutation.data.total_skipped > 0 && (
                              <span className="text-yellow-600 ml-1">
                                {importToolsMutation.data.total_skipped} skipped (already exist).
                              </span>
                            )}
                            {importToolsMutation.data.total_created === 0 && importToolsMutation.data.total_skipped === 0 && (
                              <span className="text-gray-500">No tools to import.</span>
                            )}
                          </span>
                        )}
                      </div>
                    </>
                  ) : (
                    <div className="py-4 text-center text-sm text-gray-500">
                      No cached tools. Click Refresh to scan the external server.
                    </div>
                  )}
                </div>
              )}

              {/* Discovery Error */}
              {isDiscovering(source.id) && discoverTools.isError && (
                <div className="mt-4 p-3 bg-red-50 rounded-md">
                  <p className="text-sm text-red-700">
                    Discovery failed: {discoverTools.error?.message || 'Unknown error'}
                  </p>
                </div>
              )}
              {/* Show error also when not currently discovering but last attempt failed */}
              {!isDiscovering(source.id) && expandedSourceId === source.id && discoverTools.isError && discoverTools.variables === source.id && (
                <div className="mt-4 p-3 bg-red-50 rounded-md">
                  <p className="text-sm text-red-700">
                    Discovery failed: {discoverTools.error?.message || 'Unknown error'}
                  </p>
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-12 bg-gray-50 rounded-lg border-2 border-dashed border-gray-300">
          <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m9.86-2.556a4.5 4.5 0 00-6.364-6.364L4.5 8.243a4.5 4.5 0 001.242 7.244" />
          </svg>
          <h3 className="mt-2 text-sm font-medium text-gray-900">No external sources</h3>
          <p className="mt-1 text-sm text-gray-500">
            Connect an external MCP server to import its tools.
          </p>
          <button
            onClick={() => setShowAddForm(true)}
            className="mt-4 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700"
          >
            Add Source
          </button>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      <ConfirmModal
        isOpen={!!deleteTarget}
        title="Delete External Source"
        message={`Delete "${deleteTarget?.name}"? Associated tools will keep working but cannot be re-synced.`}
        confirmLabel="Delete"
        destructive
        isLoading={deleteSource.isPending}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}

// --- Add Source Form ---

interface AddSourceFormProps {
  onSubmit: (data: ExternalMCPSourceCreateInput) => Promise<void>
  onCancel: () => void
  isLoading: boolean
  error?: string
}

function AddSourceForm({ onSubmit, onCancel, isLoading, error }: AddSourceFormProps) {
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [authType, setAuthType] = useState<'none' | 'bearer' | 'header' | 'oauth'>('none')
  const [authSecretName, setAuthSecretName] = useState('')
  const [authHeaderName, setAuthHeaderName] = useState('')
  const [transportType, setTransportType] = useState<'streamable_http' | 'sse'>('streamable_http')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    await onSubmit({
      name,
      url,
      auth_type: authType,
      auth_secret_name: authSecretName || undefined,
      auth_header_name: authHeaderName || undefined,
      transport_type: transportType,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="border border-indigo-200 rounded-lg p-4 bg-indigo-50/30">
      <h4 className="text-sm font-medium text-gray-900 mb-4">Add External MCP Source</h4>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
          <input
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="e.g. GitHub MCP"
            required
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-indigo-500 focus:border-indigo-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">URL</label>
          <input
            type="url"
            value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://mcp.example.com/mcp"
            required
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono focus:ring-indigo-500 focus:border-indigo-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Transport</label>
          <select
            value={transportType}
            onChange={e => setTransportType(e.target.value as 'streamable_http' | 'sse')}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-indigo-500 focus:border-indigo-500"
          >
            <option value="streamable_http">Streamable HTTP</option>
            <option value="sse">SSE</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Auth Type</label>
          <select
            value={authType}
            onChange={e => setAuthType(e.target.value as 'none' | 'bearer' | 'header' | 'oauth')}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-indigo-500 focus:border-indigo-500"
          >
            <option value="none">None</option>
            <option value="bearer">Bearer Token</option>
            <option value="header">Custom Header</option>
            <option value="oauth">OAuth 2.1 (Browser Login)</option>
          </select>
        </div>
        {authType === 'oauth' && (
          <div className="col-span-2">
            <p className="text-xs text-gray-500">
              After adding, click &quot;Authenticate&quot; to sign in via the external server&apos;s OAuth flow.
              MCPbox will discover the OAuth endpoints automatically (RFC 9728 + RFC 8414).
            </p>
          </div>
        )}
        {(authType === 'bearer' || authType === 'header') && (
          <>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Auth Secret Name
                <span className="text-xs text-gray-400 ml-1">(from server secrets)</span>
              </label>
              <input
                type="text"
                value={authSecretName}
                onChange={e => setAuthSecretName(e.target.value)}
                placeholder="e.g. GITHUB_TOKEN"
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-indigo-500 focus:border-indigo-500"
              />
            </div>
            {authType === 'header' && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Header Name</label>
                <input
                  type="text"
                  value={authHeaderName}
                  onChange={e => setAuthHeaderName(e.target.value)}
                  placeholder="e.g. X-API-Key"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-indigo-500 focus:border-indigo-500"
                />
              </div>
            )}
          </>
        )}
      </div>
      {error && (
        <p className="mt-3 text-sm text-red-600">{error}</p>
      )}
      <div className="mt-4 flex items-center gap-3">
        <button
          type="submit"
          disabled={isLoading || !name || !url}
          className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700 disabled:opacity-50"
        >
          {isLoading ? 'Adding...' : 'Add Source'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 text-sm font-medium text-gray-700 hover:text-gray-900"
        >
          Cancel
        </button>
      </div>
    </form>
  )
}
