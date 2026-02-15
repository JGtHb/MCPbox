import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Header } from '../components/Layout'
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
  cloudflareKeys,
  AccessPolicyType,
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
          ? 'bg-green-500 text-white'
          : isCurrent
            ? 'bg-purple-500 text-white'
            : isPending
              ? 'bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400'
              : 'bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400'
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
            <span className="mt-1 text-xs text-gray-500 dark:text-gray-400 hidden sm:block">
              {s.label}
            </span>
          </div>
          {index < steps.length - 1 && (
            <div
              className={`w-8 sm:w-12 h-0.5 mx-1 sm:mx-2 ${
                completedStep >= s.step + 1
                  ? 'bg-green-500'
                  : 'bg-gray-200 dark:bg-gray-700'
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
      className={`bg-white dark:bg-gray-800 rounded-lg shadow p-4 sm:p-6 mb-4 ${
        isActive ? 'ring-2 ring-purple-500' : ''
      } ${isComplete && !isActive ? 'opacity-75' : ''}`}
    >
      <div className="flex items-start gap-4">
        <StepStatus step={step} currentStep={isActive ? step : 0} completedStep={isComplete ? step : step - 1} />
        <div className="flex-1">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-lg font-medium text-gray-900 dark:text-white">{title}</h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">{description}</p>
            </div>
            {isComplete && !isActive && onEdit && (
              <button
                onClick={onEdit}
                className="px-3 py-1.5 text-sm bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-300 rounded transition-colors"
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
      className="px-3 py-1.5 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-300 rounded text-sm transition-colors"
    >
      {copied ? 'Copied!' : label}
    </button>
  )
}

// Error display
function ErrorDisplay({ error }: { error: string }) {
  return (
    <div className="p-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg">
      <p className="text-sm text-red-800 dark:text-red-300">{error}</p>
    </div>
  )
}

// Success display
function SuccessDisplay({ message }: { message: string }) {
  return (
    <div className="p-4 bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-800 rounded-lg">
      <p className="text-sm text-green-800 dark:text-green-300">{message}</p>
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
    <div className="p-4 bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-800 rounded-lg">
      <p className="font-medium text-amber-800 dark:text-amber-300">
        Existing resources found:
      </p>
      <ul className="mt-2 text-sm text-amber-700 dark:text-amber-400">
        {conflicts?.map((c) => (
          <li key={c.id}>
            &bull; {c.resource_type}: {c.name}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-sm text-amber-700 dark:text-amber-400">
        These will be deleted and recreated. This cannot be undone.
      </p>
      <div className="mt-3 flex gap-2">
        <button
          onClick={onConfirm}
          disabled={isPending}
          className="px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm font-medium"
        >
          {isPending ? 'Replacing...' : 'Replace Existing'}
        </button>
        <button
          onClick={onCancel}
          disabled={isPending}
          className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50 transition-colors text-sm"
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

  // Access policy state
  const [policyType, setPolicyType] = useState<AccessPolicyType>('everyone')
  const [policyEmails, setPolicyEmails] = useState<string[]>([])
  const [policyEmailInput, setPolicyEmailInput] = useState('')
  const [policyEmailDomain, setPolicyEmailDomain] = useState('')

  // Step results
  const [workerUrl, setWorkerUrl] = useState<string | null>(null)
  const [tokenError, setTokenError] = useState<string | null>(null)

  // Mutations
  const startWithApiTokenMutation = useStartWithApiToken()
  const setApiTokenMutation = useSetApiToken()
  const createTunnelMutation = useCreateTunnel()
  const createVpcServiceMutation = useCreateVpcService()
  const deployWorkerMutation = useDeployWorker()
  const configureJwtMutation = useConfigureWorkerJwt()
  const teardownMutation = useTeardown()

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
      await queryClient.refetchQueries({ queryKey: cloudflareKeys.status() })
      setCurrentStep(6)
    } catch {
      // Error handled by mutation
    }
  }

  const handleTeardown = async () => {
    if (!configId) return
    if (!confirm('Are you sure you want to delete all Cloudflare resources? This cannot be undone.')) {
      return
    }
    try {
      await teardownMutation.mutateAsync(configId)
      navigate('/tunnel')
    } catch {
      // Error handled by mutation
    }
  }

  if (isLoading) {
    return (
      <div className="dark:bg-gray-900 min-h-full">
        <Header title="Remote Access Setup" />
        <div className="p-4 sm:p-6 max-w-4xl flex items-center justify-center min-h-[400px]">
          <div className="animate-spin h-8 w-8 border-4 border-purple-500 border-t-transparent rounded-full" />
        </div>
      </div>
    )
  }

  return (
    <div className="dark:bg-gray-900 min-h-full">
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

              <div className="p-4 bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-800 rounded-lg">
                <h4 className="text-sm font-medium text-blue-800 dark:text-blue-300 mb-2">
                  {configId ? 'Update API Token' : 'Create an API Token'}
                </h4>
                <p className="text-sm text-blue-700 dark:text-blue-400 mb-3">
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
                <ul className="text-sm text-blue-700 dark:text-blue-400 space-y-1 list-disc list-inside">
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
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  API Token
                </label>
                <input
                  type="password"
                  value={apiToken}
                  onChange={(e) => setApiToken(e.target.value)}
                  placeholder={configId ? 'Enter new API token' : 'Enter your Cloudflare API token'}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                />
              </div>

              <div className="flex gap-3">
                {configId && (
                  <button
                    onClick={() => setCurrentStep(2)}
                    className="flex-1 px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
                  >
                    Cancel
                  </button>
                )}
                <button
                  onClick={configId ? handleUpdateApiToken : handleStartWithApiToken}
                  disabled={!apiToken || startWithApiTokenMutation.isPending || setApiTokenMutation.isPending}
                  className={`${configId ? 'flex-1' : 'w-full'} px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors`}
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
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Tunnel Name
                </label>
                <input
                  type="text"
                  value={tunnelName}
                  onChange={(e) => setTunnelName(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
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
                className="w-full px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
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
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  VPC Service Name
                </label>
                <input
                  type="text"
                  value={vpcServiceName}
                  onChange={(e) => setVpcServiceName(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
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
                className="w-full px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
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
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Worker Name
                </label>
                <input
                  type="text"
                  value={workerName}
                  onChange={(e) => setWorkerName(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
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
                className="w-full px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {deployWorkerMutation.isPending ? 'Deploying...' : 'Deploy Worker'}
              </button>
            </div>
          )}
          {completedStep >= 4 && currentStep !== 4 && (
            <div className="space-y-3">
              <SuccessDisplay message={`Worker: ${status?.worker_name}`} />
              {workerUrl && (
                <div className="flex items-center gap-2 p-2 bg-gray-50 dark:bg-gray-700 rounded">
                  <span className="text-sm text-gray-600 dark:text-gray-400">URL:</span>
                  <code className="text-sm font-mono text-gray-900 dark:text-white">{workerUrl}</code>
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
              <div className="p-4 bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-800 rounded-lg">
                <p className="text-sm text-blue-700 dark:text-blue-300">
                  This creates a Cloudflare Access for SaaS (OIDC) application and syncs
                  the credentials to your Worker. Users authenticate via Cloudflare Access
                  when connecting from Claude or any MCP client.
                </p>
              </div>

              {/* Access Policy Configuration */}
              <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 space-y-4">
                <div>
                  <h4 className="text-sm font-medium text-gray-900 dark:text-white mb-1">
                    Access Policy
                  </h4>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
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
                      className="mt-1"
                    />
                    <div>
                      <span className="text-sm font-medium text-gray-900 dark:text-white">Everyone</span>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
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
                      className="mt-1"
                    />
                    <div className="flex-1">
                      <span className="text-sm font-medium text-gray-900 dark:text-white">Email Domain</span>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        Only users with emails from a specific domain
                      </p>
                      {policyType === 'email_domain' && (
                        <input
                          type="text"
                          value={policyEmailDomain}
                          onChange={(e) => setPolicyEmailDomain(e.target.value)}
                          placeholder="company.com"
                          className="mt-2 w-full px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
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
                      className="mt-1"
                    />
                    <div className="flex-1">
                      <span className="text-sm font-medium text-gray-900 dark:text-white">Specific Emails</span>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
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
                              className="flex-1 px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                            />
                            <button
                              type="button"
                              onClick={handleAddPolicyEmail}
                              className="px-3 py-1.5 text-sm bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors"
                            >
                              Add
                            </button>
                          </div>
                          {policyEmails.length > 0 && (
                            <div className="flex flex-wrap gap-2">
                              {policyEmails.map((email) => (
                                <span
                                  key={email}
                                  className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-purple-100 dark:bg-purple-900/40 text-purple-800 dark:text-purple-300 rounded-full"
                                >
                                  {email}
                                  <button
                                    type="button"
                                    onClick={() => handleRemovePolicyEmail(email)}
                                    className="text-purple-600 dark:text-purple-400 hover:text-purple-800 dark:hover:text-purple-200"
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

                <p className="text-xs text-gray-400 dark:text-gray-500">
                  For advanced rules, use the{' '}
                  <a
                    href="https://one.dash.cloudflare.com"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline hover:text-gray-600 dark:hover:text-gray-300"
                  >
                    Cloudflare Dashboard
                  </a>{' '}
                  after setup.
                </p>
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
                className="w-full px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
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
          description="Add your Worker URL to Claude or any MCP client."
          isActive={currentStep === 6}
          isComplete={false}
        >
          {currentStep === 6 && (
            <div className="space-y-4">
              <div className="p-4 bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-800 rounded-lg">
                <p className="text-sm text-green-800 dark:text-green-300 mb-2">
                  Setup complete! Add this URL to Claude Web, OpenAI, or any MCP client:
                </p>
                {workerUrl && (
                  <div className="flex items-center gap-2 mt-3">
                    <code className="flex-1 text-sm font-mono text-green-900 dark:text-green-100 bg-green-100 dark:bg-green-800/50 px-3 py-2 rounded">
                      {workerUrl}/mcp
                    </code>
                    <CopyButton text={`${workerUrl}/mcp`} label="Copy" />
                  </div>
                )}
              </div>

              <div className="p-4 bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-800 rounded-lg">
                <p className="text-sm text-blue-800 dark:text-blue-300 mb-2">
                  When connecting, the MCP client will perform an OAuth 2.1 flow.
                  You&apos;ll be redirected to Cloudflare Access to authenticate with your email.
                </p>
                <p className="text-xs text-blue-600 dark:text-blue-400">
                  Make sure the tunnel is running:{' '}
                  <code className="bg-blue-100 dark:bg-blue-800 px-1 rounded">docker compose --profile remote up -d</code>
                </p>
              </div>

              <button
                onClick={() => navigate('/tunnel')}
                className="w-full px-4 py-2.5 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors font-medium"
              >
                Complete Setup
              </button>

              <p className="text-xs text-gray-500 dark:text-gray-400 mt-3">
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
            className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
          >
            Back to Tunnel
          </button>

          {configId && (
            <button
              onClick={handleTeardown}
              disabled={teardownMutation.isPending}
              className="px-4 py-2 bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 rounded-lg hover:bg-red-200 dark:hover:bg-red-900/50 transition-colors"
            >
              {teardownMutation.isPending ? 'Removing...' : 'Remove All Resources'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
