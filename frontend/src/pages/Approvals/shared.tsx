import { APPROVAL_STATUS_COLORS, APPROVAL_STATUS_LABELS } from '../../lib/constants'

// Status badge component for approval items
export function StatusBadge({ status }: { status: string }) {
  const colors = APPROVAL_STATUS_COLORS[status] || 'bg-overlay text-subtle'
  const label = APPROVAL_STATUS_LABELS[status] || status

  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${colors}`}>
      {label}
    </span>
  )
}

// Format a date string for display
export function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })
}

// Check if a status is pending (actionable)
export function isPendingStatus(status?: string): boolean {
  return !status || status === 'pending_review' || status === 'pending'
}

// Stats Card Component
export function StatCard({
  label,
  pendingValue,
  approvedValue,
  loading,
  onClick,
  active,
}: {
  label: string
  pendingValue: number
  approvedValue: number
  loading: boolean
  onClick: () => void
  active: boolean
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-lg border p-4 text-left transition-colors ${
        active
          ? 'border-rose bg-rose/10'
          : 'border-hl-med bg-surface hover:border-hl-high'
      }`}
    >
      <p className="text-sm font-medium text-subtle">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-on-base">
        {loading ? '...' : pendingValue}
      </p>
      <p className="mt-1 text-xs text-muted">
        {loading ? '' : `${approvedValue} approved`}
      </p>
    </button>
  )
}

// Tab Button Component
export function TabButton({
  label,
  count,
  active,
  onClick,
}: {
  label: string
  count: number
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-iris focus:ring-inset ${
        active
          ? 'border-rose text-rose'
          : 'border-transparent text-subtle hover:border-hl-high hover:text-on-base'
      }`}
    >
      {label}
      {count > 0 && (
        <span
          className={`ml-2 rounded-full px-2.5 py-0.5 text-xs font-medium ${
            active ? 'bg-rose/10 text-rose' : 'bg-hl-low text-subtle'
          }`}
        >
          {count}
        </span>
      )}
    </button>
  )
}

// Severity badge colors
export function severityColor(severity: string | null): string {
  switch (severity?.toUpperCase()) {
    case 'CRITICAL':
      return 'bg-love text-base'
    case 'HIGH':
      return 'bg-love/10 text-love'
    case 'MEDIUM':
      return 'bg-gold/10 text-gold'
    case 'LOW':
      return 'bg-hl-low text-on-base'
    default:
      return 'bg-hl-low text-subtle'
  }
}

// OpenSSF Scorecard color (0-10 scale)
export function scorecardColor(score: number): string {
  if (score >= 7) return 'text-foam'
  if (score >= 4) return 'text-gold'
  return 'text-love'
}
