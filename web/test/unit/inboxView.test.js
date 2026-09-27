import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, ssrContextKey } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createServer } from 'vite'

let vite, View, inboxApi
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: View } = await vite.ssrLoadModule('/src/views/InboxView.vue'))
  ;({ inboxApi } = await vite.ssrLoadModule('/src/apis/inbox_api.js'))
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

test('快速切换分类时迟到的旧响应不能覆盖当前收件箱', async (t) => {
  let finishUnread, finishArchived
  t.mock.method(inboxApi, 'list', (folder) => new Promise((resolve) => {
    if (folder === 'unread') finishUnread = resolve
    if (folder === 'archived') finishArchived = resolve
  }))
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/inbox', component: View }] })
  await router.push('/inbox')
  await router.isReady()
  let instance
  const Component = { ...View, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp(Component)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()
  instance.setupState.folder = 'archived'
  await settle()
  finishArchived([{ id: 'archived-only' }])
  await settle()
  finishUnread([{ id: 'old-unread' }])
  await settle()
  assert.deepEqual(instance.setupState.items.map((item) => item.id), ['archived-only'])
  assert.equal(instance.setupState.loading, false)
})
