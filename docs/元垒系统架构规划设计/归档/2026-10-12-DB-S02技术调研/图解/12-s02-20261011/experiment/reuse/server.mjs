import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { readFileSync, openSync, closeSync, constants } from 'node:fs'
import { createHash } from 'node:crypto'

const root = dirname(fileURLToPath(import.meta.url))
const repo = resolve(root, '../../../../../..')
if (!process.env.S02_REUSE_DEPS) throw Error('S02_REUSE_DEPS_required')
const require = createRequire(resolve(repo, 'web/package.json'))
const { createServer, build } = await import(require.resolve('vite'))
const vue = (await import(require.resolve('@vitejs/plugin-vue'))).default
const files = { metrics: ['metrics.json', 'application/json'], image: ['sample.png', 'image/png'], report: ['report.html', 'text/html'], notes: ['notes.md', 'text/markdown'] }

/** 仅读取合成夹具中的声明文件，拒绝符号链接。 */
function readFixture(name) {
  const fd = openSync(resolve(root, '../fixtures', name), constants.O_RDONLY | constants.O_NOFOLLOW)
  try { return readFileSync(fd) } finally { closeSync(fd) }
}

const config = {
  configFile: false, root, plugins: [vue()],
  resolve: { alias: { vue: require.resolve('vue/dist/vue.runtime.esm-bundler.js'), 'markdown-it': require.resolve('markdown-it'), dompurify: require.resolve('dompurify'), '@formkit/vue': resolve(process.env.S02_REUSE_DEPS, 'node_modules/@formkit/vue/dist/index.mjs'), '@static-frame': resolve(repo, 'web/src/utils/dashboardFrame.js') } },
  build: { outDir: '/tmp/yuanlei-s02-reuse-build', emptyOutDir: true },
  server: { host: '127.0.0.1', port: 5189, strictPort: true, fs: { allow: [resolve(root, '..'), process.env.S02_REUSE_DEPS, resolve(repo, 'web/node_modules'), resolve(repo, 'web/src/utils')] } }
}
if (process.argv.includes('--tiny-build')) config.build.rollupOptions = { input: resolve(root, 'tiny.html') }
if (process.argv.includes('--build') || process.argv.includes('--tiny-build')) { await build(config); process.exit(0) }
config.plugins.push({
  name: 's02-synthetic-http',
  configureServer(server) {
    server.middlewares.use((req, res, next) => {
      const url = new URL(req.url, 'http://localhost')
      if (!url.pathname.startsWith('/_lab/')) return next()
      res.setHeader('Cache-Control', 'no-store')
      res.setHeader('X-S02-Data', 'synthetic; no-product-auth')
      const fail = (code, error) => { res.statusCode = code; res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({ error })) }
      if (req.method !== 'GET') return fail(405, 'read_only')
      if (url.searchParams.get('project') !== 'fixture-a') return fail(403, 'project_scope_denied')
      if (url.pathname === '/_lab/system') {
        res.setHeader('Content-Type', 'application/json'); return res.end(readFixture('system.json'))
      }
      if (url.pathname !== '/_lab/file') return fail(404, 'unknown_endpoint')
      const entry = files[url.searchParams.get('alias')]
      if (!entry || url.searchParams.has('path')) return fail(403, 'file_not_declared')
      try {
        const bytes = readFixture(entry[0])
        res.setHeader('Content-Type', entry[1]); res.setHeader('X-Content-SHA256', createHash('sha256').update(bytes).digest('hex')); res.end(bytes)
      } catch { return fail(403, 'file_boundary_denied') }
    })
  }
})
const server = await createServer(config)
await server.listen()
console.log('S02 synthetic lab: http://127.0.0.1:5189')
