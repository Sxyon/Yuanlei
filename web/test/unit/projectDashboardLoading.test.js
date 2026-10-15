import assert from 'node:assert/strict'
import { after, before, beforeEach, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, reactive, ssrContextKey } from 'vue'
import { routeLocationKey } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { createServer } from 'vite'

let vite, View, dashboardApi, boardApi
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: View } = await vite.ssrLoadModule(
    '/src/components/project/capabilities/OverviewWorkspace.vue'
  ))
  ;({ projectDashboardApi: dashboardApi } = await vite.ssrLoadModule(
    '/src/apis/project_dashboard_api.js'
  ))
  ;({ governanceBoardApi: boardApi } = await vite.ssrLoadModule(
    '/src/apis/governance_board_api.js'
  ))
})
beforeEach(() => setActivePinia(createPinia()))
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
  await nextTick()
}
function mount(t, props) {
  let instance
  const app = renderer.createApp({
    render: () =>
      h(
        {
          ...View,
          render() {
            instance = getCurrentInstance()
            return h('div')
          }
        },
        props
      )
  })
  app.provide(ssrContextKey, { modules: new Set() })
  app.provide(routeLocationKey, reactive({ query: {} }))
  app.mount({})
  t.after(() => app.unmount())
  return () => instance.setupState
}
function stub(t) {
  t.mock.method(boardApi, 'getProjectBoard', async (project) => ({
    project: { id: project },
    overview: {}
  }))
  t.mock.method(boardApi, 'listTopics', async () => [])
  t.mock.method(boardApi, 'recentActivity', async () => ({ items: [] }))
}
test('切换到无蓝图项目后迟到正文不能污染新项目或留下加载状态', async (t) => {
  stub(t)
  let finish
  t.mock.method(boardApi, 'listBlueprints', async (project) => ({
    documents: project === 'first' ? [{ name: 'plan.md' }] : []
  }))
  t.mock.method(
    boardApi,
    'getBlueprint',
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  const props = reactive({ projectId: 'first' }),
    state = mount(t, props)
  await settle()
  assert.ok(finish)
  props.projectId = 'second'
  await settle()
  assert.equal(state().loading, false)
  assert.equal(state().blueprint, null)
  finish({ name: 'plan.md', content: '旧项目内容' })
  await settle()
  assert.equal(state().blueprint, null)
  assert.equal(state().board.project.id, 'second')
})
test('蓝图读取失败不阻塞总览事实与显式打开的业务大屏', async (t) => {
  stub(t)
  t.mock.method(boardApi, 'listBlueprints', async () => {
    throw new Error('蓝图暂不可读')
  })
  t.mock.method(dashboardApi, 'getDashboard', async () => ({
    state: 'ready',
    html: '<p>自定义页面</p>'
  }))
  const state = mount(t, reactive({ projectId: 'custom' }))
  await settle()
  assert.equal(state().board.project.id, 'custom')
  assert.match(state().error, /蓝图暂不可读/)
  await state().readBusiness()
  assert.equal(state().business.state, 'ready')
  assert.match(state().business.html, /自定义页面/)
})
test('蓝图正文挂起时总览已可读，业务大屏读取独立完成', async (t) => {
  stub(t)
  let finishBlueprint, finishDashboard
  t.mock.method(boardApi, 'listBlueprints', async () => ({ documents: [{ name: 'plan.md' }] }))
  t.mock.method(
    boardApi,
    'getBlueprint',
    () =>
      new Promise((resolve) => {
        finishBlueprint = resolve
      })
  )
  t.mock.method(
    dashboardApi,
    'getDashboard',
    () =>
      new Promise((resolve) => {
        finishDashboard = resolve
      })
  )
  const state = mount(t, reactive({ projectId: 'scope' }))
  await settle()
  assert.equal(state().board.project.id, 'scope')
  assert.equal(state().loading, true)
  const business = state().readBusiness()
  finishDashboard({ state: 'ready', html: '独立业务页面' })
  await business
  assert.equal(state().business.state, 'ready')
  assert.equal(state().blueprint, null)
  finishBlueprint({ name: 'plan.md', content: '合成蓝图' })
  await settle()
  assert.equal(state().loading, false)
  assert.equal(state().blueprint.content, '合成蓝图')
})
test('最后一份蓝图移除后刷新清空旧正文', async (t) => {
  stub(t)
  let documents = [{ name: 'plan.md' }]
  t.mock.method(boardApi, 'listBlueprints', async () => ({ documents }))
  t.mock.method(boardApi, 'getBlueprint', async () => ({ name: 'plan.md', content: '已删除正文' }))
  const state = mount(t, reactive({ projectId: 'scope' }))
  await settle()
  assert.equal(state().blueprint.content, '已删除正文')
  documents = []
  await state().load()
  assert.equal(state().blueprint, null)
  assert.equal(state().loading, false)
})
