import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, API_URL } from './client'
import { tokens } from './auth'

// Types
export interface ActivityLog {
  id: string
  server_id: string | null
  log_type: 'mcp_request' | 'mcp_response' | 'network' | 'alert' | 'error' | 'system' | 'audit'
  level: 'debug' | 'info' | 'warning' | 'error'
  message: string
  details: Record<string, unknown> | null
  request_id: string | null
  duration_ms: number | null
  created_at: string
}

export interface ActivityStats {
  total: number
  errors: number
  avg_duration_ms: number
  by_type: Record<string, number>
  by_level: Record<string, number>
  requests_per_minute: number
}

export interface ActivityLogsListResponse {
  items: ActivityLog[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface ActivityLogsParams {
  page?: number
  pageSize?: number
  serverId?: string
  logType?: string
  level?: string
  search?: string
}

// API functions
export async function fetchActivityLogs(
  params: ActivityLogsParams = {}
): Promise<ActivityLogsListResponse> {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.pageSize) searchParams.set('page_size', String(params.pageSize))
  if (params.serverId) searchParams.set('server_id', params.serverId)
  if (params.logType) searchParams.set('log_type', params.logType)
  if (params.level) searchParams.set('level', params.level)
  if (params.search) searchParams.set('search', params.search)
  const qs = searchParams.toString()
  return api.get<ActivityLogsListResponse>(`/api/activity/logs${qs ? `?${qs}` : ''}`)
}

export async function getActivityStats(
  period: '1h' | '6h' | '24h' | '7d' = '1h',
  serverId?: string
): Promise<ActivityStats> {
  const params = new URLSearchParams({ period })
  if (serverId) params.set('server_id', serverId)
  return api.get<ActivityStats>(`/api/activity/stats?${params}`)
}

// Hooks
export function useActivityStats(period: '1h' | '6h' | '24h' | '7d' = '1h', serverId?: string) {
  return useQuery({
    queryKey: ['activity', 'stats', period, serverId],
    queryFn: () => getActivityStats(period, serverId),
    refetchInterval: 10000, // Refresh every 10 seconds
  })
}

export function useActivityLogs(params: ActivityLogsParams = {}) {
  return useQuery({
    queryKey: ['activity', 'logs', params],
    queryFn: () => fetchActivityLogs(params),
    refetchInterval: 15000,
  })
}

// WebSocket hook for live streaming
export interface WebSocketMessage {
  type: 'connected' | 'log' | 'pong' | 'filter_updated'
  data?: ActivityLog
  message?: string
  filters?: {
    server_id: string | null
    log_types: string[] | null
    levels: string[] | null
  }
}

export interface UseActivityStreamOptions {
  server_id?: string
  log_types?: string[]
  levels?: string[]
  maxLogs?: number
  enabled?: boolean
}

export function useActivityStream(options: UseActivityStreamOptions = {}) {
  const { server_id, log_types, levels, maxLogs = 500, enabled = true } = options

  const [logs, setLogs] = useState<ActivityLog[]>([])
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<number | null>(null)
  const reconnectAttemptsRef = useRef(0)

  const connect = useCallback(() => {
    if (!enabled) return

    // Build WebSocket URL from centralized API_URL
    const wsUrl = API_URL.replace(/^http/, 'ws')
    const params = new URLSearchParams()

    // SECURITY: Pass JWT token as query parameter for WebSocket auth
    // (WebSocket API doesn't support custom headers)
    const accessToken = tokens.getAccessToken()
    if (accessToken) params.set('token', accessToken)

    if (server_id) params.set('server_id', server_id)
    if (log_types?.length) params.set('log_types', log_types.join(','))
    if (levels?.length) params.set('levels', levels.join(','))

    const query = params.toString()
    const url = `${wsUrl}/api/activity/stream${query ? `?${query}` : ''}`

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      setError(null)
      reconnectAttemptsRef.current = 0
    }

    ws.onmessage = (event) => {
      try {
        const message: WebSocketMessage = JSON.parse(event.data)

        if (message.type === 'log' && message.data) {
          setLogs((prev) => {
            const newLogs = [message.data!, ...prev]
            return newLogs.slice(0, maxLogs)
          })
        }
      } catch (e) {
        // Log malformed messages for debugging but don't break the connection
        console.warn('Malformed WebSocket message:', event.data, e)
      }
    }

    ws.onclose = () => {
      setConnected(false)
      wsRef.current = null

      // Attempt reconnect with exponential backoff
      if (enabled && reconnectAttemptsRef.current < 5) {
        const delay = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current), 30000)
        reconnectAttemptsRef.current++
        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current)
        }
        reconnectTimeoutRef.current = window.setTimeout(connect, delay)
      }
    }

    ws.onerror = () => {
      setError('WebSocket connection error')
    }
  }, [enabled, server_id, log_types, levels, maxLogs])

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    setConnected(false)
  }, [])

  const updateFilters = useCallback(
    (newFilters: { server_id?: string; log_types?: string[]; levels?: string[] }) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({
            type: 'filter',
            ...newFilters,
          })
        )
      }
    },
    []
  )

  const clearLogs = useCallback(() => {
    setLogs([])
  }, [])

  // Connect on mount and when filters change
  useEffect(() => {
    if (enabled) {
      connect()
    }
    return () => {
      disconnect()
    }
  }, [connect, disconnect, enabled])

  return {
    logs,
    connected,
    error,
    updateFilters,
    clearLogs,
    reconnect: connect,
  }
}

// Utility functions
export function getLogTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    mcp_request: 'MCP Request',
    mcp_response: 'MCP Response',
    network: 'Network',
    alert: 'Alert',
    error: 'Error',
    system: 'System',
    audit: 'Audit',
  }
  return labels[type] || type
}

/**
 * Get complete Tailwind CSS classes for log type badges.
 * Note: Using full class names instead of dynamic interpolation because
 * Tailwind purges unused classes at build time.
 */
export function getLogTypeBadgeClasses(type: string): string {
  const classes: Record<string, string> = {
    mcp_request: 'bg-pine/10 text-pine',
    mcp_response: 'bg-foam/10 text-foam',
    network: 'bg-iris/10 text-iris',
    alert: 'bg-gold/10 text-gold',
    error: 'bg-love/10 text-love',
    system: 'bg-overlay text-subtle',
    audit: 'bg-iris/10 text-iris',
  }
  return classes[type] || 'bg-overlay text-subtle'
}
