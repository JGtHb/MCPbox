import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Header } from '../components/Layout'
import { useHealth } from '../api/health'
import { useDashboard } from '../api/dashboard'
import { useTunnelStatus } from '../api/tunnel'

export function Dashboard() {
  const [period, setPeriod] = useState<'1h' | '6h' | '24h' | '7d'>('24h')
  const [expandedErrorIdx, setExpandedErrorIdx] = useState<number | null>(null)
  const { data: health } = useHealth()
  const { data: tunnelStatus } = useTunnelStatus()
  const { data: dashboard, isLoading, error } = useDashboard(period)

  const formatNumber = (n: number) => {
    if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`
    if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
    return n.toString()
  }

  const formatDuration = (ms: number) => {
    if (ms < 1) return '<1ms'
    if (ms < 1000) return `${Math.round(ms)}ms`
    return `${(ms / 1000).toFixed(1)}s`
  }

  const formatChartLabel = (timestamp: string, position?: 'start' | 'end') => {
    const date = new Date(timestamp)
    if (period === '7d') {
      return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
    }
    if (period === '24h') {
      // For 24h, start and end times are always the same clock time.
      // Show "date, time" for start and just "date" for end to avoid looking identical.
      if (position === 'end') {
        return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
      }
      return date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    }
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }

  const formatBarTooltip = (timestamp: string, value: number, label: string) => {
    const date = new Date(timestamp)
    const timeStr = period === '7d' || period === '24h'
      ? date.toLocaleString()
      : date.toLocaleTimeString()
    return `${timeStr}: ${value} ${label}`
  }

  return (
    <div className="bg-base min-h-full">
      <Header title="Dashboard" />
      <div className="p-6 space-y-6">
        {/* Period Selector */}
        <div className="flex justify-end">
          <div className="inline-flex rounded-md shadow-sm">
            {(['1h', '6h', '24h', '7d'] as const).map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`px-3 py-1.5 text-sm font-medium first:rounded-l-md last:rounded-r-md border ${
                  period === p
                    ? 'bg-iris text-base border-iris'
                    : 'bg-overlay text-muted border-hl-med hover:bg-hl-low'
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          <div className="bg-surface rounded-lg shadow p-4">
            <h3 className="text-xs font-medium text-subtle uppercase">Servers</h3>
            <p className="text-2xl font-bold text-on-base">
              {isLoading ? '-' : dashboard?.stats.total_servers ?? 0}
            </p>
            <p className="text-xs text-subtle">
              {dashboard?.stats.active_servers ?? 0} active
            </p>
          </div>

          <div className="bg-surface rounded-lg shadow p-4">
            <h3 className="text-xs font-medium text-subtle uppercase">Tools</h3>
            <p className="text-2xl font-bold text-on-base">
              {isLoading ? '-' : dashboard?.stats.total_tools ?? 0}
            </p>
            <p className="text-xs text-subtle">
              {dashboard?.stats.enabled_tools ?? 0} enabled
            </p>
          </div>

          <div className="bg-surface rounded-lg shadow p-4">
            <h3 className="text-xs font-medium text-subtle uppercase">Requests</h3>
            <p className="text-2xl font-bold text-pine">
              {isLoading ? '-' : formatNumber(dashboard?.stats.total_requests_24h ?? 0)}
            </p>
            <p className="text-xs text-subtle">in {period}</p>
          </div>

          <div className="bg-surface rounded-lg shadow p-4">
            <h3 className="text-xs font-medium text-subtle uppercase">Errors</h3>
            <p
              className={`text-2xl font-bold ${
                (dashboard?.stats.total_errors_24h ?? 0) > 0 ? 'text-love' : 'text-on-base'
              }`}
            >
              {isLoading ? '-' : formatNumber(dashboard?.stats.total_errors_24h ?? 0)}
            </p>
            <p className="text-xs text-subtle">
              {dashboard?.stats.error_rate_24h?.toFixed(1) ?? 0}% rate
            </p>
          </div>

          <div className="bg-surface rounded-lg shadow p-4">
            <h3 className="text-xs font-medium text-subtle uppercase">Avg Response</h3>
            <p className="text-2xl font-bold text-on-base">
              {isLoading ? '-' : formatDuration(dashboard?.stats.avg_response_time_ms ?? 0)}
            </p>
            <p className="text-xs text-subtle">latency</p>
          </div>

          <div className="bg-surface rounded-lg shadow p-4">
            <h3 className="text-xs font-medium text-subtle uppercase">Tunnel</h3>
            <p
              className={`text-2xl font-bold ${
                tunnelStatus?.status === 'connected' ? 'text-foam' : 'text-muted'
              }`}
            >
              {tunnelStatus?.status === 'connected' ? 'Online' : 'Offline'}
            </p>
            <p className="text-xs text-subtle">
              {tunnelStatus?.status === 'connected'
                ? (tunnelStatus?.url ? 'Connected' : 'Via VPC')
                : 'Not configured'}
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Request Time Series Chart */}
          <div className="bg-surface rounded-lg shadow p-4">
            <h3 className="text-sm font-medium text-on-base mb-4">Request Volume</h3>
            {dashboard?.requests_over_time && dashboard.requests_over_time.length > 0 ? (
              <div className="h-48 flex items-end gap-0.5">
                {dashboard.requests_over_time.slice(-24).map((point, i) => {
                  const max = Math.max(...dashboard.requests_over_time.map((p) => p.value), 1)
                  const height = (point.value / max) * 100
                  return (
                    <div
                      key={i}
                      className="flex-1 bg-pine rounded-t hover:bg-pine/80 transition-colors"
                      style={{ height: `${Math.max(height, 2)}%` }}
                      title={formatBarTooltip(point.timestamp, point.value, 'requests')}
                    />
                  )
                })}
              </div>
            ) : (
              <div className="h-48 flex items-center justify-center text-muted text-sm">
                No data available
              </div>
            )}
            <div className="flex justify-between text-xs text-muted mt-2">
              <span>
                {dashboard?.requests_over_time?.[0]
                  ? formatChartLabel(dashboard.requests_over_time[0].timestamp, 'start')
                  : '-'}
              </span>
              <span>
                {dashboard?.requests_over_time?.length
                  ? formatChartLabel(dashboard.requests_over_time[dashboard.requests_over_time.length - 1].timestamp, 'end')
                  : '-'}
              </span>
            </div>
          </div>

          {/* Error Time Series */}
          <div className="bg-surface rounded-lg shadow p-4">
            <h3 className="text-sm font-medium text-on-base mb-4">Errors Over Time</h3>
            {dashboard?.errors_over_time && dashboard.errors_over_time.some((p) => p.value > 0) ? (
              <div className="h-48 flex items-end gap-0.5">
                {dashboard.errors_over_time.slice(-24).map((point, i) => {
                  const max = Math.max(...dashboard.errors_over_time.map((p) => p.value), 1)
                  const height = (point.value / max) * 100
                  return (
                    <div
                      key={i}
                      className="flex-1 bg-love rounded-t hover:bg-love/80 transition-colors"
                      style={{ height: `${Math.max(height, point.value > 0 ? 5 : 0)}%` }}
                      title={formatBarTooltip(point.timestamp, point.value, 'errors')}
                    />
                  )
                })}
              </div>
            ) : (
              <div className="h-48 flex items-center justify-center text-foam text-sm">
                No errors in this period
              </div>
            )}
            <div className="flex justify-between text-xs text-muted mt-2">
              <span>
                {dashboard?.errors_over_time?.[0]
                  ? formatChartLabel(dashboard.errors_over_time[0].timestamp, 'start')
                  : '-'}
              </span>
              <span>
                {dashboard?.errors_over_time?.length
                  ? formatChartLabel(dashboard.errors_over_time[dashboard.errors_over_time.length - 1].timestamp, 'end')
                  : '-'}
              </span>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Server Summary */}
          <div className="bg-surface rounded-lg shadow p-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium text-on-base">Servers</h3>
              <Link to="/servers" className="text-xs text-pine hover:text-pine/80">
                View all
              </Link>
            </div>
            {dashboard?.servers && dashboard.servers.length > 0 ? (
              <div className="space-y-2">
                {dashboard.servers.slice(0, 5).map((server) => (
                  <Link
                    key={server.id}
                    to={`/servers/${server.id}`}
                    className="block p-2 rounded hover:bg-hl-low transition-colors"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span
                          className={`w-2 h-2 rounded-full ${
                            server.status === 'running'
                              ? 'bg-foam'
                              : server.status === 'deployed'
                              ? 'bg-pine'
                              : 'bg-hl-high'
                          }`}
                        />
                        <span className="text-sm font-medium text-on-base truncate max-w-[140px]">
                          {server.name}
                        </span>
                      </div>
                      <div className="text-xs text-subtle">
                        {server.tool_count} tools
                      </div>
                    </div>
                    <div className="flex items-center justify-between mt-1 text-xs text-muted">
                      <span>{server.requests_24h} requests</span>
                      {server.errors_24h > 0 && (
                        <span className="text-love">{server.errors_24h} errors</span>
                      )}
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 text-subtle text-sm">
                <p>No servers yet</p>
                <p className="text-muted mt-1">
                  Use <code className="bg-overlay px-1 rounded">mcpbox_create_server</code> to create one
                </p>
              </div>
            )}
          </div>

          {/* Top Tools */}
          <div className="bg-surface rounded-lg shadow p-4">
            <h3 className="text-sm font-medium text-on-base mb-4">Top Tools</h3>
            {dashboard?.top_tools && dashboard.top_tools.length > 0 ? (
              <div className="space-y-3">
                {dashboard.top_tools.map((tool, i) => (
                  <div key={`${tool.tool_name}-${tool.server_name}`} className="flex items-center gap-3">
                    <span className="text-xs font-medium text-muted w-4">{i + 1}</span>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-on-base truncate">
                        {tool.tool_name}
                      </div>
                      <div className="text-xs text-subtle">
                        {tool.server_name && <span>{tool.server_name} · </span>}
                        {tool.invocations} calls · {formatDuration(tool.avg_duration_ms)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 text-subtle text-sm">
                <p>No tool usage data</p>
                <p className="text-xs text-muted mt-1">
                  Statistics appear after tools are executed
                </p>
              </div>
            )}
          </div>

          {/* Recent Errors */}
          <div className="bg-surface rounded-lg shadow p-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium text-on-base">Recent Errors</h3>
              <Link to="/activity?level=error" className="text-xs text-pine hover:text-pine/80">
                View all
              </Link>
            </div>
            {dashboard?.recent_errors && dashboard.recent_errors.length > 0 ? (
              <div className="space-y-3">
                {dashboard.recent_errors.slice(0, 5).map((err, i) => (
                  <div
                    key={i}
                    className="text-sm cursor-pointer hover:bg-hl-low rounded p-1 -m-1 transition-colors"
                    onClick={() => setExpandedErrorIdx(expandedErrorIdx === i ? null : i)}
                  >
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-love shrink-0" />
                      <span className={`text-on-base ${expandedErrorIdx === i ? '' : 'truncate'}`}>
                        {err.message}
                      </span>
                    </div>
                    <div className="text-xs text-muted ml-4 mt-0.5">
                      {new Date(err.timestamp).toLocaleString()}
                      {err.tool_name && ` · ${err.tool_name}`}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 text-foam text-sm">
                No recent errors
              </div>
            )}
          </div>
        </div>

        {/* System Status */}
        <div className="bg-surface rounded-lg shadow p-4">
          <h3 className="text-sm font-medium text-on-base mb-4">System Status</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="flex items-center gap-3">
              <span
                className={`w-3 h-3 rounded-full ${
                  health?.status === 'healthy' ? 'bg-foam' : 'bg-love'
                }`}
              />
              <div>
                <div className="text-sm font-medium text-on-base">Backend API</div>
                <div className="text-xs text-subtle">
                  {health?.status === 'healthy' ? 'Healthy' : 'Unhealthy'}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <span
                className={`w-3 h-3 rounded-full ${
                  health?.database === 'connected' ? 'bg-foam' : 'bg-love'
                }`}
              />
              <div>
                <div className="text-sm font-medium text-on-base">Database</div>
                <div className="text-xs text-subtle">
                  {health?.database === 'connected' ? 'Connected' : 'Disconnected'}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <span
                className={`w-3 h-3 rounded-full ${
                  health?.sandbox === 'connected' ? 'bg-foam' : 'bg-love'
                }`}
              />
              <div>
                <div className="text-sm font-medium text-on-base">Sandbox</div>
                <div className="text-xs text-subtle">
                  {health?.sandbox === 'connected' ? 'Running' : 'Stopped'}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <span
                className={`w-3 h-3 rounded-full ${
                  tunnelStatus?.status === 'connected' ? 'bg-foam' : 'bg-hl-high'
                }`}
              />
              <div>
                <div className="text-sm font-medium text-on-base">Tunnel</div>
                <div className="text-xs text-subtle">
                  {tunnelStatus?.status === 'connected' ? 'Connected' : 'Offline'}
                </div>
              </div>
            </div>
          </div>
        </div>

        {error && (
          <div className="bg-love/10 border border-love/30 rounded-lg p-4 text-sm text-love">
            Failed to load dashboard data: {error instanceof Error ? error.message : 'Unknown error'}
          </div>
        )}
      </div>
    </div>
  )
}
