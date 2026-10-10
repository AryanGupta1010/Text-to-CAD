import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/providers': 'http://127.0.0.1:8000',
      '/settings': 'http://127.0.0.1:8000',
      '/cad': 'http://127.0.0.1:8000',
      '/generate-cad': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    }
  }
})
