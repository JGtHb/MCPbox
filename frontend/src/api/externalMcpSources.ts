import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

// Types
export interface ExternalMCPSource {
  id: string
  server_id: string
  name: string
  url: string
  auth_type: 'none' | 'bearer' | 'header' | 'oauth'
  auth_secret_name: string | null
  auth_header_name: string | null
  transport_type: 'streamable_http' | 'sse'
  status: 'active' | 'error' | 'disabled'
  last_discovered_at: string | null
  tool_count: number
  created_at: string
  updated_at: string
  oauth_issuer: string | null
  oauth_client_id: string | null
  oauth_authenticated: boolean
}

export interface ExternalMCPSourceCreateInput {
  name: string
  url: string
  auth_type?: 'none' | 'bearer' | 'header' | 'oauth'
  auth_secret_name?: string
  auth_header_name?: string
  transport_type?: 'streamable_http' | 'sse'
}

export interface DiscoveredTool {
  name: string
  description: string | null
  input_schema: Record<string, unknown>
  already_imported: boolean
}

export interface DiscoverToolsResponse {
  source_id: string
  source_name: string
  tools: DiscoveredTool[]
  total: number
}

export interface ToolResponse {
  id: string
  server_id: string
  name: string
  description: string | null
  enabled: boolean
  tool_type: string
  approval_status: string
}

export interface ImportToolResult {
  name: string
  status: 'created' | 'skipped_conflict' | 'skipped_not_found'
  tool_id: string | null
  reason: string | null
}

export interface ImportToolsResponse {
  created: ImportToolResult[]
  skipped: ImportToolResult[]
  total_requested: number
  total_created: number
  total_skipped: number
}

export interface OAuthStartResponse {
  auth_url: string
  issuer: string
}

// Query keys
export const externalSourceKeys = {
  all: ['externalSources'] as const,
  lists: () => [...externalSourceKeys.all, 'list'] as const,
  list: (serverId: string) => [...externalSourceKeys.lists(), serverId] as const,
  detail: (sourceId: string) => [...externalSourceKeys.all, 'detail', sourceId] as const,
  discover: (sourceId: string) => [...externalSourceKeys.all, 'discover', sourceId] as const,
}

// API functions
export async function fetchSources(serverId: string): Promise<ExternalMCPSource[]> {
  return api.get<ExternalMCPSource[]>(`/api/external-sources/servers/${serverId}/sources`)
}

export async function createSource(
  serverId: string,
  data: ExternalMCPSourceCreateInput
): Promise<ExternalMCPSource> {
  return api.post<ExternalMCPSource>(`/api/external-sources/servers/${serverId}/sources`, data)
}

export async function updateSource(
  sourceId: string,
  data: Partial<ExternalMCPSourceCreateInput & { status: string }>
): Promise<ExternalMCPSource> {
  return api.put<ExternalMCPSource>(`/api/external-sources/sources/${sourceId}`, data)
}

export async function deleteSource(sourceId: string): Promise<void> {
  await api.delete(`/api/external-sources/sources/${sourceId}`)
}

export async function discoverTools(sourceId: string): Promise<DiscoverToolsResponse> {
  return api.post<DiscoverToolsResponse>(
    `/api/external-sources/sources/${sourceId}/discover`,
    {}
  )
}

export async function fetchCachedTools(sourceId: string): Promise<DiscoverToolsResponse> {
  return api.get<DiscoverToolsResponse>(
    `/api/external-sources/sources/${sourceId}/cached-tools`
  )
}

export async function importTools(
  sourceId: string,
  toolNames: string[]
): Promise<ImportToolsResponse> {
  return api.post<ImportToolsResponse>(
    `/api/external-sources/sources/${sourceId}/import`,
    { tool_names: toolNames }
  )
}

export async function startOAuth(
  sourceId: string,
  callbackUrl: string
): Promise<OAuthStartResponse> {
  return api.post<OAuthStartResponse>(
    `/api/external-sources/sources/${sourceId}/oauth/start`,
    { callback_url: callbackUrl }
  )
}

export async function exchangeOAuthCode(
  state: string,
  code: string
): Promise<{ success: boolean; source_id: string }> {
  return api.post<{ success: boolean; source_id: string }>(
    '/api/external-sources/oauth/exchange',
    { state, code }
  )
}

// React Query hooks
export function useExternalSources(serverId: string | undefined) {
  return useQuery({
    queryKey: externalSourceKeys.list(serverId || ''),
    queryFn: () => fetchSources(serverId!),
    enabled: !!serverId,
  })
}

export function useCachedTools(sourceId: string | null) {
  return useQuery({
    queryKey: externalSourceKeys.discover(sourceId || ''),
    queryFn: () => fetchCachedTools(sourceId!),
    enabled: !!sourceId,
  })
}

export function useCreateExternalSource(serverId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: ExternalMCPSourceCreateInput) => createSource(serverId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: externalSourceKeys.list(serverId),
      })
    },
  })
}

export function useDeleteExternalSource(serverId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: deleteSource,
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: externalSourceKeys.list(serverId),
      })
    },
  })
}

export function useRenameSource(serverId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ sourceId, name }: { sourceId: string; name: string }) =>
      updateSource(sourceId, { name }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: externalSourceKeys.list(serverId),
      })
    },
  })
}

export function useDiscoverTools(serverId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: discoverTools,
    onSuccess: (_data, sourceId) => {
      // Invalidate cached tools for this source (triggers refetch)
      queryClient.invalidateQueries({
        queryKey: externalSourceKeys.discover(sourceId),
      })
      // Invalidate source list to update tool_count and last_discovered_at
      queryClient.invalidateQueries({
        queryKey: externalSourceKeys.list(serverId),
      })
    },
  })
}

export function useImportTools(serverId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ sourceId, toolNames }: { sourceId: string; toolNames: string[] }) =>
      importTools(sourceId, toolNames),
    onSuccess: (_data, { sourceId }) => {
      queryClient.invalidateQueries({
        queryKey: externalSourceKeys.list(serverId),
      })
      // Invalidate cached tools so already_imported flags refresh
      queryClient.invalidateQueries({
        queryKey: externalSourceKeys.discover(sourceId),
      })
      // Also invalidate tools list since we created new tools
      queryClient.invalidateQueries({ queryKey: ['tools'] })
    },
  })
}

export function useStartOAuth(serverId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ sourceId, callbackUrl }: { sourceId: string; callbackUrl: string }) =>
      startOAuth(sourceId, callbackUrl),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: externalSourceKeys.list(serverId),
      })
    },
  })
}
