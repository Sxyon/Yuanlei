import assert from 'node:assert/strict'
import { after, before, beforeEach, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, reactive, ssrContextKey } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createServer } from 'vite'
import { routeLocationKey, routerKey } from 'vue-router'

let vite, View, api
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  globalThis.window = { addEventListener() {}, removeEventListener() {}, confirm: () => true }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: View } = await vite.ssrLoadModule(
    '/src/components/project/capabilities/BlueprintWorkspace.vue'
  ))
  ;({ governanceBoardApi: api } = await vite.ssrLoadModule('/src/apis/governance_board_api.js'))
})
beforeEach(() => setActivePinia(createPinia()))
after(async () => {
  await vite?.close()
  delete globalThis.localStorage
  delete globalThis.window
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
const flush = async () => {
  await nextTick()
  await new Promise((resolve) => setImmediate(resolve))
  await nextTick()
}
const settle = async (predicate) => {
  for (let i = 0; i < 50 && !predicate(); i++) await flush()
  assert.ok(predicate(), '蓝图状态未收敛')
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
  app.provide(routerKey, { replace: async () => {}, push: async () => {} })
  app.mount({})
  t.after(() => app.unmount())
  return () => instance.setupState
}
function stub(t) {
  t.mock.method(api, 'listBlueprints', async () => ({
    documents: [{ name: '方向.md' }, { name: '预算.md' }]
  }))
  t.mock.method(api, 'listBlueprintArchives', async () => ({
    documents: [{ name: '方向.md', archive_name: 'old.md' }]
  }))
  t.mock.method(api, 'getBlueprint', async (_, name) => ({ name, content: `已存正文:${name}` }))
  t.mock.method(api, 'getBlueprintArchive', async (_, name) => ({ name, content: `历史:${name}` }))
}
test('连续查看历史后返回恢复抽屉、选择、折叠、编辑、草稿和容器滚动', async (t) => {
  stub(t)
  const state = mount(t, reactive({ projectId: 'first' }))
  await settle(() => state().entries['方向.md'])
  state().selected = '预算.md'
  state().layout = 'drawer'
  state().expanded = { '预算.md': true }
  state().editing = { '预算.md': true }
  state().entries['预算.md'].content = '未保存预算'
  state().content = { scrollTop: 320, querySelector: () => null }
  await state().showHistory('old.md')
  state().content.scrollTop = 0
  await state().showHistory('older.md')
  assert.equal(state().history.content, '历史:older.md')
  await state().returnFromHistory()
  assert.equal(state().selected, '预算.md')
  assert.equal(state().layout, 'drawer')
  assert.deepEqual(state().expanded, { '预算.md': true })
  assert.deepEqual(state().editing, { '预算.md': true })
  assert.equal(state().entries['预算.md'].content, '未保存预算')
  assert.equal(state().content.scrollTop, 320)
})
test('保存使用回读事实，请求期间新增输入保留为草稿', async (t) => {
  stub(t)
  let finish
  t.mock.method(
    api,
    'putBlueprint',
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  const state = mount(t, reactive({ projectId: 'first' }))
  await settle(() => state().entries['方向.md'])
  state().entries['方向.md'].content = '提交正文'
  state().editing = { '方向.md': true }
  const saving = state().save('方向.md')
  state().entries['方向.md'].content = '继续输入'
  t.mock.method(api, 'getBlueprint', async (_, name) => ({ name, content: '文件回读正文' }))
  finish({ content: '错误写响应' })
  await saving
  assert.equal(state().entries['方向.md'].saved, '文件回读正文')
  assert.equal(state().entries['方向.md'].content, '继续输入')
  assert.equal(state().editing['方向.md'], true)
})
test('切项目时旧文件响应和历史错误不能污染新项目', async (t) => {
  stub(t)
  let lateRead, lateArchive
  t.mock.method(api, 'getBlueprint', (project, name) =>
    project === 'first'
      ? new Promise((resolve) => {
          lateRead = resolve
        })
      : Promise.resolve({ name, content: '新项目' })
  )
  t.mock.method(
    api,
    'getBlueprintArchive',
    () =>
      new Promise((_, reject) => {
        lateArchive = reject
      })
  )
  const props = reactive({ projectId: 'first' }),
    state = mount(t, props)
  await settle(() => lateRead)
  const history = state().showHistory('old.md')
  props.projectId = 'second'
  await settle(() => state().entries['方向.md']?.content === '新项目')
  lateRead({ name: '方向.md', content: '旧项目' })
  lateArchive(new Error('旧历史错误'))
  await history
  await flush()
  assert.equal(state().entries['方向.md'].content, '新项目')
  assert.equal(state().history, null)
  assert.equal(state().error, '')
})

test('实际RouterView装配的蓝图离开保护可取消导航', async (t) => {
  stub(t)
  const { createRouter, createMemoryHistory, RouterView } = await import('vue-router')
  let instance
  const Component = {
    ...View,
    render() {
      instance = getCurrentInstance()
      return h('div')
    }
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/blueprints', component: Component, props: { projectId: 'route-project' } },
      { path: '/outside', component: { render: () => h('div') } }
    ]
  })
  await router.push('/blueprints')
  await router.isReady()
  const app = renderer.createApp({ render: () => h(RouterView) })
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle(() => instance.setupState.entries['方向.md'])
  await router.push('/blueprints?blueprint=方向.md')
  await router.push('/blueprints?blueprint=预算.md')
  assert.equal(instance.setupState.selected, '预算.md')
  router.back()
  await settle(() => instance.setupState.selected === '方向.md')
  await router.push('/blueprints?blueprint=不存在.md')
  assert.equal(instance.setupState.selected, '不存在.md')
  assert.equal(
    instance.setupState.documents.some((item) => item.name === instance.setupState.selected),
    false
  )
  await router.push('/blueprints?blueprint=方向.md')
  instance.setupState.entries['方向.md'].content = '未保存正文'
  const confirm = window.confirm
  window.confirm = () => false
  await router.push('/outside')
  assert.equal(router.currentRoute.value.path, '/blueprints')
  window.confirm = () => true
  await router.push('/outside')
  assert.equal(router.currentRoute.value.path, '/outside')
  window.confirm = confirm
})

test('当前蓝图历史只来自准确名称，全归档目录保留其他蓝图', async (t) => {
  stub(t)
  t.mock.method(api, 'listBlueprintArchives', async () => ({
    documents: [
      { name: '方向.md', archive_name: 'a-old.md' },
      { name: '预算.md', archive_name: 'b-old.md' }
    ]
  }))
  const state = mount(t, reactive({ projectId: 'history-project' }))
  await settle(() => state().entries['方向.md'])
  assert.deepEqual(
    state().currentArchives.map((item) => item.archive_name),
    ['a-old.md']
  )
  state().selected = '预算.md'
  assert.deepEqual(
    state().currentArchives.map((item) => item.archive_name),
    ['b-old.md']
  )
  assert.equal(state().archives.length, 2)
  state().openHistoryMenu('all-archives')
  assert.equal(state().archiveDirectoryOpen, true)
})
