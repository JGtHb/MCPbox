import { useState, useCallback } from 'react'
import { Header } from '../../components/Layout'
import { useExecutionStats } from '../../api/executionLogs'
import { formatDuration } from '../../components/Server/ExecutionLogsTab'
import { useActivityStream } from '../../api/activity'
import { StatCard } from './StatCard'
import { ExecutionHistoryTab } from './ExecutionHistoryTab'
import { ProtocolLogsTab } from './ProtocolLogsTab'

type ActiveTab = 'executions' | 'protocol'

export function Activity() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('executions')
  const [execTotal, setExecTotal] = useState<number | null>(null)
  const [protoTotal, setProtoTotal] = useState<number | null>(null)

  // Execution stats
  const { data: stats, isLoading: statsLoading } = useExecutionStats(24)

  // WebSocket for live indicator only
  const { connected } = useActivityStream({
    maxLogs: 1,
  })

  const handleExecTotalChange = useCallback((total: number) => {
    setExecTotal(total)
  }, [])

  const handleProtoTotalChange = useCallback((total: number) => {
    setProtoTotal(total)
  }, [])

  const successRate =
    stats && stats.total_executions > 0
      ? ((stats.successful / stats.total_executions) * 100).toFixed(1)
      : '0'

  return (
    <div className="bg-base min-h-full">
      <Header title="Activity" />
      <div className="p-4 sm:p-6">
        {/* Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4 mb-6">
          <StatCard
            title="Total Executions"
            value={stats?.total_executions ?? 0}
            subtitle={`${stats?.period_executions ?? 0} in last 24h`}
            loading={statsLoading}
          />
          <StatCard
            title="Success Rate"
            value={`${successRate}%`}
            subtitle={`${stats?.failed ?? 0} failed`}
            loading={statsLoading}
            color={stats && stats.failed > 0 ? 'red' : 'green'}
          />
          <StatCard
            title="Avg Duration"
            value={stats?.avg_duration_ms != null ? formatDuration(Math.round(stats.avg_duration_ms)) : '-'}
            loading={statsLoading}
          />
          <StatCard
            title="Active Tools"
            value={stats?.unique_tools ?? 0}
            subtitle={`${stats?.unique_users ?? 0} users`}
            loading={statsLoading}
          />
        </div>

        {/* Tabs */}
        <div className="bg-surface rounded-lg shadow mb-6">
          <div className="border-b border-hl-med">
            <nav className="flex -mb-px">
              <button
                onClick={() => setActiveTab('executions')}
                className={`px-4 sm:px-6 py-3 text-sm font-medium border-b-2 transition-colors focus:outline-none focus:ring-2 focus:ring-iris focus:ring-inset ${
                  activeTab === 'executions'
                    ? 'border-rose text-rose'
                    : 'border-transparent text-subtle hover:text-on-base hover:border-hl-high'
                }`}
              >
                Execution History
                {execTotal != null && (
                  <span className="ml-2 text-xs font-normal text-muted">
                    ({execTotal})
                  </span>
                )}
              </button>
              <button
                onClick={() => setActiveTab('protocol')}
                className={`px-4 sm:px-6 py-3 text-sm font-medium border-b-2 transition-colors focus:outline-none focus:ring-2 focus:ring-iris focus:ring-inset ${
                  activeTab === 'protocol'
                    ? 'border-rose text-rose'
                    : 'border-transparent text-subtle hover:text-on-base hover:border-hl-high'
                }`}
              >
                Protocol Logs
                {protoTotal != null && (
                  <span className="ml-2 text-xs font-normal text-muted">
                    ({protoTotal})
                  </span>
                )}
              </button>

              {/* Live indicator */}
              <div className="ml-auto flex items-center pr-4">
                <span className="flex items-center gap-1.5">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      connected ? 'bg-foam animate-pulse' : 'bg-muted'
                    }`}
                  />
                  <span className="text-xs text-subtle">
                    {connected ? 'Live' : 'Offline'}
                  </span>
                </span>
              </div>
            </nav>
          </div>

          {activeTab === 'executions' && (
            <ExecutionHistoryTab onTotalChange={handleExecTotalChange} />
          )}

          {activeTab === 'protocol' && (
            <ProtocolLogsTab onTotalChange={handleProtoTotalChange} />
          )}
        </div>
      </div>
    </div>
  )
}
