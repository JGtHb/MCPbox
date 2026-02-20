import { useMutation } from '@tanstack/react-query'
import { api } from './client'

// Types
export interface ExportedTool {
  name: string
  description: string | null
  enabled: boolean
  timeout_ms: number | null
  python_code: string | null
  input_schema: Record<string, unknown> | null
}

export interface ExportedServer {
  name: string
  description: string | null
  tools: ExportedTool[]
}

export interface ExportResponse {
  version: string
  exported_at: string
  servers: ExportedServer[]
}

export interface ImportRequest {
  version: string
  servers: ExportedServer[]
}

export interface ImportResult {
  success: boolean
  servers_created: number
  tools_created: number
  errors: string[]
  warnings: string[]
}

// API functions
export async function exportAllServers(): Promise<ExportResponse> {
  return api.get<ExportResponse>('/api/export/servers')
}

export async function importServers(data: ImportRequest): Promise<ImportResult> {
  return api.post<ImportResult>('/api/export/import', data)
}

// React Query hooks
export function useExportAll() {
  return useMutation({
    mutationFn: exportAllServers,
  })
}

export function useImportServers() {
  return useMutation({
    mutationFn: importServers,
  })
}

// Utility function to trigger download
export function downloadAsJson(data: unknown, filename: string) {
  const json = JSON.stringify(data, null, 2)
  const blob = new Blob([json], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  } finally {
    URL.revokeObjectURL(url)
  }
}
