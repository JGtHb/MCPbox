import type { ReactNode } from 'react'

interface HeaderProps {
  title: string
  action?: ReactNode
}

export function Header({ title, action }: HeaderProps) {
  return (
    <header className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white">{title}</h2>
        {action && <div>{action}</div>}
      </div>
    </header>
  )
}
