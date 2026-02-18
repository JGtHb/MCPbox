import type { ReactNode } from 'react'

interface HeaderProps {
  title: string
  action?: ReactNode
}

export function Header({ title, action }: HeaderProps) {
  return (
    <header className="bg-surface border-b border-hl-med px-6 py-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-on-base">{title}</h2>
        {action && <div>{action}</div>}
      </div>
    </header>
  )
}
