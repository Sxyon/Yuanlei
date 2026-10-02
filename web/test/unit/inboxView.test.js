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

test('失败与中断通知跳到对应任务并标记已读', async (t) => {
  const updates = []
  t.mock.method(inboxApi, 'list', async () => ([
    {
      id: 'notice-1', kind: 'task_failed', source_id: 'task-1', project_id: 'p1',
      title: '任务执行失败', summary: 'boom', read_at: null, archived_at: null,
      created_at: '2026-09-29T00:00:00Z'
    },
    {
      id: 'notice-2', kind: 'task_interrupted', source_id: 'task-2', project_id: 'p1',
      title: '任务执行中断', summary: null, read_at: '2026-09-29T01:00:00Z', archived_at: null,
      created_at: '2026-09-29T00:30:00Z'
    }
  ]))
  t.mock.method(inboxApi, 'update', async (itemId, payload) => {
    updates.push([itemId, payload])
    return {}
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/inbox', component: View },
      { path: '/projects/:project_id/work/tasks/:task_id', component: { render: () => h('div') } }
    ]
  })
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
  await instance.setupState.openItem(instance.setupState.items[0])
  assert.equal(router.currentRoute.value.fullPath, '/projects/p1/work/tasks/task-1')
  assert.deepEqual(updates, [['notice-1', { read: true }]])
})

test('任务巡检通知显示中文并可跳转到项目任务列表', async (t) => {
  const updates = []
  t.mock.method(inboxApi, 'list', async () => ([
    {
      id: 'notice-3', kind: 'task_inspection', source_id: 'run-1', project_id: 'p1',
      title: '任务巡检提醒：周报', summary: '任务已过计划结束日期', read_at: null, archived_at: null,
      created_at: '2026-09-30T00:00:00Z'
    }
  ]))
  t.mock.method(inboxApi, 'update', async (itemId, payload) => {
    updates.push([itemId, payload])
    return {}
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/inbox', component: View },
      { path: '/projects/:project_id/work/tasks', component: { render: () => h('div') } }
    ]
  })
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
  assert.deepEqual(instance.setupState.kindInfo('task_inspection'), {
    label: '任务巡检', action: '查看任务', target: 'project_tasks'
  })
  await instance.setupState.openItem(instance.setupState.items[0])
  assert.equal(router.currentRoute.value.fullPath, '/projects/p1/work/tasks')
  assert.deepEqual(updates, [['notice-3', { read: true }]])
})

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
