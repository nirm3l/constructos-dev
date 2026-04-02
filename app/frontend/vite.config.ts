import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import pkg from './package.json'

const runtimeEnv = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env ?? {}
const resolvedFrontendVersion =
  runtimeEnv.VITE_APP_VERSION
  || runtimeEnv.APP_VERSION
  || pkg.version
  || 'dev'

export default defineConfig({
  base: '/static/',
  define: {
    'import.meta.env.VITE_APP_VERSION': JSON.stringify(resolvedFrontendVersion),
  },
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.indexOf('node_modules') === -1) return
          if (id.indexOf('@tanstack/react-query') !== -1) return 'vendor-query'
          if (
            id.indexOf('react-markdown') !== -1
            || id.indexOf('remark') !== -1
            || id.indexOf('rehype') !== -1
            || id.indexOf('highlight.js') !== -1
          ) {
            return 'vendor-markdown'
          }
        },
      },
    },
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000'
    }
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
  },
})
