import { render, screen, waitFor, fireEvent } from '../../test/utils'
import { Dashboard } from '../Dashboard'

describe('Dashboard', () => {
  it('renders the dashboard header', async () => {
    render(<Dashboard />)

    expect(screen.getByText('Dashboard')).toBeInTheDocument()
  })

  it('shows period selector with default 24h selected', async () => {
    render(<Dashboard />)

    expect(screen.getByRole('button', { name: '24h' })).toHaveClass('bg-rose')
  })

  it('allows changing the period', async () => {
    render(<Dashboard />)

    fireEvent.click(screen.getByRole('button', { name: '1h' }))

    expect(screen.getByRole('button', { name: '1h' })).toHaveClass('bg-rose')
    expect(screen.getByRole('button', { name: '24h' })).not.toHaveClass('bg-rose')
  })

  it('displays stats cards', async () => {
    render(<Dashboard />)

    await waitFor(() => {
      // Some labels appear multiple times on the page
      expect(screen.getAllByText('Servers').length).toBeGreaterThan(0)
      expect(screen.getByText('Tools')).toBeInTheDocument()
      expect(screen.getByText('Requests')).toBeInTheDocument()
      expect(screen.getAllByText('Errors').length).toBeGreaterThan(0)
      expect(screen.getByText('Avg Response')).toBeInTheDocument()
      expect(screen.getAllByText('Tunnel').length).toBeGreaterThan(0)
    })
  })

  it('displays system status section', async () => {
    render(<Dashboard />)

    await waitFor(() => {
      expect(screen.getByText('System Status')).toBeInTheDocument()
      expect(screen.getByText('Backend API')).toBeInTheDocument()
      expect(screen.getByText('Database')).toBeInTheDocument()
      expect(screen.getByText('Sandbox')).toBeInTheDocument()
    })
  })

  it('displays server list section', async () => {
    render(<Dashboard />)

    await waitFor(() => {
      // The Servers heading in the server summary section
      expect(screen.getAllByText('Servers').length).toBeGreaterThan(0)
      // There are multiple "View all" links on the page (servers and errors)
      const viewAllLinks = screen.getAllByRole('link', { name: 'View all' })
      expect(viewAllLinks.length).toBeGreaterThan(0)
    })
  })

  it('displays top tools section', async () => {
    render(<Dashboard />)

    await waitFor(() => {
      expect(screen.getByText('Top Tools')).toBeInTheDocument()
    })
  })

  it('displays recent errors section', async () => {
    render(<Dashboard />)

    await waitFor(() => {
      expect(screen.getByText('Recent Errors')).toBeInTheDocument()
    })
  })

  it('displays chart sections', async () => {
    render(<Dashboard />)

    await waitFor(() => {
      expect(screen.getByText('Request Volume')).toBeInTheDocument()
      expect(screen.getByText('Errors Over Time')).toBeInTheDocument()
    })
  })

  it('shows loading placeholder while data loads', () => {
    render(<Dashboard />)

    // Check for loading indicator in stats (shows "-" while loading)
    const statCards = screen.getAllByText('-')
    expect(statCards.length).toBeGreaterThan(0)
  })

  it('has link to servers page', async () => {
    render(<Dashboard />, {
      routerProps: { initialEntries: ['/'] },
    })

    await waitFor(() => {
      // There are multiple "View all" links - check they exist
      const viewAllLinks = screen.getAllByRole('link', { name: 'View all' })
      expect(viewAllLinks.length).toBeGreaterThan(0)
      // First one should link to servers
      expect(viewAllLinks[0]).toHaveAttribute('href', '/servers')
    })
  })
})
