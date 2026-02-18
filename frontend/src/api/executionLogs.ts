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

export interface ExecutionStats {
  total_executions: number
  successful: number
  failed: number
  avg_duration_ms: number | null
  period_executions: number
  period_hours: number
  unique_tools: number
  unique_users: number
}

export interface AllExecutionLogsParams {
  page?: number
  pageSize?: number
  toolName?: string
  serverId?: string
  success?: boolean
  executedBy?: string
}

// Query keys
export const executionLogKeys = {
  all: ['executionLogs'] as const,
  global: (params: AllExecutionLogsParams) =>
    [...executionLogKeys.all, 'global', params] as const,
  stats: (periodHours?: number) =>
    [...executionLogKeys.all, 'stats', periodHours] as const,
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

// Global execution logs API
export async function fetchAllExecutionLogs(
  params: AllExecutionLogsParams = {}
): Promise<ExecutionLogListResponse> {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.pageSize) searchParams.set('page_size', String(params.pageSize))
  if (params.toolName) searchParams.set('tool_name', params.toolName)
  if (params.serverId) searchParams.set('server_id', params.serverId)
  if (params.success !== undefined) searchParams.set('success', String(params.success))
  if (params.executedBy) searchParams.set('executed_by', params.executedBy)

  const qs = searchParams.toString()
  return api.get<ExecutionLogListResponse>(`/api/execution-logs${qs ? `?${qs}` : ''}`)
}

export async function fetchExecutionStats(
  periodHours: number = 24
): Promise<ExecutionStats> {
  return api.get<ExecutionStats>(`/api/execution-logs/stats?period_hours=${periodHours}`)
}

// Global execution logs hooks
export function useAllExecutionLogs(params: AllExecutionLogsParams = {}) {
  return useQuery({
    queryKey: executionLogKeys.global(params),
    queryFn: () => fetchAllExecutionLogs(params),
    refetchInterval: 15000,
  })
}

export function useExecutionStats(periodHours: number = 24) {
  return useQuery({
    queryKey: executionLogKeys.stats(periodHours),
    queryFn: () => fetchExecutionStats(periodHours),
    refetchInterval: 30000,
  })
}
