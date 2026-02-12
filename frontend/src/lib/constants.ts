/**
 * Shared constants for the MCPbox frontend.
 * Centralized definitions for colors, labels, and other reusable values.
 */

// --- Server Status ---

export type ServerStatus = 'imported' | 'building' | 'ready' | 'running' | 'stopped' | 'error'

export const STATUS_COLORS: Record<ServerStatus, string> = {
  imported: 'bg-gray-100 text-gray-800',
  building: 'bg-yellow-100 text-yellow-800',
  ready: 'bg-blue-100 text-blue-800',
  running: 'bg-green-100 text-green-800',
  stopped: 'bg-gray-100 text-gray-600',
  error: 'bg-red-100 text-red-800',
}

export const STATUS_LABELS: Record<ServerStatus, string> = {
  imported: 'Imported',
  building: 'Building',
  ready: 'Ready',
  running: 'Running',
  stopped: 'Stopped',
  error: 'Error',
}
