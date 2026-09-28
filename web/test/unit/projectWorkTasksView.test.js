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
  await instance.setupState.createTask()
  assert.deepEqual(calls.map((item) => item[0]), ['code', 'task'])
  assert.equal(calls[1][1].due_date, '2026-10-08')
  assert.equal(router.currentRoute.value.params.task_id, 'created-task')
})
