import { useState, useRef, useEffect, useCallback } from 'react'
import { Header } from '../components/Layout'
import {
  useExportAll,
  useImportServers,
  downloadAsJson,
  ImportRequest,
  ImportResult,
} from '../api/export'
import { changePassword } from '../api/auth'
import {
  useEnhancedModuleConfig,
  useUpdateModuleConfig,
  usePyPIInfo,
  useInstallModule,
  useSyncModules,
  useSecurityPolicy,
  useUpdateSecurityPolicy,
  ModuleInfo,
  SecurityPolicy,
} from '../api/settings'
import { useAuth } from '../contexts'

// Debounce hook for PyPI lookups
function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value)

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value)
    }, delay)

    return () => {
      clearTimeout(handler)
    }
  }, [value, delay])

  return debouncedValue
}

// Module status badge component
function ModuleStatusBadge({ module }: { module: ModuleInfo }) {
  if (module.is_stdlib) {
    return (
      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400">
        stdlib
      </span>
    )
  }

  if (module.is_installed) {
    return (
      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
        {module.installed_version ? `v${module.installed_version}` : 'installed'}
      </span>
    )
  }

  if (module.error) {
    return (
      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400" title={module.error}>
        failed
      </span>
    )
  }

  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400">
      not installed
    </span>
  )
}

// Security policy toggle descriptions
const POLICY_LABELS: Record<string, { label: string; description: string; warning?: string; options: [string, string]; optionLabels: [string, string] }> = {
  remote_tool_editing: {
    label: 'Remote Tool Creation',
    description: 'Whether remote sessions (via Cloudflare tunnel) can create, update, or delete tools and servers.',
    warning: 'Enabling this allows remote LLM sessions to modify your tools. Only enable if you exclusively use remote access.',
    options: ['disabled', 'enabled'],
    optionLabels: ['Disabled', 'Enabled'],
  },
  tool_approval_mode: {
    label: 'Tool Approval Mode',
    description: 'Whether new tools require admin approval before becoming active.',
    warning: 'Auto-approve means LLM-created tools become active immediately without human review.',
    options: ['require_approval', 'auto_approve'],
    optionLabels: ['Require Approval', 'Auto-Approve'],
  },
  network_access_policy: {
    label: 'Network Access Policy',
    description: 'Whether tools can reach any public host, or only explicitly approved hosts.',
    warning: 'Allowing all public access removes the network allowlist protection.',
    options: ['require_approval', 'allow_all_public'],
    optionLabels: ['Require Approval', 'Allow All Public'],
  },
  module_approval_mode: {
    label: 'Module Approval Mode',
    description: 'Whether module import requests require admin approval or are auto-added.',
    warning: 'Auto-approve means LLM-requested modules are added to the allowlist without review.',
    options: ['require_approval', 'auto_approve'],
    optionLabels: ['Require Approval', 'Auto-Approve'],
  },
  redact_secrets_in_output: {
    label: 'Secret Redaction in Output',
    description: 'Whether known secret values are scrubbed from tool return values and stdout.',
    warning: 'Disabling redaction may expose secrets in tool output returned to the LLM.',
    options: ['enabled', 'disabled'],
    optionLabels: ['Enabled', 'Disabled'],
  },
}

function PolicyToggle({
  settingKey,
  policy,
  onUpdate,
  isPending,
}: {
  settingKey: string
  policy: SecurityPolicy
  onUpdate: (key: string, value: string) => void
  isPending: boolean
}) {
  const meta = POLICY_LABELS[settingKey]
  if (!meta) return null

  const currentValue = policy[settingKey as keyof SecurityPolicy] as string
  const isSecure = currentValue === meta.options[0]

  return (
    <div className="flex items-start justify-between py-3">
      <div className="flex-1 pr-4">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-900 dark:text-white">{meta.label}</span>
          {!isSecure && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400">
              relaxed
            </span>
          )}
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{meta.description}</p>
      </div>
      <select
        value={currentValue}
        onChange={(e) => onUpdate(settingKey, e.target.value)}
        disabled={isPending}
        className="text-sm border border-gray-300 dark:border-gray-600 rounded-lg px-2 py-1 bg-white dark:bg-gray-700 text-gray-900 dark:text-white disabled:opacity-50"
      >
        <option value={meta.options[0]}>{meta.optionLabels[0]}</option>
        <option value={meta.options[1]}>{meta.optionLabels[1]}</option>
      </select>
    </div>
  )
}

export function Settings() {
  // Export/Import state
  const exportAll = useExportAll()
  const importServers = useImportServers()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [importResult, setImportResult] = useState<ImportResult | null>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)

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
    return () => {
      pendingTimeoutsRef.current.forEach(clearTimeout)
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
    const meta = POLICY_LABELS[key]
    if (meta && value === meta.options[1] && meta.warning) {
      setPolicyWarning(meta.warning)
    }

    try {
      await updatePolicy.mutateAsync({ [key]: key === 'log_retention_days' ? parseInt(value) : value })
    } catch (error) {
      setPolicyError(error instanceof Error ? error.message : 'Failed to update policy')
    }
  }

  // Password change state
  const { logout } = useAuth()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [passwordSuccess, setPasswordSuccess] = useState(false)
  const [isChangingPassword, setIsChangingPassword] = useState(false)

  const handleExportAll = async () => {
    setExportError(null)
    try {
      const data = await exportAll.mutateAsync()
      const filename = `mcpbox-export-${new Date().toISOString().split('T')[0]}.json`
      downloadAsJson(data, filename)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Export failed'
      setExportError(message)
    }
  }

  const handleImportClick = () => {
    fileInputRef.current?.click()
  }

  const handleFileSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    setImportResult(null)
    setImportError(null)

    try {
      const text = await file.text()
      const data = JSON.parse(text) as ImportRequest

      // Validate basic structure
      if (!data.servers || !Array.isArray(data.servers)) {
        setImportError('Invalid export file: missing servers array')
        return
      }

      const result = await importServers.mutateAsync(data)
      setImportResult(result)
    } catch (error) {
      if (error instanceof SyntaxError) {
        setImportError('Invalid JSON file')
      } else {
        setImportError(`Import failed: ${error}`)
      }
    }

    // Clear file input
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
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

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault()
    setPasswordError(null)
    setPasswordSuccess(false)

    // Validate
    if (newPassword.length < 12) {
      setPasswordError('New password must be at least 12 characters')
      return
    }
    if (newPassword !== confirmPassword) {
      setPasswordError('Passwords do not match')
      return
    }

    setIsChangingPassword(true)

    try {
      await changePassword(currentPassword, newPassword)
      setPasswordSuccess(true)
      // Clear form
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      // Logout after short delay to show success message
      pendingTimeoutsRef.current.push(setTimeout(() => {
        logout()
      }, 2000))
    } catch (error) {
      setPasswordError(error instanceof Error ? error.message : 'Password change failed')
    } finally {
      setIsChangingPassword(false)
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
        <div className="max-w-3xl space-y-6">
          {/* Account Settings */}
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
            <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Account</h3>
            <form onSubmit={handlePasswordChange} className="space-y-4">
              <div>
                <label htmlFor="current-password" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Current Password
                </label>
                <input
                  id="current-password"
                  type="password"
                  autoComplete="current-password"
                  value={currentPassword}
                  onChange={e => setCurrentPassword(e.target.value)}
                  disabled={isChangingPassword}
                  className="w-full max-w-sm px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-700 dark:text-white"
                />
              </div>
              <div>
                <label htmlFor="new-password" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  New Password
                </label>
                <input
                  id="new-password"
                  type="password"
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={e => setNewPassword(e.target.value)}
                  disabled={isChangingPassword}
                  className="w-full max-w-sm px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-700 dark:text-white"
                />
                <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                  Minimum 12 characters
                </p>
              </div>
              <div>
                <label htmlFor="confirm-password" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Confirm New Password
                </label>
                <input
                  id="confirm-password"
                  type="password"
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={e => setConfirmPassword(e.target.value)}
                  disabled={isChangingPassword}
                  className="w-full max-w-sm px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-700 dark:text-white"
                />
              </div>

              {passwordError && (
                <div className="p-3 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-400 border border-red-200 dark:border-red-800 max-w-sm">
                  {passwordError}
                </div>
              )}

              {passwordSuccess && (
                <div className="p-3 rounded-lg bg-green-50 dark:bg-green-900/20 text-green-800 dark:text-green-400 border border-green-200 dark:border-green-800 max-w-sm">
                  Password changed successfully. You will be logged out...
                </div>
              )}

              <button
                type="submit"
                disabled={isChangingPassword || !currentPassword || !newPassword || !confirmPassword}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isChangingPassword ? 'Changing...' : 'Change Password'}
              </button>
            </form>
          </div>

          {/* Security Policy */}
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
            <div className="mb-4">
              <h3 className="text-lg font-medium text-gray-900 dark:text-white">Security Policy</h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                Controls that affect security posture. Defaults are the most restrictive options.
              </p>
            </div>

            {policyLoading ? (
              <div className="animate-pulse space-y-3">
                <div className="h-12 bg-gray-100 dark:bg-gray-700 rounded"></div>
                <div className="h-12 bg-gray-100 dark:bg-gray-700 rounded"></div>
                <div className="h-12 bg-gray-100 dark:bg-gray-700 rounded"></div>
              </div>
            ) : securityPolicy ? (
              <div className="space-y-1 divide-y divide-gray-100 dark:divide-gray-700">
                {Object.keys(POLICY_LABELS).map((key) => (
                  <PolicyToggle
                    key={key}
                    settingKey={key}
                    policy={securityPolicy}
                    onUpdate={handlePolicyUpdate}
                    isPending={updatePolicy.isPending}
                  />
                ))}

                {/* Log retention (numeric input) */}
                <div className="flex items-start justify-between py-3">
                  <div className="flex-1 pr-4">
                    <span className="text-sm font-medium text-gray-900 dark:text-white">Log Retention</span>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                      How long execution logs are kept before cleanup.
                    </p>
                  </div>
                  <div className="flex items-center gap-1">
                    <input
                      type="number"
                      value={securityPolicy.log_retention_days}
                      onChange={(e) => {
                        const val = parseInt(e.target.value)
                        if (val >= 1 && val <= 3650) {
                          handlePolicyUpdate('log_retention_days', e.target.value)
                        }
                      }}
                      min={1}
                      max={3650}
                      disabled={updatePolicy.isPending}
                      className="w-20 text-sm border border-gray-300 dark:border-gray-600 rounded-lg px-2 py-1 bg-white dark:bg-gray-700 text-gray-900 dark:text-white disabled:opacity-50"
                    />
                    <span className="text-sm text-gray-500 dark:text-gray-400">days</span>
                  </div>
                </div>

                {policyWarning && (
                  <div className="pt-3">
                    <div className="text-sm text-yellow-600 dark:text-yellow-400 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg px-3 py-2">
                      {policyWarning}
                    </div>
                  </div>
                )}

                {policyError && (
                  <div className="pt-3">
                    <div className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-3 py-2">
                      {policyError}
                    </div>
                  </div>
                )}
              </div>
            ) : null}
          </div>

          {/* Python Modules */}
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-lg font-medium text-gray-900 dark:text-white">Python Modules</h3>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  Modules that can be imported in tool code. Third-party packages are auto-installed.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleSyncAll}
                  disabled={syncModules.isPending || updateModules.isPending}
                  className="text-sm px-3 py-1 text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300 border border-blue-300 dark:border-blue-600 rounded-lg disabled:opacity-50"
                  title="Reinstall all third-party packages"
                >
                  {syncModules.isPending ? 'Syncing...' : 'Sync Packages'}
                </button>
                {moduleConfig?.is_custom && (
                  <button
                    onClick={handleResetModules}
                    disabled={updateModules.isPending}
                    className="text-sm text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300 disabled:opacity-50"
                  >
                    Reset to defaults
                  </button>
                )}
              </div>
            </div>

            {modulesLoading ? (
              <div className="animate-pulse space-y-2">
                <div className="h-10 bg-gray-100 dark:bg-gray-700 rounded"></div>
                <div className="h-40 bg-gray-100 dark:bg-gray-700 rounded"></div>
              </div>
            ) : moduleConfig ? (
              <div className="space-y-4">
                {/* Status badges */}
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                      moduleConfig.is_custom
                        ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
                        : 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300'
                    }`}
                  >
                    {moduleConfig.is_custom ? 'Custom' : 'Defaults'}
                  </span>
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    {stdlibCount} stdlib
                  </span>
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    {installedCount} installed
                  </span>
                  {notInstalledCount > 0 && (
                    <span className="text-xs text-yellow-600 dark:text-yellow-400">
                      {notInstalledCount} not installed
                    </span>
                  )}
                </div>

                {/* Add module input with PyPI preview */}
                <div className="space-y-2">
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={newModule}
                      onChange={(e) => setNewModule(e.target.value)}
                      onKeyPress={handleModuleKeyPress}
                      placeholder="Add module (e.g., requests, numpy)"
                      className="flex-1 max-w-sm px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-700 dark:text-white"
                    />
                    <button
                      onClick={handleAddModule}
                      disabled={!newModule.trim() || updateModules.isPending}
                      className="px-4 py-2 text-sm text-white bg-blue-600 hover:bg-blue-700 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {updateModules.isPending ? 'Adding...' : 'Add'}
                    </button>
                  </div>

                  {/* PyPI info preview */}
                  {debouncedNewModule && (
                    <div className="max-w-sm">
                      {pypiLoading ? (
                        <div className="text-xs text-gray-500 dark:text-gray-400 animate-pulse">
                          Looking up package info...
                        </div>
                      ) : pypiInfo ? (
                        <div className="text-xs p-2 rounded-lg bg-gray-50 dark:bg-gray-700/50 border border-gray-200 dark:border-gray-600">
                          {pypiInfo.is_stdlib ? (
                            <span className="text-gray-600 dark:text-gray-400">
                              <strong>{pypiInfo.module_name}</strong> is a Python standard library module (no install needed)
                            </span>
                          ) : pypiInfo.pypi_info ? (
                            <div className="space-y-1">
                              <div className="flex items-center gap-2">
                                <span className="font-medium text-gray-900 dark:text-white">
                                  {pypiInfo.pypi_info.name}
                                </span>
                                <span className="text-gray-500">v{pypiInfo.pypi_info.version}</span>
                              </div>
                              {pypiInfo.pypi_info.summary && (
                                <p className="text-gray-600 dark:text-gray-400 line-clamp-2">
                                  {pypiInfo.pypi_info.summary}
                                </p>
                              )}
                              {pypiInfo.module_name !== pypiInfo.package_name && (
                                <p className="text-gray-500 dark:text-gray-500 italic">
                                  Package: {pypiInfo.package_name}
                                </p>
                              )}
                            </div>
                          ) : pypiInfo.error ? (
                            <span className="text-yellow-600 dark:text-yellow-400">
                              {pypiInfo.error}
                            </span>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  )}
                </div>

                {/* Error display */}
                {moduleError && (
                  <div className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-3 py-2">
                    {moduleError}
                  </div>
                )}

                {/* Module list */}
                <div className="border border-gray-200 dark:border-gray-700 rounded-lg divide-y divide-gray-100 dark:divide-gray-700 max-h-80 overflow-y-auto">
                  {moduleConfig.allowed_modules.length === 0 ? (
                    <div className="p-4 text-center text-sm text-gray-500 dark:text-gray-400">
                      No modules allowed. Add some modules above.
                    </div>
                  ) : (
                    moduleConfig.allowed_modules
                      .slice()
                      .sort((a, b) => a.module_name.localeCompare(b.module_name))
                      .map((module) => (
                        <div
                          key={module.module_name}
                          className="flex items-center justify-between px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-700/50"
                        >
                          <div className="flex items-center gap-2">
                            <code className="text-sm text-gray-800 dark:text-gray-200">
                              {module.module_name}
                            </code>
                            {module.module_name !== module.package_name && !module.is_stdlib && (
                              <span className="text-xs text-gray-400 dark:text-gray-500">
                                ({module.package_name})
                              </span>
                            )}
                            <ModuleStatusBadge module={module} />
                          </div>
                          <div className="flex items-center gap-1">
                            {/* Retry button for failed installs */}
                            {!module.is_stdlib && !module.is_installed && (
                              <button
                                onClick={() => handleRetryInstall(module.module_name)}
                                disabled={installModule.isPending}
                                className="p-1 text-blue-500 hover:text-blue-700 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded transition-colors disabled:opacity-50"
                                title="Retry installation"
                              >
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                                </svg>
                              </button>
                            )}
                            {/* Remove button */}
                            <button
                              onClick={() => handleRemoveModule(module.module_name)}
                              disabled={updateModules.isPending}
                              className="p-1 text-gray-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-colors disabled:opacity-50"
                              aria-label={`Remove ${module.module_name}`}
                            >
                              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                              </svg>
                            </button>
                          </div>
                        </div>
                      ))
                  )}
                </div>

              </div>
            ) : null}
          </div>

          {/* Export/Import */}
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
            <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Export / Import</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
              Backup your servers and tools, or migrate from another MCPbox instance.
              Note: Credentials are not included in exports for security.
            </p>
            <div className="space-y-4">
              {/* Export Section */}
              <div className="flex items-center gap-4">
                <button
                  onClick={handleExportAll}
                  disabled={exportAll.isPending}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  {exportAll.isPending ? 'Exporting...' : 'Export All Servers'}
                </button>
                <span className="text-sm text-gray-500 dark:text-gray-400">
                  Download all servers and tools as JSON
                </span>
              </div>

              {/* Export Error */}
              {exportError && (
                <div className="p-3 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-400 border border-red-200 dark:border-red-800">
                  <div className="flex items-center gap-2">
                    <svg className="w-5 h-5 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                    <span>{exportError}</span>
                  </div>
                </div>
              )}

              {/* Import Section */}
              <div className="border-t border-gray-200 dark:border-gray-700 pt-4">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".json"
                  onChange={handleFileSelect}
                  className="hidden"
                />
                <div className="flex items-center gap-4">
                  <button
                    onClick={handleImportClick}
                    disabled={importServers.isPending}
                    className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50 flex items-center gap-2"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                    </svg>
                    {importServers.isPending ? 'Importing...' : 'Import from File'}
                  </button>
                  <span className="text-sm text-gray-500 dark:text-gray-400">
                    Import servers from an MCPbox export file
                  </span>
                </div>
              </div>

              {/* Import Result */}
              {importResult && (
                <div
                  className={`p-3 rounded-lg ${
                    importResult.success
                      ? 'bg-green-50 dark:bg-green-900/20 text-green-800 dark:text-green-400 border border-green-200 dark:border-green-800'
                      : 'bg-yellow-50 dark:bg-yellow-900/20 text-yellow-800 dark:text-yellow-400 border border-yellow-200 dark:border-yellow-800'
                  }`}
                >
                  <div className="flex items-start gap-2">
                    {importResult.success ? (
                      <svg className="w-5 h-5 text-green-500 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                    ) : (
                      <svg className="w-5 h-5 text-yellow-500 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                      </svg>
                    )}
                    <div>
                      <p className="font-medium">
                        Imported {importResult.servers_created} server{importResult.servers_created !== 1 ? 's' : ''} and {importResult.tools_created} tool{importResult.tools_created !== 1 ? 's' : ''}
                      </p>
                      {importResult.errors.length > 0 && (
                        <ul className="mt-2 text-sm list-disc list-inside">
                          {importResult.errors.map((err, i) => (
                            <li key={i}>{err}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* Import Error */}
              {importError && (
                <div className="p-3 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-400 border border-red-200 dark:border-red-800">
                  <div className="flex items-center gap-2">
                    <svg className="w-5 h-5 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                    <span>{importError}</span>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* About */}
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
            <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">About</h3>
            <div className="text-sm text-gray-600 dark:text-gray-400 space-y-1">
              <p>MCPbox - MCP Server Builder</p>
              <p>Build and deploy MCP servers with ease</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
