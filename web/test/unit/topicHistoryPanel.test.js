import assert from 'node:assert/strict'
import { before, after, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, ref, ssrContextKey } from 'vue'
import { Modal } from 'ant-design-vue'
import { createServer } from 'vite'

let vite, Panel, api
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: Panel } = await vite.ssrLoadModule('/src/components/project/TopicHistoryPanel.vue'))
  ;({ governanceBoardApi: api } = await vite.ssrLoadModule('/src/apis/governance_board_api.js'))
})
after(async () => { await vite?.close(); delete globalThis.localStorage })
const renderer = createRenderer({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {},
  parentNode: () => null, nextSibling: () => null
})
const settle = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }
const topic = id => ({ id, admission_status: 'canonical', progress: 'open', revision_number: 1 })
function mountPanel(t, current = ref(topic('a'))) {
  const instances = []
  const drafts = {}
  const Component = { ...Panel, render() { instances.push(getCurrentInstance()); return h('div') } }
  const app = renderer.createApp({ render: () => h(Component, { key: current.value.id, projectId: 'project', topic: current.value, draft: drafts[current.value.id] ||= { content: '', discussionType: 'discussion' } }) })
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  return { instances, current, app }
}

test('旧分页响应不能污染更新后的首屏，刷新按请求代数隔离', async t => {
  let finishPage
  let reads = 0
  t.mock.method(api, 'getTopicTimeline', (_project, _id, before) => {
    reads += 1
    if (before) return new Promise(resolve => { finishPage = resolve })
    return Promise.resolve({ items: [{ sequence: reads === 1 ? 4 : 5 }], next_before: reads === 1 ? 4 : null })
  })
  const { instances } = mountPanel(t)
  await settle()
  const state = instances.at(-1).setupState
  const oldPage = state.loadMore(false)
  await settle()
  await state.loadMore(true)
  finishPage({ items: [{ sequence: 3 }], next_before: 3 })
  await oldPage
  assert.deepEqual(state.events.map(event => event.sequence), [5])
  assert.equal(state.nextBefore, null)
})

test('切换议题后旧发布响应不清空新议题草稿', async t => {
  t.mock.method(api, 'getTopicTimeline', async () => ({ items: [], next_before: null }))
  let finishPost
  const submitted = []
  t.mock.method(api, 'createTopicComment', (...args) => {
    submitted.push(args)
    return new Promise(resolve => { finishPost = resolve })
  })
  const { instances, current } = mountPanel(t)
  await settle()
  const old = instances.at(-1).setupState
  old.content = 'A 的重议'
  old.discussionType = 'reconsideration'
  const posting = old.post()
  current.value = topic('b')
  await settle()
  const active = instances.at(-1).setupState
  active.content = 'B 的未发送草稿'
  finishPost({ id: 'posted' })
  await posting
  assert.equal(active.content, 'B 的未发送草稿')
  assert.deepEqual(submitted[0], ['project', 'a', 'A 的重议', 'reconsideration'])
})


test('切换后返回同一议题仍保留未发送草稿', async t => {
  t.mock.method(api, 'getTopicTimeline', async () => ({ items: [], next_before: null }))
  const { instances, current } = mountPanel(t)
  await settle()
  instances.at(-1).setupState.content = 'A 未发送草稿'
  instances.at(-1).setupState.discussionType = 'correction'
  current.value = topic('b')
  await settle()
  instances.at(-1).setupState.content = 'B 未发送草稿'
  current.value = topic('a')
  await settle()
  assert.equal(instances.at(-1).setupState.content, 'A 未发送草稿')
  assert.equal(instances.at(-1).setupState.discussionType, 'correction')
})

test('发布等待期间后来写入的草稿保留，缺原因不发请求', async t => {
  t.mock.method(api, 'getTopicTimeline', async () => ({ items: [], next_before: null }))
  let finish
  t.mock.method(api, 'createTopicComment', () => new Promise(resolve => { finish = resolve }))
  const operations = t.mock.method(api, 'operateTopic', async () => ({}))
  const { instances } = mountPanel(t)
  await settle()
  const state = instances.at(-1).setupState
  state.content = '正在发布'
  const posting = state.post()
  state.content = '后来写入'
  finish({})
  await posting
  assert.equal(state.content, '后来写入')
  state.action = 'close'
  await state.operate()
  assert.equal(state.error, '请填写操作原因')
  assert.equal(operations.mock.callCount(), 0)
  assert.equal(state.actionLabel, '关闭议题')
})


test('缺决策、缺重开提示、有删除草稿均不提交', async t => {
  t.mock.method(api, 'getTopicTimeline', async () => ({ items: [], next_before: null }))
  const operations = t.mock.method(api, 'operateTopic', async () => ({}))
  const { instances } = mountPanel(t)
  await settle()
  const state = instances.at(-1).setupState
  state.action = 'decide'
  await state.operate()
  assert.match(state.error, /请选择.*关联决策/)
  state.action = 'reopen'
  state.reason = '重新评估'
  await state.operate()
  assert.match(state.error, /请选择原方案/)
  state.action = 'delete'
  state.content = '未发布内容'
  await state.operate()
  assert.match(state.error, /清空讨论草稿/)
  assert.equal(operations.mock.callCount(), 0)
})

test('离开议题销毁删除确认，迟到确认不删除旧议题', async t => {
  t.mock.method(api, 'getTopicTimeline', async () => ({ items: [], next_before: null }))
  const operations = t.mock.method(api, 'operateTopic', async () => ({}))
  let options
  const destroy = t.mock.fn()
  t.mock.method(Modal, 'confirm', config => { options = config; return { destroy } })
  const { instances, app } = mountPanel(t)
  await settle()
  const state = instances.at(-1).setupState
  state.action = 'delete'
  state.reason = '无价值'
  const pending = state.operate()
  app.unmount()
  options.onOk()
  await pending
  assert.equal(destroy.mock.callCount(), 1)
  assert.equal(operations.mock.callCount(), 0)
})
