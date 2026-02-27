import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

// =============================================================================
// Types
// =============================================================================

export type AccessPolicyType = 'everyone' | 'emails' | 'email_domain'

export interface AccessPolicyConfig {
  policy_type: AccessPolicyType
  emails: string[]
  email_domain: string | null
}

// Primary authentication method
export interface StartWithApiTokenRequest {
  api_token: string
}

export interface StartWithApiTokenResponse {
  success: boolean
  config_id: string | null
  account_id: string | null
  account_name: string | null
  team_domain: string | null
  message: string | null
  error: string | null
}

export interface SetApiTokenRequest {
  config_id: string
  api_token: string
}

export interface SetApiTokenResponse {
  success: boolean
  message: string | null
}

export interface CreateTunnelRequest {
  config_id: string
  name: string
  force?: boolean
}

export interface CreateTunnelResponse {
  success: boolean
  tunnel_id: string
  tunnel_name: string
  tunnel_token: string
  message: string | null
}

export interface CreateVpcServiceRequest {
  config_id: string
  name: string
  force?: boolean
}

export interface CreateVpcServiceResponse {
  success: boolean
  vpc_service_id: string
  vpc_service_name: string
  message: string | null
}

export interface DeployWorkerRequest {
  config_id: string
  name: string
}

export interface DeployWorkerResponse {
  success: boolean
  worker_name: string
  worker_url: string
  message: string | null
}

export interface ConfigureJwtRequest {
  config_id: string
  access_policy?: AccessPolicyConfig
}

export interface ConfigureJwtResponse {
  success: boolean
  team_domain: string
  worker_url: string
  worker_test_result: string
  message: string | null
}

export interface WizardStatusResponse {
  config_id: string | null
  status: string
  completed_step: number
  error_message: string | null

  account_id: string | null
  account_name: string | null
  team_domain: string | null

  tunnel_id: string | null
  tunnel_name: string | null
  has_tunnel_token: boolean

  vpc_service_id: string | null
  vpc_service_name: string | null

  worker_name: string | null
  worker_url: string | null

  access_policy_type: string | null
  access_policy_emails: string[] | null
  access_policy_email_domain: string | null

  allowed_cors_origins: string[] | null
  allowed_redirect_uris: string[] | null

  created_at: string | null
  updated_at: string | null
}

export interface TeardownResponse {
  success: boolean
  deleted_resources: string[]
  errors: string[]
  message: string | null
}

export interface WorkerConfigResponse {
  success: boolean
  allowed_cors_origins: string[]
  allowed_redirect_uris: string[]
  kv_synced: boolean
  message: string | null
}

// =============================================================================
// API Functions
// =============================================================================

export async function getWizardStatus(): Promise<WizardStatusResponse> {
  return api.get<WizardStatusResponse>('/api/cloudflare/status')
}

export async function startWithApiToken(
  data: StartWithApiTokenRequest
): Promise<StartWithApiTokenResponse> {
  return api.post<StartWithApiTokenResponse>('/api/cloudflare/start', data)
}

export async function setApiToken(data: SetApiTokenRequest): Promise<SetApiTokenResponse> {
  return api.post<SetApiTokenResponse>('/api/cloudflare/api-token', data)
}

export async function createTunnel(data: CreateTunnelRequest): Promise<CreateTunnelResponse> {
  return api.post<CreateTunnelResponse>('/api/cloudflare/tunnel', data)
}

export async function createVpcService(
  data: CreateVpcServiceRequest
): Promise<CreateVpcServiceResponse> {
  return api.post<CreateVpcServiceResponse>('/api/cloudflare/vpc-service', data)
}

export async function deployWorker(data: DeployWorkerRequest): Promise<DeployWorkerResponse> {
  return api.post<DeployWorkerResponse>('/api/cloudflare/worker', data)
}

export async function configureWorkerJwt(
  data: ConfigureJwtRequest
): Promise<ConfigureJwtResponse> {
  return api.post<ConfigureJwtResponse>('/api/cloudflare/worker-jwt-config', data)
}

export async function teardown(configId: string): Promise<TeardownResponse> {
  return api.delete<TeardownResponse>(`/api/cloudflare/teardown/${configId}`)
}

export async function updateAccessPolicy(
  configId: string,
  accessPolicy: AccessPolicyConfig
): Promise<{ success: boolean; message: string }> {
  return api.put<{ success: boolean; message: string }>('/api/cloudflare/access-policy', {
    config_id: configId,
    access_policy: accessPolicy,
  })
}

export async function getWorkerConfig(configId: string): Promise<WorkerConfigResponse> {
  return api.get<WorkerConfigResponse>(`/api/cloudflare/worker-config/${configId}`)
}

export async function updateWorkerConfig(
  configId: string,
  corsOrigins: string[],
  redirectUris: string[]
): Promise<WorkerConfigResponse> {
  return api.put<WorkerConfigResponse>('/api/cloudflare/worker-config', {
    config_id: configId,
    allowed_cors_origins: corsOrigins,
    allowed_redirect_uris: redirectUris,
  })
}

// =============================================================================
// Query Keys
// =============================================================================

export const cloudflareKeys = {
  all: ['cloudflare'] as const,
  status: () => [...cloudflareKeys.all, 'status'] as const,
  workerConfig: (configId: string) => [...cloudflareKeys.all, 'workerConfig', configId] as const,
}

// =============================================================================
// Hooks
// =============================================================================

export function useCloudflareStatus() {
  return useQuery({
    queryKey: cloudflareKeys.status(),
    queryFn: getWizardStatus,
  })
}

export function useStartWithApiToken() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: startWithApiToken,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: cloudflareKeys.status() })
    },
  })
}

export function useSetApiToken() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: setApiToken,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: cloudflareKeys.status() })
    },
  })
}

export function useCreateTunnel() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: createTunnel,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: cloudflareKeys.status() })
    },
  })
}

export function useCreateVpcService() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: createVpcService,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: cloudflareKeys.status() })
    },
  })
}

export function useDeployWorker() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: deployWorker,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: cloudflareKeys.status() })
    },
  })
}

export function useConfigureWorkerJwt() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: configureWorkerJwt,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: cloudflareKeys.status() })
    },
  })
}

export function useTeardown() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: teardown,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: cloudflareKeys.status() })
    },
  })
}

export function useUpdateAccessPolicy() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ configId, accessPolicy }: { configId: string; accessPolicy: AccessPolicyConfig }) =>
      updateAccessPolicy(configId, accessPolicy),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: cloudflareKeys.status() })
    },
  })
}

export function useWorkerConfig(configId: string | null) {
  return useQuery({
    queryKey: cloudflareKeys.workerConfig(configId || ''),
    queryFn: () => getWorkerConfig(configId!),
    enabled: !!configId,
  })
}

export function useUpdateWorkerConfig() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({
      configId,
      corsOrigins,
      redirectUris,
    }: {
      configId: string
      corsOrigins: string[]
      redirectUris: string[]
    }) => updateWorkerConfig(configId, corsOrigins, redirectUris),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: cloudflareKeys.workerConfig(variables.configId) })
      queryClient.invalidateQueries({ queryKey: cloudflareKeys.status() })
    },
  })
}

