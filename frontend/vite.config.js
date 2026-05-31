import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { compression } from 'vite-plugin-compression2'
import fs from 'node:fs'
import path from 'node:path'
import { extname } from 'node:path'

// ─── Pre-compressed asset middleware (preview mode) ──────────────────────
// vite preview's sirv-based static handler is wired into the underlying
// http.Server's 'request' event. To beat sirv to a request, we use
// prependListener — BUT prependListener only wins if our handler is fully
// synchronous: any `await` yields the event loop, sirv responds, and our
// handler is left holding stale headers (we hit "Cannot set headers after
// they are sent to the client" the first time we tried this with async fs).
//
// Therefore we pre-load every .br / .gz under dist/ into memory at server
// startup, and the request-handler is a pure-sync map lookup. Cuts the
// 1.17 MB tdesign chunk to 255 KB on the wire (brotli) or 315 KB (gzip).
function servePreCompressed() {
  return {
    name: 'serve-pre-compressed',
    configurePreviewServer(server) {
      const distRoot = path.resolve(process.cwd(), 'dist')
      // Map: urlPath ('/assets/foo.js') -> { br?: Buffer, gzip?: Buffer, contentType }
      const assetCache = new Map()

      function loadAssets(dir, urlPrefix) {
        let entries
        try { entries = fs.readdirSync(dir, { withFileTypes: true }) } catch { return }
        for (const entry of entries) {
          const full = path.join(dir, entry.name)
          const urlPath = urlPrefix + '/' + entry.name
          if (entry.isDirectory()) { loadAssets(full, urlPath); continue }
          if (!entry.isFile()) continue
          const m = entry.name.match(/^(.+)\.(br|gz)$/)
          if (!m) continue
          const baseUrlPath = urlPrefix + '/' + m[1]
          const ext = extname(m[1])
          if (!['.js', '.css', '.svg', '.json', '.html'].includes(ext)) continue
          const encoding = m[2] === 'br' ? 'br' : 'gzip'
          let body
          try { body = fs.readFileSync(full) } catch { continue }
          const existing = assetCache.get(baseUrlPath) || { contentType: mimeFor(ext) }
          existing[encoding] = body
          assetCache.set(baseUrlPath, existing)
        }
      }
      loadAssets(distRoot, '')
      console.log('[serve-pre-compressed] cached ' + assetCache.size + ' precompressed assets from ' + distRoot)

      const handle = (req, res) => {
        if (!req.url || req.method !== 'GET') return
        const url = req.url.split('?')[0]
        const cached = assetCache.get(url)
        if (!cached) return
        const accept = String(req.headers['accept-encoding'] || '')
        let encoding = null
        if (accept.includes('br') && cached.br)        encoding = 'br'
        else if (accept.includes('gzip') && cached.gzip) encoding = 'gzip'
        if (!encoding) return
        const body = cached[encoding]
        try {
          res.setHeader('Content-Encoding', encoding)
          res.setHeader('Content-Type', cached.contentType)
          res.setHeader('Content-Length', String(body.length))
          res.setHeader('Vary', 'Accept-Encoding')
          res.setHeader('Cache-Control', 'public, max-age=31536000, immutable')
          res.statusCode = 200
          res.end(body)
        } catch { /* shouldn't happen — we run before sirv synchronously */ }
      }

      // Synchronous prepended request listener — runs before sirv's listener
      // and never yields the event loop, so sirv's handler can't race us.
      server.httpServer.prependListener('request', handle)
    },
  }
}

function mimeFor(ext) {
  switch (ext) {
    case '.js':   return 'text/javascript; charset=utf-8'
    case '.css':  return 'text/css; charset=utf-8'
    case '.svg':  return 'image/svg+xml'
    case '.json': return 'application/json; charset=utf-8'
    case '.html': return 'text/html; charset=utf-8'
    default:      return 'application/octet-stream'
  }
}

export default defineConfig({
  plugins: [
    vue(),

    // Pre-compress at build time. Generates dist/**/*.{js,css,svg,html}.{gz,br}
    // so the runtime cost is zero and we can serve them directly.
    compression({ algorithm: 'gzip',           exclude: [/\.(br|gz)$/], threshold: 1024 }),
    compression({ algorithm: 'brotliCompress', exclude: [/\.(br|gz)$/], threshold: 1024 }),

    servePreCompressed(),
  ],

  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vue-vendor':    ['vue', 'vue-router'],
          'tdesign':       ['tdesign-vue-next'],
          'tdesign-icons': ['tdesign-icons-vue-next'],
          'socket':        ['socket.io-client'],
        },
      },
    },
    chunkSizeWarningLimit: 800,
  },

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
