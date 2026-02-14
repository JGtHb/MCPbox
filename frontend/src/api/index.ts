export { api, ApiError } from './client'
export { useHealth, fetchHealth } from './health'
export type { HealthResponse } from './types'

// Server API
export {
  useServers,
  useServer,
  useServerStatus,
  useDeleteServer,
  useStartServer,
  useStopServer,
  useRestartServer,
} from './servers'
export type { Server, ServerDetail, ContainerStatus } from './servers'

// Tool API
export { useTools } from './tools'
export type { Tool, ToolListItem } from './tools'
