import { NavLink } from 'react-router-dom'
import { useAuth } from '../../contexts'

interface NavItem {
  to: string
  label: string
  icon: string
}

const navItems: NavItem[] = [
  { to: '/', label: 'Dashboard', icon: '📊' },
  { to: '/servers', label: 'Servers', icon: '🖥️' },
  { to: '/tunnel', label: 'Tunnel', icon: '🌐' },
  { to: '/activity', label: 'Activity', icon: '📈' },
  { to: '/approvals', label: 'Approvals', icon: '✅' },
  { to: '/settings', label: 'Settings', icon: '⚙️' },
]

type Theme = 'light' | 'dark' | 'system'

interface SidebarProps {
  isDark: boolean
  theme: Theme
  setTheme: (theme: Theme) => void
  onClose?: () => void
}

export function Sidebar({ isDark, theme, setTheme, onClose }: SidebarProps) {
  const { logout } = useAuth()
  return (
    <aside className="w-64 h-full bg-overlay text-on-base flex flex-col">
      {/* Logo with close button on mobile */}
      <div className="p-4 border-b border-hl-med flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">MCPbox</h1>
          <p className="text-xs text-muted">MCP Server Management</p>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="lg:hidden p-2 text-muted hover:text-on-base hover:bg-hl-med rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
            aria-label="Close sidebar"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 overflow-y-auto">
        <ul className="space-y-2">
          {navItems.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                onClick={onClose}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${
                    isActive
                      ? 'bg-iris text-base font-medium'
                      : 'text-subtle hover:bg-hl-med hover:text-on-base'
                  }`
                }
              >
                <span className="text-lg">{item.icon}</span>
                <span>{item.label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      {/* Theme Toggle */}
      <div className="p-4 border-t border-hl-med">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-muted">Theme</span>
          <span className="text-xs text-subtle">{isDark ? 'Dark' : 'Light'}</span>
        </div>
        <div className="flex rounded-lg overflow-hidden bg-hl-low">
          <button
            onClick={() => setTheme('light')}
            className={`flex-1 px-2 py-1.5 text-xs transition-colors focus:outline-none focus:ring-2 focus:ring-iris focus:z-10 ${
              theme === 'light'
                ? 'bg-iris text-base'
                : 'text-muted hover:text-on-base'
            }`}
            aria-label="Light mode"
          >
            ☀️
          </button>
          <button
            onClick={() => setTheme('system')}
            className={`flex-1 px-2 py-1.5 text-xs transition-colors focus:outline-none focus:ring-2 focus:ring-iris focus:z-10 ${
              theme === 'system'
                ? 'bg-iris text-base'
                : 'text-muted hover:text-on-base'
            }`}
            aria-label="System theme"
          >
            💻
          </button>
          <button
            onClick={() => setTheme('dark')}
            className={`flex-1 px-2 py-1.5 text-xs transition-colors focus:outline-none focus:ring-2 focus:ring-iris focus:z-10 ${
              theme === 'dark'
                ? 'bg-iris text-base'
                : 'text-muted hover:text-on-base'
            }`}
            aria-label="Dark mode"
          >
            🌙
          </button>
        </div>
      </div>

      {/* Logout */}
      <div className="p-4 border-t border-hl-med">
        <button
          onClick={logout}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-subtle hover:bg-hl-med hover:text-on-base transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
        >
          <span className="text-lg">🚪</span>
          <span>Logout</span>
        </button>
      </div>

      {/* Footer */}
      <div className="p-4 border-t border-hl-med text-xs text-muted">
        <p>v0.1.0 • Development</p>
      </div>
    </aside>
  )
}
