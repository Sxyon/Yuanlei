import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, ssrContextKey } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createServer } from 'vite'

let vite, View, projectWorkApi, projectAgentApi
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: View } = await vite.ssrLoadModule('/src/views/ProjectWorkTasksView.vue'))
  ;({ projectWorkApi } = await vite.ssrLoadModule('/src/apis/project_work_api.js'))
  ;({ projectAgentApi } = await vite.ssrLoadModule('/src/apis/project_agent_api.js'))
})
after(async () => {
  await vite?.close()
  delete globalThis.localStorage
})

const renderer = createRenderer({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {},
  parentNode: () => null, nextSibling: () => null
})
const settle = async () => {
  await nextTick()
  await new Promise((resolve) => setImmediate(resolve))
}

test('切换项目清空任务草稿并忽略迟到的旧项目响应', async (t) => {
  const finish = {}
  t.mock.method(projectWorkApi, 'listTasks', (projectId) => new Promise((resolve) => { finish[projectId] = resolve }))
  t.mock.method(projectWorkApi, 'getCode', async (projectId) => ({ code: projectId.toUpperCase() }))
  t.mock.method(projectWorkApi, 'listTopics', async () => [])
  t.mock.method(projectAgentApi, 'list', async () => ({ agents: [] }))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/projects/:project_id/work/tasks', component: View }]
  })
  await router.push('/projects/a/work/tasks')
  await router.isReady()
  let instance
  const Component = { ...View, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp(Component)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()
  instance.setupState.title = 'A 的草稿'
  instance.setupState.description = 'A 的内容'
  instance.setupState.parentId = 'a-parent'
  instance.setupState.ownerSlug = 'a-agent'

  await router.push('/projects/b/work/tasks')
  await settle()
  assert.equal(instance.setupState.title, '')
  assert.equal(instance.setupState.description, '')
  assert.equal(instance.setupState.parentId, undefined)
  assert.equal(instance.setupState.ownerSlug, undefined)
  finish.b([{ id: 'b-task', title: 'B 的任务' }])
  await settle()
  finish.a([{ id: 'a-task', title: 'A 的任务' }])
  await settle()
  assert.equal(instance.setupState.tasks[0].id, 'b-task')
  assert.equal(instance.setupState.projectCode, 'B')
})

test('保存缩写后迟到的旧读取不能清除固化状态', async (t) => {
  let finishCode
  t.mock.method(projectWorkApi, 'listTasks', async () => [])
  t.mock.method(projectWorkApi, 'getCode', () => new Promise((resolve) => { finishCode = resolve }))
  t.mock.method(projectWorkApi, 'configureCode', async () => ({ code: 'YL' }))
  t.mock.method(projectWorkApi, 'listTopics', async () => [])
  t.mock.method(projectAgentApi, 'list', async () => ({ agents: [] }))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/projects/:project_id/work/tasks', component: View }]
  })
  await router.push('/projects/a/work/tasks')
  await router.isReady()
  let instance
  const Component = { ...View, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp(Component)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()
  instance.setupState.projectCode = 'YL'
  await instance.setupState.saveCode()
  finishCode({ code: null })
  await settle()
  assert.equal(instance.setupState.projectCode, 'YL')
  assert.equal(instance.setupState.codeSaved, true)
})

test('首次创建先固化项目缩写，再持久化带计划日期的任务', async (t) => {
  const calls = []
  let code = null
  t.mock.method(projectWorkApi, 'listTasks', async () => [])
  t.mock.method(projectWorkApi, 'getCode', async () => ({ code }))
  t.mock.method(projectWorkApi, 'configureCode', async (_projectId, value) => {
    calls.push(['code', value])
    code = value
    return { code }
  })
  t.mock.method(projectWorkApi, 'listTopics', async () => [
    { id: 'topic-1', title: '议题', status: 'proposed', code: 'TOP' }
  ])
  t.mock.method(projectWorkApi, 'createTask', async (_projectId, payload) => {
    calls.push(['task', payload])
    return { id: 'created-task' }
  })
  t.mock.method(projectAgentApi, 'list', async () => ({ agents: [] }))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/projects/:project_id/work/tasks', component: View },
      { name: 'ProjectWorkTaskView', path: '/projects/:project_id/work/tasks/:task_id', component: { render: () => h('div') } }
    ]
  })
  await router.push('/projects/a/work/tasks')
  await router.isReady()
  let instance
  const Component = { ...View, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp(Component)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()
  instance.setupState.projectCode = 'YL'
  instance.setupState.title = '访谈客户'
  instance.setupState.startDate = '2026-10-01'
  instance.setupState.dueDate = '2026-10-08'
  instance.setupState.topicId = 'topic-1'
  await instance.setupState.createTask()
  assert.deepEqual(calls.map((item) => item[0]), ['code', 'task'])
  assert.equal(calls[1][1].due_date, '2026-10-08')
  assert.equal(calls[1][1].topic_id, 'topic-1')
  assert.equal(router.currentRoute.value.params.task_id, 'created-task')
})

test('为未设缩写的议题保存编号并更新本地列表', async (t) => {
  const calls = []
  t.mock.method(projectWorkApi, 'listTasks', async () => [])
  t.mock.method(projectWorkApi, 'getCode', async () => ({ code: 'YL' }))
  t.mock.method(projectWorkApi, 'listTopics', async () => [
    { id: 'topic-1', title: '议题', status: 'proposed', code: null }
  ])
  t.mock.method(projectWorkApi, 'configureTopicCode', async (_projectId, topicId, value) => {
    calls.push([topicId, value])
    return { topic_id: topicId, code: value.toUpperCase() }
  })
  t.mock.method(projectAgentApi, 'list', async () => ({ agents: [] }))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/projects/:project_id/work/tasks', component: View }]
  })
  await router.push('/projects/a/work/tasks')
  await router.isReady()
  let instance
  const Component = { ...View, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp(Component)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()
  instance.setupState.topicCodeDrafts = { 'topic-1': 'reg' }
  await instance.setupState.saveTopicCode({ id: 'topic-1' })
  assert.deepEqual(calls, [['topic-1', 'reg']])
  assert.equal(instance.setupState.topics[0].code, 'REG')
})

test('看板状态更新失败时回读服务端事实，不保留乐观选择', async (t) => {
  const reads = []
  t.mock.method(projectWorkApi, 'listTasks', async () => {
    // 第二次读取代表失败后服务端事实（此处被其他来源改为 blocked），用于证明确实回读了服务端。
    const current = reads.length === 0 ? 'todo' : 'blocked'
    reads.push(current)
    return [{ id: 't1', number: 'P-1', title: '任务', status: current }]
  })
  t.mock.method(projectWorkApi, 'getCode', async () => ({ code: 'P' }))
  t.mock.method(projectWorkApi, 'listTopics', async () => [])
  t.mock.method(projectAgentApi, 'list', async () => ({ agents: [] }))
  t.mock.method(projectWorkApi, 'updateTask', async () => { throw new Error('状态更新失败') })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/projects/:project_id/work/tasks', component: View }]
  })
  await router.push('/projects/p/work/tasks')
  await router.isReady()
  let instance
  const Component = { ...View, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp(Component)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()

  await instance.setupState.changeStatus(instance.setupState.tasks[0], 'in_progress')
  await settle()
  // 更新失败后必须再读一次服务端（共两次），并以服务端事实为准，而非保留乐观选择。
  assert.deepEqual(reads, ['todo', 'blocked'])
  assert.equal(instance.setupState.tasks[0].status, 'blocked')
  assert.equal(instance.setupState.actionError, '状态更新失败')
})

test('看板完成任务先检查成果，检查失败也需明确选择保留', async (t) => {
  t.mock.method(projectWorkApi, 'listTasks', async () => [{ id: 'task', status: 'todo' }])
  t.mock.method(projectWorkApi, 'getCode', async () => ({ code: 'TEST' }))
  t.mock.method(projectWorkApi, 'listTopics', async () => [])
  t.mock.method(projectAgentApi, 'list', async () => ({ agents: [] }))
  const writes = []
  t.mock.method(projectWorkApi, 'updateTask', async (...args) => { writes.push(args) })
  t.mock.method(projectWorkApi, 'getGitOutcomes', async () => { throw new Error('Gitea 暂不可用') })
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:project_id/work/tasks', component: View }] })
  await router.push('/projects/a/work/tasks')
  await router.isReady()
  let instance
  const app = renderer.createApp({ ...View, render() { instance = getCurrentInstance(); return h('div') } })
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()
  const state = instance.setupState
  await state.changeStatus({ id: 'task' }, 'done')
  assert.equal(writes.length, 0)
  assert.equal(state.gitCompletionOpen, true)
  assert.deepEqual(state.gitCompletion.errors, ['Gitea 暂不可用'])
  await state.changeStatus(state.gitCompletionTask, 'done', true)
  assert.deepEqual(writes, [['a', 'task', { status: 'done' }]])
  assert.equal(state.gitCompletionOpen, false)
})
