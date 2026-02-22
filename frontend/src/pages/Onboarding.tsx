import { useState } from 'react'
import { applySecurityProfile, completeOnboarding, SecurityProfileName } from '../api/settings'

interface OnboardingProps {
  onComplete: (redirectToTunnel: boolean) => void
}

const PROFILES: {
  id: SecurityProfileName
  label: string
  description: string
  details: string[]
  badge?: string
}[] = [
  {
    id: 'strict',
    label: 'Strict',
    description: 'Review every tool, module, and network request before it goes live.',
    details: [
      'Tool approval required',
      'Module approval required',
      'Network allowlist enforced',
      'Remote tool editing disabled',
    ],
    badge: 'Recommended',
  },
  {
    id: 'balanced',
    label: 'Balanced',
    description: 'Tools and modules are auto-approved; network access still requires review.',
    details: [
      'Tools auto-approved',
      'Modules auto-approved',
      'Network allowlist enforced',
      'Remote tool editing disabled',
    ],
  },
  {
    id: 'permissive',
    label: 'Permissive',
    description: 'Everything auto-approved. Best for trusted or local-only environments.',
    details: [
      'Tools auto-approved',
      'Modules auto-approved',
      'All public network access allowed',
      'Remote tool editing enabled',
    ],
  },
]

export function Onboarding({ onComplete }: OnboardingProps) {
  const [step, setStep] = useState<1 | 2>(1)
  const [selectedProfile, setSelectedProfile] = useState<SecurityProfileName>('strict')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleApplyProfile = async () => {
    setError(null)
    setIsLoading(true)
    try {
      await applySecurityProfile(selectedProfile)
      setStep(2)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to apply security profile')
    } finally {
      setIsLoading(false)
    }
  }

  const handleFinish = async (setupTunnel: boolean) => {
    setError(null)
    setIsLoading(true)
    try {
      await completeOnboarding()
      onComplete(setupTunnel)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to complete onboarding')
    } finally {
      setIsLoading(false)
    }
  }

  const handleSkip = async () => {
    setError(null)
    setIsLoading(true)
    try {
      await completeOnboarding()
      onComplete(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to complete onboarding')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-base/80" role="dialog" aria-modal="true">
      <div className="relative bg-surface rounded-lg shadow-xl w-full max-w-lg mx-4 p-6 sm:p-8">
        {/* Skip button */}
        <button
          onClick={handleSkip}
          disabled={isLoading}
          className="absolute top-4 right-4 text-muted hover:text-on-base text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-iris rounded"
          aria-label="Skip onboarding"
        >
          Skip
        </button>

        {/* Step indicator */}
        <div className="flex items-center justify-center gap-2 mb-6">
          <div
            className={`h-2 w-8 rounded-full transition-colors ${
              step === 1 ? 'bg-iris' : 'bg-hl-med'
            }`}
          />
          <div
            className={`h-2 w-8 rounded-full transition-colors ${
              step === 2 ? 'bg-iris' : 'bg-hl-med'
            }`}
          />
        </div>

        {step === 1 && (
          <SecurityProfileStep
            selectedProfile={selectedProfile}
            onSelect={setSelectedProfile}
            onNext={handleApplyProfile}
            isLoading={isLoading}
            error={error}
          />
        )}

        {step === 2 && (
          <RemoteAccessStep
            onSetupNow={() => handleFinish(true)}
            onSkip={() => handleFinish(false)}
            isLoading={isLoading}
            error={error}
          />
        )}
      </div>
    </div>
  )
}

function SecurityProfileStep({
  selectedProfile,
  onSelect,
  onNext,
  isLoading,
  error,
}: {
  selectedProfile: SecurityProfileName
  onSelect: (profile: SecurityProfileName) => void
  onNext: () => void
  isLoading: boolean
  error: string | null
}) {
  return (
    <div>
      <h2 className="text-xl font-semibold text-on-base text-center mb-1">
        Security Defaults
      </h2>
      <p className="text-sm text-subtle text-center mb-6">
        Choose how MCPbox handles tool and module approvals. You can change these anytime in Settings.
      </p>

      <div className="space-y-3">
        {PROFILES.map(profile => (
          <button
            key={profile.id}
            onClick={() => onSelect(profile.id)}
            className={`w-full text-left rounded-lg border p-4 transition-colors focus:outline-none focus:ring-2 focus:ring-iris ${
              selectedProfile === profile.id
                ? 'border-iris bg-iris/5'
                : 'border-hl-med hover:border-hl-high'
            }`}
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sm font-medium text-on-base">{profile.label}</span>
              {profile.badge && (
                <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-iris/10 text-iris">
                  {profile.badge}
                </span>
              )}
              {selectedProfile === profile.id && (
                <svg
                  className="ml-auto h-5 w-5 text-iris flex-shrink-0"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  aria-hidden="true"
                >
                  <path
                    fillRule="evenodd"
                    d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z"
                    clipRule="evenodd"
                  />
                </svg>
              )}
            </div>
            <p className="text-xs text-subtle mb-2">{profile.description}</p>
            <div className="flex flex-wrap gap-1.5">
              {profile.details.map(detail => (
                <span
                  key={detail}
                  className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-hl-low text-muted"
                >
                  {detail}
                </span>
              ))}
            </div>
          </button>
        ))}
      </div>

      {error && <ErrorMessage message={error} />}

      <button
        onClick={onNext}
        disabled={isLoading}
        className="mt-6 w-full flex justify-center py-2.5 px-4 text-sm font-medium rounded-lg text-base bg-iris hover:bg-iris/80 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-iris disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {isLoading ? 'Applying...' : 'Continue'}
      </button>
    </div>
  )
}

function RemoteAccessStep({
  onSetupNow,
  onSkip,
  isLoading,
  error,
}: {
  onSetupNow: () => void
  onSkip: () => void
  isLoading: boolean
  error: string | null
}) {
  return (
    <div>
      <h2 className="text-xl font-semibold text-on-base text-center mb-1">
        Remote Access
      </h2>
      <p className="text-sm text-subtle text-center mb-6">
        Connect MCPbox to Cloudflare so you can use it from claude.ai, mobile, and other MCP clients.
      </p>

      <div className="rounded-lg border border-hl-med p-4 mb-6">
        <div className="flex items-start gap-3">
          <svg
            className="h-6 w-6 text-iris flex-shrink-0 mt-0.5"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={1.5}
            stroke="currentColor"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418"
            />
          </svg>
          <div>
            <p className="text-sm font-medium text-on-base mb-1">What this enables</p>
            <ul className="space-y-1 text-xs text-subtle">
              <li>Use your tools from claude.ai via the MCP Portal</li>
              <li>Access MCPbox from any device, anywhere</li>
              <li>Secured with Cloudflare Access + OAuth 2.1</li>
            </ul>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-hl-med p-4 mb-6">
        <div className="flex items-start gap-3">
          <svg
            className="h-6 w-6 text-subtle flex-shrink-0 mt-0.5"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={1.5}
            stroke="currentColor"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z"
            />
          </svg>
          <div>
            <p className="text-sm text-subtle">
              You only need this if you want remote access. For local-only use (e.g., Claude Desktop on the same machine), you can skip this.
            </p>
          </div>
        </div>
      </div>

      {error && <ErrorMessage message={error} />}

      <div className="space-y-3">
        <button
          onClick={onSetupNow}
          disabled={isLoading}
          className="w-full flex justify-center py-2.5 px-4 text-sm font-medium rounded-lg text-base bg-iris hover:bg-iris/80 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-iris disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isLoading ? 'Finishing...' : 'Set up Remote Access'}
        </button>
        <button
          onClick={onSkip}
          disabled={isLoading}
          className="w-full flex justify-center py-2.5 px-4 text-sm font-medium rounded-lg bg-hl-low text-subtle hover:bg-hl-med border border-hl-med focus:outline-none focus:ring-2 focus:ring-iris disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isLoading ? 'Finishing...' : 'Skip for now'}
        </button>
      </div>
    </div>
  )
}

function ErrorMessage({ message }: { message: string }) {
  return (
    <div className="mt-4 rounded-md bg-love/10 p-3">
      <p className="text-sm text-love">{message}</p>
    </div>
  )
}
