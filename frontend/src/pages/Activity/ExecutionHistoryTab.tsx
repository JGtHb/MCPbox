import { useState, useMemo, useEffect } from 'react'
import {
  useAllExecutionLogs,
  type AllExecutionLogsParams,
} from '../../api/executionLogs'
import { LogDetail } from '../../components/Server/ExecutionLogsTab'
import { Pagination } from '../../components/ui'

type SuccessFilter = 'all' | 'success' | 'failure'

const PAGE_SIZE_OPTIONS = [10, 20, 50] as const

interface ExecutionHistoryTabProps {
  onTotalChange?: (total: number) => void
}

export function ExecutionHistoryTab({ onTotalChange }: ExecutionHistoryTabProps) {
  const [execPage, setExecPage] = useState(1)
  const [execPageSize, setExecPageSize] = useState(20)
  const [toolNameFilter, setToolNameFilter] = useState('')
  const [successFilter, setSuccessFilter] = useState<SuccessFilter>('all')

  const execParams: AllExecutionLogsParams = useMemo(
    () => ({
      page: execPage,
      pageSize: execPageSize,
      toolName: toolNameFilter || undefined,
      success: successFilter === 'all' ? undefined : successFilter === 'success',
    }),
    [execPage, execPageSize, toolNameFilter, successFilter]
  )

  const { data: logsData, isLoading: logsLoading } = useAllExecutionLogs(execParams)

  useEffect(() => {
    if (logsData) {
      onTotalChange?.(logsData.total)
    }
  }, [logsData, onTotalChange])

  const handleToolNameChange = (value: string) => {
    setToolNameFilter(value)
    setExecPage(1)
  }

  const handleSuccessFilterChange = (value: SuccessFilter) => {
    setSuccessFilter(value)
    setExecPage(1)
  }

  const handleExecPageSizeChange = (value: number) => {
    setExecPageSize(value)
    setExecPage(1)
  }

  return (
    <div>
      {/* Execution Filters */}
      <div className="px-4 py-3 border-b border-hl-med">
        <div className="flex flex-wrap items-center gap-3 sm:gap-4">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-on-base hidden sm:inline">
              Tool:
            </span>
            <input
              type="text"
              value={toolNameFilter}
              onChange={(e) => handleToolNameChange(e.target.value)}
              placeholder="Filter by tool name..."
              className="px-3 py-1 text-sm border border-hl-med rounded-lg bg-surface text-on-base w-48 focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
            />
          </div>

          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-on-base hidden sm:inline">
              Status:
            </span>
            <div className="flex rounded-lg overflow-hidden border border-hl-med">
              {(['all', 'success', 'failure'] as SuccessFilter[]).map((f) => (
                <button
                  key={f}
                  onClick={() => handleSuccessFilterChange(f)}
                  className={`px-3 py-1 text-sm ${
                    successFilter === f
                      ? 'bg-rose text-base'
                      : 'bg-surface text-on-base hover:bg-hl-low'
                  }`}
                >
                  {f === 'all' ? 'All' : f === 'success' ? 'Success' : 'Failed'}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2 ml-auto">
            <span className="text-sm text-subtle hidden sm:inline">
              Show:
            </span>
            <select
              value={execPageSize}
              onChange={(e) => handleExecPageSizeChange(Number(e.target.value))}
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

      {/* Execution Logs List */}
      {logsLoading ? (
        <div className="p-8 text-center text-subtle">
          Loading execution logs...
        </div>
      ) : !logsData || logsData.items.length === 0 ? (
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
              d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"
            />
          </svg>
          <p className="text-subtle mb-1">No executions yet</p>
          <p className="text-xs text-muted">
            Tool executions will appear here when tools are called
          </p>
        </div>
      ) : (
        <>
          <div className="p-4 space-y-2">
            {logsData.items.map((log) => (
              <LogDetail key={log.id} log={log} />
            ))}
          </div>

          <Pagination page={execPage} totalPages={logsData.pages} onPageChange={setExecPage} />
        </>
      )}
    </div>
  )
}
