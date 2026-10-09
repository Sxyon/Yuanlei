import assert from 'node:assert/strict'
import test from 'node:test'
import { createPinia, setActivePinia, disposePinia } from 'pinia'
import { createRenderer, getCurrentInstance, h, nextTick, ssrContextKey } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createServer } from 'vite'

test('项目导航按用户和项目隔离；窄屏临时打开不覆盖桌面偏好', async t => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  let narrow = false
  globalThis.window = { matchMedia: () => ({ matches: narrow }) }
  const vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  const pinia = createPinia(); setActivePinia(pinia)
  let app
  try {
    const { projectApi } = await vite.ssrLoadModule('/src/apis/project_api.js')
    t.mock.method(projectApi, 'getProjects', async () => [{ id: 'a', name: 'A' }, { id: 'b', name: 'B' }])
    const { useUserStore } = await vite.ssrLoadModule('/src/stores/user.js')
    const user = useUserStore(); user.uid = 'first-user'
    const { useChatUIStore } = await vite.ssrLoadModule('/src/stores/chatUI.js')
    const ui = useChatUIStore()
    const { default: Layout } = await vite.ssrLoadModule('/src/layouts/ProjectLayout.vue')
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:project_id/dashboard', name: 'ProjectDashboardComp', component: Layout }] })
    await router.push('/projects/a/dashboard'); await router.isReady()
    let instance
    const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}), insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
    app = renderer.createApp({ ...Layout, render() { instance = getCurrentInstance(); return h('div') } })
    app.use(pinia); app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.mount({})
    await nextTick()
    const state = () => instance.setupState
    state().toggleNavigation(); assert.equal(state().collapsed, true)
    await router.push('/projects/b/dashboard'); await nextTick(); assert.equal(state().collapsed, false)
    await router.push('/projects/a/dashboard'); await nextTick(); assert.equal(state().collapsed, true)
    narrow = true; state().toggleNavigation(); assert.equal(state().mobileOpen, true); assert.equal(state().collapsed, true)
    user.uid = 'second-user'; await nextTick(); assert.equal(state().collapsed, false); assert.equal(state().mobileOpen, false)
    assert.equal(Object.keys(ui.projectNavigationCollapsed).length, 1)
  } finally { app?.unmount(); disposePinia(pinia); await vite.close(); delete globalThis.window; delete globalThis.localStorage }
})
