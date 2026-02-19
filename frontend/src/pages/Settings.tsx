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
import {
  useCloudflareStatus,
  useUpdateAccessPolicy,
  AccessPolicyType,
  AccessPolicyConfig,
} from '../api/cloudflare'
import { useAuth } from '../contexts'

// =============================================================================
// Tab types and navigation
// =============================================================================

type SettingsTabId = 'security' | 'modules' | 'users' | 'account' | 'about'

function getTabFromHash(): SettingsTabId {
  const hash = window.location.hash.replace('#', '')
  const validTabs: SettingsTabId[] = ['security', 'modules', 'users', 'account', 'about']
  return validTabs.includes(hash as SettingsTabId) ? (hash as SettingsTabId) : 'security'
}

const SETTINGS_TABS: { id: SettingsTabId; label: string }[] = [
  { id: 'security', label: 'Security' },
  { id: 'modules', label: 'Modules' },
  { id: 'users', label: 'Users' },
  { id: 'account', label: 'Account' },
  { id: 'about', label: 'About' },
]

// =============================================================================
// Debounce hook for PyPI lookups
// =============================================================================

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

// =============================================================================
// Module status badge component
// =============================================================================

function ModuleStatusBadge({ module }: { module: ModuleInfo }) {
  if (module.is_stdlib) {
    return (
      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-hl-low text-subtle">
        stdlib
      </span>
    )
  }

  if (module.is_installed) {
    return (
      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-foam/10 text-foam">
        {module.installed_version ? `v${module.installed_version}` : 'installed'}
      </span>
    )
  }

  if (module.error) {
    return (
      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-love/10 text-love" title={module.error}>
        failed
      </span>
    )
  }

  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-gold/10 text-gold">
      not installed
    </span>
  )
}

// =============================================================================
// Security policy toggle descriptions
// =============================================================================

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
          <span className="text-sm font-medium text-on-base">{meta.label}</span>
          {!isSecure && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-gold/10 text-gold">
              relaxed
            </span>
          )}
        </div>
        <p className="text-xs text-subtle mt-0.5">{meta.description}</p>
      </div>
      <select
        value={currentValue}
        onChange={(e) => onUpdate(settingKey, e.target.value)}
        disabled={isPending}
        className="text-sm border border-hl-med rounded-lg px-2 py-1 bg-surface text-on-base disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
      >
        <option value={meta.options[0]}>{meta.optionLabels[0]}</option>
        <option value={meta.options[1]}>{meta.optionLabels[1]}</option>
      </select>
    </div>
  )
}

// =============================================================================
// Users Tab Component
// =============================================================================

function UsersTab() {
  const { data: cfStatus, isLoading: statusLoading } = useCloudflareStatus()
  const updateAccessPolicy = useUpdateAccessPolicy()

  const [policyType, setPolicyType] = useState<AccessPolicyType>('everyone')
  const [emails, setEmails] = useState<string[]>([])
  const [emailDomain, setEmailDomain] = useState('')
  const [newEmail, setNewEmail] = useState('')
  const [emailError, setEmailError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [initialized, setInitialized] = useState(false)

  // Initialize local state from server data
  useEffect(() => {
    if (cfStatus && !initialized) {
      if (cfStatus.access_policy_type) {
        setPolicyType(cfStatus.access_policy_type as AccessPolicyType)
      }
      if (cfStatus.access_policy_emails) {
        setEmails(cfStatus.access_policy_emails)
      }
      if (cfStatus.access_policy_email_domain) {
        setEmailDomain(cfStatus.access_policy_email_domain)
      }
      setInitialized(true)
    }
  }, [cfStatus, initialized])

  const isConfigured = cfStatus?.config_id != null

  const handleAddEmail = () => {
    const email = newEmail.trim().toLowerCase()
    setEmailError(null)

    if (!email) return

    // Basic email validation
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setEmailError('Please enter a valid email address')
      return
    }

    if (emails.includes(email)) {
      setEmailError('This email is already in the list')
      return
    }

    setEmails([...emails, email])
    setNewEmail('')
  }

  const handleRemoveEmail = (emailToRemove: string) => {
    setEmails(emails.filter((e) => e !== emailToRemove))
  }

  const handleEmailKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleAddEmail()
    }
  }

  const handleSave = async () => {
    setSaveError(null)
    setSaveSuccess(null)

    if (!cfStatus?.config_id) return

    const accessPolicy: AccessPolicyConfig = {
      policy_type: policyType,
      emails: policyType === 'emails' ? emails : [],
      email_domain: policyType === 'email_domain' ? emailDomain : null,
    }

    try {
      const result = await updateAccessPolicy.mutateAsync({
        configId: cfStatus.config_id,
        accessPolicy,
      })
      setSaveSuccess(result.message || 'Access policy updated successfully')
      setTimeout(() => setSaveSuccess(null), 4000)
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : 'Failed to update access policy')
    }
  }

  if (statusLoading) {
    return (
      <div className="bg-surface rounded-lg shadow p-6">
        <div className="animate-pulse space-y-3">
          <div className="h-6 bg-hl-low rounded w-48"></div>
          <div className="h-4 bg-hl-low rounded w-96"></div>
          <div className="h-32 bg-hl-low rounded"></div>
        </div>
      </div>
    )
  }

  if (!isConfigured) {
    return (
      <div className="bg-surface rounded-lg shadow p-6">
        <h3 className="text-lg font-medium text-on-base mb-4">Approved Users</h3>
        <div className="p-4 rounded-lg bg-hl-low border border-hl-med">
          <p className="text-sm text-subtle">
            Remote access is not configured. Set up Cloudflare tunnel first.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-surface rounded-lg shadow p-6">
      <div className="mb-4">
        <h3 className="text-lg font-medium text-on-base">Approved Users</h3>
        <p className="text-sm text-subtle mt-1">
          Controls who can access MCPbox remotely via the Cloudflare tunnel. Changes are synced to the Cloudflare Access Policy.
        </p>
      </div>

      {/* Policy type radio group */}
      <div className="space-y-3 mb-6">
        <label className="block text-sm font-medium text-on-base">
          Access Policy Type
        </label>
        <div className="space-y-2">
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="radio"
              name="policyType"
              value="everyone"
              checked={policyType === 'everyone'}
              onChange={() => setPolicyType('everyone')}
              className="text-iris focus:ring-iris"
            />
            <span className="text-sm text-on-base">Everyone</span>
          </label>
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="radio"
              name="policyType"
              value="emails"
              checked={policyType === 'emails'}
              onChange={() => setPolicyType('emails')}
              className="text-iris focus:ring-iris"
            />
            <span className="text-sm text-on-base">Specific Emails</span>
          </label>
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="radio"
              name="policyType"
              value="email_domain"
              checked={policyType === 'email_domain'}
              onChange={() => setPolicyType('email_domain')}
              className="text-iris focus:ring-iris"
            />
            <span className="text-sm text-on-base">Email Domain</span>
          </label>
        </div>
      </div>

      {/* Everyone warning */}
      {policyType === 'everyone' && (
        <div className="mb-6 p-3 rounded-lg bg-gold/10 border border-gold/30">
          <div className="flex items-start gap-2">
            <svg className="w-5 h-5 text-gold flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <p className="text-sm text-gold">
              Anyone with the URL can access MCPbox remotely. This is not recommended for production use.
            </p>
          </div>
        </div>
      )}

      {/* Specific emails management */}
      {policyType === 'emails' && (
        <div className="mb-6 space-y-4">
          <div className="flex gap-2">
            <input
              type="email"
              value={newEmail}
              onChange={(e) => {
                setNewEmail(e.target.value)
                setEmailError(null)
              }}
              onKeyPress={handleEmailKeyPress}
              placeholder="user@example.com"
              className="flex-1 max-w-sm px-3 py-2 text-sm border border-hl-med rounded-lg focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris bg-surface text-on-base"
            />
            <button
              onClick={handleAddEmail}
              disabled={!newEmail.trim()}
              className="px-4 py-2 text-sm font-medium text-base bg-iris hover:bg-iris/80 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
            >
              Add
            </button>
          </div>

          {emailError && (
            <div className="text-sm text-love">
              {emailError}
            </div>
          )}

          {emails.length > 0 ? (
            <div className="border border-hl-med rounded-lg divide-y divide-hl-low max-h-60 overflow-y-auto">
              {emails.map((email) => (
                <div
                  key={email}
                  className="flex items-center justify-between px-3 py-2 hover:bg-hl-low"
                >
                  <span className="text-sm text-on-base">{email}</span>
                  <button
                    onClick={() => handleRemoveEmail(email)}
                    className="p-1 text-muted hover:text-love hover:bg-love/10 rounded transition-colors focus:outline-none focus:ring-2 focus:ring-love"
                    aria-label={`Remove ${email}`}
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div className="p-4 text-center text-sm text-subtle border border-hl-med rounded-lg">
              No approved emails. Add email addresses above.
            </div>
          )}
        </div>
      )}

      {/* Email domain input */}
      {policyType === 'email_domain' && (
        <div className="mb-6 space-y-2">
          <label className="block text-sm font-medium text-on-base">
            Allowed Domain
          </label>
          <input
            type="text"
            value={emailDomain}
            onChange={(e) => setEmailDomain(e.target.value.trim())}
            placeholder="company.com"
            className="w-full max-w-sm px-3 py-2 text-sm border border-hl-med rounded-lg focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris bg-surface text-on-base"
          />
          <p className="text-xs text-subtle">
            Any email address ending in @{emailDomain || 'domain.com'} will be allowed access.
          </p>
        </div>
      )}

      {/* Save button */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={updateAccessPolicy.isPending}
          className="px-4 py-2 bg-iris text-base rounded-lg text-sm font-medium hover:bg-iris/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
        >
          {updateAccessPolicy.isPending ? 'Saving...' : 'Save Changes'}
        </button>

        {saveSuccess && (
          <span className="text-sm text-foam">{saveSuccess}</span>
        )}
      </div>

      {saveError && (
        <div className="mt-4 p-3 rounded-lg bg-love/10 text-love border border-love/30">
          {saveError}
        </div>
      )}

      {/* Sync note */}
      <div className="mt-6 pt-4 border-t border-hl-med">
        <p className="text-xs text-subtle">
          Changes are synced to the Cloudflare Access Policy on the OIDC application. The Access Policy is the source of truth for email enforcement.
        </p>
      </div>
    </div>
  )
}

// =============================================================================
// Main Settings Component
// =============================================================================

export function Settings() {
  // Tab state
  const [activeTab, setActiveTab] = useState<SettingsTabId>(getTabFromHash)

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
              <div className="bg-surface rounded-lg shadow p-6">
                <div className="mb-4">
                  <h3 className="text-lg font-medium text-on-base">Security Policy</h3>
                  <p className="text-sm text-subtle mt-1">
                    Controls that affect security posture. Defaults are the most restrictive options.
                  </p>
                </div>

                {policyLoading ? (
                  <div className="animate-pulse space-y-3">
                    <div className="h-12 bg-hl-low rounded"></div>
                    <div className="h-12 bg-hl-low rounded"></div>
                    <div className="h-12 bg-hl-low rounded"></div>
                  </div>
                ) : securityPolicy ? (
                  <div className="space-y-1 divide-y divide-hl-low">
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
                        <span className="text-sm font-medium text-on-base">Log Retention</span>
                        <p className="text-xs text-subtle mt-0.5">
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
                          className="w-20 text-sm border border-hl-med rounded-lg px-2 py-1 bg-surface text-on-base disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
                        />
                        <span className="text-sm text-subtle">days</span>
                      </div>
                    </div>

                    {/* MCP rate limit (numeric input) */}
                    <div className="flex items-start justify-between py-3">
                      <div className="flex-1 pr-4">
                        <span className="text-sm font-medium text-on-base">MCP Rate Limit</span>
                        <p className="text-xs text-subtle mt-0.5">
                          Requests per minute for the MCP gateway. All remote users share a single IP via cloudflared.
                        </p>
                        <p className="text-xs text-muted mt-0.5">
                          The MCP gateway process requires a restart for changes to take effect.
                        </p>
                      </div>
                      <div className="flex items-center gap-1">
                        <input
                          type="number"
                          value={securityPolicy.mcp_rate_limit_rpm}
                          onChange={(e) => {
                            const val = parseInt(e.target.value)
                            if (val >= 10 && val <= 10000) {
                              handlePolicyUpdate('mcp_rate_limit_rpm', e.target.value)
                            }
                          }}
                          min={10}
                          max={10000}
                          disabled={updatePolicy.isPending}
                          className="w-24 text-sm border border-hl-med rounded-lg px-2 py-1 bg-surface text-on-base disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
                        />
                        <span className="text-sm text-subtle">req/min</span>
                      </div>
                    </div>

                    {policyWarning && (
                      <div className="pt-3">
                        <div className="text-sm text-gold bg-gold/10 border border-gold/30 rounded-lg px-3 py-2">
                          {policyWarning}
                        </div>
                      </div>
                    )}

                    {policyError && (
                      <div className="pt-3">
                        <div className="text-sm text-love bg-love/10 border border-love/30 rounded-lg px-3 py-2">
                          {policyError}
                        </div>
                      </div>
                    )}
                  </div>
                ) : null}
              </div>
            )}

            {/* Modules Tab */}
            {activeTab === 'modules' && (
              <div className="bg-surface rounded-lg shadow p-6">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="text-lg font-medium text-on-base">Python Modules</h3>
                    <p className="text-sm text-subtle mt-1">
                      Modules that can be imported in tool code. Third-party packages are auto-installed.
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleSyncAll}
                      disabled={syncModules.isPending || updateModules.isPending}
                      className="text-sm px-3 py-1 text-pine hover:text-pine/80 border border-iris/50 rounded-lg disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
                      title="Reinstall all third-party packages"
                    >
                      {syncModules.isPending ? 'Syncing...' : 'Sync Packages'}
                    </button>
                    {moduleConfig?.is_custom && (
                      <button
                        onClick={handleResetModules}
                        disabled={updateModules.isPending}
                        className="text-sm text-pine hover:text-pine/80 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-iris rounded-lg px-2 py-1 transition-colors"
                      >
                        Reset to defaults
                      </button>
                    )}
                  </div>
                </div>

                {modulesLoading ? (
                  <div className="animate-pulse space-y-2">
                    <div className="h-10 bg-hl-low rounded"></div>
                    <div className="h-40 bg-hl-low rounded"></div>
                  </div>
                ) : moduleConfig ? (
                  <div className="space-y-4">
                    {/* Status badges */}
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                          moduleConfig.is_custom
                            ? 'bg-pine/10 text-pine'
                            : 'bg-hl-low text-on-base'
                        }`}
                      >
                        {moduleConfig.is_custom ? 'Custom' : 'Defaults'}
                      </span>
                      <span className="text-xs text-subtle">
                        {stdlibCount} stdlib
                      </span>
                      <span className="text-xs text-subtle">
                        {installedCount} installed
                      </span>
                      {notInstalledCount > 0 && (
                        <span className="text-xs text-gold">
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
                          className="flex-1 max-w-sm px-3 py-2 text-sm border border-hl-med rounded-lg focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris bg-surface text-on-base"
                        />
                        <button
                          onClick={handleAddModule}
                          disabled={!newModule.trim() || updateModules.isPending}
                          className="px-4 py-2 text-sm font-medium text-base bg-iris hover:bg-iris/80 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
                        >
                          {updateModules.isPending ? 'Adding...' : 'Add'}
                        </button>
                      </div>

                      {/* PyPI info preview */}
                      {debouncedNewModule && (
                        <div className="max-w-sm">
                          {pypiLoading ? (
                            <div className="text-xs text-subtle animate-pulse">
                              Looking up package info...
                            </div>
                          ) : pypiInfo ? (
                            <div className="text-xs p-2 rounded-lg bg-hl-low border border-hl-med">
                              {pypiInfo.is_stdlib ? (
                                <span className="text-subtle">
                                  <strong>{pypiInfo.module_name}</strong> is a Python standard library module (no install needed)
                                </span>
                              ) : pypiInfo.pypi_info ? (
                                <div className="space-y-1">
                                  <div className="flex items-center gap-2">
                                    <span className="font-medium text-on-base">
                                      {pypiInfo.pypi_info.name}
                                    </span>
                                    <span className="text-subtle">v{pypiInfo.pypi_info.version}</span>
                                  </div>
                                  {pypiInfo.pypi_info.summary && (
                                    <p className="text-subtle line-clamp-2">
                                      {pypiInfo.pypi_info.summary}
                                    </p>
                                  )}
                                  {pypiInfo.module_name !== pypiInfo.package_name && (
                                    <p className="text-subtle italic">
                                      Package: {pypiInfo.package_name}
                                    </p>
                                  )}
                                </div>
                              ) : pypiInfo.error ? (
                                <span className="text-gold">
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
                      <div className="text-sm text-love bg-love/10 border border-love/30 rounded-lg px-3 py-2">
                        {moduleError}
                      </div>
                    )}

                    {/* Module list */}
                    <div className="border border-hl-med rounded-lg divide-y divide-hl-low max-h-80 overflow-y-auto">
                      {moduleConfig.allowed_modules.length === 0 ? (
                        <div className="p-4 text-center text-sm text-subtle">
                          No modules allowed. Add some modules above.
                        </div>
                      ) : (
                        moduleConfig.allowed_modules
                          .slice()
                          .sort((a, b) => a.module_name.localeCompare(b.module_name))
                          .map((module) => (
                            <div
                              key={module.module_name}
                              className="flex items-center justify-between px-3 py-2 hover:bg-hl-low"
                            >
                              <div className="flex items-center gap-2">
                                <code className="text-sm text-on-base">
                                  {module.module_name}
                                </code>
                                {module.module_name !== module.package_name && !module.is_stdlib && (
                                  <span className="text-xs text-muted">
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
                                    className="p-1 text-pine hover:text-pine/80 hover:bg-pine/10 rounded transition-colors disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-iris"
                                    aria-label="Retry installation"
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
                                  className="p-1 text-muted hover:text-love hover:bg-love/10 rounded transition-colors disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-love"
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
            )}

            {/* Users Tab */}
            {activeTab === 'users' && <UsersTab />}

            {/* Account Tab */}
            {activeTab === 'account' && (
              <>
                {/* Change Password */}
                <div className="bg-surface rounded-lg shadow p-6">
                  <h3 className="text-lg font-medium text-on-base mb-4">Change Password</h3>
                  <form onSubmit={handlePasswordChange} className="space-y-4">
                    <div>
                      <label htmlFor="current-password" className="block text-sm font-medium text-on-base mb-1">
                        Current Password
                      </label>
                      <input
                        id="current-password"
                        type="password"
                        autoComplete="current-password"
                        value={currentPassword}
                        onChange={e => setCurrentPassword(e.target.value)}
                        disabled={isChangingPassword}
                        className="w-full max-w-sm px-3 py-2 border border-hl-med rounded-lg focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris bg-surface text-on-base"
                      />
                    </div>
                    <div>
                      <label htmlFor="new-password" className="block text-sm font-medium text-on-base mb-1">
                        New Password
                      </label>
                      <input
                        id="new-password"
                        type="password"
                        autoComplete="new-password"
                        value={newPassword}
                        onChange={e => setNewPassword(e.target.value)}
                        disabled={isChangingPassword}
                        className="w-full max-w-sm px-3 py-2 border border-hl-med rounded-lg focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris bg-surface text-on-base"
                      />
                      <p className="mt-1 text-xs text-subtle">
                        Minimum 12 characters
                      </p>
                    </div>
                    <div>
                      <label htmlFor="confirm-password" className="block text-sm font-medium text-on-base mb-1">
                        Confirm New Password
                      </label>
                      <input
                        id="confirm-password"
                        type="password"
                        autoComplete="new-password"
                        value={confirmPassword}
                        onChange={e => setConfirmPassword(e.target.value)}
                        disabled={isChangingPassword}
                        className="w-full max-w-sm px-3 py-2 border border-hl-med rounded-lg focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris bg-surface text-on-base"
                      />
                    </div>

                    {passwordError && (
                      <div className="p-3 rounded-lg bg-love/10 text-love border border-love/30 max-w-sm">
                        {passwordError}
                      </div>
                    )}

                    {passwordSuccess && (
                      <div className="p-3 rounded-lg bg-foam/10 text-foam border border-foam/30 max-w-sm">
                        Password changed successfully. You will be logged out...
                      </div>
                    )}

                    <button
                      type="submit"
                      disabled={isChangingPassword || !currentPassword || !newPassword || !confirmPassword}
                      className="px-4 py-2 bg-iris text-base rounded-lg text-sm font-medium hover:bg-iris/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
                    >
                      {isChangingPassword ? 'Changing...' : 'Change Password'}
                    </button>
                  </form>
                </div>

                {/* Export/Import */}
                <div className="bg-surface rounded-lg shadow p-6">
                  <h3 className="text-lg font-medium text-on-base mb-4">Export / Import</h3>
                  <p className="text-sm text-subtle mb-4">
                    Backup your servers and tools, or migrate from another MCPbox instance.
                    Note: Credentials are not included in exports for security.
                  </p>
                  <div className="space-y-4">
                    {/* Export Section */}
                    <div className="flex items-center gap-4">
                      <button
                        onClick={handleExportAll}
                        disabled={exportAll.isPending}
                        className="px-4 py-2 bg-iris text-base rounded-lg text-sm font-medium hover:bg-iris/80 disabled:opacity-50 flex items-center gap-2 transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                        </svg>
                        {exportAll.isPending ? 'Exporting...' : 'Export All Servers'}
                      </button>
                      <span className="text-sm text-subtle">
                        Download all servers and tools as JSON
                      </span>
                    </div>

                    {/* Export Error */}
                    {exportError && (
                      <div className="p-3 rounded-lg bg-love/10 text-love border border-love/30">
                        <div className="flex items-center gap-2">
                          <svg className="w-5 h-5 text-love" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                          <span>{exportError}</span>
                        </div>
                      </div>
                    )}

                    {/* Import Section */}
                    <div className="border-t border-hl-med pt-4">
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
                          className="px-4 py-2 bg-hl-low text-on-base border border-hl-med rounded-lg text-sm font-medium hover:bg-hl-med disabled:opacity-50 flex items-center gap-2 transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                          </svg>
                          {importServers.isPending ? 'Importing...' : 'Import from File'}
                        </button>
                        <span className="text-sm text-subtle">
                          Import servers from an MCPbox export file
                        </span>
                      </div>
                    </div>

                    {/* Import Result */}
                    {importResult && (
                      <div
                        className={`p-3 rounded-lg ${
                          importResult.success
                            ? 'bg-foam/10 text-foam border border-foam/30'
                            : 'bg-gold/10 text-gold border border-gold/30'
                        }`}
                      >
                        <div className="flex items-start gap-2">
                          {importResult.success ? (
                            <svg className="w-5 h-5 text-foam flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                            </svg>
                          ) : (
                            <svg className="w-5 h-5 text-gold flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
                      <div className="p-3 rounded-lg bg-love/10 text-love border border-love/30">
                        <div className="flex items-center gap-2">
                          <svg className="w-5 h-5 text-love" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                          <span>{importError}</span>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </>
            )}

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
