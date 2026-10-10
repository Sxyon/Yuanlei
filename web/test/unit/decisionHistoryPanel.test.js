import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'
import { before, after, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, ref, ssrContextKey } from 'vue'
import { createServer } from 'vite'
import { Modal } from 'ant-design-vue'
import { routeLocationKey } from 'vue-router'

let useUserStore, clearGovernanceDrafts
let vite, Panel, api
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ useUserStore } = await vite.ssrLoadModule('/src/stores/user.js'))
  ;({ clearGovernanceDrafts } = await vite.ssrLoadModule('/src/utils/governanceDrafts.js'))
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
function mountPanel(t, selectedId = ref(''), route = { query: {} }, preserve = false) {
  const pinia = createPinia(); setActivePinia(pinia); if (!preserve) clearGovernanceDrafts(); useUserStore().uid = 'test-user'
  let instance
  const Component = { ...Panel, render() { instance = getCurrentInstance(); return h('div') } }
  const projectId = ref('project')
  const decisions = ref([decision('a'), decision('b')])
  const selectedEvents = []
  const app = renderer.createApp({ render: () => h(Component, { projectId: projectId.value, decisions: decisions.value, selectedId: selectedId.value, onSelect: id => selectedEvents.push(id) }) })
  app.use(pinia)
  app.provide(ssrContextKey, { modules: new Set() }); app.provide(routeLocationKey, route); app.mount({})
  t.after(() => app.unmount())
  return { state: () => instance.setupState, projectId, decisions, app, selectedEvents }
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


test('去向深链读取精确旧决策版本，迟到快照不能串入另一决策', async t => {
  let finishOld
  t.mock.method(api, 'getDecision', async (_project, id) => ({ ...decision(id), revision_number: 33, timeline: [{ sequence: 60 }] }))
  const reads = []
  t.mock.method(api, 'getDecisionRevision', (_project, id, revision) => {
    reads.push([id, revision])
    return id === 'a' ? new Promise(resolve => { finishOld = resolve }) : Promise.resolve({ number: 1, snapshot: { title: 'b旧依据', conclusion: '旧结论' } })
  })
  const id = ref('a')
  const { state } = mountPanel(t, id, { query: { decision_revision: '1' } })
  await settle()
  id.value = 'b'; await settle()
  finishOld({ number: 1, snapshot: { title: 'a旧依据' } }); await settle()
  assert.deepEqual(reads, [['a', '1'], ['b', '1']])
  assert.equal(state().referencedRevision.snapshot.title, 'b旧依据')
  assert.equal(state().referencedRevision.number, 1)
  assert.equal(state().detail.revision_number, 33)
})


test('重新进入恢复准确决策草稿及原修订，冲突不会换成当前修订重放', async t => {
  t.mock.method(api, 'getDecision', async (_p, id) => decision(id))
  const first = mountPanel(t)
  await first.state().open(decision('a'))
  first.state().beginEdit(); first.state().draft.conclusion = '原修订草稿'; first.state().reason = '核对'
  first.app.unmount()
  t.mock.method(api, 'getDecision', async (_p, id) => ({ ...decision(id), revision_number: 3 }))
  const writes = t.mock.method(api, 'updateDecision', async (_p, _id, body) => { assert.equal(body.expected_revision, 1); throw new Error('revision_conflict') })
  const restored = mountPanel(t, ref('a'), { query: {} }, true)
  await settle()
  assert.equal(restored.state().draft.conclusion, '原修订草稿')
  assert.equal(restored.state().actionRevision, 1)
  await restored.state().submit()
  assert.equal(writes.mock.callCount(), 1)
  assert.equal(restored.state().draft.expected_revision, 1)
  assert.equal(restored.state().action, 'edit')
})


test('正在编辑的决策移除后保留准确复制出口且允许打开另一决策', async t => {
  t.mock.method(api, 'getDecision', async (_p, id) => decision(id))
  const panel = mountPanel(t)
  await panel.state().open(decision('a'))
  panel.state().beginEdit(); panel.state().draft.conclusion = 'A未提交正文'
  panel.decisions.value = [decision('b')]; await settle()
  assert.equal(panel.state().selected, null)
  assert.equal(panel.state().action, '')
  assert.match(panel.state().removedDraft.content, /A未提交正文/)
  await panel.state().open(decision('b'))
  assert.equal(panel.state().detail.id, 'b')
})

test('恢复路由中的决定仅加载详情，不改写同时定位的建议锚点', async t => {
  t.mock.method(api, 'getDecision', async (_project, id) => decision(id))
  const { state, selectedEvents } = mountPanel(t, ref('a'), { query: { decision_id: 'a', task_id: 'suggestion' }, hash: '#task-suggestion' })
  await settle()
  assert.equal(state().detail.id, 'a')
  assert.deepEqual(selectedEvents, [])
  state().openById('b')
  await settle()
  assert.deepEqual(selectedEvents, ['b'])
})
