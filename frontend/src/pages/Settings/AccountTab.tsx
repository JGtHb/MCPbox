import { useState, useRef, useEffect } from 'react'
import {
  useExportAll,
  useImportServers,
  downloadAsJson,
  ImportRequest,
  ImportResult,
} from '../../api/export'
import { changePassword } from '../../api/auth'
import { useAuth } from '../../contexts'

// =============================================================================
// AccountTab component
// =============================================================================

export function AccountTab() {
  // Export/Import state
  const exportAll = useExportAll()
  const importServers = useImportServers()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [importResult, setImportResult] = useState<ImportResult | null>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)

  // Password change state
  const { logout } = useAuth()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [passwordSuccess, setPasswordSuccess] = useState(false)
  const [isChangingPassword, setIsChangingPassword] = useState(false)

  // Track pending timeouts for cleanup on unmount
  const pendingTimeoutsRef = useRef<ReturnType<typeof setTimeout>[]>([])
  useEffect(() => {
    const timeouts = pendingTimeoutsRef.current
    return () => {
      timeouts.forEach(clearTimeout)
    }
  }, [])

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

  return (
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
                    Imported {importResult.servers_created} server{importResult.servers_created !== 1 ? 's' : ''}, {importResult.tools_created} tool{importResult.tools_created !== 1 ? 's' : ''}
                    {(importResult.module_requests_created > 0 || importResult.network_access_requests_created > 0) && (
                      <>, {importResult.module_requests_created + importResult.network_access_requests_created} approval request{importResult.module_requests_created + importResult.network_access_requests_created !== 1 ? 's' : ''}</>
                    )}
                  </p>
                  {importResult.errors.length > 0 && (
                    <ul className="mt-2 text-sm list-disc list-inside">
                      {importResult.errors.map((err, i) => (
                        <li key={i}>{err}</li>
                      ))}
                    </ul>
                  )}
                  {importResult.warnings?.length > 0 && (
                    <ul className="mt-2 text-sm list-disc list-inside text-gold">
                      {importResult.warnings.map((warn, i) => (
                        <li key={i}>{warn}</li>
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
  )
}
