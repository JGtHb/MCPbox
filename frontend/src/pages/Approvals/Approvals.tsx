import { useState } from 'react'
import { useApprovalStats } from '../../api/approvals'
import { StatCard, TabButton } from './shared'
import { ToolsQueue } from './ToolsQueue'
import { ModuleRequestsQueue } from './ModuleRequestsQueue'
import { NetworkRequestsQueue } from './NetworkRequestsQueue'

type TabType = 'tools' | 'modules' | 'network'

export function Approvals() {
  const [activeTab, setActiveTab] = useState<TabType>('tools')
  const { data: stats, isLoading: statsLoading } = useApprovalStats()

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold text-on-base">Approval Queue</h1>
        <p className="mt-1 text-sm text-subtle">
          Review and approve tool publishing requests, module whitelist requests, and network
          access requests. Approved items appear below pending ones on each tab for easy revocation.
        </p>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard
          label="Tools"
          pendingValue={stats?.pending_tools ?? 0}
          approvedValue={stats?.approved_tools ?? 0}
          loading={statsLoading}
          onClick={() => setActiveTab('tools')}
          active={activeTab === 'tools'}
        />
        <StatCard
          label="Module Requests"
          pendingValue={stats?.pending_module_requests ?? 0}
          approvedValue={stats?.approved_module_requests ?? 0}
          loading={statsLoading}
          onClick={() => setActiveTab('modules')}
          active={activeTab === 'modules'}
        />
        <StatCard
          label="Network Requests"
          pendingValue={stats?.pending_network_requests ?? 0}
          approvedValue={stats?.approved_network_requests ?? 0}
          loading={statsLoading}
          onClick={() => setActiveTab('network')}
          active={activeTab === 'network'}
        />
      </div>

      {/* Tabs */}
      <div className="border-b border-hl-med">
        <nav className="-mb-px flex space-x-8">
          <TabButton
            label="Tools"
            count={stats?.pending_tools ?? 0}
            active={activeTab === 'tools'}
            onClick={() => setActiveTab('tools')}
          />
          <TabButton
            label="Module Requests"
            count={stats?.pending_module_requests ?? 0}
            active={activeTab === 'modules'}
            onClick={() => setActiveTab('modules')}
          />
          <TabButton
            label="Network Requests"
            count={stats?.pending_network_requests ?? 0}
            active={activeTab === 'network'}
            onClick={() => setActiveTab('network')}
          />
        </nav>
      </div>

      {/* Tab Content */}
      <div className="mt-4">
        {activeTab === 'tools' && <ToolsQueue />}
        {activeTab === 'modules' && <ModuleRequestsQueue />}
        {activeTab === 'network' && <NetworkRequestsQueue />}
      </div>
    </div>
  )
}

export default Approvals
