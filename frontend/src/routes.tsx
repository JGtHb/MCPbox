import { createBrowserRouter } from 'react-router-dom'
import { Layout } from './components/Layout'
import {
  Activity,
  Approvals,
  CloudflareWizard,
  Dashboard,
  NotFound,
  Servers,
  ServerDetail,
  Tunnel,
  Settings,
} from './pages'
import { OAuthCallback } from './pages/OAuthCallback'

export const router = createBrowserRouter([
  // OAuth callback - outside Layout (runs in popup window)
  {
    path: '/oauth/callback',
    element: <OAuthCallback />,
  },
  {
    path: '/',
    element: <Layout />,
    children: [
      {
        index: true,
        element: <Dashboard />,
      },
      {
        path: 'servers',
        element: <Servers />,
      },
      {
        path: 'servers/:id',
        element: <ServerDetail />,
      },
      {
        path: 'tunnel',
        element: <Tunnel />,
      },
      {
        path: 'tunnel/setup',
        element: <CloudflareWizard />,
      },
      {
        path: 'activity',
        element: <Activity />,
      },
      {
        path: 'approvals',
        element: <Approvals />,
      },
      {
        path: 'settings',
        element: <Settings />,
      },
      {
        path: '*',
        element: <NotFound />,
      },
    ],
  },
])
