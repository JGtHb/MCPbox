// API Response Types

export interface HealthResponse {
  status: 'healthy' | 'unhealthy'
  version: string
  database: 'connected' | 'disconnected'
  sandbox: 'connected' | 'disconnected'
}

