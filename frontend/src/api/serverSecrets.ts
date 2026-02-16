import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

// Types
export interface Secret {
  id: string
  server_id: string
  key_name: string
  description: string | null
  has_value: boolean
  created_at: string
  updated_at: string
}

export interface SecretListResponse {
  items: Secret[]
  total: number
}

export interface SecretCreateInput {
  server_id: string
  key_name: string
  description?: string
}

export interface SecretSetValueInput {
  server_id: string
  key_name: string
  value: string
}

// Query keys
export const secretKeys = {
  all: ['secrets'] as const,
  lists: () => [...secretKeys.all, 'list'] as const,
  list: (serverId: string) => [...secretKeys.lists(), serverId] as const,
}

// API functions
export async function fetchSecrets(serverId: string): Promise<SecretListResponse> {
  return api.get<SecretListResponse>(`/api/servers/${serverId}/secrets`)
}

export async function createSecret(input: SecretCreateInput): Promise<Secret> {
  return api.post<Secret>(`/api/servers/${input.server_id}/secrets`, {
    key_name: input.key_name,
    description: input.description,
  })
}

export async function setSecretValue(input: SecretSetValueInput): Promise<Secret> {
  return api.put<Secret>(
    `/api/servers/${input.server_id}/secrets/${input.key_name}`,
    { value: input.value }
  )
}

export async function deleteSecret(serverId: string, keyName: string): Promise<void> {
  await api.delete(`/api/servers/${serverId}/secrets/${keyName}`)
}

// React Query hooks
export function useSecrets(serverId: string | undefined) {
  return useQuery({
    queryKey: secretKeys.list(serverId || ''),
    queryFn: () => fetchSecrets(serverId!),
    enabled: !!serverId,
  })
}

export function useCreateSecret() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: createSecret,
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({
        queryKey: secretKeys.list(variables.server_id),
      })
    },
  })
}

export function useSetSecretValue() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: setSecretValue,
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({
        queryKey: secretKeys.list(variables.server_id),
      })
    },
  })
}

export function useDeleteSecret() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ serverId, keyName }: { serverId: string; keyName: string }) =>
      deleteSecret(serverId, keyName),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({
        queryKey: secretKeys.list(variables.serverId),
      })
    },
  })
}
