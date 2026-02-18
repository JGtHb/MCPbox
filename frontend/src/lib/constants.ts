/**
 * Shared constants for the MCPbox frontend.
 * Centralized definitions for colors, labels, and other reusable values.
 */

// --- Server Status ---

export type ServerStatus = 'imported' | 'ready' | 'running' | 'stopped' | 'error'

export const STATUS_COLORS: Record<ServerStatus, string> = {
  imported: 'bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-300',
  ready: 'bg-blue-100 dark:bg-blue-900/50 text-blue-800 dark:text-blue-300',
  running: 'bg-green-100 dark:bg-green-900/50 text-green-800 dark:text-green-300',
  stopped: 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400',
  error: 'bg-red-100 dark:bg-red-900/50 text-red-800 dark:text-red-300',
}

export const STATUS_LABELS: Record<ServerStatus, string> = {
  imported: 'Imported',
  ready: 'Ready',
  running: 'Running',
  stopped: 'Stopped',
  error: 'Error',
}
