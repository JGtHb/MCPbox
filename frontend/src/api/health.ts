import { useQuery } from '@tanstack/react-query'
import { api } from './client'
import type { HealthResponse } from './types'

// Query keys
export const healthKeys = {
  all: ['health'] as const,
  detail: () => [...healthKeys.all, 'detail'] as const,
}

// API functions
export async function fetchHealth(): Promise<HealthResponse> {
  return api.get<HealthResponse>('/health')
}

// React Query hooks
export function useHealth() {
  return useQuery({
    queryKey: healthKeys.all,
    queryFn: fetchHealth,
    refetchInterval: 30000, // Refetch every 30 seconds
  })
}
