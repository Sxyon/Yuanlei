import assert from 'node:assert/strict'
import { setImmediate } from 'node:timers'
import { after, before, test } from 'node:test'
import { createRenderer, getCurrentInstance, h, nextTick, ssrContextKey } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { Modal } from 'ant-design-vue'
import { createServer } from 'vite'
let vite, View, api
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  globalThis.window = { addEventListener() {}, removeEventListener() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: View } = await vite.ssrLoadModule('/src/components/project/ProjectThemeManager.vue'))
  ;({ projectThemeApi: api } = await vite.ssrLoadModule('/src/apis/project_theme_api.js'))
})
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
test('主题候选取消来源切换和真实路由离开时保留未保存正文', async (t) => {
  setActivePinia(createPinia())
  const sources = [
    { id: 'a', kind: 'project', versions: [] },
    { id: 'b', kind: 'project', versions: [] }
  ]
  t.mock.method(api, 'catalog', async () => ({ sources }))
  t.mock.method(api, 'candidate', async (id) => ({
    source: { id, candidate_revision: 1 },
    package: { manifest: {}, theme: { name: id } }
  }))
  let confirmation, instance
  t.mock.method(Modal, 'confirm', (options) => {
    confirmation = options
    return { destroy() {} }
  })
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
      {
        path: '/settings',
        component: Component,
        props: { projectId: 'test-project', projects: [], stayInProject: true }
      },
      { path: '/topics', component: { render: () => h('div') } }
    ]
  })
  await router.push('/settings')
  await router.isReady()
  const app = renderer.createApp({ render: () => h(RouterView) })
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await nextTick()
  const state = () => instance.setupState
  await state().openSource(sources[0])
  state().definition = JSON.stringify({ manifest: {}, theme: { name: '未保存候选' } })
  const switching = state().openSource(sources[1])
  assert.equal(confirmation.title, '放弃未保存的主题候选？')
  confirmation.onCancel()
  await switching
  assert.equal(state().activeId, 'a')
  assert.match(state().definition, /未保存候选/)
  confirmation = null
  const leaving = router.push('/topics')
  for (let i = 0; i < 20 && !confirmation; i++)
    await new Promise((resolve) => setImmediate(resolve))
  assert.ok(confirmation)
  confirmation.onCancel()
  await leaving
  assert.equal(router.currentRoute.value.path, '/settings')
  assert.match(state().definition, /未保存候选/)
})
