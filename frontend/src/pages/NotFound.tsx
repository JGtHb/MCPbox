import { Link } from 'react-router-dom'
import { Header } from '../components/Layout'

export function NotFound() {
  return (
    <div className="min-h-full">
      <Header title="Page Not Found" />
      <div className="flex items-center justify-center p-6 min-h-[60vh]">
        <div className="max-w-md w-full text-center">
          <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-hl-low flex items-center justify-center">
            <span className="text-3xl font-bold text-muted">404</span>
          </div>
          <h2 className="text-xl font-semibold text-on-base mb-2">
            Page not found
          </h2>
          <p className="text-subtle mb-6">
            The page you are looking for does not exist or has been moved.
          </p>
          <Link
            to="/"
            className="inline-flex px-4 py-2 text-sm font-medium text-base bg-iris rounded-lg hover:bg-iris/80 transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-iris"
          >
            Go to Dashboard
          </Link>
        </div>
      </div>
    </div>
  )
}
