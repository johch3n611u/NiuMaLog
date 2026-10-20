import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 開發時 /api 轉給後端；正式版由 FastAPI 直接服務同源靜態檔，不需要 proxy。
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
