import { useCallback, useRef, useState, useEffect } from 'react'

interface UseCopyToClipboardResult {
  /** Whether the text was recently copied */
  copied: boolean
  /** Copy text to clipboard */
  copy: (text: string) => Promise<boolean>
  /** Reset the copied state */
  reset: () => void
}

/**
 * Hook for copying text to the clipboard with feedback state.
 *
 * @param resetDelay - Time in ms before `copied` resets to false (default: 2000)
 * @returns Object with copied state and copy function
 *
 * @example
 * ```tsx
 * const { copied, copy } = useCopyToClipboard()
 *
 * return (
 *   <button onClick={() => copy(text)}>
 *     {copied ? 'Copied!' : 'Copy'}
 *   </button>
 * )
 * ```
 */
export function useCopyToClipboard(resetDelay = 2000): UseCopyToClipboardResult {
  const [copied, setCopied] = useState(false)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Clean up timeout on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
      }
    }
  }, [])

  const copy = useCallback(
    async (text: string): Promise<boolean> => {
      // Clear any existing timeout
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
        timeoutRef.current = null
      }

      try {
        await navigator.clipboard.writeText(text)
        setCopied(true)
        timeoutRef.current = setTimeout(() => setCopied(false), resetDelay)
        return true
      } catch {
        // Clipboard API failed - return false to indicate failure
        // Caller can handle the error as appropriate for their UI
        return false
      }
    },
    [resetDelay]
  )

  const reset = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
    setCopied(false)
  }, [])

  return { copied, copy, reset }
}
