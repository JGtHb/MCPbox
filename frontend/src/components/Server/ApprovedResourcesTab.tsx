import { useServerModuleRequests, useServerNetworkRequests } from '../../api/approvals'

interface ApprovedResourcesTabProps {
  serverId: string
}

const STATUS_COLORS: Record<string, string> = {
  approved: 'bg-green-100 dark:bg-green-900/50 text-green-700 dark:text-green-300',
  pending: 'bg-yellow-100 dark:bg-yellow-900/50 text-yellow-800 dark:text-yellow-300',
  rejected: 'bg-red-100 dark:bg-red-900/50 text-red-700 dark:text-red-300',
}

export function ApprovedResourcesTab({ serverId }: ApprovedResourcesTabProps) {
  const { data: moduleData, isLoading: modulesLoading } = useServerModuleRequests(serverId)
  const { data: networkData, isLoading: networkLoading } = useServerNetworkRequests(serverId)

  if (modulesLoading || networkLoading) {
    return (
      <div className="space-y-6">
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
          <div className="animate-pulse space-y-3">
            <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/4" />
            <div className="h-10 bg-gray-200 dark:bg-gray-700 rounded" />
            <div className="h-10 bg-gray-200 dark:bg-gray-700 rounded" />
          </div>
        </div>
      </div>
    )
  }

  const modules = moduleData?.items ?? []
  const networkHosts = networkData?.items ?? []

  return (
    <div className="space-y-6">
      {/* Approved Modules */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow">
        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 className="text-lg font-medium text-gray-900 dark:text-white">
            Approved Modules ({modules.length})
          </h3>
        </div>
        {modules.length === 0 ? (
          <div className="px-6 py-8 text-center">
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
                d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"
              />
            </svg>
            <p className="text-gray-500 dark:text-gray-400">
              No approved modules for this server
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-700">
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Module
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Tool
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {modules.map((mod) => (
                  <tr key={mod.id}>
                    <td className="px-6 py-3 text-sm font-mono text-gray-900 dark:text-white">
                      {mod.module_name}
                    </td>
                    <td className="px-6 py-3 text-sm text-gray-600 dark:text-gray-400">
                      {mod.tool_name}
                    </td>
                    <td className="px-6 py-3">
                      <span
                        className={`inline-flex px-2 py-0.5 text-xs font-medium rounded ${STATUS_COLORS[mod.status] || 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300'}`}
                      >
                        {mod.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Approved Network Access */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow">
        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 className="text-lg font-medium text-gray-900 dark:text-white">
            Approved Network Access ({networkHosts.length})
          </h3>
        </div>
        {networkHosts.length === 0 ? (
          <div className="px-6 py-8 text-center">
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
                d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9"
              />
            </svg>
            <p className="text-gray-500 dark:text-gray-400">
              No approved network access for this server
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-700">
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Host
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Port
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Tool
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {networkHosts.map((req) => (
                  <tr key={req.id}>
                    <td className="px-6 py-3 text-sm font-mono text-gray-900 dark:text-white">
                      {req.host}
                    </td>
                    <td className="px-6 py-3 text-sm text-gray-600 dark:text-gray-400">
                      {req.port ?? 'Any'}
                    </td>
                    <td className="px-6 py-3 text-sm text-gray-600 dark:text-gray-400">
                      {req.tool_name}
                    </td>
                    <td className="px-6 py-3">
                      <span
                        className={`inline-flex px-2 py-0.5 text-xs font-medium rounded ${STATUS_COLORS[req.status] || 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300'}`}
                      >
                        {req.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
