import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, RenderOptions } from '@testing-library/react'
import { MemoryRouter, MemoryRouterProps } from 'react-router-dom'
import { ReactElement, ReactNode } from 'react'

// Create a new QueryClient for each test
function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
        staleTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  })
}

interface AllProvidersProps {
  children: ReactNode
  routerProps?: MemoryRouterProps
}

function AllProviders({ children, routerProps }: AllProvidersProps) {
  const queryClient = createTestQueryClient()

  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter {...routerProps}>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

interface CustomRenderOptions extends Omit<RenderOptions, 'wrapper'> {
  routerProps?: MemoryRouterProps
}

function customRender(ui: ReactElement, options?: CustomRenderOptions) {
  const { routerProps, ...renderOptions } = options || {}

  return render(ui, {
    wrapper: ({ children }) => (
      <AllProviders routerProps={routerProps}>{children}</AllProviders>
    ),
    ...renderOptions,
  })
}

// Re-export everything from testing-library
export * from '@testing-library/react'
export { userEvent } from '@testing-library/user-event'

// Override render method
export { customRender as render }

// Helper to create a test query client for hook testing
export { createTestQueryClient }

// Wait for async operations to complete
export async function waitForLoadingToFinish() {
  // Small delay to allow React Query to settle
  await new Promise((resolve) => setTimeout(resolve, 0))
}

// Helper to get mock data
export { createMockServer, createMockServerDetail, createMockTool, createMockToolListItem, mockServers, mockTools } from './mocks/handlers'
