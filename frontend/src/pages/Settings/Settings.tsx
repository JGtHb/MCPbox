import { useState, useRef, useEffect, useCallback } from 'react'
import { Header } from '../../components/Layout'
import {
  useEnhancedModuleConfig,
  useUpdateModuleConfig,
  usePyPIInfo,
  useInstallModule,
  useSyncModules,
  useSecurityPolicy,
  useUpdateSecurityPolicy,
} from '../../api/settings'
import { useDebounce, useHashTab } from '../../hooks'
import { SecurityTab } from './SecurityTab'
import { ModulesTab } from './ModulesTab'
import { UsersTab } from './UsersTab'
import { AccountTab } from './AccountTab'

// =============================================================================
// Tab types and navigation
// =============================================================================

type SettingsTabId = 'security' | 'modules' | 'users' | 'account' | 'about'

const VALID_TABS = ['security', 'modules', 'users', 'account', 'about'] as const

const SETTINGS_TABS: { id: SettingsTabId; label: string }[] = [
  { id: 'security', label: 'Security' },
  { id: 'modules', label: 'Modules' },
  { id: 'users', label: 'Users' },
  { id: 'account', label: 'Account' },
  { id: 'about', label: 'About' },
]

// POLICY_LABELS needed for warning lookup in handlePolicyUpdate
const POLICY_WARNINGS: Record<string, { options: [string, string]; warning?: string }> = {
  remote_tool_editing: {
    options: ['disabled', 'enabled'],
    warning: 'Enabling this allows remote LLM sessions to modify your tools. Only enable if you exclusively use remote access.',
  },
  tool_approval_mode: {
    options: ['require_approval', 'auto_approve'],
    warning: 'Auto-approve means LLM-created tools become active immediately without human review.',
  },
  network_access_policy: {
    options: ['require_approval', 'allow_all_public'],
    warning: 'Allowing all public access removes the network allowlist protection.',
  },
  module_approval_mode: {
    options: ['require_approval', 'auto_approve'],
    warning: 'Auto-approve means LLM-requested modules are added to the allowlist without review.',
  },
  redact_secrets_in_output: {
    options: ['enabled', 'disabled'],
    warning: 'Disabling redaction may expose secrets in tool output returned to the LLM.',
  },
}

// =============================================================================
// Main Settings Component
// =============================================================================

export function Settings() {
  // Tab state
  const [activeTab, setActiveTab] = useHashTab<SettingsTabId>(VALID_TABS, 'security')

  // Module config state
  const { data: moduleConfig, isLoading: modulesLoading, refetch: refetchModules } = useEnhancedModuleConfig()
  const updateModules = useUpdateModuleConfig()
  const installModule = useInstallModule()
  const syncModules = useSyncModules()
  const [newModule, setNewModule] = useState('')
  const [moduleError, setModuleError] = useState<string | null>(null)

  // Debounced module name for PyPI lookup
  const debouncedNewModule = useDebounce(newModule.trim(), 500)
  const { data: pypiInfo, isLoading: pypiLoading } = usePyPIInfo(debouncedNewModule, debouncedNewModule.length > 1)

  // Track pending timeouts for cleanup on unmount
  const pendingTimeoutsRef = useRef<ReturnType<typeof setTimeout>[]>([])
  useEffect(() => {
    const timeouts = pendingTimeoutsRef.current
    return () => {
      timeouts.forEach(clearTimeout)
    }
  }, [])

  // Security policy state
  const { data: securityPolicy, isLoading: policyLoading } = useSecurityPolicy()
  const updatePolicy = useUpdateSecurityPolicy()
  const [policyError, setPolicyError] = useState<string | null>(null)
  const [policyWarning, setPolicyWarning] = useState<string | null>(null)

  const handlePolicyUpdate = async (key: string, value: string) => {
    setPolicyError(null)
    setPolicyWarning(null)

    // Show warning when switching to less-secure option
    const meta = POLICY_WARNINGS[key]
    if (meta && value === meta.options[1] && meta.warning) {
      setPolicyWarning(meta.warning)
    }

    try {
      await updatePolicy.mutateAsync({ [key]: key === 'log_retention_days' ? parseInt(value) : value })
    } catch (error) {
      setPolicyError(error instanceof Error ? error.message : 'Failed to update policy')
    }
  }

  // Module handlers
  const handleAddModule = useCallback(async () => {
    const moduleName = newModule.trim()
    if (!moduleName) return
    setModuleError(null)

    // Check if already in list
    const existingModules = moduleConfig?.allowed_modules.map(m => m.module_name) || []
    if (existingModules.includes(moduleName)) {
      setNewModule('')
      return
    }

    try {
      await updateModules.mutateAsync({ add_modules: [moduleName] })
      setNewModule('')
      // Refetch to get updated install status
      pendingTimeoutsRef.current.push(setTimeout(() => refetchModules(), 1000))
    } catch (error) {
      setModuleError(error instanceof Error ? error.message : 'Failed to add module')
    }
  }, [newModule, moduleConfig, updateModules, refetchModules])

  const handleRemoveModule = async (moduleName: string) => {
    setModuleError(null)
    try {
      await updateModules.mutateAsync({ remove_modules: [moduleName] })
    } catch (error) {
      setModuleError(error instanceof Error ? error.message : 'Failed to remove module')
    }
  }

  const handleResetModules = async () => {
    setModuleError(null)
    try {
      await updateModules.mutateAsync({ reset_to_defaults: true })
    } catch (error) {
      setModuleError(error instanceof Error ? error.message : 'Failed to reset modules')
    }
  }

  const handleRetryInstall = async (moduleName: string) => {
    setModuleError(null)
    try {
      await installModule.mutateAsync({ moduleName })
      // Refetch to get updated status
      pendingTimeoutsRef.current.push(setTimeout(() => refetchModules(), 500))
    } catch (error) {
      setModuleError(error instanceof Error ? error.message : 'Installation failed')
    }
  }

  const handleSyncAll = async () => {
    setModuleError(null)
    try {
      const result = await syncModules.mutateAsync()
      if (result.failed_count > 0) {
        setModuleError(`Sync completed with ${result.failed_count} failures`)
      }
      // Refetch to get updated status
      pendingTimeoutsRef.current.push(setTimeout(() => refetchModules(), 500))
    } catch (error) {
      setModuleError(error instanceof Error ? error.message : 'Sync failed')
    }
  }

  const handleModuleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleAddModule()
    }
  }

  // Count modules by type
  const stdlibCount = moduleConfig?.allowed_modules.filter(m => m.is_stdlib).length || 0
  const installedCount = moduleConfig?.allowed_modules.filter(m => !m.is_stdlib && m.is_installed).length || 0
  const notInstalledCount = moduleConfig?.allowed_modules.filter(m => !m.is_stdlib && !m.is_installed).length || 0

  return (
    <div>
      <Header title="Settings" />
      <div className="p-6">
        <div className="max-w-3xl">
          {/* Tab Navigation */}
          <div className="border-b border-hl-med mb-6">
            <nav className="-mb-px flex space-x-6 overflow-x-auto" aria-label="Settings tabs">
              {SETTINGS_TABS.map((tab) => {
                const isActive = tab.id === activeTab
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`whitespace-nowrap py-3 px-1 border-b-2 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-iris focus:ring-inset ${
                      isActive
                        ? 'border-rose text-rose'
                        : 'border-transparent text-subtle hover:text-on-base hover:border-hl-med'
                    }`}
                    aria-current={isActive ? 'page' : undefined}
                  >
                    {tab.label}
                  </button>
                )
              })}
            </nav>
          </div>

          {/* Tab Content */}
          <div className="space-y-6">
            {/* Security Tab */}
            {activeTab === 'security' && (
              <SecurityTab
                securityPolicy={securityPolicy}
                policyLoading={policyLoading}
                policyError={policyError}
                policyWarning={policyWarning}
                onPolicyUpdate={handlePolicyUpdate}
                updatePending={updatePolicy.isPending}
              />
            )}

            {/* Modules Tab */}
            {activeTab === 'modules' && (
              <ModulesTab
                moduleConfig={moduleConfig}
                modulesLoading={modulesLoading}
                moduleError={moduleError}
                newModule={newModule}
                setNewModule={setNewModule}
                debouncedNewModule={debouncedNewModule}
                pypiInfo={pypiInfo}
                pypiLoading={pypiLoading}
                handleAddModule={handleAddModule}
                handleRemoveModule={handleRemoveModule}
                handleResetModules={handleResetModules}
                handleRetryInstall={handleRetryInstall}
                handleSyncAll={handleSyncAll}
                handleModuleKeyPress={handleModuleKeyPress}
                updateModulesPending={updateModules.isPending}
                syncModulesPending={syncModules.isPending}
                installModulePending={installModule.isPending}
                stdlibCount={stdlibCount}
                installedCount={installedCount}
                notInstalledCount={notInstalledCount}
              />
            )}

            {/* Users Tab */}
            {activeTab === 'users' && <UsersTab />}

            {/* Account Tab */}
            {activeTab === 'account' && <AccountTab />}

            {/* About Tab */}
            {activeTab === 'about' && (
              <div className="bg-surface rounded-lg shadow p-6">
                <h3 className="text-lg font-medium text-on-base mb-4">About</h3>
                <div className="text-sm text-subtle space-y-1">
                  <p>MCPbox - MCP Server Builder</p>
                  <p>Build and deploy MCP servers with ease</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
