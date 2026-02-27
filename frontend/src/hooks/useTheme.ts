import { useCallback, useEffect, useState } from 'react'

type Theme = 'light' | 'dark' | 'system'

const THEME_KEY = 'mcpbox-theme'

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(() => {
    if (typeof window === 'undefined') return 'system'
    return (localStorage.getItem(THEME_KEY) as Theme) || 'system'
  })

  const [isDark, setIsDark] = useState(false)

  // Determine if dark mode should be active
  useEffect(() => {
    const updateDarkMode = () => {
      let shouldBeDark = false

      if (theme === 'dark') {
        shouldBeDark = true
      } else if (theme === 'system') {
        shouldBeDark = window.matchMedia('(prefers-color-scheme: dark)').matches
      }

      setIsDark(shouldBeDark)

      // Update document class
      if (shouldBeDark) {
        document.documentElement.classList.add('dark')
      } else {
        document.documentElement.classList.remove('dark')
      }

      // Sync iOS/Android status bar color with current theme.
      // The <meta name="theme-color"> in index.html uses media queries
      // for system-preference detection, but when the user overrides
      // the theme via the in-app toggle we must update both meta tags
      // so the browser picks up the correct color immediately.
      const themeColor = shouldBeDark ? '#232136' : '#faf4ed'
      document
        .querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')
        .forEach((meta) => {
          meta.setAttribute('content', themeColor)
        })
    }

    updateDarkMode()

    // Listen for system preference changes
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => {
      if (theme === 'system') {
        updateDarkMode()
      }
    }

    mediaQuery.addEventListener('change', handler)
    return () => mediaQuery.removeEventListener('change', handler)
  }, [theme])

  const setTheme = useCallback((newTheme: Theme) => {
    setThemeState(newTheme)
    localStorage.setItem(THEME_KEY, newTheme)
  }, [])

  return {
    theme,
    setTheme,
    isDark,
  }
}
