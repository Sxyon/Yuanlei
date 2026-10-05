import assert from 'node:assert/strict'
import { before, after, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, ref, ssrContextKey } from 'vue'
import { createServer } from 'vite'
import { Modal } from 'ant-design-vue'

let vite, Panel, api
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: Panel } = await vite.ssrLoadModule('/src/components/project/DecisionHistoryPanel.vue'))
  ;({ governanceBoardApi: api } = await vite.ssrLoadModule('/src/apis/governance_board_api.js'))
})
after(async () => { await vite?.close(); delete globalThis.localStorage })
const renderer = createRenderer({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {},
  parentNode: () => null, nextSibling: () => null
})
const settle = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }
const decision = id => ({ id, title: id, status: 'draft', revision_number: 1, conclusion: '原草案', rationale: '', relation_type: 'ordinary', topic_id: null, target_decision_id: null, timeline: [], next_before: null })
function mountPanel(t) {
  let instance
  const Component = { ...Panel, render() { instance = getCurrentInstance(); return h('div') } }
  const projectId = ref('project')
  const app = renderer.createApp({ render: () => h(Component, { projectId: projectId.value, decisions: [decision('a'), decision('b')] }) })
  app.provide(ssrContextKey, { modules: new Set() }); app.mount({})
  t.after(() => app.unmount())
  return { state: () => instance.setupState, projectId, app }
}

test('决策切换丢弃延迟旧响应，局部历史不会串入新决策', async t => {
  let finishOld
  t.mock.method(api, 'getDecision', (_project, id) => id === 'a' ? new Promise(resolve => { finishOld = resolve }) : Promise.resolve(decision(id)))
  const { state } = mountPanel(t)
  const pending = state().open(decision('a'))
  await state().open(decision('b'))
  finishOld({ ...decision('a'), timeline: [{ sequence: 9 }] })
  await pending
  assert.equal(state().detail.id, 'b')
  assert.deepEqual(state().events, [])
})

test('并发修订冲突保留可复制草案，不能被切换决策静默覆盖', async t => {
  t.mock.method(api, 'getDecision', async (_project, id) => decision(id))
  t.mock.method(api, 'updateDecision', async () => { throw new Error('决策已被修改，请保留草稿并重新读取') })
  const { state } = mountPanel(t)
  await state().open(decision('a'))
  state().beginEdit(); state().draft.conclusion = '第二页独有草稿'; state().reason = '修订'
  await state().submit()
  assert.equal(state().draft.conclusion, '第二页独有草稿')
  assert.equal(state().action, 'edit')
  await state().open(decision('b'))
  assert.equal(state().selected.id, 'a')
  assert.equal(state().draft.conclusion, '第二页独有草稿')
  assert.match(state().error, /尚未保存/)
})

test('旧分页响应和切换项目后的响应不进入当前历史', async t => {
  let finishPage
  t.mock.method(api, 'getDecision', (_project, id, before) => before ? new Promise(resolve => { finishPage = resolve }) : Promise.resolve({ ...decision(id), next_before: 4, timeline: [{ sequence: 4 }] }))
  const { state, projectId } = mountPanel(t)
  await state().open(decision('a'))
  const pending = state().loadMore()
  projectId.value = 'other-project'; await settle()
  finishPage({ timeline: [{ sequence: 3 }], next_before: null }); await pending
  assert.equal(state().selected, null)
  assert.deepEqual(state().events, [])
})


test('离开项目销毁删除确认，迟到确认不会删除草案', async t => {
  let confirm, destroyed = false
  t.mock.method(api, 'getDecision', async (_project, id) => decision(id))
  const operations = t.mock.method(api, 'operateDecision', async () => ({}))
  t.mock.method(Modal, 'confirm', options => { confirm = options; return { destroy() { destroyed = true } } })
  const { state, app } = mountPanel(t)
  await state().open(decision('a'))
  state().chooseAction('delete'); state().reason = '误建'
  await state().submit()
  app.unmount()
  await confirm.onOk()
  assert.equal(destroyed, true)
  assert.equal(operations.mock.callCount(), 0)
})
