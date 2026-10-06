import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, ssrContextKey } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createServer } from 'vite'
let vite, Panel, api, workApi
before(async () => {
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: Panel } = await vite.ssrLoadModule(
    '/src/components/project/WorkSuggestionsPanel.vue'
  ))
  ;({ governanceBoardApi: api } = await vite.ssrLoadModule('/src/apis/governance_board_api.js'))
  ;({ projectWorkApi: workApi } = await vite.ssrLoadModule('/src/apis/project_work_api.js'))
})
after(async () => {
  await vite?.close()
})
const renderer = createRenderer({
  createElement: () => ({}),
  createText: () => ({}),
  createComment: () => ({}),
  insert() {},
  remove() {},
  setText() {},
  setElementText() {},
  patchProp() {},
  parentNode: () => null,
  nextSibling: () => null
})
const settle = async () => {
  await nextTick()
  await new Promise((resolve) => setImmediate(resolve))
}
async function mount(t) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { render: () => h('div') } },
      {
        path: '/projects/:project_id/work/tasks/:task_id',
        name: 'ProjectWorkTaskView',
        component: { render: () => h('div') }
      }
    ]
  })
  await router.push('/')
  await router.isReady()
  let instance
  const app = renderer.createApp(
    {
      ...Panel,
      render() {
        instance = getCurrentInstance()
        return h('div')
      }
    },
    { projectId: 'project' }
  )
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()
  return { state: instance.setupState, router }
}
test('新建纳入沿用来源与复核，失败保留草稿并能补齐编号后重试跳转', async (t) => {
  t.mock.method(workApi, 'listTasks', async () => [])
  t.mock.method(workApi, 'listTopics', async () => [{ id: 'topic', title: '方向', code: null }])
  t.mock.method(workApi, 'getCode', async () => null)
  t.mock.method(workApi, 'configureCode', async (_project, code) => ({ code }))
  const calls = []
  t.mock.method(api, 'admitTask', async (...args) => {
    calls.push(args)
    if (calls.length === 1) throw new Error('请先配置议题缩写')
    return { work: { id: 'formal' } }
  })
  const { state, router } = await mount(t)
  await state.open({
    id: 'suggestion',
    title: '原建议',
    description: '原内容',
    topic_id: 'topic',
    decision_id: 'decision'
  })
  state.title = '个人修订'
  state.description = '修订描述'
  state.reason = '确认'
  state.reviewConfirmed = true
  await state.submit()
  assert.equal(state.title, '个人修订')
  assert.equal(state.description, '修订描述')
  assert.equal(state.decisionId, 'decision')
  assert.equal(state.selected.id, 'suggestion')
  assert.match(state.error, /议题缩写/)
  state.codeDraft = 'PROJ'
  await state.saveCode()
  assert.equal(state.projectCode, 'PROJ')
  await state.submit()
  assert.equal(router.currentRoute.value.params.task_id, 'formal')
  assert.deepEqual(calls[1][2], {
    mode: 'create',
    title: '个人修订',
    description: '修订描述',
    topic_id: 'topic',
    source_decision_id: 'decision',
    review_confirmed: true,
    review_note: '确认'
  })
})
test('关联已有工作只提交映射，竞争失败保留所选目标', async (t) => {
  t.mock.method(workApi, 'listTasks', async () => [
    { id: 'existing', number: 'GEN-1', title: '已有' }
  ])
  t.mock.method(workApi, 'listTopics', async () => [])
  t.mock.method(workApi, 'getCode', async () => ({ code: 'PROJ' }))
  let sent
  t.mock.method(api, 'admitTask', async (_project, _id, payload) => {
    sent = payload
    throw Object.assign(new Error('建议已纳入其他正式工作'), {
      response: { data: { detail: { code: 'suggestion_already_admitted' } } }
    })
  })
  t.mock.method(api, 'getProjectBoard', async () => ({
    governance: { tasks: [{ id: 's', work: { id: 'winning-work' } }] }
  }))
  const { state } = await mount(t)
  await state.open({ id: 's', title: '建议', topic_id: 'different' })
  state.mode = 'link'
  state.workId = 'existing'
  state.reason = '补充来源'
  await state.submit()
  assert.deepEqual(sent, { mode: 'link', work_task_id: 'existing', review_note: '补充来源' })
  assert.equal(state.workId, 'existing')
  assert.equal(state.mode, 'link')
  assert.equal(state.selected.id, 's')
  assert.match(state.error, /已纳入/)
  assert.equal(state.existingWork.id, 'winning-work')
})
test('关闭弹窗后迟到候选不覆盖选择', async (t) => {
  let finish
  t.mock.method(
    workApi,
    'listTasks',
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  t.mock.method(workApi, 'listTopics', async () => [])
  t.mock.method(workApi, 'getCode', async () => ({ code: 'OLD' }))
  const { state } = await mount(t)
  const loading = state.open({ id: 'a', title: '旧建议' })
  await settle()
  state.close()
  finish([{ id: 'old' }])
  await loading
  assert.equal(state.selected, null)
  assert.deepEqual(state.works, [])
  assert.equal(state.projectCode, '')
})
