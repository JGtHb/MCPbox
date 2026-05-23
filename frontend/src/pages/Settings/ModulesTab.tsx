import {
  ModuleInfo,
  EnhancedModuleConfigResponse,
  PyPIInfoResponse,
} from '../../api/settings'

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
// ModulesTab component
// =============================================================================

export interface ModulesTabProps {
  moduleConfig: EnhancedModuleConfigResponse | undefined
  modulesLoading: boolean
  moduleError: string | null
  newModule: string
  setNewModule: (value: string) => void
  debouncedNewModule: string
  pypiInfo: PyPIInfoResponse | undefined
  pypiLoading: boolean
  handleAddModule: () => void
  handleRemoveModule: (moduleName: string) => void
  handleResetModules: () => void
  handleRetryInstall: (moduleName: string) => void
  handleSyncAll: () => void
  handleModuleKeyPress: (e: React.KeyboardEvent) => void
  updateModulesPending: boolean
  syncModulesPending: boolean
  installModulePending: boolean
  stdlibCount: number
  installedCount: number
  notInstalledCount: number
}

export function ModulesTab({
  moduleConfig,
  modulesLoading,
  moduleError,
  newModule,
  setNewModule,
  debouncedNewModule,
  pypiInfo,
  pypiLoading,
  handleAddModule,
  handleRemoveModule,
  handleResetModules,
  handleRetryInstall,
  handleSyncAll,
  handleModuleKeyPress,
  updateModulesPending,
  syncModulesPending,
  installModulePending,
  stdlibCount,
  installedCount,
  notInstalledCount,
}: ModulesTabProps) {
  return (
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
            disabled={syncModulesPending || updateModulesPending}
            className="text-sm px-3 py-1 text-pine hover:text-pine/80 border border-iris/50 rounded-lg disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
            title="Reinstall all third-party packages"
          >
            {syncModulesPending ? 'Syncing...' : 'Sync Packages'}
          </button>
          {moduleConfig?.is_custom && (
            <button
              onClick={handleResetModules}
              disabled={updateModulesPending}
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
                disabled={!newModule.trim() || updateModulesPending}
                className="px-4 py-2 text-sm font-medium text-base bg-iris hover:bg-iris/80 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
              >
                {updateModulesPending ? 'Adding...' : 'Add'}
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
                          disabled={installModulePending}
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
                        disabled={updateModulesPending}
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
  )
}
