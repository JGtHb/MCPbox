import { Link } from 'react-router-dom'
import { Header } from '../components/Layout'

export function NotFound() {
  return (
    <div className="dark:bg-gray-900 min-h-full">
      <Header title="Page Not Found" />
      <div className="flex items-center justify-center p-6 min-h-[60vh]">
        <div className="max-w-md w-full text-center">
          <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-gray-100 dark:bg-gray-800 flex items-center justify-center">
            <span className="text-3xl font-bold text-gray-400 dark:text-gray-500">404</span>
          </div>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
            Page not found
          </h2>
          <p className="text-gray-600 dark:text-gray-400 mb-6">
            The page you are looking for does not exist or has been moved.
          </p>
          <Link
            to="/"
            className="inline-flex px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 dark:focus:ring-offset-gray-900"
          >
            Go to Dashboard
          </Link>
        </div>
      </div>
    </div>
  )
}
