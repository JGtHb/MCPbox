import { http, HttpResponse } from 'msw'
import type { Server, ServerDetail, ContainerStatus } from '../../api/servers'
import type { Tool, ToolListItem, CodeValidationResponse, TestCodeResponse } from '../../api/tools'

// Base URL for API requests (must match the API client's base URL)
const API_BASE = 'http://localhost:8000'

// Mock data factories
export const createMockServer = (overrides?: Partial<Server>): Server => ({
  id: 'server-1',
  name: 'Test Server',
  description: 'A test server',
  status: 'ready',
  network_mode: 'monitored',
  tool_count: 2,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
  ...overrides,
})

export const createMockServerDetail = (overrides?: Partial<ServerDetail>): ServerDetail => ({
  ...createMockServer(),
  container_id: null,
  allowed_hosts: null,
  default_timeout_ms: 30000,
  helper_code: null,
  // NOTE: allowed_modules removed - now global in Settings
  ...overrides,
})

export const createMockTool = (overrides?: Partial<Tool>): Tool => ({
  id: 'tool-1',
  server_id: 'server-1',
  name: 'test_tool',
  description: 'A test tool',
  enabled: true,
  timeout_ms: 30000,
  python_code: 'async def main(): return "test"',
  input_schema: null,
  current_version: 1,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
  ...overrides,
})

export const createMockToolListItem = (overrides?: Partial<ToolListItem>): ToolListItem => ({
  id: 'tool-1',
  name: 'test_tool',
  description: 'A test tool',
  enabled: true,
  ...overrides,
})

// Default mock data
export const mockServers: Server[] = [
  createMockServer({ id: 'server-1', name: 'API Server' }),
  createMockServer({ id: 'server-2', name: 'MCP Server' }),
]

export const mockTools: ToolListItem[] = [
  createMockToolListItem({ id: 'tool-1', name: 'get_users' }),
  createMockToolListItem({ id: 'tool-2', name: 'create_user' }),
]

// MSW handlers
export const handlers = [
  // Health endpoints
  http.get(`${API_BASE}/health`, () => {
    return HttpResponse.json({
      status: 'healthy',
      version: '0.1.0',
      database: 'connected',
    })
  }),

  http.get(`${API_BASE}/health/detail`, () => {
    return HttpResponse.json({
      status: 'healthy',
      version: '0.1.0',
      database: 'connected',
      sandbox: 'connected',
    })
  }),

  // Server endpoints
  http.get(`${API_BASE}/api/servers`, () => {
    return HttpResponse.json(mockServers)
  }),

  http.get(`${API_BASE}/api/servers/:id`, ({ params }) => {
    const server = mockServers.find((s) => s.id === params.id)
    if (!server) {
      return new HttpResponse(null, { status: 404 })
    }
    return HttpResponse.json(createMockServerDetail({ ...server }))
  }),

  http.post(`${API_BASE}/api/servers`, async ({ request }) => {
    const body = (await request.json()) as { name: string; description?: string }
    return HttpResponse.json(
      createMockServerDetail({
        id: `server-${Date.now()}`,
        name: body.name,
        description: body.description || null,
      }),
      { status: 201 }
    )
  }),

  http.patch(`${API_BASE}/api/servers/:id`, async ({ params, request }) => {
    const body = (await request.json()) as Record<string, unknown>
    const server = mockServers.find((s) => s.id === params.id)
    if (!server) {
      return new HttpResponse(null, { status: 404 })
    }
    return HttpResponse.json(createMockServerDetail({ ...server, ...body }))
  }),

  http.delete(`${API_BASE}/api/servers/:id`, ({ params }) => {
    const server = mockServers.find((s) => s.id === params.id)
    if (!server) {
      return new HttpResponse(null, { status: 404 })
    }
    return new HttpResponse(null, { status: 204 })
  }),

  http.post(`${API_BASE}/api/servers/:id/start`, ({ params }) => {
    const status: ContainerStatus = {
      server_id: params.id as string,
      container_id: `container-${params.id}`,
      status: 'running',
      health: 'healthy',
      started_at: new Date().toISOString(),
      registered_tools: 2,
    }
    return HttpResponse.json(status)
  }),

  http.post(`${API_BASE}/api/servers/:id/stop`, ({ params }) => {
    const status: ContainerStatus = {
      server_id: params.id as string,
      container_id: null,
      status: 'stopped',
      health: null,
      started_at: null,
      registered_tools: 0,
    }
    return HttpResponse.json(status)
  }),

  http.get(`${API_BASE}/api/servers/:id/status`, ({ params }) => {
    const status: ContainerStatus = {
      server_id: params.id as string,
      container_id: null,
      status: 'ready',
      health: null,
      started_at: null,
      registered_tools: 0,
    }
    return HttpResponse.json(status)
  }),

  // Tool endpoints
  http.get(`${API_BASE}/api/servers/:serverId/tools`, () => {
    return HttpResponse.json(mockTools)
  }),

  http.get(`${API_BASE}/api/tools/:id`, ({ params }) => {
    const toolListItem = mockTools.find((t) => t.id === params.id)
    if (!toolListItem) {
      return new HttpResponse(null, { status: 404 })
    }
    return HttpResponse.json(createMockTool({ ...toolListItem }))
  }),

  http.post(`${API_BASE}/api/servers/:serverId/tools`, async ({ params, request }) => {
    const body = (await request.json()) as { name: string; description?: string }
    return HttpResponse.json(
      createMockTool({
        id: `tool-${Date.now()}`,
        server_id: params.serverId as string,
        name: body.name,
        description: body.description || null,
      }),
      { status: 201 }
    )
  }),

  http.patch(`${API_BASE}/api/tools/:id`, async ({ params, request }) => {
    const body = (await request.json()) as Record<string, unknown>
    return HttpResponse.json(
      createMockTool({
        id: params.id as string,
        ...body,
      })
    )
  }),

  http.delete(`${API_BASE}/api/tools/:id`, () => {
    return new HttpResponse(null, { status: 204 })
  }),

  // Code validation endpoint
  http.post(`${API_BASE}/api/tools/validate-code`, async ({ request }) => {
    const body = (await request.json()) as { code: string }
    const hasMain = body.code.includes('def main(')

    const response: CodeValidationResponse = {
      valid: hasMain,
      has_main: hasMain,
      error: hasMain ? null : 'Code must contain a main() function',
      parameters: hasMain
        ? [{ name: 'query', type: 'str' }]
        : [],
      input_schema: hasMain
        ? { type: 'object', properties: { query: { type: 'string' } }, required: ['query'] }
        : null,
    }
    return HttpResponse.json(response)
  }),

  // Code test endpoint
  http.post(`${API_BASE}/api/tools/test-code`, async () => {
    const response: TestCodeResponse = {
      success: true,
      result: { message: 'Test passed' },
      error: null,
      error_detail: null,
      stdout: 'Execution output',
      duration_ms: 150,
      debug_info: null,
    }
    return HttpResponse.json(response)
  }),

  // Dashboard endpoint
  http.get(`${API_BASE}/api/dashboard`, () => {
    const now = new Date()
    return HttpResponse.json({
      stats: {
        total_servers: 2,
        active_servers: 1,
        total_tools: 5,
        enabled_tools: 4,
        total_requests_24h: 150,
        total_errors_24h: 3,
        error_rate_24h: 2.0,
        avg_response_time_ms: 245,
      },
      servers: [
        {
          id: 'server-1',
          name: 'API Server',
          status: 'running',
          tool_count: 3,
          requests_24h: 100,
          errors_24h: 2,
        },
        {
          id: 'server-2',
          name: 'OpenAPI Server',
          status: 'ready',
          tool_count: 2,
          requests_24h: 50,
          errors_24h: 1,
        },
      ],
      top_tools: [
        { tool_name: 'get_weather', invocations: 75, avg_duration_ms: 180 },
        { tool_name: 'get_users', invocations: 45, avg_duration_ms: 220 },
        { tool_name: 'create_order', invocations: 30, avg_duration_ms: 350 },
      ],
      recent_errors: [
        {
          message: 'Timeout exceeded',
          timestamp: new Date(now.getTime() - 3600000).toISOString(),
          tool_name: 'get_weather',
        },
      ],
      requests_over_time: Array.from({ length: 24 }, (_, i) => ({
        timestamp: new Date(now.getTime() - (23 - i) * 3600000).toISOString(),
        value: Math.floor(Math.random() * 20) + 5,
      })),
      errors_over_time: Array.from({ length: 24 }, (_, i) => ({
        timestamp: new Date(now.getTime() - (23 - i) * 3600000).toISOString(),
        value: i === 20 ? 2 : 0,
      })),
    })
  }),

  // Activity logs
  http.get(`${API_BASE}/api/activity/logs`, () => {
    return HttpResponse.json({
      items: [],
      total: 0,
      page: 1,
      page_size: 50,
      pages: 0,
    })
  }),

  // Tunnel endpoints
  http.get(`${API_BASE}/api/tunnel/status`, () => {
    return HttpResponse.json({
      status: 'disconnected',
      url: null,
      started_at: null,
      error: null,
    })
  }),

  http.post(`${API_BASE}/api/tunnel/start`, () => {
    return HttpResponse.json({
      status: 'connected',
      url: 'https://test-tunnel.trycloudflare.com',
      started_at: new Date().toISOString(),
      error: null,
    })
  }),

  http.post(`${API_BASE}/api/tunnel/stop`, () => {
    return HttpResponse.json({
      status: 'disconnected',
      url: null,
      started_at: null,
      error: null,
    })
  }),

  // Settings/Config
  http.get(`${API_BASE}/api/config`, () => {
    return HttpResponse.json({
      app_name: 'MCPbox',
      app_version: '0.1.0',
    })
  }),
]
