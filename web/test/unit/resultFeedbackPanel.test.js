import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, ssrContextKey } from 'vue'
import { createServer } from 'vite'

let vite, Panel, api, governance
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: Panel } = await vite.ssrLoadModule('/src/components/project/ResultFeedbackPanel.vue'))
  ;({ projectWorkApi: api } = await vite.ssrLoadModule('/src/apis/project_work_api.js'))
  ;({ governanceBoardApi: governance } = await vite.ssrLoadModule('/src/apis/governance_board_api.js'))
})
after(async () => { await vite?.close(); delete globalThis.localStorage })
const renderer = createRenderer({ patchProp() {}, insert() {}, remove() {}, createElement: () => ({}), createText: () => ({}), createComment: () => ({}), setText() {}, setElementText() {}, parentNode: () => null, nextSibling: () => null })
async function settle() { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }
function mount(t) {
  let instance
  const component = { ...Panel, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp(component, { projectId: 'p', taskId: 't', taskNumber: 'P-GEN-1', result: { id: 'r', version: 2, summary: '输出', review_comment: '补证据' } })
  app.provide(ssrContextKey, {})
  app.mount({}); t.after(() => app.unmount())
  return () => instance.setupState
}

test('议题反馈保留失败草稿与幂等确认标识', async t => {
  t.mock.method(governance, 'listTopics', async () => [{ id: 'topic', title: '议题', revision_number: 3 }])
  const calls = []
  t.mock.method(api, 'topicFeedback', async (...args) => { calls.push(args); throw new Error('版本冲突') })
  const state = mount(t)
  await state().open('topic'); state().target = 'topic'; state().content = '我的反馈'
  await state().save(); await state().save()
  assert.equal(state().content, '我的反馈'); assert.equal(state().error, '版本冲突')
  assert.equal(calls[0][3].request_id, calls[1][3].request_id)
  assert.equal(calls[0][3].expected_topic_revision, 3)
})

test('迟到蓝图预览不串目标；冲突刷新保留草稿并要求人工合并', async t => {
  t.mock.method(governance, 'listBlueprints', async () => ({ documents: [{ name: '甲.md' }, { name: '乙.md' }], shared_workdir: true }))
  let resolveOld
  t.mock.method(api, 'blueprintPreview', async (_p, _t, _r, name) => name === '甲.md' ? new Promise(resolve => { resolveOld = resolve }) : { name, content: '乙全文', original_content: '外部最新原文', content_hash: 'hash-b', file_identity: 'id-b', result_version: 2 })
  const state = mount(t)
  await state().open('blueprint'); state().target = '甲.md'; const old = state().selectTarget()
  await settle(); state().target = '乙.md'; await state().selectTarget()
  resolveOld({ name: '甲.md', content: '甲迟到正文' }); await old
  assert.equal(state().content, '乙全文'); assert.equal(state().preview.name, '乙.md')
  state().content = '待合并草稿'; await state().selectTarget(true)
  assert.equal(state().content, '待合并草稿'); assert.equal(state().comparison, '外部最新原文')
  assert.equal(state().ready, false)
  state().merged = true; assert.equal(state().ready, true)
  t.mock.method(api, 'blueprintPreview', async () => ({ name: '乙.md', content: '复盘', original_content: '', content_hash: 'empty', file_identity: 'empty-id', result_version: 2 }))
  await state().selectTarget(true)
  assert.equal(state().comparison, '')
  assert.equal(state().content, '待合并草稿')
  assert.equal(state().ready, false)
})
