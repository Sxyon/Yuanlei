import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, KeepAlive, nextTick, ssrContextKey } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { createServer } from 'vite'

let vite, View, projectWorkExecutionApi, projectAgentApi
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: View } = await vite.ssrLoadModule('/src/views/ProjectAgentWorkbenchView.vue'))
  ;({ projectWorkExecutionApi } = await vite.ssrLoadModule('/src/apis/project_work_execution_api.js'))
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

test('切换智能体时忽略旧工作台响应，接受后回读队列事实', async (t) => {
  let finishA
  t.mock.method(projectWorkExecutionApi, 'getWorkbench', async (_projectId, agentSlug) => {
    if (agentSlug === 'a') return new Promise((resolve) => { finishA = resolve })
    return { agent_slug: 'b', current: null, pending_acceptance: [{ id: 'assignment' }], queued: [], recent: [] }
  })
  let accepted = false
  t.mock.method(projectWorkExecutionApi, 'accept', async () => { accepted = true })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/projects/:project_id/agents/:agent_slug/workbench', component: View }]
  })
  await router.push('/projects/project/agents/a/workbench')
  await router.isReady()
  let instance
  const Component = { ...View, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp(Component)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()
  await router.push('/projects/project/agents/b/workbench')
  await settle()
  finishA({ agent_slug: 'a', current: null, pending_acceptance: [], queued: [], recent: [] })
  await settle()
  assert.equal(instance.setupState.workbench.agent_slug, 'b')
  await instance.setupState.accept({ id: 'assignment' })
  assert.equal(accepted, true)
  assert.equal(instance.setupState.workbench.agent_slug, 'b')
})

test('离开工作台后不再用空路由参数请求智能体队列', async (t) => {
  const calls = []
  t.mock.method(projectWorkExecutionApi, 'getWorkbench', async (projectId, agentSlug) => {
    calls.push([projectId, agentSlug])
    return { agent_slug: agentSlug, current: null, pending_acceptance: [], queued: [], recent: [] }
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/projects/:project_id/agents/:agent_slug/workbench', component: View },
      { path: '/inbox', component: { render: () => h('div') } }
    ]
  })
  await router.push('/projects/project/agents/agent/workbench')
  await router.isReady()
  const Component = { render() { return h(RouterView, null, { default: ({ Component: Current }) => h(KeepAlive, null, { default: () => h(Current) }) }) } }
  const app = renderer.createApp(Component)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()
  await router.push('/inbox')
  await settle()

  assert.deepEqual(calls, [['project', 'agent']])
})

test('最近失败工作可重新执行并创建新的执行意图', async (t) => {
  const assigned = []
  t.mock.method(projectWorkExecutionApi, 'getWorkbench', async () => ({
    agent_slug: 'agent',
    auto_accept_work: false,
    work_default_model_spec: null,
    current: null,
    pending_acceptance: [],
    queued: [],
    recent: [
      { id: 'exec-1', task_id: 'task-9', agent_slug: 'agent', status: 'failed', current_run_id: 'run-1', error_message: '失败' }
    ]
  }))
  t.mock.method(projectWorkExecutionApi, 'assign', async (projectId, taskId, agentSlug) => {
    assigned.push([projectId, taskId, agentSlug])
    return { id: 'exec-2' }
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/projects/:project_id/agents/:agent_slug/workbench', component: View }]
  })
  await router.push('/projects/project/agents/agent/workbench')
  await router.isReady()
  let instance
  const Component = { ...View, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp(Component)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()
  assert.equal(instance.setupState.workbench.recent[0].current_run_id, 'run-1')
  await instance.setupState.retry(instance.setupState.workbench.recent[0])
  assert.deepEqual(assigned, [['project', 'task-9', 'agent']])
})

test('设置保存完成时页面已离开，不再触发空路由回读', async (t) => {
  const reads = []
  let finishSave
  let instance
  t.mock.method(projectWorkExecutionApi, 'getWorkbench', async (projectId, agentSlug) => {
    reads.push([projectId, agentSlug])
    return {
      agent_slug: agentSlug,
      auto_accept_work: false,
      work_default_model_spec: null,
      current: null,
      pending_acceptance: [],
      queued: [],
      recent: []
    }
  })
  t.mock.method(projectWorkExecutionApi, 'updateWorkbenchConfig', () => new Promise((resolve) => {
    finishSave = resolve
  }))
  const RoutedView = {
    ...View,
    render() {
      instance = getCurrentInstance()
      return h('div')
    }
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/projects/:project_id/agents/:agent_slug/workbench', component: RoutedView },
      { path: '/inbox', component: { render: () => h('div') } }
    ]
  })
  await router.push('/projects/project/agents/agent/workbench')
  await router.isReady()
  const Component = {
    render() { return h(RouterView, null, { default: ({ Component: Current }) => h(KeepAlive, null, { default: () => h(Current) }) }) }
  }
  const app = renderer.createApp(Component)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()
  instance.setupState.autoAcceptWork = true
  const save = instance.setupState.saveSettings()
  await router.push('/inbox')
  await settle()
  finishSave({ auto_accept_work: true, work_default_model_spec: null })
  await save
  await settle()

  assert.deepEqual(reads, [['project', 'agent']])
})

test('工作台标题使用项目智能体显示名而非 slug', async (t) => {
  t.mock.method(projectWorkExecutionApi, 'getWorkbench', async (projectId, agentSlug) => ({
    agent_slug: agentSlug,
    auto_accept_work: false,
    work_default_model_spec: null,
    current: null,
    pending_acceptance: [],
    queued: [],
    recent: []
  }))
  t.mock.method(projectAgentApi, 'list', async () => ({
    agents: [{ slug: 'agent', name: '调研员码农' }]
  }))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/projects/:project_id/agents/:agent_slug/workbench', component: View }]
  })
  await router.push('/projects/project/agents/agent/workbench')
  await router.isReady()
  let instance
  const Component = { ...View, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp(Component)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()

  assert.equal(instance.setupState.workbenchTitle, '智能体工作台 · 调研员码农')
})

test('归属列表读取失败时工作台标题降级为 slug 且不报错', async (t) => {
  t.mock.method(projectWorkExecutionApi, 'getWorkbench', async (projectId, agentSlug) => ({
    agent_slug: agentSlug,
    auto_accept_work: false,
    work_default_model_spec: null,
    current: null,
    pending_acceptance: [],
    queued: [],
    recent: []
  }))
  t.mock.method(projectAgentApi, 'list', async () => { throw new Error('归属列表不可用') })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/projects/:project_id/agents/:agent_slug/workbench', component: View }]
  })
  await router.push('/projects/project/agents/agent/workbench')
  await router.isReady()
  let instance
  const Component = { ...View, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp(Component)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()

  assert.equal(instance.setupState.error, '')
  assert.equal(instance.setupState.workbenchTitle, '智能体工作台 · agent')
})

test('保存任务设置提交自动接受开关与默认模型', async (t) => {
  const saves = []
  t.mock.method(projectWorkExecutionApi, 'getWorkbench', async (projectId, agentSlug) => ({
    agent_slug: agentSlug,
    auto_accept_work: false,
    work_default_model_spec: null,
    current: null,
    pending_acceptance: [],
    queued: [],
    recent: []
  }))
  t.mock.method(projectAgentApi, 'list', async () => ({ agents: [] }))
  t.mock.method(projectWorkExecutionApi, 'updateWorkbenchConfig', async (projectId, agentSlug, config) => {
    saves.push([projectId, agentSlug, config])
    return {}
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/projects/:project_id/agents/:agent_slug/workbench', component: View }]
  })
  await router.push('/projects/project/agents/agent/workbench')
  await router.isReady()
  let instance
  const Component = { ...View, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp(Component)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()

  instance.setupState.autoAcceptWork = true
  instance.setupState.selectWorkModel('deepseek:deepseek-chat')
  assert.equal(instance.setupState.settingsChanged, true)
  await instance.setupState.saveSettings()
  assert.deepEqual(saves, [
    ['project', 'agent', { auto_accept_work: true, work_default_model_spec: 'deepseek:deepseek-chat' }]
  ])
})
