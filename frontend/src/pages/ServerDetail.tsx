import { useState, useEffect, useCallback } from 'react'
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

  const [importToast, setImportToast] = useState<string | null>(null)

  const { data: server, isLoading } = useServer(id || '')
  const { data: serverStatus } = useServerStatus(id || '', server?.status === 'running')
  const { data: tools } = useTools(id || '')

  const handleImportSuccess = useCallback((count: number) => {
    setActiveTab('tools')
    setImportToast(`${count} tool${count !== 1 ? 's' : ''} imported successfully`)
    setTimeout(() => setImportToast(null), 4000)
  }, [])

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
        {/* Import success toast */}
        {importToast && (
          <div className="mb-4 p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg flex items-center justify-between">
            <div className="flex items-center gap-2">
              <svg className="h-5 w-5 text-green-600 dark:text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              <span className="text-sm font-medium text-green-800 dark:text-green-300">{importToast}</span>
            </div>
            <button
              onClick={() => setImportToast(null)}
              className="text-green-600 dark:text-green-400 hover:text-green-800 dark:hover:text-green-200"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        )}

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
          <ExternalSourcesTab serverId={server.id} onImportSuccess={handleImportSuccess} />
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
