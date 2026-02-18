import { useState } from 'react'
import { useServers } from '../../api/servers'
import { ServerCard } from './ServerCard'

export function ServerList() {
  const { data: servers, isLoading, error } = useServers()
  const [search, setSearch] = useState('')

  if (isLoading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[...Array(3)].map((_, i) => (
          <div
            key={i}
            className="bg-surface rounded-lg shadow p-4 animate-pulse"
          >
            <div className="h-6 bg-hl-med rounded w-3/4 mb-2"></div>
            <div className="h-4 bg-hl-med rounded w-1/2"></div>
            <div className="mt-4 h-8 bg-hl-med rounded"></div>
          </div>
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-love/10 border border-love/20 rounded-lg p-4">
        <p className="text-love">
          Failed to load servers: {error instanceof Error ? error.message : 'Unknown error'}
        </p>
      </div>
    )
  }

  if (!servers || servers.length === 0) {
    return (
      <div className="bg-surface rounded-lg shadow">
        <div className="p-8 text-center">
          <svg
            className="mx-auto h-12 w-12 text-muted"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01"
            />
          </svg>
          <h3 className="mt-4 text-lg font-medium text-on-base">No servers yet</h3>
          <p className="mt-2 text-sm text-muted">
            Use MCP tools like <code className="text-xs bg-hl-low px-1 py-0.5 rounded">mcpbox_create_server</code> to create your first server.
          </p>
        </div>
      </div>
    )
  }

  const filteredServers = servers.filter(
    (server) =>
      server.name.toLowerCase().includes(search.toLowerCase()) ||
      (server.description?.toLowerCase().includes(search.toLowerCase()) ?? false)
  )

  return (
    <div className="space-y-4">
      {servers.length > 3 && (
        <div>
          <input
            type="text"
            placeholder="Search servers..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full sm:w-64 px-3 py-2 text-sm border border-hl-med rounded-lg bg-surface text-on-base placeholder-muted focus:outline-none focus:ring-2 focus:ring-iris"
          />
        </div>
      )}
      {filteredServers.length === 0 ? (
        <div className="text-center py-8 text-muted text-sm">
          No servers match &ldquo;{search}&rdquo;
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredServers.map((server) => (
            <ServerCard key={server.id} server={server} />
          ))}
        </div>
      )}
    </div>
  )
}
