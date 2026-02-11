import { useQuery } from '@tanstack/react-query'
import { api } from './client'

// Types
export interface Tool {
  id: string
  server_id: string
  name: string
  description: string | null
  enabled: boolean
  timeout_ms: number | null
  python_code: string | null
  input_schema: Record<string, unknown> | null
  current_version: number
  created_at: string
  updated_at: string
}

export interface ToolListItem {
  id: string
  name: string
  description: string | null
  enabled: boolean
}

// Code validation types (used by test mocks)
export interface CodeParameter {
  name: string
  type: string | null
}

export interface CodeValidationResponse {
  valid: boolean
  has_main: boolean
  error: string | null
  parameters: CodeParameter[]
  input_schema: Record<string, unknown> | null
}

// Test code types (used by test mocks)
export interface ErrorDetail {
  message: string
  error_type: string
  line_number: number | null
  code_context: string[]
  traceback: string[]
  source_file: string
}

export interface HttpCallInfo {
  method: string
  url: string
  status_code: number | null
  duration_ms: number
  request_headers: Record<string, string> | null
  response_preview: string | null
  error: string | null
}

export interface DebugInfoType {
  http_calls: HttpCallInfo[]
  timing_breakdown: Record<string, number>
}

export interface TestCodeResponse {
  success: boolean
  result: unknown
  error: string | null
  error_detail: ErrorDetail | null
  stdout: string | null
  duration_ms: number | null
  debug_info: DebugInfoType | null
}

// Query keys
export const toolKeys = {
  all: ['tools'] as const,
  lists: () => [...toolKeys.all, 'list'] as const,
  list: (serverId: string) => [...toolKeys.lists(), serverId] as const,
}

// Paginated response type
interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

// API functions
export async function fetchTools(serverId: string): Promise<ToolListItem[]> {
  const response = await api.get<PaginatedResponse<ToolListItem>>(`/api/servers/${serverId}/tools`)
  return response.items
}

// React Query hooks
export function useTools(serverId: string) {
  return useQuery({
    queryKey: toolKeys.list(serverId),
    queryFn: () => fetchTools(serverId),
    enabled: !!serverId,
  })
}
