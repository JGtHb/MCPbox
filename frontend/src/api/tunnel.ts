import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

// Types
export interface TunnelStatus {
  status: 'disconnected' | 'connecting' | 'connected' | 'error'
  url: string | null
  started_at: string | null
  error: string | null
}

// Named Tunnel Configuration Types
export interface TunnelConfiguration {
  id: string
  name: string
  description: string | null
  public_url: string | null
  is_active: boolean
  has_token: boolean
  created_at: string
  updated_at: string
}

export interface TunnelConfigurationListItem {
  id: string
  name: string
  description: string | null
  public_url: string | null
  is_active: boolean
  has_token: boolean
  created_at: string
}

export interface TunnelConfigurationListResponse {
  items: TunnelConfigurationListItem[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface TunnelConfigurationCreate {
  name: string
  description?: string
  public_url?: string
  tunnel_token: string
}

export interface TunnelConfigurationUpdate {
  name?: string
  description?: string
  public_url?: string
  tunnel_token?: string
}

export interface TunnelConfigurationActivateResponse {
  message: string
  configuration: TunnelConfiguration
}

// API functions
export async function getTunnelStatus(): Promise<TunnelStatus> {
  return api.get<TunnelStatus>('/api/tunnel/status')
}

export async function startTunnel(): Promise<TunnelStatus> {
  return api.post<TunnelStatus>('/api/tunnel/start', {})
}

export async function stopTunnel(): Promise<TunnelStatus> {
  return api.post<TunnelStatus>('/api/tunnel/stop', {})
}

// Configuration API functions
export async function listTunnelConfigurations(
  page = 1,
  pageSize = 20
): Promise<TunnelConfigurationListResponse> {
  return api.get<TunnelConfigurationListResponse>(
    `/api/tunnel/configurations?page=${page}&page_size=${pageSize}`
  )
}

export async function getTunnelConfiguration(id: string): Promise<TunnelConfiguration> {
  return api.get<TunnelConfiguration>(`/api/tunnel/configurations/${id}`)
}

export async function createTunnelConfiguration(
  data: TunnelConfigurationCreate
): Promise<TunnelConfiguration> {
  return api.post<TunnelConfiguration>('/api/tunnel/configurations', data)
}

export async function updateTunnelConfiguration(
  id: string,
  data: TunnelConfigurationUpdate
): Promise<TunnelConfiguration> {
  return api.put<TunnelConfiguration>(`/api/tunnel/configurations/${id}`, data)
}

export async function deleteTunnelConfiguration(id: string): Promise<{ message: string }> {
  return api.delete<{ message: string }>(`/api/tunnel/configurations/${id}`)
}

export async function activateTunnelConfiguration(
  id: string
): Promise<TunnelConfigurationActivateResponse> {
  return api.post<TunnelConfigurationActivateResponse>(
    `/api/tunnel/configurations/${id}/activate`,
    {}
  )
}

export async function getActiveConfiguration(): Promise<TunnelConfiguration | null> {
  return api.get<TunnelConfiguration | null>('/api/tunnel/configurations/active/current')
}

// Query keys
export const tunnelKeys = {
  all: ['tunnel'] as const,
  status: () => [...tunnelKeys.all, 'status'] as const,
  configurations: () => [...tunnelKeys.all, 'configurations'] as const,
  configurationsList: (page: number) => [...tunnelKeys.configurations(), 'list', page] as const,
  configuration: (id: string) => [...tunnelKeys.configurations(), id] as const,
  activeConfiguration: () => [...tunnelKeys.configurations(), 'active'] as const,
}

// Hooks
export function useTunnelStatus() {
  return useQuery({
    queryKey: tunnelKeys.status(),
    queryFn: getTunnelStatus,
    refetchInterval: (query) => {
      // Poll more frequently when connecting, less when stable
      const status = query.state.data?.status
      if (status === 'connecting') return 1000 // 1 second
      if (status === 'connected') return 10000 // 10 seconds
      return 5000 // 5 seconds default
    },
  })
}

export function useStartTunnel() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: startTunnel,
    onSuccess: (data) => {
      queryClient.setQueryData(tunnelKeys.status(), data)
    },
    onError: () => {
      // Refetch to get actual status
      queryClient.invalidateQueries({ queryKey: tunnelKeys.status() })
    },
  })
}

export function useStopTunnel() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: stopTunnel,
    onSuccess: (data) => {
      queryClient.setQueryData(tunnelKeys.status(), data)
    },
  })
}

// Configuration Hooks
export function useTunnelConfigurations(page = 1) {
  return useQuery({
    queryKey: tunnelKeys.configurationsList(page),
    queryFn: () => listTunnelConfigurations(page),
  })
}

export function useTunnelConfiguration(id: string) {
  return useQuery({
    queryKey: tunnelKeys.configuration(id),
    queryFn: () => getTunnelConfiguration(id),
    enabled: !!id,
  })
}

export function useActiveConfiguration() {
  return useQuery({
    queryKey: tunnelKeys.activeConfiguration(),
    queryFn: getActiveConfiguration,
  })
}

export function useCreateTunnelConfiguration() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: createTunnelConfiguration,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: tunnelKeys.configurations() })
    },
  })
}

export function useUpdateTunnelConfiguration() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: TunnelConfigurationUpdate }) =>
      updateTunnelConfiguration(id, data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: tunnelKeys.configuration(id) })
      queryClient.invalidateQueries({ queryKey: tunnelKeys.configurations() })
    },
  })
}

export function useDeleteTunnelConfiguration() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: deleteTunnelConfiguration,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: tunnelKeys.configurations() })
      queryClient.invalidateQueries({ queryKey: tunnelKeys.activeConfiguration() })
    },
  })
}

export function useActivateTunnelConfiguration() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: activateTunnelConfiguration,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: tunnelKeys.configurations() })
      queryClient.invalidateQueries({ queryKey: tunnelKeys.activeConfiguration() })
    },
  })
}
