import { SecurityPolicy } from '../../api/settings'

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
// SecurityTab component
// =============================================================================

export interface SecurityTabProps {
  securityPolicy: SecurityPolicy | undefined
  policyLoading: boolean
  policyError: string | null
  policyWarning: string | null
  onPolicyUpdate: (key: string, value: string) => void
  updatePending: boolean
}

export function SecurityTab({
  securityPolicy,
  policyLoading,
  policyError,
  policyWarning,
  onPolicyUpdate,
  updatePending,
}: SecurityTabProps) {
  return (
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
              onUpdate={onPolicyUpdate}
              isPending={updatePending}
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
                    onPolicyUpdate('log_retention_days', e.target.value)
                  }
                }}
                min={1}
                max={3650}
                disabled={updatePending}
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
                    onPolicyUpdate('mcp_rate_limit_rpm', e.target.value)
                  }
                }}
                min={10}
                max={10000}
                disabled={updatePending}
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
  )
}
