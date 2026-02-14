import { useQuery } from '@tanstack/react-query'
import { api } from './client'

// Types
export interface ServerSummary {
  id: string
  name: string
  status: string
  tool_count: number
  requests_24h: number
  errors_24h: number
}

export interface TimeSeriesPoint {
  timestamp: string
  value: number
}

export interface DashboardStats {
  total_servers: number
  active_servers: number
  total_tools: number
  enabled_tools: number
  total_requests_24h: number
  total_errors_24h: number
  error_rate_24h: number
  avg_response_time_ms: number
}

export interface TopTool {
  tool_name: string
  server_name: string
  invocations: number
  avg_duration_ms: number
}

export interface RecentError {
  timestamp: string
  server_name: string | null
  message: string
  tool_name: string | null
}

export interface DashboardData {
  stats: DashboardStats
  servers: ServerSummary[]
  requests_over_time: TimeSeriesPoint[]
  errors_over_time: TimeSeriesPoint[]
  top_tools: TopTool[]
  recent_errors: RecentError[]
}

// Query keys
export const dashboardKeys = {
  all: ['dashboard'] as const,
  data: (period: string) => [...dashboardKeys.all, period] as const,
}

// API functions
export async function fetchDashboard(period: string = '24h'): Promise<DashboardData> {
  return api.get<DashboardData>(`/api/dashboard?period=${period}`)
}

// React Query hooks
export function useDashboard(period: string = '24h') {
  return useQuery({
    queryKey: dashboardKeys.data(period),
    queryFn: () => fetchDashboard(period),
    refetchInterval: 30000, // Refresh every 30 seconds
  })
}
