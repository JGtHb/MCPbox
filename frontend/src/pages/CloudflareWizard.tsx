import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Header } from '../components/Layout'
import { ConfirmModal } from '../components/ui'
import { ApiError } from '../api/client'
import {
  useCloudflareStatus,
  useStartWithApiToken,
  useSetApiToken,
  useCreateTunnel,
  useCreateVpcService,
  useDeployWorker,
  useConfigureWorkerJwt,
  useTeardown,
  useUpdateWorkerConfig,
  cloudflareKeys,
  AccessPolicyType,
  getZones,
  Zone,
} from '../api/cloudflare'

// Step status indicator
function StepStatus({
  step,
  currentStep,
  completedStep,
}: {
  step: number
  currentStep: number
  completedStep: number
}) {
  const isComplete = completedStep >= step
  const isCurrent = currentStep === step
  const isPending = step > completedStep && step !== currentStep

  return (
    <div
      className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
        isComplete
          ? 'bg-foam text-base'
          : isCurrent
            ? 'bg-rose text-base'
            : isPending
              ? 'bg-hl-med text-muted'
              : 'bg-hl-med text-muted'
      }`}
    >
      {isComplete ? (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      ) : (
        step
      )}
    </div>
  )
}

// Progress stepper
function ProgressStepper({
  currentStep,
  completedStep,
}: {
  currentStep: number
  completedStep: number
}) {
  const steps = [
    { step: 1, label: 'API Token' },
    { step: 2, label: 'Tunnel' },
    { step: 3, label: 'VPC Service' },
    { step: 4, label: 'Worker' },
    { step: 5, label: 'Access' },
    { step: 6, label: 'Connect' },
  ]

  return (
    <div className="flex items-center justify-between mb-8">
      {steps.map((s, index) => (
        <div key={s.step} className="flex items-center">
          <div className="flex flex-col items-center">
            <StepStatus step={s.step} currentStep={currentStep} completedStep={completedStep} />
            <span className="mt-1 text-xs text-muted hidden sm:block">
              {s.label}
            </span>
          </div>
          {index < steps.length - 1 && (
            <div
              className={`w-8 sm:w-12 h-0.5 mx-1 sm:mx-2 ${
                completedStep >= s.step + 1
                  ? 'bg-foam'
                  : 'bg-hl-med'
              }`}
            />
          )}
        </div>
      ))}
    </div>
  )
}

// Step card wrapper
function StepCard({
  step,
  title,
  description,
  isActive,
  isComplete,
  onEdit,
  children,
}: {
  step: number
  title: string
  description: string
  isActive: boolean
  isComplete: boolean
  onEdit?: () => void
  children: React.ReactNode
}) {
  return (
    <div
      className={`bg-surface rounded-lg shadow p-4 sm:p-6 mb-4 ${
        isActive ? 'ring-2 ring-iris' : ''
      } ${isComplete && !isActive ? 'opacity-75' : ''}`}
    >
      <div className="flex items-start gap-4">
        <StepStatus step={step} currentStep={isActive ? step : 0} completedStep={isComplete ? step : step - 1} />
        <div className="flex-1">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-lg font-medium text-on-base">{title}</h3>
              <p className="text-sm text-muted mt-1">{description}</p>
            </div>
            {isComplete && !isActive && onEdit && (
              <button
                onClick={onEdit}
                className="px-3 py-1.5 text-sm bg-hl-low hover:bg-hl-med text-subtle rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
              >
                Edit
              </button>
            )}
          </div>
          {(isActive || isComplete) && <div className="mt-4">{children}</div>}
        </div>
      </div>
    </div>
  )
}

// Copy button component
function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard API not available
    }
  }

  return (
    <button
      onClick={handleCopy}
      className="px-3 py-1.5 bg-hl-low hover:bg-hl-med text-subtle rounded-md text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
    >
      {copied ? 'Copied!' : label}
    </button>
  )
}

// Error display
function ErrorDisplay({ error }: { error: string }) {
  return (
    <div className="p-4 bg-love/10 border border-love/20 rounded-lg">
      <p className="text-sm text-love">{error}</p>
    </div>
  )
}

// Success display
function SuccessDisplay({ message }: { message: string }) {
  return (
    <div className="p-4 bg-foam/10 border border-foam/20 rounded-lg">
      <p className="text-sm text-foam">{message}</p>
    </div>
  )
}

// Conflict warning display
function ConflictWarning({
  error,
  onConfirm,
  onCancel,
  isPending,
}: {
  error: ApiError
  onConfirm: () => void
  onCancel: () => void
  isPending?: boolean
}) {
  const conflicts = error.conflicts
  return (
    <div className="p-4 bg-gold/10 border border-gold/20 rounded-lg">
      <p className="font-medium text-gold">
        Existing resources found:
      </p>
      <ul className="mt-2 text-sm text-gold">
        {conflicts?.map((c) => (
          <li key={c.id}>
            &bull; {c.resource_type}: {c.name}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-sm text-gold">
        These will be deleted and recreated. This cannot be undone.
      </p>
      <div className="mt-3 flex gap-2">
        <button
          onClick={onConfirm}
          disabled={isPending}
          className="px-4 py-2 bg-gold text-base rounded-lg hover:bg-gold/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm font-medium focus:outline-none focus:ring-2 focus:ring-gold"
        >
          {isPending ? 'Replacing...' : 'Replace Existing'}
        </button>
        <button
          onClick={onCancel}
          disabled={isPending}
          className="px-4 py-2 bg-hl-low text-subtle rounded-lg hover:bg-hl-med disabled:opacity-50 transition-colors text-sm focus:outline-none focus:ring-2 focus:ring-iris"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

export function CloudflareWizard() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data: status, isLoading } = useCloudflareStatus()

  // Form state
  const [currentStep, setCurrentStep] = useState(1)
  const [apiToken, setApiToken] = useState('')
  const [tunnelName, setTunnelName] = useState('mcpbox-tunnel')
  const [vpcServiceName, setVpcServiceName] = useState('mcpbox-service')
  const [workerName, setWorkerName] = useState('mcpbox-proxy')
  const [configId, setConfigId] = useState<string | null>(null)

  // Teardown confirm modal
  const [showTeardownConfirm, setShowTeardownConfirm] = useState(false)

  // Access policy state
  const [policyType, setPolicyType] = useState<AccessPolicyType>('everyone')
  const [policyEmails, setPolicyEmails] = useState<string[]>([])
  const [policyEmailInput, setPolicyEmailInput] = useState('')
  const [policyEmailDomain, setPolicyEmailDomain] = useState('')

  // Allowed origins state (optional, for non-Claude MCP clients)
  const [showOrigins, setShowOrigins] = useState(false)
  const [wizardCorsOrigins, setWizardCorsOrigins] = useState<string[]>([])
  const [wizardRedirectUris, setWizardRedirectUris] = useState<string[]>([])
  const [wizardNewCorsOrigin, setWizardNewCorsOrigin] = useState('')
  const [wizardNewRedirectUri, setWizardNewRedirectUri] = useState('')
  const [wizardOriginError, setWizardOriginError] = useState<string | null>(null)
  const [wizardRedirectError, setWizardRedirectError] = useState<string | null>(null)

  // Step results
  const [workerUrl, setWorkerUrl] = useState<string | null>(null)
  const [tokenError, setTokenError] = useState<string | null>(null)
  const [_zones, setZones] = useState<Zone[]>([])
  const [selectedZone, setSelectedZone] = useState<string | null>(null)

  // Mutations
  const startWithApiTokenMutation = useStartWithApiToken()
  const setApiTokenMutation = useSetApiToken()
  const createTunnelMutation = useCreateTunnel()
  const createVpcServiceMutation = useCreateVpcService()
  const deployWorkerMutation = useDeployWorker()
  const configureJwtMutation = useConfigureWorkerJwt()
  const teardownMutation = useTeardown()
  const updateWorkerConfigMutation = useUpdateWorkerConfig()

  // Initialize from existing status
  useEffect(() => {
    if (status && status.config_id) {
      setConfigId(status.config_id)
      setCurrentStep(Math.min(status.completed_step + 1, 6))
      if (status.tunnel_name) setTunnelName(status.tunnel_name)
      if (status.vpc_service_name) setVpcServiceName(status.vpc_service_name)
      if (status.worker_name) setWorkerName(status.worker_name)
      if (status.worker_url) setWorkerUrl(status.worker_url)
    }
  }, [status])

  const completedStep = status?.completed_step || 0

  // Step handlers
  const handleStartWithApiToken = async () => {
    if (!apiToken) return
    setTokenError(null)
    try {
      const result = await startWithApiTokenMutation.mutateAsync({
        api_token: apiToken,
      })
      if (result.success && result.config_id) {
        setConfigId(result.config_id)
        if (result.zones && result.zones.length > 0) {
          setZones(result.zones)
          setSelectedZone(result.zones[0].name)
        }
        setCurrentStep(2)
        queryClient.invalidateQueries({ queryKey: cloudflareKeys.status() })
      } else if (result.error) {
        setTokenError(result.error)
      }
    } catch (e) {
      setTokenError(e instanceof Error ? e.message : 'Failed to verify API token')
    }
  }

  const handleUpdateApiToken = async () => {
    if (!apiToken || !configId) return
    setTokenError(null)
    try {
      const result = await setApiTokenMutation.mutateAsync({
        config_id: configId,
        api_token: apiToken,
      })
      if (result.success) {
        setApiToken('')
        // Fetch zones with the new token
        try {
          const fetchedZones = await getZones(configId)
          if (fetchedZones.length > 0) {
            setZones(fetchedZones)
            if (!selectedZone) {
              setSelectedZone(fetchedZones[0].name)
            }
          }
        } catch {
          // Ignore zone fetch errors
        }
        setCurrentStep(2)
        queryClient.invalidateQueries({ queryKey: cloudflareKeys.status() })
      }
    } catch (e) {
      setTokenError(e instanceof Error ? e.message : 'Failed to update API token')
    }
  }

  const handleCreateTunnel = async () => {
    if (!configId) return
    try {
      const result = await createTunnelMutation.mutateAsync({
        config_id: configId,
        name: tunnelName,
      })
      if (result.success) {
        await queryClient.refetchQueries({ queryKey: cloudflareKeys.status() })
        setCurrentStep(3)
      }
    } catch {
      // Error handled by mutation
    }
  }

  const handleCreateVpcService = async () => {
    if (!configId) return
    try {
      const result = await createVpcServiceMutation.mutateAsync({
        config_id: configId,
        name: vpcServiceName,
      })
      if (result.success) {
        await queryClient.refetchQueries({ queryKey: cloudflareKeys.status() })
        setCurrentStep(4)
      }
    } catch {
      // Error handled by mutation
    }
  }

  const handleDeployWorker = async () => {
    if (!configId) return
    try {
      const result = await deployWorkerMutation.mutateAsync({
        config_id: configId,
        name: workerName,
      })
      if (result.success) {
        setWorkerUrl(result.worker_url)
        await queryClient.refetchQueries({ queryKey: cloudflareKeys.status() })
        setCurrentStep(5)
      }
    } catch {
      // Error handled by mutation
    }
  }

  const handleAddPolicyEmail = () => {
    const email = policyEmailInput.trim()
    if (email && email.includes('@') && !policyEmails.includes(email)) {
      setPolicyEmails([...policyEmails, email])
      setPolicyEmailInput('')
    }
  }

  const handleRemovePolicyEmail = (email: string) => {
    setPolicyEmails(policyEmails.filter((e) => e !== email))
  }

  const handleConfigureAccess = async () => {
    if (!configId) return
    try {
      // Build access policy from form state
      const accessPolicy =
        policyType === 'emails' && policyEmails.length > 0
          ? { policy_type: 'emails' as const, emails: policyEmails, email_domain: null }
          : policyType === 'email_domain' && policyEmailDomain
            ? { policy_type: 'email_domain' as const, emails: [], email_domain: policyEmailDomain }
            : undefined
      const result = await configureJwtMutation.mutateAsync({
        config_id: configId,
        access_policy: accessPolicy,
      })
      if (result.success && result.worker_url) {
        setWorkerUrl(result.worker_url)
      }
      // Save allowed origins if any were configured
      if (configId && (wizardCorsOrigins.length > 0 || wizardRedirectUris.length > 0)) {
        try {
          await updateWorkerConfigMutation.mutateAsync({
            configId,
            corsOrigins: wizardCorsOrigins,
            redirectUris: wizardRedirectUris,
          })
        } catch {
          // Non-fatal: origins can be configured later in Settings
        }
      }
      await queryClient.refetchQueries({ queryKey: cloudflareKeys.status() })
      setCurrentStep(6)
    } catch {
      // Error handled by mutation
    }
  }

  const handleTeardown = () => {
    if (!configId) return
    setShowTeardownConfirm(true)
  }

  const confirmTeardown = async () => {
    if (!configId) return
    setShowTeardownConfirm(false)
    try {
      await teardownMutation.mutateAsync(configId)
      navigate('/tunnel')
    } catch {
      // Error handled by mutation
    }
  }

  if (isLoading) {
    return (
      <div className="min-h-full">
        <Header title="Remote Access Setup" />
        <div className="p-4 sm:p-6 max-w-4xl flex items-center justify-center min-h-[400px]">
          <div className="animate-spin h-8 w-8 border-4 border-iris border-t-transparent rounded-full" />
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-full">
      <Header title="Remote Access Setup" />
      <div className="p-4 sm:p-6 max-w-4xl mx-auto">
        {/* Progress Stepper */}
        <ProgressStepper currentStep={currentStep} completedStep={completedStep} />

        {/* Step 1: API Token */}
        <StepCard
          step={1}
          title="API Token"
          description="Provide a Cloudflare API token with the required permissions."
          isActive={currentStep === 1}
          isComplete={completedStep >= 1}
          onEdit={() => setCurrentStep(1)}
        >
          {currentStep === 1 && (
            <div className="space-y-4">
              {/* Show current account if editing */}
              {configId && (
                <SuccessDisplay message={`Currently connected as: ${status?.account_name || 'Connected'}`} />
              )}

              <div className="p-4 bg-pine/10 border border-pine/20 rounded-lg">
                <h4 className="text-sm font-medium text-pine mb-2">
                  {configId ? 'Update API Token' : 'Create an API Token'}
                </h4>
                <p className="text-sm text-pine mb-3">
                  {configId ? 'Enter a new API token to update your credentials. ' : ''}
                  Create an API token at{' '}
                  <a
                    href="https://dash.cloudflare.com/profile/api-tokens"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline font-medium"
                  >
                    Cloudflare API Tokens
                  </a>{' '}
                  with these permissions:
                </p>
                <ul className="text-sm text-pine space-y-1 list-disc list-inside">
                  <li>Account &rarr; Cloudflare Tunnel &rarr; Edit</li>
                  <li>Account &rarr; Workers Scripts &rarr; Edit</li>
                  <li>Account &rarr; Workers KV Storage &rarr; Edit</li>
                  <li>Account &rarr; Connectivity Directory &rarr; Admin</li>
                  <li>Account &rarr; MCP Portals &rarr; Edit</li>
                  <li>Account &rarr; Access: Organizations, Identity Providers, and Groups &rarr; Read</li>
                  <li>Account &rarr; Access: Apps and Policies &rarr; Edit</li>
                  <li>Zone &rarr; Zone &rarr; Read (for all zones)</li>
                </ul>
              </div>

              <div>
                <label className="block text-sm font-medium text-subtle mb-2">
                  API Token
                </label>
                <input
                  type="password"
                  value={apiToken}
                  onChange={(e) => setApiToken(e.target.value)}
                  placeholder={configId ? 'Enter new API token' : 'Enter your Cloudflare API token'}
                  className="w-full px-3 py-2 border border-hl-med rounded-lg bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
                />
              </div>

              <div className="flex gap-3">
                {configId && (
                  <button
                    onClick={() => setCurrentStep(2)}
                    className="flex-1 px-4 py-2 bg-hl-low text-subtle rounded-lg hover:bg-hl-med transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
                  >
                    Cancel
                  </button>
                )}
                <button
                  onClick={configId ? handleUpdateApiToken : handleStartWithApiToken}
                  disabled={!apiToken || startWithApiTokenMutation.isPending || setApiTokenMutation.isPending}
                  className={`${configId ? 'flex-1' : 'w-full'} px-4 py-2 bg-iris text-base rounded-lg hover:bg-iris/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-iris`}
                >
                  {startWithApiTokenMutation.isPending || setApiTokenMutation.isPending
                    ? 'Verifying...'
                    : configId
                      ? 'Update Token'
                      : 'Continue'}
                </button>
              </div>

              {/* Error Display */}
              {(startWithApiTokenMutation.error || setApiTokenMutation.error || tokenError) && (
                <ErrorDisplay
                  error={
                    tokenError ||
                    (setApiTokenMutation.error instanceof Error
                      ? setApiTokenMutation.error.message
                      : startWithApiTokenMutation.error instanceof Error
                        ? startWithApiTokenMutation.error.message
                        : 'Authentication failed')
                  }
                />
              )}
            </div>
          )}
          {completedStep >= 1 && currentStep !== 1 && (
            <SuccessDisplay message={`Account: ${status?.account_name || 'Connected'}`} />
          )}
        </StepCard>

        {/* Step 2: Create Tunnel */}
        <StepCard
          step={2}
          title="Create Tunnel"
          description="Create a Cloudflare tunnel for secure connection."
          isActive={currentStep === 2}
          isComplete={completedStep >= 2}
          onEdit={() => setCurrentStep(2)}
        >
          {currentStep === 2 && (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-subtle mb-2">
                  Tunnel Name
                </label>
                <input
                  type="text"
                  value={tunnelName}
                  onChange={(e) => setTunnelName(e.target.value)}
                  className="w-full px-3 py-2 border border-hl-med rounded-lg bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
                />
              </div>

              {createTunnelMutation.error &&
                (createTunnelMutation.error instanceof ApiError &&
                createTunnelMutation.error.isConflict ? (
                  <ConflictWarning
                    error={createTunnelMutation.error}
                    isPending={createTunnelMutation.isPending}
                    onConfirm={() =>
                      createTunnelMutation.mutate(
                        { config_id: configId!, name: tunnelName, force: true },
                        {
                          onSuccess: async (result) => {
                            if (result.success) {
                              await queryClient.refetchQueries({
                                queryKey: cloudflareKeys.status(),
                              })
                              setCurrentStep(3)
                            }
                          },
                        }
                      )
                    }
                    onCancel={() => createTunnelMutation.reset()}
                  />
                ) : (
                  <ErrorDisplay
                    error={
                      createTunnelMutation.error instanceof Error
                        ? createTunnelMutation.error.message
                        : 'Failed to create tunnel'
                    }
                  />
                ))}

              <button
                onClick={handleCreateTunnel}
                disabled={!tunnelName || createTunnelMutation.isPending}
                className="w-full px-4 py-2 bg-iris text-base rounded-lg hover:bg-iris/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
              >
                {createTunnelMutation.isPending ? 'Creating...' : 'Create Tunnel'}
              </button>
            </div>
          )}
          {completedStep >= 2 && currentStep !== 2 && (
            <div className="space-y-3">
              <SuccessDisplay message={`Tunnel: ${status?.tunnel_name}`} />
            </div>
          )}
        </StepCard>

        {/* Step 3: Create VPC Service */}
        <StepCard
          step={3}
          title="Create VPC Service"
          description="Create a virtual private cloud service for the tunnel."
          isActive={currentStep === 3}
          isComplete={completedStep >= 3}
          onEdit={() => setCurrentStep(3)}
        >
          {currentStep === 3 && (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-subtle mb-2">
                  VPC Service Name
                </label>
                <input
                  type="text"
                  value={vpcServiceName}
                  onChange={(e) => setVpcServiceName(e.target.value)}
                  className="w-full px-3 py-2 border border-hl-med rounded-lg bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
                />
              </div>

              {createVpcServiceMutation.error &&
                (createVpcServiceMutation.error instanceof ApiError &&
                createVpcServiceMutation.error.isConflict ? (
                  <ConflictWarning
                    error={createVpcServiceMutation.error}
                    isPending={createVpcServiceMutation.isPending}
                    onConfirm={() =>
                      createVpcServiceMutation.mutate(
                        { config_id: configId!, name: vpcServiceName, force: true },
                        {
                          onSuccess: async (result) => {
                            if (result.success) {
                              await queryClient.refetchQueries({
                                queryKey: cloudflareKeys.status(),
                              })
                              setCurrentStep(4)
                            }
                          },
                        }
                      )
                    }
                    onCancel={() => createVpcServiceMutation.reset()}
                  />
                ) : (
                  <ErrorDisplay
                    error={
                      createVpcServiceMutation.error instanceof Error
                        ? createVpcServiceMutation.error.message
                        : 'Failed to create VPC service'
                    }
                  />
                ))}

              <button
                onClick={handleCreateVpcService}
                disabled={!vpcServiceName || createVpcServiceMutation.isPending}
                className="w-full px-4 py-2 bg-iris text-base rounded-lg hover:bg-iris/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
              >
                {createVpcServiceMutation.isPending ? 'Creating...' : 'Create VPC Service'}
              </button>
            </div>
          )}
          {completedStep >= 3 && currentStep !== 3 && (
            <SuccessDisplay message={`VPC Service: ${status?.vpc_service_name}`} />
          )}
        </StepCard>

        {/* Step 4: Deploy Worker */}
        <StepCard
          step={4}
          title="Deploy Worker"
          description="Deploy the MCPbox proxy Worker to Cloudflare."
          isActive={currentStep === 4}
          isComplete={completedStep >= 4}
          onEdit={() => setCurrentStep(4)}
        >
          {currentStep === 4 && (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-subtle mb-2">
                  Worker Name
                </label>
                <input
                  type="text"
                  value={workerName}
                  onChange={(e) => setWorkerName(e.target.value)}
                  className="w-full px-3 py-2 border border-hl-med rounded-lg bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
                />
              </div>

              {deployWorkerMutation.error && (
                <ErrorDisplay
                  error={
                    deployWorkerMutation.error instanceof Error
                      ? deployWorkerMutation.error.message
                      : 'Failed to deploy Worker'
                  }
                />
              )}

              <button
                onClick={handleDeployWorker}
                disabled={!workerName || deployWorkerMutation.isPending}
                className="w-full px-4 py-2 bg-iris text-base rounded-lg hover:bg-iris/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
              >
                {deployWorkerMutation.isPending ? 'Deploying...' : 'Deploy Worker'}
              </button>
            </div>
          )}
          {completedStep >= 4 && currentStep !== 4 && (
            <div className="space-y-3">
              <SuccessDisplay message={`Worker: ${status?.worker_name}`} />
              {workerUrl && (
                <div className="flex items-center gap-2 p-2 bg-hl-low rounded">
                  <span className="text-sm text-subtle">URL:</span>
                  <code className="text-sm font-mono text-on-base">{workerUrl}</code>
                </div>
              )}
            </div>
          )}
        </StepCard>

        {/* Step 5: Configure Access (OIDC) */}
        <StepCard
          step={5}
          title="Configure Access"
          description="Create OIDC authentication and set access policy."
          isActive={currentStep === 5}
          isComplete={completedStep >= 5}
          onEdit={() => setCurrentStep(5)}
        >
          {currentStep === 5 && (
            <div className="space-y-4">
              <div className="p-4 bg-pine/10 border border-pine/20 rounded-lg">
                <p className="text-sm text-pine">
                  This creates a Cloudflare Access for SaaS (OIDC) application and syncs
                  the credentials to your Worker. Users authenticate via Cloudflare Access
                  when connecting from any MCP client.
                </p>
              </div>

              {/* Access Policy Configuration */}
              <div className="border border-hl-med rounded-lg p-4 space-y-4">
                <div>
                  <h4 className="text-sm font-medium text-on-base mb-1">
                    Access Policy
                  </h4>
                  <p className="text-xs text-muted">
                    Choose who can access your MCP tools remotely.
                  </p>
                </div>

                <div className="space-y-3">
                  <label className="flex items-start gap-3 cursor-pointer">
                    <input
                      type="radio"
                      name="policyType"
                      value="everyone"
                      checked={policyType === 'everyone'}
                      onChange={() => setPolicyType('everyone')}
                      className="mt-1 focus:outline-none focus:ring-2 focus:ring-iris"
                    />
                    <div>
                      <span className="text-sm font-medium text-on-base">Everyone</span>
                      <p className="text-xs text-muted">
                        Any authenticated Cloudflare user can access
                      </p>
                    </div>
                  </label>

                  <label className="flex items-start gap-3 cursor-pointer">
                    <input
                      type="radio"
                      name="policyType"
                      value="email_domain"
                      checked={policyType === 'email_domain'}
                      onChange={() => setPolicyType('email_domain')}
                      className="mt-1 focus:outline-none focus:ring-2 focus:ring-iris"
                    />
                    <div className="flex-1">
                      <span className="text-sm font-medium text-on-base">Email Domain</span>
                      <p className="text-xs text-muted">
                        Only users with emails from a specific domain
                      </p>
                      {policyType === 'email_domain' && (
                        <input
                          type="text"
                          value={policyEmailDomain}
                          onChange={(e) => setPolicyEmailDomain(e.target.value)}
                          placeholder="company.com"
                          className="mt-2 w-full px-3 py-1.5 text-sm border border-hl-med rounded-lg bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
                        />
                      )}
                    </div>
                  </label>

                  <label className="flex items-start gap-3 cursor-pointer">
                    <input
                      type="radio"
                      name="policyType"
                      value="emails"
                      checked={policyType === 'emails'}
                      onChange={() => setPolicyType('emails')}
                      className="mt-1 focus:outline-none focus:ring-2 focus:ring-iris"
                    />
                    <div className="flex-1">
                      <span className="text-sm font-medium text-on-base">Specific Emails</span>
                      <p className="text-xs text-muted">
                        Only specific email addresses can access
                      </p>
                      {policyType === 'emails' && (
                        <div className="mt-2 space-y-2">
                          <div className="flex gap-2">
                            <input
                              type="email"
                              value={policyEmailInput}
                              onChange={(e) => setPolicyEmailInput(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  e.preventDefault()
                                  handleAddPolicyEmail()
                                }
                              }}
                              placeholder="user@example.com"
                              className="flex-1 px-3 py-1.5 text-sm border border-hl-med rounded-lg bg-surface text-on-base"
                            />
                            <button
                              type="button"
                              onClick={handleAddPolicyEmail}
                              className="px-3 py-1.5 text-sm bg-iris text-base rounded-md hover:bg-iris/80 transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
                            >
                              Add
                            </button>
                          </div>
                          {policyEmails.length > 0 && (
                            <div className="flex flex-wrap gap-2">
                              {policyEmails.map((email) => (
                                <span
                                  key={email}
                                  className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-rose/10 text-rose rounded-full"
                                >
                                  {email}
                                  <button
                                    type="button"
                                    onClick={() => handleRemovePolicyEmail(email)}
                                    aria-label={`Remove ${email}`}
                                    className="text-rose/60 hover:text-love rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-love"
                                  >
                                    &times;
                                  </button>
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </label>
                </div>

                <p className="text-xs text-muted">
                  For advanced rules, use the{' '}
                  <a
                    href="https://one.dash.cloudflare.com"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline hover:text-subtle"
                  >
                    Cloudflare Dashboard
                  </a>{' '}
                  after setup.
                </p>
              </div>

              {/* Allowed Origins (collapsible, for non-Claude MCP clients) */}
              <div className="border border-hl-med rounded-lg overflow-hidden">
                <button
                  type="button"
                  onClick={() => setShowOrigins(!showOrigins)}
                  className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris focus:ring-inset"
                >
                  <div>
                    <h4 className="text-sm font-medium text-on-base">
                      Allowed Origins
                      <span className="ml-2 text-xs text-muted font-normal">(optional)</span>
                    </h4>
                    <p className="text-xs text-muted mt-0.5">
                      Configure if using MCP clients other than Claude
                    </p>
                  </div>
                  <svg
                    className={`w-5 h-5 text-muted transition-transform ${showOrigins ? 'rotate-180' : ''}`}
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>

                {showOrigins && (
                  <div className="px-4 pb-4 space-y-4 border-t border-hl-med">
                    <div className="pt-3">
                      <p className="text-xs text-muted mb-3">
                        Built-in origins (Claude, ChatGPT, OpenAI, Cloudflare, localhost) are always allowed.
                        Add origins here for other MCP clients like Cursor, Continue, or custom clients.
                      </p>

                      {/* CORS Origins */}
                      <label className="block text-xs font-medium text-on-base mb-1">
                        CORS Origins
                      </label>
                      <div className="flex gap-2 mb-1">
                        <input
                          type="text"
                          value={wizardNewCorsOrigin}
                          onChange={(e) => { setWizardNewCorsOrigin(e.target.value); setWizardOriginError(null) }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              e.preventDefault()
                              const origin = wizardNewCorsOrigin.trim().replace(/\/+$/, '')
                              if (!origin) return
                              if (!/^https?:\/\/[a-zA-Z0-9]/.test(origin)) { setWizardOriginError('Invalid origin'); return }
                              if (origin.startsWith('http://') && !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin)) { setWizardOriginError('Non-localhost must use HTTPS'); return }
                              if (wizardCorsOrigins.includes(origin)) { setWizardOriginError('Already added'); return }
                              setWizardCorsOrigins([...wizardCorsOrigins, origin])
                              setWizardNewCorsOrigin('')
                            }
                          }}
                          placeholder="https://my-mcp-client.example.com"
                          className="flex-1 px-3 py-1.5 text-sm border border-hl-med rounded-lg bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
                        />
                        <button
                          type="button"
                          onClick={() => {
                            const origin = wizardNewCorsOrigin.trim().replace(/\/+$/, '')
                            if (!origin) return
                            if (!/^https?:\/\/[a-zA-Z0-9]/.test(origin)) { setWizardOriginError('Invalid origin'); return }
                            if (origin.startsWith('http://') && !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin)) { setWizardOriginError('Non-localhost must use HTTPS'); return }
                            if (wizardCorsOrigins.includes(origin)) { setWizardOriginError('Already added'); return }
                            setWizardCorsOrigins([...wizardCorsOrigins, origin])
                            setWizardNewCorsOrigin('')
                          }}
                          className="px-3 py-1.5 text-sm bg-iris text-base rounded-md hover:bg-iris/80 transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
                        >
                          Add
                        </button>
                      </div>
                      {wizardOriginError && <p className="text-xs text-love mb-1">{wizardOriginError}</p>}
                      {wizardCorsOrigins.length > 0 && (
                        <div className="flex flex-wrap gap-2 mb-3">
                          {wizardCorsOrigins.map((origin) => (
                            <span
                              key={origin}
                              className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-iris/10 text-iris rounded-full font-mono"
                            >
                              {origin}
                              <button
                                type="button"
                                onClick={() => setWizardCorsOrigins(wizardCorsOrigins.filter((o) => o !== origin))}
                                aria-label={`Remove ${origin}`}
                                className="text-iris/60 hover:text-love rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-love"
                              >
                                &times;
                              </button>
                            </span>
                          ))}
                        </div>
                      )}

                      {/* Redirect URIs */}
                      <label className="block text-xs font-medium text-on-base mb-1 mt-3">
                        OAuth Redirect URI Prefixes
                      </label>
                      <div className="flex gap-2 mb-1">
                        <input
                          type="text"
                          value={wizardNewRedirectUri}
                          onChange={(e) => { setWizardNewRedirectUri(e.target.value); setWizardRedirectError(null) }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              e.preventDefault()
                              const uri = wizardNewRedirectUri.trim()
                              if (!uri) return
                              if (!/^https?:\/\/[a-zA-Z0-9]/.test(uri)) { setWizardRedirectError('Invalid URI'); return }
                              if (uri.startsWith('http://') && !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?\//.test(uri)) { setWizardRedirectError('Non-localhost must use HTTPS'); return }
                              if (wizardRedirectUris.includes(uri)) { setWizardRedirectError('Already added'); return }
                              setWizardRedirectUris([...wizardRedirectUris, uri])
                              setWizardNewRedirectUri('')
                            }
                          }}
                          placeholder="https://my-mcp-client.example.com/"
                          className="flex-1 px-3 py-1.5 text-sm border border-hl-med rounded-lg bg-surface text-on-base focus:outline-none focus:ring-2 focus:ring-iris focus:border-iris"
                        />
                        <button
                          type="button"
                          onClick={() => {
                            const uri = wizardNewRedirectUri.trim()
                            if (!uri) return
                            if (!/^https?:\/\/[a-zA-Z0-9]/.test(uri)) { setWizardRedirectError('Invalid URI'); return }
                            if (uri.startsWith('http://') && !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?\//.test(uri)) { setWizardRedirectError('Non-localhost must use HTTPS'); return }
                            if (wizardRedirectUris.includes(uri)) { setWizardRedirectError('Already added'); return }
                            setWizardRedirectUris([...wizardRedirectUris, uri])
                            setWizardNewRedirectUri('')
                          }}
                          className="px-3 py-1.5 text-sm bg-iris text-base rounded-md hover:bg-iris/80 transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
                        >
                          Add
                        </button>
                      </div>
                      {wizardRedirectError && <p className="text-xs text-love mb-1">{wizardRedirectError}</p>}
                      {wizardRedirectUris.length > 0 && (
                        <div className="flex flex-wrap gap-2">
                          {wizardRedirectUris.map((uri) => (
                            <span
                              key={uri}
                              className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-iris/10 text-iris rounded-full font-mono"
                            >
                              {uri}
                              <button
                                type="button"
                                onClick={() => setWizardRedirectUris(wizardRedirectUris.filter((u) => u !== uri))}
                                aria-label={`Remove ${uri}`}
                                className="text-iris/60 hover:text-love rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-love"
                              >
                                &times;
                              </button>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>

              {configureJwtMutation.error && (
                <ErrorDisplay
                  error={
                    configureJwtMutation.error instanceof Error
                      ? configureJwtMutation.error.message
                      : 'Failed to configure access'
                  }
                />
              )}

              <button
                onClick={handleConfigureAccess}
                disabled={
                  configureJwtMutation.isPending ||
                  (policyType === 'emails' && policyEmails.length === 0) ||
                  (policyType === 'email_domain' && !policyEmailDomain)
                }
                className="w-full px-4 py-2 bg-iris text-base rounded-lg hover:bg-iris/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
              >
                {configureJwtMutation.isPending ? 'Configuring...' : 'Configure Access & OIDC'}
              </button>
            </div>
          )}
          {completedStep >= 5 && currentStep !== 5 && (
            <SuccessDisplay message="OIDC authentication configured" />
          )}
        </StepCard>

        {/* Step 6: Connect */}
        <StepCard
          step={6}
          title="Connect"
          description="Add your Worker URL to your MCP client."
          isActive={currentStep === 6}
          isComplete={false}
        >
          {currentStep === 6 && (
            <div className="space-y-4">
              <div className="p-4 bg-foam/10 border border-foam/20 rounded-lg">
                <p className="text-sm text-foam mb-2">
                  Setup complete! Add this URL to your MCP client (Claude, ChatGPT, Cursor, etc.):
                </p>
                {workerUrl && (
                  <div className="flex items-center gap-2 mt-3">
                    <code className="flex-1 text-sm font-mono text-foam bg-foam/20 px-3 py-2 rounded">
                      {workerUrl}/mcp
                    </code>
                    <CopyButton text={`${workerUrl}/mcp`} label="Copy" />
                  </div>
                )}
              </div>

              <div className="p-4 bg-pine/10 border border-pine/20 rounded-lg">
                <p className="text-sm text-pine mb-2">
                  When connecting, the MCP client will perform an OAuth 2.1 flow.
                  You&apos;ll be redirected to Cloudflare Access to authenticate with your email.
                </p>
                <p className="text-xs text-pine">
                  Make sure the tunnel is running:{' '}
                  <code className="bg-pine/20 px-1 rounded">docker compose --profile remote up -d</code>
                </p>
              </div>

              <button
                onClick={() => navigate('/tunnel')}
                className="w-full px-4 py-2.5 bg-foam text-base rounded-lg hover:bg-foam/80 transition-colors font-medium focus:outline-none focus:ring-2 focus:ring-foam"
              >
                Complete Setup
              </button>

              <p className="text-xs text-muted mt-3">
                It may take a few minutes for Cloudflare to fully propagate your
                configuration. If you see a connection error, wait 2-3 minutes and try again.
              </p>
            </div>
          )}
        </StepCard>

        {/* Actions */}
        <div className="mt-6 flex flex-col sm:flex-row gap-3">
          <button
            onClick={() => navigate('/tunnel')}
            className="px-4 py-2 bg-hl-low text-subtle rounded-lg hover:bg-hl-med transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
          >
            Back to Tunnel
          </button>

          {configId && (
            <button
              onClick={handleTeardown}
              disabled={teardownMutation.isPending}
              className="px-4 py-2 bg-love/10 text-love rounded-lg hover:bg-love/20 transition-colors focus:outline-none focus:ring-2 focus:ring-love"
            >
              {teardownMutation.isPending ? 'Removing...' : 'Remove All Resources'}
            </button>
          )}
        </div>
      </div>

      <ConfirmModal
        isOpen={showTeardownConfirm}
        title="Remove All Resources"
        message="Are you sure you want to delete all Cloudflare resources? This cannot be undone."
        confirmLabel="Remove All"
        destructive
        isLoading={teardownMutation.isPending}
        onConfirm={confirmTeardown}
        onCancel={() => setShowTeardownConfirm(false)}
      />
    </div>
  )
}
