import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    clearMocks: true,
    restoreMocks: true,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('/node_modules/recharts/es6/chart/')) return 'recharts-charts'
          if (id.includes('/node_modules/recharts/')) return 'recharts'
          if (id.includes('/node_modules/victory-vendor/')) return 'chart-utils'
          if (id.includes('/node_modules/d3-')) return 'd3'
        },
      },
    },
  },
})
