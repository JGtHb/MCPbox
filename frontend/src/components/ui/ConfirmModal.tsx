import { useCallback, useEffect, useRef, useState } from 'react'

interface ConfirmModalProps {
  /** Whether the modal is open */
  isOpen: boolean
  /** Modal title */
  title: string
  /** Modal message/description */
  message: string
  /** Text for the confirm button */
  confirmLabel?: string
  /** Text for the cancel button */
  cancelLabel?: string
  /** Whether the action is destructive (changes button color) */
  destructive?: boolean
  /** Whether the confirm action is in progress */
  isLoading?: boolean
  /** Called when user confirms */
  onConfirm: () => void
  /** Called when user cancels */
  onCancel: () => void
}

/**
 * Accessible confirmation modal to replace browser confirm() dialogs.
 *
 * Features:
 * - Focus trap (Tab cycles within modal)
 * - Escape key closes modal
 * - Click outside closes modal
 * - Auto-focus on cancel button
 * - ARIA attributes for screen readers
 *
 * @example
 * ```tsx
 * const [showConfirm, setShowConfirm] = useState(false)
 *
 * <ConfirmModal
 *   isOpen={showConfirm}
 *   title="Delete Server"
 *   message="Are you sure you want to delete this server?"
 *   destructive
 *   onConfirm={() => { deleteServer(); setShowConfirm(false) }}
 *   onCancel={() => setShowConfirm(false)}
 * />
 * ```
 */
export function ConfirmModal({
  isOpen,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  destructive = false,
  isLoading = false,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  const cancelButtonRef = useRef<HTMLButtonElement>(null)
  const modalRef = useRef<HTMLDivElement>(null)

  // Focus cancel button when modal opens
  useEffect(() => {
    if (isOpen && cancelButtonRef.current) {
      cancelButtonRef.current.focus()
    }
  }, [isOpen])

  // Handle escape key
  useEffect(() => {
    if (!isOpen) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onCancel()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onCancel])

  // Handle click outside
  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === e.currentTarget) {
        onCancel()
      }
    },
    [onCancel]
  )

  // Handle focus trap
  useEffect(() => {
    if (!isOpen || !modalRef.current) return

    const modal = modalRef.current
    const focusableElements = modal.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    )
    const firstElement = focusableElements[0]
    const lastElement = focusableElements[focusableElements.length - 1]

    const handleTab = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return

      if (e.shiftKey) {
        if (document.activeElement === firstElement) {
          e.preventDefault()
          lastElement?.focus()
        }
      } else {
        if (document.activeElement === lastElement) {
          e.preventDefault()
          firstElement?.focus()
        }
      }
    }

    modal.addEventListener('keydown', handleTab)
    return () => modal.removeEventListener('keydown', handleTab)
  }, [isOpen])

  if (!isOpen) return null

  const confirmButtonClasses = destructive
    ? 'bg-love hover:bg-love/80 focus:ring-love text-base'
    : 'bg-iris hover:bg-iris/80 focus:ring-iris text-base'

  return (
    <div
      className="fixed inset-0 z-50 overflow-y-auto"
      aria-labelledby="modal-title"
      role="dialog"
      aria-modal="true"
    >
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-base/75 transition-opacity"
        aria-hidden="true"
        onClick={handleBackdropClick}
      />

      {/* Modal container */}
      <div
        className="fixed inset-0 flex items-center justify-center p-4"
        onClick={handleBackdropClick}
      >
        {/* Modal panel */}
        <div
          ref={modalRef}
          className="relative bg-surface rounded-lg shadow-xl max-w-md w-full p-6 transform transition-all"
        >
          {/* Icon */}
          <div className="flex items-center justify-center mb-4">
            {destructive ? (
              <div className="w-12 h-12 rounded-full bg-love/10 flex items-center justify-center">
                <svg
                  className="w-6 h-6 text-love"
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
            ) : (
              <div className="w-12 h-12 rounded-full bg-iris/10 flex items-center justify-center">
                <svg
                  className="w-6 h-6 text-iris"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                  />
                </svg>
              </div>
            )}
          </div>

          {/* Title */}
          <h3
            id="modal-title"
            className="text-lg font-medium text-on-base text-center mb-2"
          >
            {title}
          </h3>

          {/* Message */}
          <p className="text-sm text-muted text-center mb-6">{message}</p>

          {/* Buttons */}
          <div className="flex space-x-3">
            <button
              ref={cancelButtonRef}
              type="button"
              onClick={onCancel}
              disabled={isLoading}
              className="flex-1 px-4 py-2 text-sm font-medium text-subtle bg-surface border border-hl-med rounded-md hover:bg-hl-low focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-iris disabled:opacity-50"
            >
              {cancelLabel}
            </button>
            <button
              type="button"
              onClick={onConfirm}
              disabled={isLoading}
              className={`flex-1 px-4 py-2 text-sm font-medium rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:opacity-50 ${confirmButtonClasses}`}
            >
              {isLoading ? (
                <span className="flex items-center justify-center">
                  <svg
                    className="animate-spin -ml-1 mr-2 h-4 w-4"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    />
                  </svg>
                  Processing...
                </span>
              ) : (
                confirmLabel
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

/**
 * Hook for managing confirm modal state.
 *
 * @example
 * ```tsx
 * const { isOpen, confirm, cancel, data } = useConfirmModal<string>()
 *
 * const handleDelete = (id: string) => {
 *   confirm(id)
 * }
 *
 * // In render:
 * <ConfirmModal
 *   isOpen={isOpen}
 *   onConfirm={() => { doDelete(data); cancel() }}
 *   onCancel={cancel}
 * />
 * ```
 */
export function useConfirmModal<T = void>() {
  const [isOpen, setIsOpen] = useState(false)
  const [data, setData] = useState<T | undefined>(undefined)

  const confirm = useCallback((value?: T) => {
    setData(value)
    setIsOpen(true)
  }, [])

  const cancel = useCallback(() => {
    setIsOpen(false)
    setData(undefined)
  }, [])

  return { isOpen, confirm, cancel, data }
}
