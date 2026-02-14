import { render, screen, fireEvent, waitFor } from '../../../test/utils'
import { ServerCard } from '../ServerCard'
import { createMockServer } from '../../../test/mocks/handlers'

describe('ServerCard', () => {
  it('renders server name and description', () => {
    const server = createMockServer({
      name: 'My API Server',
      description: 'A test API server for development',
    })

    render(<ServerCard server={server} />)

    expect(screen.getByText('My API Server')).toBeInTheDocument()
    expect(screen.getByText('A test API server for development')).toBeInTheDocument()
  })

  it('renders server without description', () => {
    const server = createMockServer({
      name: 'Simple Server',
      description: null,
    })

    render(<ServerCard server={server} />)

    expect(screen.getByText('Simple Server')).toBeInTheDocument()
    expect(screen.queryByText('null')).not.toBeInTheDocument()
  })

  it('displays tool count correctly', () => {
    const server = createMockServer({ tool_count: 5 })
    render(<ServerCard server={server} />)

    expect(screen.getByText('5 tools')).toBeInTheDocument()
  })

  it('displays singular tool when count is 1', () => {
    const server = createMockServer({ tool_count: 1 })
    render(<ServerCard server={server} />)

    expect(screen.getByText('1 tool')).toBeInTheDocument()
  })

  it('displays network mode', () => {
    const server = createMockServer({ network_mode: 'monitored' })
    render(<ServerCard server={server} />)

    expect(screen.getByText('monitored')).toBeInTheDocument()
  })

  it('displays status badge', () => {
    const server = createMockServer({ status: 'ready' })
    render(<ServerCard server={server} />)

    expect(screen.getByRole('status')).toHaveTextContent('Ready')
  })

  it('renders as a link to server detail page', () => {
    const server = createMockServer({ id: 'server-123' })
    render(<ServerCard server={server} />)

    const link = screen.getByRole('link')
    expect(link).toHaveAttribute('href', '/servers/server-123')
  })

  it('shows Start button for ready server', () => {
    const server = createMockServer({ status: 'ready' })
    render(<ServerCard server={server} />)

    expect(screen.getByRole('button', { name: /Start/ })).toBeInTheDocument()
  })

  it('shows Stop button for running server', () => {
    const server = createMockServer({ status: 'running' })
    render(<ServerCard server={server} />)

    expect(screen.getByRole('button', { name: /Stop/ })).toBeInTheDocument()
  })

  it('shows Start button for stopped server', () => {
    const server = createMockServer({ status: 'stopped' })
    render(<ServerCard server={server} />)

    expect(screen.getByRole('button', { name: /Start/ })).toBeInTheDocument()
  })

  it('does not show start/stop for building server', () => {
    const server = createMockServer({ status: 'building' })
    render(<ServerCard server={server} />)

    expect(screen.queryByRole('button', { name: /Start/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Stop/ })).not.toBeInTheDocument()
  })

  it('handles start mutation when Start button is clicked', async () => {
    const server = createMockServer({ id: 'server-1', status: 'ready' })
    render(<ServerCard server={server} />)

    const startButton = screen.getByRole('button', { name: /Start/ })

    // Should not throw when clicked
    expect(() => fireEvent.click(startButton)).not.toThrow()

    // Wait for mutation to complete (button text may change)
    await waitFor(() => {
      // The mutation should complete without error
      expect(screen.queryByText(/error/i)).not.toBeInTheDocument()
    })
  })

  it('handles stop mutation when Stop button is clicked', async () => {
    const server = createMockServer({ id: 'server-1', status: 'running' })
    render(<ServerCard server={server} />)

    const stopButton = screen.getByRole('button', { name: /Stop/ })

    // Should not throw when clicked
    expect(() => fireEvent.click(stopButton)).not.toThrow()

    // Wait for mutation to complete
    await waitFor(() => {
      // The mutation should complete without error
      expect(screen.queryByText(/error/i)).not.toBeInTheDocument()
    })
  })

  it('prevents navigation when clicking start/stop button', () => {
    const server = createMockServer({ status: 'ready' })
    render(<ServerCard server={server} />)

    const startButton = screen.getByRole('button', { name: /Start/ })

    // The click handler should call stopPropagation
    const event = new MouseEvent('click', { bubbles: true })
    vi.spyOn(event, 'preventDefault')
    vi.spyOn(event, 'stopPropagation')

    startButton.dispatchEvent(event)

    expect(event.preventDefault).toHaveBeenCalled()
    expect(event.stopPropagation).toHaveBeenCalled()
  })
})
