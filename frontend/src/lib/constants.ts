/**
 * Shared constants for the MCPbox frontend.
 * Centralized definitions for colors, labels, and other reusable values.
 */

// --- Server Status ---

export type ServerStatus = 'imported' | 'ready' | 'running' | 'stopped' | 'error'

export const STATUS_COLORS: Record<ServerStatus, string> = {
  imported: 'bg-overlay text-subtle',
  ready: 'bg-pine/10 text-pine',
  running: 'bg-foam/10 text-foam',
  stopped: 'bg-overlay text-muted',
  error: 'bg-love/10 text-love',
}

export const STATUS_LABELS: Record<ServerStatus, string> = {
  imported: 'Imported',
  ready: 'Ready',
  running: 'Running',
  stopped: 'Stopped',
  error: 'Error',
}
