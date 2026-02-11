import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Header } from '../components/Layout'
import { CodePreview } from '../components/CodePreview'
import { api } from '../api/client'
import { useServer } from '../api/servers'

interface CodePreviewResponse {
  code: string
  server_name: string
  tool_count: number
}

async function fetchCodePreview(serverId: string): Promise<CodePreviewResponse> {
  return api.get<CodePreviewResponse>(`/api/servers/${serverId}/preview`)
}

export function ServerCodePreview() {
  const { id } = useParams<{ id: string }>()
  const { data: server } = useServer(id || '')

  const { data, isLoading, error } = useQuery({
    queryKey: ['code-preview', id],
    queryFn: () => fetchCodePreview(id || ''),
    enabled: !!id,
  })

  if (isLoading) {
    return (
      <div>
        <Header title="Code Preview" />
        <div className="p-6">
          <div className="bg-gray-900 rounded-lg p-6 animate-pulse">
            <div className="h-4 bg-gray-700 rounded w-1/4 mb-4"></div>
            <div className="h-64 bg-gray-800 rounded"></div>
          </div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div>
        <Header
          title="Code Preview"
          action={
            <Link
              to={`/servers/${id}`}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
            >
              Back to Server
            </Link>
          }
        />
        <div className="p-6">
          <div className="bg-red-50 border border-red-200 rounded-lg p-6">
            <h3 className="text-lg font-medium text-red-800 mb-2">
              Failed to generate code preview
            </h3>
            <p className="text-red-700">
              {error instanceof Error ? error.message : 'Unknown error occurred'}
            </p>
            <p className="mt-4 text-sm text-red-600">
              Make sure you have at least one endpoint defined for this server.
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div>
      <Header
        title={`Code Preview: ${data?.server_name || server?.name || 'Server'}`}
        action={
          <Link
            to={`/servers/${id}`}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md hover:bg-blue-700"
          >
            Back to Server
          </Link>
        }
      />

      <div className="p-6 space-y-6">
        {/* Info Banner */}
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <div className="flex items-start">
            <svg
              className="w-5 h-5 text-blue-500 mt-0.5 mr-3 flex-shrink-0"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <div>
              <h4 className="text-sm font-medium text-blue-800">Generated FastMCP Server</h4>
              <p className="text-sm text-blue-700 mt-1">
                This is the Python code that will run in the sandbox container. It includes{' '}
                {data?.tool_count || 0} MCP {(data?.tool_count || 0) === 1 ? 'tool' : 'tools'}.
              </p>
            </div>
          </div>
        </div>

        {/* Code Preview */}
        {data?.code && (
          <CodePreview
            code={data.code}
            language="python"
            title="mcp_server.py"
          />
        )}
      </div>
    </div>
  )
}
