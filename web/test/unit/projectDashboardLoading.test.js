import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, ssrContextKey } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createServer } from 'vite'

let vite, View, dashboardApi, boardApi
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: View } = await vite.ssrLoadModule('/src/views/ProjectDashboardView.vue'))
  ;({ projectDashboardApi: dashboardApi } = await vite.ssrLoadModule(
    '/src/apis/project_dashboard_api.js'
  ))
  ;({ governanceBoardApi: boardApi } = await vite.ssrLoadModule(
    '/src/apis/governance_board_api.js'
  ))
})
after(async () => {
  await vite?.close()
  delete globalThis.localStorage
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

test('切换到无蓝图项目时过期蓝图请求不能让加载状态永久停留', async (t) => {
  let finishBlueprint
  t.mock.method(dashboardApi, 'getDashboard', async () => ({ state: 'empty' }))
  t.mock.method(boardApi, 'getProjectBoard', async (projectId) => ({
    project: { id: projectId, name: projectId },
    governance: {},
    execution: {}
  }))
  t.mock.method(boardApi, 'listBlueprints', async (projectId) => ({
    documents: projectId === 'first' ? [{ name: 'plan.md' }] : []
  }))
  t.mock.method(
    boardApi,
    'getBlueprint',
    () =>
      new Promise((resolve) => {
        finishBlueprint = resolve
      })
  )
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/projects/:project_id/dashboard', name: 'ProjectDashboardComp', component: View }
    ]
  })
  await router.push('/projects/first/dashboard')
  await router.isReady()
  let instance
  const Component = {
    ...View,
    render() {
      instance = getCurrentInstance()
      return h('div')
    }
  }
  const app = renderer.createApp(Component)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()
  assert.equal(instance.setupState.blueprintLoading, true)

  await router.push('/projects/second/dashboard')
  await settle()
  assert.equal(instance.setupState.blueprintLoading, false)
  assert.equal(instance.setupState.selectedBlueprint, '')
  assert.deepEqual(instance.setupState.blueprints, [])
  finishBlueprint({ name: 'plan.md', content: '旧项目内容' })
  await settle()
  assert.equal(instance.setupState.blueprintLoading, false)
  assert.equal(instance.setupState.blueprintContent, '')
})

test('自定义页面就绪时不请求默认概览的项目数据', async (t) => {
  t.mock.method(dashboardApi, 'getDashboard', async () => ({
    state: 'ready',
    html: '<p>自定义页面</p>',
    revision: 1,
    sha256: 'hash',
    size: 10
  }))
  const boardRead = t.mock.method(boardApi, 'getProjectBoard', () => {
    throw new Error('自定义页面不应读取项目治理数据')
  })
  const blueprintRead = t.mock.method(boardApi, 'listBlueprints', () => {
    throw new Error('自定义页面不应读取蓝图')
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/projects/:project_id/dashboard', component: View }]
  })
  await router.push('/projects/custom/dashboard')
  await router.isReady()
  let instance
  const Component = {
    ...View,
    render() {
      instance = getCurrentInstance()
      return h('div')
    }
  }
  const app = renderer.createApp(Component)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()
  assert.equal(instance.setupState.page.state, 'ready')
  assert.match(instance.setupState.srcdoc, /自定义页面/)
  assert.equal(boardRead.mock.callCount(), 0)
  assert.equal(blueprintRead.mock.callCount(), 0)
})
