import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { Header } from '../components/Layout'
import {
  ServerTabs,
  OverviewTab,
  ToolsTab,
  ExecutionLogsTab,
  ExternalSourcesTab,
  SecretsManager,
  SettingsTab,
  type TabId,
} from '../components/Server'
import { LoadingCard } from '../components/ui'
import { useServer, useServerStatus } from '../api/servers'
import { useTools } from '../api/tools'
import { useCopyToClipboard } from '../hooks/useCopyToClipboard'
import { STATUS_COLORS, STATUS_LABELS, type ServerStatus } from '../lib/constants'

// Read initial tab from URL hash
function getTabFromHash(): TabId {
  const hash = window.location.hash.replace('#', '')
  const validTabs: TabId[] = ['overview', 'tools', 'external', 'logs', 'secrets', 'settings']
  return validTabs.includes(hash as TabId) ? (hash as TabId) : 'overview'
}

export function ServerDetail() {
  const { id } = useParams<{ id: string }>()
  const [activeTab, setActiveTab] = useState<TabId>(getTabFromHash)
  const { copied, copy } = useCopyToClipboard()

  const { data: server, isLoading } = useServer(id || '')
  const { data: serverStatus } = useServerStatus(id || '', server?.status === 'running')
  const { data: tools } = useTools(id || '')

  // Sync tab to URL hash
  useEffect(() => {
    window.location.hash = activeTab
  }, [activeTab])

  // Listen for hash changes (browser back/forward)
  useEffect(() => {
    const handleHashChange = () => {
      setActiveTab(getTabFromHash())
    }
    window.addEventListener('hashchange', handleHashChange)
    return () => window.removeEventListener('hashchange', handleHashChange)
  }, [])

  if (isLoading || !server) {
    return (
      <div>
        <Header title="Server Details" />
        <div className="p-6">
          <LoadingCard lines={3} />
        </div>
      </div>
    )
  }

  const statusKey = server.status as ServerStatus
  const toolCount = tools?.length || 0

  return (
    <div>
      <Header
        title={server.name}
        action={
          <div className="flex items-center gap-3">
            <button
              onClick={() => copy(server.id)}
              className="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 font-mono flex items-center gap-1 transition-colors"
              title="Copy server ID"
            >
              {server.id.slice(0, 8)}...
              <span className="text-xs">{copied ? 'Copied' : 'Copy ID'}</span>
            </button>
            <span
              className={`px-3 py-1 text-sm font-medium rounded-full ${STATUS_COLORS[statusKey] || 'bg-gray-100 text-gray-800'}`}
              role="status"
            >
              {STATUS_LABELS[statusKey] || server.status}
            </span>
          </div>
        }
      />

      <ServerTabs activeTab={activeTab} onTabChange={setActiveTab} />

      <div className="p-6">
        {activeTab === 'overview' && (
          <OverviewTab
            server={server}
            serverStatus={serverStatus}
            toolCount={toolCount}
          />
        )}
        {activeTab === 'tools' && (
          <ToolsTab serverId={server.id} />
        )}
        {activeTab === 'external' && (
          <ExternalSourcesTab serverId={server.id} />
        )}
        {activeTab === 'logs' && (
          <ExecutionLogsTab serverId={server.id} />
        )}
        {activeTab === 'secrets' && (
          <SecretsManager serverId={server.id} />
        )}
        {activeTab === 'settings' && (
          <SettingsTab server={server} />
        )}
      </div>
    </div>
  )
}
