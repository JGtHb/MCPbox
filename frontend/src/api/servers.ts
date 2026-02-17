import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

// Types
export interface Server {
  id: string
  name: string
  description: string | null
  status: 'imported' | 'ready' | 'running' | 'stopped' | 'error'
  network_mode: 'isolated' | 'allowlist'
  tool_count: number
  created_at: string
  updated_at: string
}

export interface ServerDetail extends Server {
  allowed_hosts: string[] | null
  default_timeout_ms: number
  helper_code: string | null
  // NOTE: allowed_modules removed - now global in Settings
}

// NOTE: ModuleConfigResponse, ModuleConfigUpdate, DefaultModulesResponse removed
// Module configuration is now global - see api/settings.ts

// NOTE: ServerCreate, ServerUpdate removed - server creation/updates done via MCP tools

export interface ContainerStatus {
  server_id: string
  status: string
  registered_tools: number
  message: string | null
}

// Query keys
export const serverKeys = {
  all: ['servers'] as const,
  lists: () => [...serverKeys.all, 'list'] as const,
  list: (filters?: Record<string, unknown>) => [...serverKeys.lists(), filters] as const,
  details: () => [...serverKeys.all, 'detail'] as const,
  detail: (id: string) => [...serverKeys.details(), id] as const,
  status: (id: string) => [...serverKeys.all, 'status', id] as const,
  // NOTE: modules and defaultModules keys removed - module config now in settings
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
export async function fetchServers(): Promise<Server[]> {
  const response = await api.get<PaginatedResponse<Server>>('/api/servers')
  return response.items
}

export async function fetchServer(id: string): Promise<ServerDetail> {
  return api.get<ServerDetail>(`/api/servers/${id}`)
}

export async function deleteServer(id: string): Promise<void> {
  await api.delete(`/api/servers/${id}`)
}

export async function startServer(id: string): Promise<ContainerStatus> {
  return api.post<ContainerStatus>(`/api/sandbox/servers/${id}/start`)
}

export async function stopServer(id: string): Promise<ContainerStatus> {
  return api.post<ContainerStatus>(`/api/sandbox/servers/${id}/stop`)
}

export async function restartServer(id: string): Promise<ContainerStatus> {
  return api.post<ContainerStatus>(`/api/sandbox/servers/${id}/restart`)
}

export async function fetchServerStatus(id: string): Promise<ContainerStatus> {
  return api.get<ContainerStatus>(`/api/sandbox/servers/${id}/status`)
}

// NOTE: fetchServerModules, updateServerModules, fetchDefaultModules removed
// Module configuration is now global - see api/settings.ts

// React Query hooks
export function useServers() {
  return useQuery({
    queryKey: serverKeys.lists(),
    queryFn: fetchServers,
  })
}

export function useServer(id: string) {
  return useQuery({
    queryKey: serverKeys.detail(id),
    queryFn: () => fetchServer(id),
    enabled: !!id,
  })
}

export function useServerStatus(id: string, enabled = true) {
  return useQuery({
    queryKey: serverKeys.status(id),
    queryFn: () => fetchServerStatus(id),
    enabled: !!id && enabled,
    refetchInterval: 5000, // Poll every 5 seconds when enabled
  })
}

// NOTE: useCreateServer, useUpdateServer removed - server creation/updates done via MCP tools

export function useDeleteServer() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: deleteServer,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: serverKeys.lists() })
    },
    onError: () => {
      // Invalidate to ensure UI reflects actual state
      queryClient.invalidateQueries({ queryKey: serverKeys.lists() })
    },
  })
}

export function useStartServer() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: startServer,
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: serverKeys.lists() })
      queryClient.invalidateQueries({ queryKey: serverKeys.detail(id) })
      queryClient.invalidateQueries({ queryKey: serverKeys.status(id) })
    },
    onError: (_, id) => {
      // Invalidate to ensure UI reflects actual state
      queryClient.invalidateQueries({ queryKey: serverKeys.lists() })
      queryClient.invalidateQueries({ queryKey: serverKeys.detail(id) })
      queryClient.invalidateQueries({ queryKey: serverKeys.status(id) })
    },
  })
}

export function useStopServer() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: stopServer,
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: serverKeys.lists() })
      queryClient.invalidateQueries({ queryKey: serverKeys.detail(id) })
      queryClient.invalidateQueries({ queryKey: serverKeys.status(id) })
    },
    onError: (_, id) => {
      // Invalidate to ensure UI reflects actual state
      queryClient.invalidateQueries({ queryKey: serverKeys.lists() })
      queryClient.invalidateQueries({ queryKey: serverKeys.detail(id) })
      queryClient.invalidateQueries({ queryKey: serverKeys.status(id) })
    },
  })
}

export function useRestartServer() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: restartServer,
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: serverKeys.status(id) })
    },
    onError: (_, id) => {
      // Invalidate to ensure UI reflects actual state
      queryClient.invalidateQueries({ queryKey: serverKeys.status(id) })
    },
  })
}

// NOTE: useServerModules, useDefaultModules, useUpdateServerModules removed
// Module configuration is now global - see api/settings.ts

