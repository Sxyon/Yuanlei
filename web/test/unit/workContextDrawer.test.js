import assert from 'node:assert/strict'
import { before, after, test } from 'node:test'
import { createRenderer, getCurrentInstance, h, nextTick, ssrContextKey } from 'vue'
import { createServer } from 'vite'
let vite, Panel, api, governance
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: Panel } = await vite.ssrLoadModule('/src/components/project/WorkContextDrawer.vue'))
  ;({ projectWorkExecutionApi: api } = await vite.ssrLoadModule('/src/apis/project_work_execution_api.js'))
  ;({ governanceBoardApi: governance } = await vite.ssrLoadModule('/src/apis/governance_board_api.js'))
})
after(async () => { await vite?.close(); delete globalThis.localStorage })
const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}), insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
function mount(t) {
  let instance
  const app = renderer.createApp({ ...Panel, render() { instance = getCurrentInstance(); return h('div') } }, { projectId: 'p', task: { id: 'a' } })
  app.provide(ssrContextKey, { modules: new Set() }); app.mount({}); t.after(() => app.unmount())
  return instance
}
test('迟到蓝图列表不能覆盖已经打开的历史资料', async t => {
  let resolve, calls = 0
  t.mock.method(governance, 'listBlueprints', () => new Promise(r => { resolve = r }))
  t.mock.method(api, 'previewContext', async () => { calls++; return { fingerprint: 'new' } })
  t.mock.method(api, 'getContext', async () => ({ snapshot: { input_text: '历史正文' } }))
  const state = mount(t).setupState
  const pending = state.openPreview()
  await state.showHistory('execution', 'old')
  resolve({ documents: [] }); await pending
  assert.equal(calls, 0); assert.equal(state.snapshot.input_text, '历史正文'); assert.equal(state.history, true)
})
test('切换工作丢弃迟到预览，选择改变使旧指纹失效且保留输入', async t => {
  let resolve
  t.mock.method(api, 'previewContext', () => new Promise(r => { resolve = r }))
  const instance = mount(t), state = instance.setupState
  const pending = state.preview()
  instance.props.task = { id: 'b' }; await nextTick()
  resolve({ fingerprint: 'a', input_text: '工作甲' }); await pending
  assert.equal(state.snapshot, null); assert.equal(state.context, null)
  t.mock.method(api, 'previewContext', async () => ({ fingerprint: 'b', input_text: '工作乙' }))
  await state.preview()
  state.filePaths = '/outputs/report.md'
  assert.equal(state.context.expected_fingerprint, null)
  assert.deepEqual(state.context.selection.files, ['/outputs/report.md'])
})
