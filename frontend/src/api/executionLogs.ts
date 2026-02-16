import { useQuery } from '@tanstack/react-query'
import { api } from './client'

// Types
export interface ExecutionLog {
  id: string
  tool_id: string
  server_id: string
  tool_name: string
  input_args: Record<string, unknown> | null
  result: unknown | null
  error: string | null
  stdout: string | null
  duration_ms: number | null
  success: boolean
  executed_by: string | null
  created_at: string
}

export interface ExecutionLogListResponse {
  items: ExecutionLog[]
  total: number
  page: number
  page_size: number
  pages: number
}

// API functions
export async function fetchToolExecutionLogs(
  toolId: string,
  page: number = 1,
  pageSize: number = 20
): Promise<ExecutionLogListResponse> {
  return api.get<ExecutionLogListResponse>(
    `/api/tools/${toolId}/logs?page=${page}&page_size=${pageSize}`
  )
}

export async function fetchServerExecutionLogs(
  serverId: string,
  page: number = 1,
  pageSize: number = 20
): Promise<ExecutionLogListResponse> {
  return api.get<ExecutionLogListResponse>(
    `/api/servers/${serverId}/execution-logs?page=${page}&page_size=${pageSize}`
  )
}

export async function fetchExecutionLog(logId: string): Promise<ExecutionLog> {
  return api.get<ExecutionLog>(`/api/logs/${logId}`)
}

// React Query hooks
export function useToolExecutionLogs(
  toolId: string | undefined,
  page: number = 1,
  pageSize: number = 20
) {
  return useQuery({
    queryKey: ['executionLogs', toolId, page, pageSize],
    queryFn: () => fetchToolExecutionLogs(toolId!, page, pageSize),
    enabled: !!toolId,
    refetchInterval: 15000, // Refresh every 15 seconds
  })
}

export function useServerExecutionLogs(
  serverId: string | undefined,
  page: number = 1,
  pageSize: number = 20
) {
  return useQuery({
    queryKey: ['serverExecutionLogs', serverId, page, pageSize],
    queryFn: () => fetchServerExecutionLogs(serverId!, page, pageSize),
    enabled: !!serverId,
    refetchInterval: 15000,
  })
}

export function useExecutionLog(logId: string | undefined) {
  return useQuery({
    queryKey: ['executionLog', logId],
    queryFn: () => fetchExecutionLog(logId!),
    enabled: !!logId,
  })
}
