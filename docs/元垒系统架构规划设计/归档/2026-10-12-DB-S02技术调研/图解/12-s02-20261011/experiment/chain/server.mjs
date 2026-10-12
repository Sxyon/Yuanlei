import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = dirname(fileURLToPath(import.meta.url))
const repo = resolve(root, '../../../../../..')
const require = createRequire(resolve(repo, 'web/package.json'))
const { createServer, build } = await import(require.resolve('vite'))
const vue = (await import(require.resolve('@vitejs/plugin-vue'))).default
const config = {
  configFile: false, root, plugins: [vue()],
  resolve: { alias: { vue: require.resolve('vue/dist/vue.runtime.esm-bundler.js'), 'markdown-it': require.resolve('markdown-it'), dompurify: require.resolve('dompurify'), '@static-frame': resolve(repo, 'web/src/utils/dashboardFrame.js') } },
  build: { outDir: '/tmp/yuanlei-s02-chain-build', emptyOutDir: true },
  server: { host: '127.0.0.1', port: 5192, strictPort: true, proxy: { "^/A/": { target: "http://127.0.0.1:5190", rewrite: path => path.slice(2) }, "^/B/": { target: "http://127.0.0.1:5191", rewrite: path => path.slice(2) } }, fs: { allow: [resolve(root, ".."), resolve(repo, 'web/node_modules'), resolve(repo, 'web/src/utils')] } }
}
if (process.argv.includes('--build')) { await build(config); process.exit(0) }
const server = await createServer(config)
await server.listen()
console.log("S02 chain Vue lab: http://127.0.0.1:5192")
