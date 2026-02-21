import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: '/static/',
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8092',
      '/v1': 'http://localhost:8092',
    },
  },
})
