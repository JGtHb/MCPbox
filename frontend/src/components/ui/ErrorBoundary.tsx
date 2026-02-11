import { Component, ErrorInfo, ReactNode, useState } from 'react'

interface ErrorBoundaryProps {
  /** Content to render when there's no error */
  children: ReactNode
  /** Custom fallback UI to render on error */
  fallback?: ReactNode
  /** Called when an error is caught */
  onError?: (error: Error, errorInfo: ErrorInfo) => void
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

/**
 * Error boundary component that catches JavaScript errors in child components.
 *
 * Prevents the entire app from crashing when a component throws an error.
 *
 * @example
 * ```tsx
 * <ErrorBoundary fallback={<ErrorFallback />}>
 *   <MyComponent />
 * </ErrorBoundary>
 * ```
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    // Log errors only in development mode
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.error('ErrorBoundary caught an error:', error, errorInfo)
    }
    this.props.onError?.(error, errorInfo)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback
      }

      return (
        <ErrorFallback
          error={this.state.error}
          onReset={this.handleReset}
        />
      )
    }

    return this.props.children
  }
}

interface ErrorFallbackProps {
  /** The error that was caught */
  error?: Error | null
  /** Called when user clicks "Try Again" */
  onReset?: () => void
}

/**
 * Default fallback UI shown when an error is caught.
 *
 * @example
 * ```tsx
 * <ErrorFallback
 *   error={new Error('Something went wrong')}
 *   onReset={() => window.location.reload()}
 * />
 * ```
 */
export function ErrorFallback({ error, onReset }: ErrorFallbackProps) {
  return (
    <div
      className="min-h-[400px] flex items-center justify-center p-6"
      role="alert"
    >
      <div className="max-w-md w-full bg-white rounded-lg shadow-lg p-6 text-center">
        {/* Error Icon */}
        <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-red-100 flex items-center justify-center">
          <svg
            className="w-8 h-8 text-red-600"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
            />
          </svg>
        </div>

        {/* Title */}
        <h2 className="text-xl font-semibold text-gray-900 mb-2">
          Something went wrong
        </h2>

        {/* Message */}
        <p className="text-gray-600 mb-4">
          An unexpected error occurred. Please try again.
        </p>

        {/* Error details (development only) */}
        {error && import.meta.env.DEV && (
          <details className="mb-4 text-left">
            <summary className="text-sm text-gray-500 cursor-pointer hover:text-gray-700">
              Error details
            </summary>
            <pre className="mt-2 p-3 bg-gray-100 rounded text-xs text-red-700 overflow-auto max-h-32">
              {error.message}
              {error.stack && `\n\n${error.stack}`}
            </pre>
          </details>
        )}

        {/* Actions */}
        <div className="flex justify-center space-x-3">
          {onReset && (
            <button
              onClick={onReset}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
            >
              Try Again
            </button>
          )}
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
          >
            Reload Page
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * Hook for imperatively triggering error boundary.
 *
 * @example
 * ```tsx
 * function MyComponent() {
 *   const throwError = useErrorHandler()
 *
 *   const handleClick = async () => {
 *     try {
 *       await riskyOperation()
 *     } catch (err) {
 *       throwError(err)
 *     }
 *   }
 * }
 * ```
 */
export function useErrorHandler() {
  const [, setError] = useState<Error | null>(null)

  return (error: unknown) => {
    setError(() => {
      throw error instanceof Error ? error : new Error(String(error))
    })
  }
}
