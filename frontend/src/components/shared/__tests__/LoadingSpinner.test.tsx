import { render } from '../../../test/utils'
import { LoadingSpinner } from '../LoadingSpinner'

describe('LoadingSpinner', () => {
  it('renders an SVG element', () => {
    render(<LoadingSpinner />)
    const spinner = document.querySelector('svg')
    expect(spinner).toBeInTheDocument()
  })

  it('has aria-hidden attribute for accessibility', () => {
    render(<LoadingSpinner />)
    const spinner = document.querySelector('svg')
    expect(spinner).toHaveAttribute('aria-hidden', 'true')
  })

  it('applies small size class', () => {
    render(<LoadingSpinner size="sm" />)
    const spinner = document.querySelector('svg')
    expect(spinner).toHaveClass('h-3', 'w-3')
  })

  it('applies medium size class by default', () => {
    render(<LoadingSpinner />)
    const spinner = document.querySelector('svg')
    expect(spinner).toHaveClass('h-4', 'w-4')
  })

  it('applies large size class', () => {
    render(<LoadingSpinner size="lg" />)
    const spinner = document.querySelector('svg')
    expect(spinner).toHaveClass('h-6', 'w-6')
  })

  it('applies custom className', () => {
    render(<LoadingSpinner className="text-blue-500" />)
    const spinner = document.querySelector('svg')
    expect(spinner).toHaveClass('text-blue-500')
  })

  it('has animation class', () => {
    render(<LoadingSpinner />)
    const spinner = document.querySelector('svg')
    expect(spinner).toHaveClass('animate-spin')
  })
})
