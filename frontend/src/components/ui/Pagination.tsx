interface PaginationProps {
  page: number
  totalPages: number
  onPageChange: (page: number) => void
}

export function Pagination({ page, totalPages, onPageChange }: PaginationProps) {
  if (totalPages <= 1) return null

  return (
    <div className="flex items-center justify-between px-4 py-3 border-t border-hl-med text-sm">
      <button
        onClick={() => onPageChange(Math.max(1, page - 1))}
        disabled={page <= 1}
        className="px-3 py-1 border border-hl-med rounded-lg text-on-base disabled:opacity-50 disabled:cursor-not-allowed hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
      >
        Previous
      </button>
      <span className="text-subtle">
        Page {page} of {totalPages}
      </span>
      <button
        onClick={() => onPageChange(Math.min(totalPages, page + 1))}
        disabled={page >= totalPages}
        className="px-3 py-1 border border-hl-med rounded-lg text-on-base disabled:opacity-50 disabled:cursor-not-allowed hover:bg-hl-low transition-colors focus:outline-none focus:ring-2 focus:ring-iris"
      >
        Next
      </button>
    </div>
  )
}
