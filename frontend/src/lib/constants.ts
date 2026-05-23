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

// --- Approval Status ---

export const APPROVAL_STATUS_COLORS: Record<string, string> = {
  approved: 'bg-foam/10 text-foam',
  rejected: 'bg-love/10 text-love',
  pending_review: 'bg-gold/10 text-gold',
  pending: 'bg-gold/10 text-gold',
  draft: 'bg-overlay text-subtle',
}

export const APPROVAL_STATUS_LABELS: Record<string, string> = {
  approved: 'Approved',
  rejected: 'Rejected',
  pending_review: 'Pending',
  pending: 'Pending',
  draft: 'Draft',
}

// --- Log Level ---

export const LOG_LEVEL_COLORS: Record<string, string> = {
  debug: 'bg-overlay text-subtle',
  info: 'bg-pine/10 text-pine',
  warning: 'bg-gold/10 text-gold',
  error: 'bg-love/10 text-love',
}

export const LOG_LEVEL_LABELS: Record<string, string> = {
  debug: 'Debug',
  info: 'Info',
  warning: 'Warning',
  error: 'Error',
}
