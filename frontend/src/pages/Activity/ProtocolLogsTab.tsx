import { useState, useMemo, useEffect } from 'react'
import {
  useActivityLogs,
  type ActivityLog,
  getLogTypeLabel,
  getLogTypeBadgeClasses,
  type ActivityLogsParams,
} from '../../api/activity'
import { Pagination } from '../../components/ui'
import { LOG_LEVEL_COLORS, LOG_LEVEL_LABELS } from '../../lib/constants'

const PAGE_SIZE_OPTIONS = [10, 20, 50] as const

interface ProtocolLogsTabProps {
  onTotalChange?: (total: number) => void
}

export function ProtocolLogsTab({ onTotalChange }: ProtocolLogsTabProps) {
  const [protoPage, setProtoPage] = useState(1)
  const [protoPageSize, setProtoPageSize] = useState(20)
  const [logTypeFilter, setLogTypeFilter] = useState('')
  const [levelFilter, setLevelFilter] = useState('')
  const [searchFilter, setSearchFilter] = useState('')

  const protoParams: ActivityLogsParams = useMemo(
    () => ({
      page: protoPage,
      pageSize: protoPageSize,
      logType: logTypeFilter || undefined,
      level: levelFilter || undefined,
      search: searchFilter || undefined,
    }),
    [protoPage, protoPageSize, logTypeFilter, levelFilter, searchFilter]
  )

  const { data: protoData, isLoading: protoLoading } = useActivityLogs(protoParams)

  useEffect(() => {
    if (protoData) {
      onTotalChange?.(protoData.total)
    }
  }, [protoData, onTotalChange])

  const handleLogTypeChange = (value: string) => {
    setLogTypeFilter(value)
    setProtoPage(1)
  }

  const handleLevelChange = (value: string) => {
    setLevelFilter(value)
    setProtoPage(1)
  }

  const handleSearchChange = (value: string) => {
    setSearchFilter(value)
    setProtoPage(1)
  }

  const handleProtoPageSizeChange = (value: number) => {
    setProtoPageSize(value)
    setProtoPage(1)
  }

  return (
    <div>
      {/* Protocol Filters */}
      <div className="px-4 py-3 border-b border-hl-med">
        <div className="flex flex-wrap items-center gap-3 sm:gap-4">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-on-base hidden sm:inline">
              Type:
            </span>
            <select
              value={logTypeFilter}
              onChange={(e) => handleLogTypeChange(e.target.value)}
              className="px-2 py-1 text-sm border border-hl-med rounded-lg bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
            >
              <option value="">All</option>
              <option value="mcp_request">MCP Request</option>
              <option value="mcp_response">MCP Response</option>
              <option value="network">Network</option>
              <option value="alert">Alert</option>
              <option value="error">Error</option>
              <option value="system">System</option>
              <option value="audit">Audit</option>
            </select>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-on-base hidden sm:inline">
              Level:
            </span>
            <select
              value={levelFilter}
              onChange={(e) => handleLevelChange(e.target.value)}
              className="px-2 py-1 text-sm border border-hl-med rounded-lg bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
            >
              <option value="">All</option>
              <option value="debug">Debug</option>
              <option value="info">Info</option>
              <option value="warning">Warning</option>
              <option value="error">Error</option>
            </select>
          </div>

          <div className="flex items-center gap-2 flex-1 min-w-[200px]">
            <input
              type="text"
              value={searchFilter}
              onChange={(e) => handleSearchChange(e.target.value)}
              placeholder="Search logs..."
              className="px-3 py-1 text-sm border border-hl-med rounded-lg bg-surface text-on-base w-full max-w-xs focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
            />
          </div>

          <div className="flex items-center gap-2 ml-auto">
            <span className="text-sm text-subtle hidden sm:inline">
              Show:
            </span>
            <select
              value={protoPageSize}
              onChange={(e) => handleProtoPageSizeChange(Number(e.target.value))}
              className="px-2 py-1 text-sm border border-hl-med rounded-lg bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
            >
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
            <span className="text-sm text-subtle hidden sm:inline">
              per page
            </span>
          </div>
        </div>
      </div>

      {/* Protocol Logs List */}
      {protoLoading ? (
        <div className="p-8 text-center text-subtle">
          Loading protocol logs...
        </div>
      ) : !protoData || protoData.items.length === 0 ? (
        <div className="p-8 text-center">
          <svg
            className="w-12 h-12 text-subtle mx-auto mb-3"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
            />
          </svg>
          <p className="text-subtle mb-1">No protocol logs found</p>
          <p className="text-xs text-muted">
            Protocol activity will be recorded here as MCP interactions occur
          </p>
        </div>
      ) : (
        <>
          <div className="divide-y divide-hl-low">
            {protoData.items.map((log) => (
              <ProtocolLogEntry key={log.id} log={log} />
            ))}
          </div>

          <Pagination page={protoPage} totalPages={protoData.pages} onPageChange={setProtoPage} />
        </>
      )}
    </div>
  )
}

function ProtocolLogEntry({ log }: { log: ActivityLog }) {
  const [expanded, setExpanded] = useState(false)

  const typeStyles: Record<string, string> = {
    mcp_request: 'border-l-pine',
    mcp_response: 'border-l-foam',
    error: 'border-l-love',
    alert: 'border-l-gold',
    audit: 'border-l-iris',
    network: 'border-l-iris',
    system: 'border-l-muted',
  }

  const timestamp = new Date(log.created_at).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })

  return (
    <div
      className={`px-4 py-2.5 border-l-4 cursor-pointer hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-inset focus:ring-iris ${
        typeStyles[log.log_type] || 'border-l-muted'
      }`}
      onClick={() => setExpanded(!expanded)}
      role="button"
      tabIndex={0}
      aria-expanded={expanded}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          setExpanded(!expanded)
        }
      }}
    >
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted font-mono w-28 flex-shrink-0">
          {timestamp}
        </span>
        <span
          className={`px-1.5 py-0.5 text-xs rounded flex-shrink-0 ${getLogTypeBadgeClasses(log.log_type)}`}
        >
          {getLogTypeLabel(log.log_type)}
        </span>
        <span
          className={`px-1.5 py-0.5 text-xs rounded flex-shrink-0 ${(LOG_LEVEL_COLORS[log.level] || 'bg-overlay text-on-base')}`}
        >
          {(LOG_LEVEL_LABELS[log.level] || log.level)}
        </span>
        <span className="flex-1 text-xs text-on-base truncate">
          {log.message}
        </span>
        {log.duration_ms != null && (
          <span className="text-xs text-muted font-mono flex-shrink-0">
            {log.duration_ms}ms
          </span>
        )}
        <svg
          className={`w-3.5 h-3.5 text-muted transition-transform flex-shrink-0 ${
            expanded ? 'rotate-180' : ''
          }`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </div>

      {expanded && log.details && (
        <div className="mt-2 ml-28">
          <pre className="text-xs bg-overlay text-on-base p-3 rounded overflow-x-auto max-h-48">
            {JSON.stringify(log.details, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
