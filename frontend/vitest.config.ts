import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Node 23+ has native Web Storage API that conflicts with jsdom's localStorage.
// msw's CookieStore accesses localStorage at import time before jsdom can set up its mock.
// --no-webstorage lets jsdom provide its own implementation, but is only available on Node 23+.
const nodeMajor = parseInt(process.versions.node.split('.')[0], 10)
const testEnv: Record<string, string> = {}
if (nodeMajor >= 23) {
  testEnv.NODE_OPTIONS = '--no-webstorage'
}

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    env: testEnv,
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
