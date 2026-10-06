import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, reactive, ssrContextKey } from 'vue'
import { createServer } from 'vite'

let vite, Panel, api
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: Panel } = await vite.ssrLoadModule('/src/components/project/WorkResultsPanel.vue'))
  ;({ projectWorkApi: api } = await vite.ssrLoadModule('/src/apis/project_work_api.js'))
})
after(async () => { await vite?.close(); delete globalThis.localStorage })
const renderer = createRenderer({ patchProp() {}, insert() {}, remove() {}, createElement: () => ({}), createText: () => ({}), createComment: () => ({}), setText() {}, setElementText() {}, parentNode: () => null, nextSibling: () => null })
async function settle() { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }
function mount(t) {
  const task = reactive({ id: 'task', description: '描述', acceptance_criteria: '条件一', criteria_revision: 1, results: [], attachments: [] })
  let instance, completion
  const events = []
  const Component = { ...Panel, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp({ render: () => h(Component, { projectId: 'project', task, onRefresh: () => events.push('refresh'), onComplete: callback => { completion = callback } }) })
  app.provide(ssrContextKey, { modules: new Set() }); app.mount({})
  t.after(() => app.unmount())
  return { task, events, state: () => instance.setupState, complete: () => completion }
}

test('要求保存冲突保留描述和Markdown，最新版本需明确采用', async t => {
  t.mock.method(api, 'updateRequirements', async () => { throw new Error('要求已修改') })
  const { state, task } = mount(t)
  state().criteria = '# 我的条件'; state().description = '我的描述'
  await state().saveRequirements()
  assert.equal(state().criteria, '# 我的条件'); assert.equal(state().description, '我的描述')
  assert.equal(state().error, '要求已修改')
  task.criteria_revision = 2; task.acceptance_criteria = '其他页面的条件'
  await settle()
  assert.equal(state().revision, 1); assert.equal(state().criteria, '# 我的条件')
  state().summary = '结果草稿'
  state().adoptRequirements()
  assert.equal(state().criteria, '其他页面的条件'); assert.equal(state().revision, 2)
  assert.equal(state().summary, '结果草稿'); assert.equal(state().error, '')
})

test('结果失败保留摘要、证据、未解决事项；相同重试复用提交标识', async t => {
  const calls = []
  t.mock.method(api, 'submitResult', async (...args) => { calls.push(args); throw new Error('证据不可访问') })
  const { state } = mount(t)
  state().summary = '人工结果'; state().unresolved = '待复盘'; state().evidence = [{ kind: 'file', value: '/proof.md', title: '' }]
  await state().submit(false); await state().submit(false)
  assert.equal(calls[0][2].request_id, calls[1][2].request_id)
  assert.equal(state().summary, '人工结果'); assert.equal(state().unresolved, '待复盘')
  assert.equal(state().evidence[0].value, '/proof.md'); assert.equal(state().error, '证据不可访问')
  state().summary = '补充结果'; await state().submit(false)
  assert.notEqual(calls[1][2].request_id, calls[2][2].request_id)
})

test('提交并完成交给Git流程；确认后才发送组合接口', async t => {
  const calls = []
  t.mock.method(api, 'submitResult', async (...args) => { calls.push(args); return {} })
  const { state, complete, events } = mount(t)
  state().summary = '人工完成'; state().submit(true)
  assert.equal(calls.length, 0)
  await complete()(true)
  assert.equal(calls.length, 1); assert.equal(calls[0][2].complete, true)
  assert.equal(calls[0][2].git_outcomes_confirmed, true)
  assert.equal(state().summary, ''); assert.deepEqual(events, ['refresh'])
})

test('切换任务后旧确认和迟到响应不提交或清空新草稿，包括切回同任务', async t => {
  let finish
  const calls = []
  t.mock.method(api, 'submitResult', (...args) => { calls.push(args); return new Promise(resolve => { finish = resolve }) })
  const { state, task, complete } = mount(t)
  state().summary = 'A'; state().submit(true); const old = complete()
  task.id = 'other'; await settle(); task.id = 'task'; await settle()
  state().summary = '当前草稿'
  await old(true); assert.equal(calls.length, 0)
  const pending = state().submit(false)
  task.id = 'other'; await settle(); state().summary = '另一任务草稿'
  finish({}); await pending
  assert.equal(state().summary, '另一任务草稿'); assert.equal(state().error, '')
})

test('提交期间追加输入保留；验收失败意见不丢失', async t => {
  let finish
  t.mock.method(api, 'submitResult', () => new Promise(resolve => { finish = resolve }))
  t.mock.method(api, 'reviewResult', async () => { throw new Error('条件已改变') })
  const { state } = mount(t)
  state().summary = '第一份'; const pending = state().submit(false)
  state().summary = '第二份尚未提交'; finish({}); await pending
  assert.equal(state().summary, '第二份尚未提交')
  state().comments = { result: '我的验收意见' }
  await state().review({ id: 'result', version: 1 }, 'accepted', false)
  assert.equal(state().comments.result, '我的验收意见'); assert.equal(state().error, '条件已改变')
})

test('丢响应后切换提交动作使用新标识，同一动作重试仍幂等', async t => {
  const calls = []
  t.mock.method(api, 'submitResult', async (...args) => { calls.push(args[2]); throw new Error('响应丢失') })
  const { state, complete } = mount(t)
  state().summary = '同一结果'
  await state().submit(false); await state().submit(false)
  assert.equal(calls[0].request_id, calls[1].request_id)
  state().submit(true); await complete()(true)
  assert.notEqual(calls[1].request_id, calls[2].request_id)
  state().submit(true); await complete()(true)
  assert.equal(calls[2].request_id, calls[3].request_id)
})
