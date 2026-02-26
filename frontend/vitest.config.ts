import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    // Node 25+ has native Web Storage API that conflicts with jsdom's localStorage.
    // msw's CookieStore accesses localStorage at import time before jsdom can set up its mock.
    // Disabling native webstorage lets jsdom provide its own implementation.
    env: {
      NODE_OPTIONS: '--no-webstorage',
    },
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: [
        'node_modules/',
        'src/test/',
        '**/*.d.ts',
        '**/*.config.*',
        '**/main.tsx',
      ],
    },
  },
})
