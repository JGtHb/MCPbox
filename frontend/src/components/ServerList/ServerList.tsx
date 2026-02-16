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
            className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 animate-pulse"
          >
            <div className="h-6 bg-gray-200 dark:bg-gray-700 rounded w-3/4 mb-2"></div>
            <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/2"></div>
            <div className="mt-4 h-8 bg-gray-200 dark:bg-gray-700 rounded"></div>
          </div>
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg p-4">
        <p className="text-red-800 dark:text-red-300">
          Failed to load servers: {error instanceof Error ? error.message : 'Unknown error'}
        </p>
      </div>
    )
  }

  if (!servers || servers.length === 0) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow">
        <div className="p-8 text-center">
          <svg
            className="mx-auto h-12 w-12 text-gray-400 dark:text-gray-500"
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
          <h3 className="mt-4 text-lg font-medium text-gray-900 dark:text-white">No servers yet</h3>
          <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
            Use MCP tools like <code className="text-xs bg-gray-100 dark:bg-gray-700 px-1 py-0.5 rounded">mcpbox_create_server</code> to create your first server.
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
            className="w-full sm:w-64 px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:focus:ring-blue-400"
          />
        </div>
      )}
      {filteredServers.length === 0 ? (
        <div className="text-center py-8 text-gray-500 dark:text-gray-400 text-sm">
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
