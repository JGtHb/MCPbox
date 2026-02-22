import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

// Types
export interface ModuleConfigResponse {
  allowed_modules: string[]
  default_modules: string[]
  is_custom: boolean
}

export interface ModuleConfigUpdate {
  add_modules?: string[]
  remove_modules?: string[]
  reset_to_defaults?: boolean
}

// Enhanced module types
export interface ModuleInfo {
  module_name: string
  package_name: string
  is_stdlib: boolean
  is_installed: boolean
  installed_version?: string | null
  pypi_info?: PyPIInfo | null
  error?: string | null
}

export interface PyPIInfo {
  name: string
  version: string
  summary?: string | null
  author?: string | null
  license?: string | null
  home_page?: string | null
  requires_python?: string | null
  package_url: string
}

export interface EnhancedModuleConfigResponse {
  allowed_modules: ModuleInfo[]
  default_modules: string[]
  is_custom: boolean
  installed_packages: { name: string; version: string }[]
}

export interface PyPIInfoResponse {
  module_name: string
  package_name: string
  is_stdlib: boolean
  pypi_info?: PyPIInfo | null
  error?: string | null
}

export interface ModuleInstallResponse {
  module_name: string
  package_name: string
  status: string
  version?: string | null
  error_message?: string | null
}

export interface ModuleSyncResponse {
  success: boolean
  installed_count: number
  failed_count: number
  stdlib_count: number
  results: ModuleInstallResponse[]
}

// Security policy types
export interface SecurityPolicy {
  remote_tool_editing: string
  tool_approval_mode: string
  network_access_policy: string
  module_approval_mode: string
  redact_secrets_in_output: string
  log_retention_days: number
  mcp_rate_limit_rpm: number
}

export interface SecurityPolicyUpdate {
  remote_tool_editing?: string
  tool_approval_mode?: string
  network_access_policy?: string
  module_approval_mode?: string
  redact_secrets_in_output?: string
  log_retention_days?: number
  mcp_rate_limit_rpm?: number
}

// Query keys
export const settingsKeys = {
  all: ['settings'] as const,
  modules: () => [...settingsKeys.all, 'modules'] as const,
  modulesEnhanced: () => [...settingsKeys.all, 'modules', 'enhanced'] as const,
  securityPolicy: () => [...settingsKeys.all, 'security-policy'] as const,
  pypiInfo: (moduleName: string) =>
    [...settingsKeys.all, 'modules', 'pypi', moduleName] as const,
}

// API functions
export async function fetchEnhancedModuleConfig(): Promise<EnhancedModuleConfigResponse> {
  return api.get<EnhancedModuleConfigResponse>('/api/settings/modules/enhanced')
}

export async function updateModuleConfig(
  data: ModuleConfigUpdate
): Promise<ModuleConfigResponse> {
  return api.patch<ModuleConfigResponse>('/api/settings/modules', data)
}

export async function fetchPyPIInfo(
  moduleName: string
): Promise<PyPIInfoResponse> {
  return api.get<PyPIInfoResponse>(
    `/api/settings/modules/pypi/${encodeURIComponent(moduleName)}`
  )
}

export async function installModule(
  moduleName: string,
  version?: string
): Promise<ModuleInstallResponse> {
  return api.post<ModuleInstallResponse>(
    `/api/settings/modules/${encodeURIComponent(moduleName)}/install`,
    version ? { version } : {}
  )
}

export async function syncModules(): Promise<ModuleSyncResponse> {
  return api.post<ModuleSyncResponse>('/api/settings/modules/sync', {})
}

// React Query hooks
export function useEnhancedModuleConfig() {
  return useQuery({
    queryKey: settingsKeys.modulesEnhanced(),
    queryFn: fetchEnhancedModuleConfig,
  })
}

export function useUpdateModuleConfig() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: updateModuleConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: settingsKeys.modules() })
      queryClient.invalidateQueries({ queryKey: settingsKeys.modulesEnhanced() })
    },
    onError: () => {
      queryClient.invalidateQueries({ queryKey: settingsKeys.modules() })
      queryClient.invalidateQueries({ queryKey: settingsKeys.modulesEnhanced() })
    },
  })
}

export function usePyPIInfo(moduleName: string, enabled = true) {
  return useQuery({
    queryKey: settingsKeys.pypiInfo(moduleName),
    queryFn: () => fetchPyPIInfo(moduleName),
    enabled: enabled && moduleName.length > 0,
    staleTime: 5 * 60 * 1000, // Cache for 5 minutes
  })
}

export function useInstallModule() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({
      moduleName,
      version,
    }: {
      moduleName: string
      version?: string
    }) => installModule(moduleName, version),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: settingsKeys.modulesEnhanced() })
    },
  })
}

export function useSyncModules() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: syncModules,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: settingsKeys.modulesEnhanced() })
    },
  })
}

// Security policy API functions
export async function fetchSecurityPolicy(): Promise<SecurityPolicy> {
  return api.get<SecurityPolicy>('/api/settings/security-policy')
}

export async function updateSecurityPolicy(
  data: SecurityPolicyUpdate
): Promise<SecurityPolicy> {
  return api.patch<SecurityPolicy>('/api/settings/security-policy', data)
}

// Security policy hooks
export function useSecurityPolicy() {
  return useQuery({
    queryKey: settingsKeys.securityPolicy(),
    queryFn: fetchSecurityPolicy,
  })
}

export function useUpdateSecurityPolicy() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: updateSecurityPolicy,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: settingsKeys.securityPolicy() })
    },
  })
}

// Security profile presets (onboarding)
export type SecurityProfileName = 'strict' | 'balanced' | 'permissive'

export interface SecurityProfileResponse {
  profile: string
  applied_settings: Record<string, string>
}

export async function applySecurityProfile(
  profile: SecurityProfileName
): Promise<SecurityProfileResponse> {
  return api.patch<SecurityProfileResponse>('/api/settings/security-profile', { profile })
}

export async function completeOnboarding(): Promise<{ onboarding_completed: boolean }> {
  return api.post<{ onboarding_completed: boolean }>(
    '/api/settings/onboarding-complete',
    {}
  )
}
