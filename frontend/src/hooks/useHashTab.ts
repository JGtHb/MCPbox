import { useState, useEffect, useCallback } from 'react'

/**
 * Manage tab state synchronized with the URL hash.
 *
 * Reads the initial tab from `window.location.hash`, keeps it in sync
 * as the user navigates, and handles browser back/forward.
 */
export function useHashTab<T extends string>(
  validTabs: readonly T[],
  defaultTab: T,
): [T, (tab: T) => void] {
  const readHash = useCallback((): T => {
    const hash = window.location.hash.replace('#', '')
    return (validTabs as readonly string[]).includes(hash) ? (hash as T) : defaultTab
  }, [validTabs, defaultTab])

  const [activeTab, setActiveTab] = useState<T>(readHash)

  // Sync tab → hash
  useEffect(() => {
    window.location.hash = activeTab
  }, [activeTab])

  // Sync hash → tab (browser back/forward)
  useEffect(() => {
    const handleHashChange = () => setActiveTab(readHash())
    window.addEventListener('hashchange', handleHashChange)
    return () => window.removeEventListener('hashchange', handleHashChange)
  }, [readHash])

  return [activeTab, setActiveTab]
}
