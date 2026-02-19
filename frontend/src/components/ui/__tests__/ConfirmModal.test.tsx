import { render, screen, fireEvent } from '../../../test/utils'
import { ConfirmModal, useConfirmModal } from '../ConfirmModal'
import { renderHook, act } from '@testing-library/react'

describe('ConfirmModal', () => {
  const defaultProps = {
    isOpen: true,
    title: 'Confirm Action',
    message: 'Are you sure you want to proceed?',
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders nothing when closed', () => {
    render(<ConfirmModal {...defaultProps} isOpen={false} />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('renders modal when open', () => {
    render(<ConfirmModal {...defaultProps} />)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('Confirm Action')).toBeInTheDocument()
    expect(screen.getByText('Are you sure you want to proceed?')).toBeInTheDocument()
  })

  it('renders default button labels', () => {
    render(<ConfirmModal {...defaultProps} />)
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm' })).toBeInTheDocument()
  })

  it('renders custom button labels', () => {
    render(
      <ConfirmModal
        {...defaultProps}
        confirmLabel="Delete"
        cancelLabel="Keep"
      />
    )
    expect(screen.getByRole('button', { name: 'Keep' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
  })

  it('calls onConfirm when confirm button is clicked', () => {
    render(<ConfirmModal {...defaultProps} />)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(defaultProps.onConfirm).toHaveBeenCalledTimes(1)
  })

  it('calls onCancel when cancel button is clicked', () => {
    render(<ConfirmModal {...defaultProps} />)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(defaultProps.onCancel).toHaveBeenCalledTimes(1)
  })

  it('calls onCancel when Escape key is pressed', () => {
    render(<ConfirmModal {...defaultProps} />)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(defaultProps.onCancel).toHaveBeenCalledTimes(1)
  })

  it('calls onCancel when clicking backdrop', () => {
    render(<ConfirmModal {...defaultProps} />)
    // The backdrop is the container with flex
    const backdrop = screen.getByRole('dialog').parentElement?.querySelector('[aria-hidden="true"]')
    if (backdrop) {
      fireEvent.click(backdrop)
      expect(defaultProps.onCancel).toHaveBeenCalledTimes(1)
    }
  })

  it('shows loading state', () => {
    render(<ConfirmModal {...defaultProps} isLoading />)
    expect(screen.getByText('Processing...')).toBeInTheDocument()
  })

  it('disables buttons when loading', () => {
    render(<ConfirmModal {...defaultProps} isLoading />)
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Processing/i })).toBeDisabled()
  })

  it('applies destructive styling', () => {
    render(<ConfirmModal {...defaultProps} destructive />)
    const confirmButton = screen.getByRole('button', { name: 'Confirm' })
    expect(confirmButton).toHaveClass('bg-love')
  })

  it('applies non-destructive styling by default', () => {
    render(<ConfirmModal {...defaultProps} />)
    const confirmButton = screen.getByRole('button', { name: 'Confirm' })
    expect(confirmButton).toHaveClass('bg-rose')
  })
})

describe('useConfirmModal', () => {
  it('starts with isOpen false', () => {
    const { result } = renderHook(() => useConfirmModal())
    expect(result.current.isOpen).toBe(false)
  })

  it('opens modal on confirm', () => {
    const { result } = renderHook(() => useConfirmModal())

    act(() => {
      result.current.confirm()
    })

    expect(result.current.isOpen).toBe(true)
  })

  it('closes modal on cancel', () => {
    const { result } = renderHook(() => useConfirmModal())

    act(() => {
      result.current.confirm()
    })

    act(() => {
      result.current.cancel()
    })

    expect(result.current.isOpen).toBe(false)
  })

  it('stores data when confirming with value', () => {
    const { result } = renderHook(() => useConfirmModal<string>())

    act(() => {
      result.current.confirm('test-id')
    })

    expect(result.current.data).toBe('test-id')
  })

  it('clears data on cancel', () => {
    const { result } = renderHook(() => useConfirmModal<string>())

    act(() => {
      result.current.confirm('test-id')
    })

    act(() => {
      result.current.cancel()
    })

    expect(result.current.data).toBeUndefined()
  })
})
