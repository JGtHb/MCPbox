interface StatCardProps {
  title: string
  value: number | string
  subtitle?: string
  loading?: boolean
  color?: 'blue' | 'green' | 'red' | 'gray'
}

export function StatCard({ title, value, subtitle, loading, color = 'blue' }: StatCardProps) {
  const colorClasses = {
    blue: 'text-pine',
    green: 'text-foam',
    red: 'text-love',
    gray: 'text-subtle',
  }

  return (
    <div className="bg-surface rounded-lg shadow p-3 sm:p-4">
      <p className="text-xs sm:text-sm text-subtle">{title}</p>
      {loading ? (
        <div className="h-8 bg-hl-low rounded animate-pulse mt-1" />
      ) : (
        <>
          <p className={`text-xl sm:text-2xl font-bold ${colorClasses[color]}`}>{value}</p>
          {subtitle && <p className="text-xs text-muted mt-1">{subtitle}</p>}
        </>
      )}
    </div>
  )
}
