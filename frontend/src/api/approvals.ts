import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

// Types
export interface ToolApprovalQueueItem {
  id: string
  server_id: string
  server_name: string
  name: string
  description: string | null
  python_code: string | null
  created_by: string | null
  publish_notes: string | null
  approval_requested_at: string | null
  current_version: number
}

export interface VulnerabilityInfo {
  id: string
  summary: string
  severity: string | null
  fixed_version: string | null
  link: string | null
}

export interface PyPIPackageInfo {
  package_name: string
  is_stdlib: boolean
  is_installed: boolean
  installed_version: string | null
  latest_version: string | null
  summary: string | null
  author: string | null
  license: string | null
  home_page: string | null
  // Safety data from external sources
  vulnerabilities: VulnerabilityInfo[]
  vulnerability_count: number
  scorecard_score: number | null
  scorecard_date: string | null
  dependency_count: number | null
  source_repo: string | null
  error: string | null
}

export interface ModuleRequestQueueItem {
  id: string
  tool_id: string
  tool_name: string
  server_id: string
  server_name: string
  module_name: string
  justification: string
  requested_by: string | null
  status: string
  created_at: string
  pypi_info: PyPIPackageInfo | null
}

export interface NetworkAccessRequestQueueItem {
  id: string
  tool_id: string
  tool_name: string
  server_id: string
  server_name: string
  host: string
  port: number | null
  justification: string
  requested_by: string | null
  status: string
  created_at: string
}

export interface ApprovalDashboardStats {
  pending_tools: number
  pending_module_requests: number
  pending_network_requests: number
  recently_approved: number
  recently_rejected: number
}

interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

// API functions
export async function getApprovalStats(): Promise<ApprovalDashboardStats> {
  return api.get<ApprovalDashboardStats>('/api/approvals/stats')
}

export async function getPendingTools(
  page = 1,
  pageSize = 20,
  search?: string
): Promise<PaginatedResponse<ToolApprovalQueueItem>> {
  const params = new URLSearchParams({
    page: page.toString(),
    page_size: pageSize.toString(),
  })
  if (search) params.set('search', search)
  return api.get<PaginatedResponse<ToolApprovalQueueItem>>(
    `/api/approvals/tools?${params.toString()}`
  )
}

export async function getPendingModuleRequests(
  page = 1,
  pageSize = 20,
  search?: string
): Promise<PaginatedResponse<ModuleRequestQueueItem>> {
  const params = new URLSearchParams({
    page: page.toString(),
    page_size: pageSize.toString(),
  })
  if (search) params.set('search', search)
  return api.get<PaginatedResponse<ModuleRequestQueueItem>>(
    `/api/approvals/modules?${params.toString()}`
  )
}

export async function getPendingNetworkRequests(
  page = 1,
  pageSize = 20,
  search?: string
): Promise<PaginatedResponse<NetworkAccessRequestQueueItem>> {
  const params = new URLSearchParams({
    page: page.toString(),
    page_size: pageSize.toString(),
  })
  if (search) params.set('search', search)
  return api.get<PaginatedResponse<NetworkAccessRequestQueueItem>>(
    `/api/approvals/network?${params.toString()}`
  )
}

export async function takeToolAction(
  toolId: string,
  action: 'approve' | 'reject',
  reason?: string
): Promise<void> {
  await api.post(`/api/approvals/tools/${toolId}/action`, {
    action,
    reason,
  })
}

export async function takeModuleRequestAction(
  requestId: string,
  action: 'approve' | 'reject',
  reason?: string
): Promise<void> {
  await api.post(`/api/approvals/modules/${requestId}/action`, {
    action,
    reason,
  })
}

export async function takeNetworkRequestAction(
  requestId: string,
  action: 'approve' | 'reject',
  reason?: string
): Promise<void> {
  await api.post(`/api/approvals/network/${requestId}/action`, {
    action,
    reason,
  })
}

// Bulk action types and functions
export interface BulkActionResponse {
  success: boolean
  processed_count: number
  failed: { id: string; error: string }[]
}

export async function bulkToolAction(
  toolIds: string[],
  action: 'approve' | 'reject',
  reason?: string
): Promise<BulkActionResponse> {
  return api.post<BulkActionResponse>('/api/approvals/tools/bulk-action', {
    tool_ids: toolIds,
    action,
    reason,
  })
}

export async function bulkModuleRequestAction(
  requestIds: string[],
  action: 'approve' | 'reject',
  reason?: string
): Promise<BulkActionResponse> {
  return api.post<BulkActionResponse>('/api/approvals/modules/bulk-action', {
    request_ids: requestIds,
    action,
    reason,
  })
}

export async function bulkNetworkRequestAction(
  requestIds: string[],
  action: 'approve' | 'reject',
  reason?: string
): Promise<BulkActionResponse> {
  return api.post<BulkActionResponse>('/api/approvals/network/bulk-action', {
    request_ids: requestIds,
    action,
    reason,
  })
}

// React Query hooks
export function useApprovalStats() {
  return useQuery({
    queryKey: ['approvals', 'stats'],
    queryFn: getApprovalStats,
    refetchInterval: 30000, // Refresh every 30 seconds
  })
}

export function usePendingTools(page = 1, pageSize = 20, search?: string) {
  return useQuery({
    queryKey: ['approvals', 'tools', page, pageSize, search],
    queryFn: () => getPendingTools(page, pageSize, search),
  })
}

export function usePendingModuleRequests(page = 1, pageSize = 20, search?: string) {
  return useQuery({
    queryKey: ['approvals', 'modules', page, pageSize, search],
    queryFn: () => getPendingModuleRequests(page, pageSize, search),
  })
}

export function usePendingNetworkRequests(page = 1, pageSize = 20, search?: string) {
  return useQuery({
    queryKey: ['approvals', 'network', page, pageSize, search],
    queryFn: () => getPendingNetworkRequests(page, pageSize, search),
  })
}

export function useToolAction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      toolId,
      action,
      reason,
    }: {
      toolId: string
      action: 'approve' | 'reject'
      reason?: string
    }) => takeToolAction(toolId, action, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
    },
  })
}

export function useModuleRequestAction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      requestId,
      action,
      reason,
    }: {
      requestId: string
      action: 'approve' | 'reject'
      reason?: string
    }) => takeModuleRequestAction(requestId, action, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
    },
  })
}

export function useNetworkRequestAction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      requestId,
      action,
      reason,
    }: {
      requestId: string
      action: 'approve' | 'reject'
      reason?: string
    }) => takeNetworkRequestAction(requestId, action, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
    },
  })
}

// Bulk action hooks
export function useBulkToolAction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      toolIds,
      action,
      reason,
    }: {
      toolIds: string[]
      action: 'approve' | 'reject'
      reason?: string
    }) => bulkToolAction(toolIds, action, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
    },
  })
}

export function useBulkModuleRequestAction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      requestIds,
      action,
      reason,
    }: {
      requestIds: string[]
      action: 'approve' | 'reject'
      reason?: string
    }) => bulkModuleRequestAction(requestIds, action, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
    },
  })
}

export function useBulkNetworkRequestAction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      requestIds,
      action,
      reason,
    }: {
      requestIds: string[]
      action: 'approve' | 'reject'
      reason?: string
    }) => bulkNetworkRequestAction(requestIds, action, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
    },
  })
}
