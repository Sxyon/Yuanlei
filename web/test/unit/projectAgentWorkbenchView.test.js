import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, KeepAlive, nextTick, ssrContextKey } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { createServer } from 'vite'

let vite, View, projectWorkExecutionApi
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: View } = await vite.ssrLoadModule('/src/views/ProjectAgentWorkbenchView.vue'))
  ;({ projectWorkExecutionApi } = await vite.ssrLoadModule('/src/apis/project_work_execution_api.js'))
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
