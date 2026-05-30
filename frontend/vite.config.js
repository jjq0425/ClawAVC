import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 15101,
    proxy: {
      '/api/': 'http://127.0.0.1:15100',
      '/wss': {
        target: 'http://127.0.0.1:15100',
        ws: true,
      },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 15101,
    proxy: {
      '/api/': 'http://127.0.0.1:15100',
      '/wss': {
        target: 'http://127.0.0.1:15100',
        ws: true,
      },
    },
  },
})
