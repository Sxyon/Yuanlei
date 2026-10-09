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

test('业务页面就绪仍加载管理兜底，蓝图失败不影响业务页面', async (t) => {
  t.mock.method(dashboardApi, 'getDashboard', async () => ({
    state: 'ready',
    html: '<p>自定义页面</p>',
    revision: 1,
    sha256: 'hash',
    size: 10
  }))
  const boardRead = t.mock.method(boardApi, 'getProjectBoard', async () => ({ project: { id: 'custom' }, overview: {} }))
  const blueprintRead = t.mock.method(boardApi, 'listBlueprints', async () => {
    throw new Error('蓝图暂不可读')
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
  assert.equal(instance.setupState.business, false)
  assert.equal(instance.setupState.board.project.id, 'custom')
  assert.ok(instance.setupState.blueprintError)
  assert.equal(boardRead.mock.callCount(), 1)
  assert.equal(blueprintRead.mock.callCount(), 1)
})

test('业务读取和蓝图正文挂起时管理独立就绪；蓝图不阻塞业务显示', async t => {
  let finishDashboard, finishBlueprint
  t.mock.method(dashboardApi, 'getDashboard', () => new Promise(resolve => { finishDashboard = resolve }))
  t.mock.method(boardApi, 'getProjectBoard', async () => ({ project: { id: 'scope' }, overview: {} }))
  t.mock.method(boardApi, 'listBlueprints', async () => ({ documents: [{ name: 'plan.md' }] }))
  t.mock.method(boardApi, 'getBlueprint', () => new Promise(resolve => { finishBlueprint = resolve }))
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:project_id/dashboard', component: View }] })
  await router.push('/projects/scope/dashboard'); await router.isReady()
  let instance
  const app = renderer.createApp({ ...View, render() { instance = getCurrentInstance(); return h('div') } })
  app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.mount({}); t.after(() => app.unmount())
  await settle()
  const state = () => instance.setupState
  assert.equal(state().boardLoading, false); assert.equal(state().board.project.id, 'scope')
  assert.equal(state().businessLoading, true); assert.equal(state().blueprintLoading, true)
  finishDashboard({ state: 'ready', html: '<p>独立业务页面</p>' }); await settle()
  assert.equal(state().businessLoading, false); assert.equal(state().loading, false)
  assert.equal(state().blueprintLoading, true); assert.match(state().srcdoc, /独立业务页面/)
  finishBlueprint({ content: '合成蓝图' }); await settle()
  assert.equal(state().blueprintLoading, false)
})


test('同项目最后一份蓝图移除后刷新清空旧正文与选择', async t => {
  let documents = [{ name: 'plan.md' }]
  t.mock.method(dashboardApi, 'getDashboard', async () => ({ state: 'empty' }))
  t.mock.method(boardApi, 'getProjectBoard', async () => ({ project: { id: 'scope' }, overview: {} }))
  t.mock.method(boardApi, 'listBlueprints', async () => ({ documents }))
  t.mock.method(boardApi, 'getBlueprint', async () => ({ content: '已删除蓝图的合成正文' }))
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:project_id/dashboard', component: View }] })
  await router.push('/projects/scope/dashboard'); await router.isReady()
  let instance
  const app = renderer.createApp({ ...View, render() { instance = getCurrentInstance(); return h('div') } })
  app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.mount({}); t.after(() => app.unmount())
  await settle()
  assert.equal(instance.setupState.blueprintContent, '已删除蓝图的合成正文')
  documents = []
  await instance.setupState.load(); await settle()
  assert.equal(instance.setupState.selectedBlueprint, '')
  assert.equal(instance.setupState.blueprintContent, '')
  assert.equal(instance.setupState.blueprintLoading, false)
})
