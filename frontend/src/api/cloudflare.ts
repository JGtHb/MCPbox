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

export interface Zone {
  id: string
  name: string
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
  zones: Zone[]
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

export interface CreateMcpServerRequest {
  config_id: string
  server_id: string
  server_name: string
  force?: boolean
  access_policy?: AccessPolicyConfig
}

export interface CreateMcpServerResponse {
  success: boolean
  mcp_server_id: string
  tools_synced: number
  message: string | null
}

export interface CreateMcpPortalRequest {
  config_id: string
  portal_id: string
  portal_name: string
  hostname: string
  force?: boolean
  access_policy?: AccessPolicyConfig
}

export interface CreateMcpPortalResponse {
  success: boolean
  mcp_portal_id: string
  mcp_portal_hostname: string
  portal_url: string
  mcp_portal_aud: string
  message: string | null
}

export interface ConfigureJwtRequest {
  config_id: string
  aud?: string
}

export interface ConfigureJwtResponse {
  success: boolean
  team_domain: string
  aud: string
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

  mcp_server_id: string | null

  mcp_portal_id: string | null
  mcp_portal_hostname: string | null
  mcp_portal_aud: string | null

  created_at: string | null
  updated_at: string | null
}

export interface TeardownResponse {
  success: boolean
  deleted_resources: string[]
  errors: string[]
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

export async function createMcpServer(
  data: CreateMcpServerRequest
): Promise<CreateMcpServerResponse> {
  return api.post<CreateMcpServerResponse>('/api/cloudflare/mcp-server', data)
}

export async function createMcpPortal(
  data: CreateMcpPortalRequest
): Promise<CreateMcpPortalResponse> {
  return api.post<CreateMcpPortalResponse>('/api/cloudflare/mcp-portal', data)
}

export async function configureWorkerJwt(
  data: ConfigureJwtRequest
): Promise<ConfigureJwtResponse> {
  return api.post<ConfigureJwtResponse>('/api/cloudflare/worker-jwt-config', data)
}

export async function syncTools(configId: string): Promise<{ tools_synced: number; message: string }> {
  return api.post<{ tools_synced: number; message: string }>(`/api/cloudflare/sync-tools/${configId}`)
}

export async function teardown(configId: string): Promise<TeardownResponse> {
  return api.delete<TeardownResponse>(`/api/cloudflare/teardown/${configId}`)
}

export async function getZones(configId: string): Promise<Zone[]> {
  return api.get<Zone[]>(`/api/cloudflare/zones/${configId}`)
}

// =============================================================================
// Query Keys
// =============================================================================

export const cloudflareKeys = {
  all: ['cloudflare'] as const,
  status: () => [...cloudflareKeys.all, 'status'] as const,
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

export function useCreateMcpServer() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: createMcpServer,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: cloudflareKeys.status() })
    },
  })
}

export function useCreateMcpPortal() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: createMcpPortal,
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

export function useSyncTools() {
  return useMutation({
    mutationFn: syncTools,
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

