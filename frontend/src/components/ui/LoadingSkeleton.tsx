interface LoadingCardProps {
  /** Number of text lines to show */
  lines?: number
  /** Whether to show an avatar/icon placeholder */
  showAvatar?: boolean
  /** Additional CSS classes */
  className?: string
}

/**
 * Loading skeleton for card-style content.
 *
 * @example
 * ```tsx
 * <LoadingCard lines={3} showAvatar />
 * ```
 */
export function LoadingCard({
  lines = 2,
  showAvatar = false,
  className = '',
}: LoadingCardProps) {
  return (
    <div
      className={`bg-white rounded-lg shadow p-6 animate-pulse ${className}`}
      role="status"
      aria-label="Loading content..."
    >
      <div className="flex items-start space-x-4">
        {showAvatar && (
          <div className="w-12 h-12 bg-gray-200 rounded-full flex-shrink-0" />
        )}
        <div className="flex-1 space-y-3">
          <div className="h-5 bg-gray-200 rounded w-3/4" />
          {Array.from({ length: lines - 1 }).map((_, i) => (
            <div
              key={i}
              className="h-4 bg-gray-200 rounded"
              style={{ width: `${60 + Math.random() * 30}%` }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
