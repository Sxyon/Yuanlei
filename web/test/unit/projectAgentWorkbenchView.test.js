import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, ssrContextKey } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
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
