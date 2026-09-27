import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, ssrContextKey } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createServer } from 'vite'

let vite, View, projectWorkApi
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: View } = await vite.ssrLoadModule('/src/views/ProjectWorkTaskView.vue'))
  ;({ projectWorkApi } = await vite.ssrLoadModule('/src/apis/project_work_api.js'))
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

test('快速切换任务时迟到的旧任务响应不能覆盖当前详情', async (t) => {
  let finishA, finishB
  t.mock.method(projectWorkApi, 'getTask', (_projectId, taskId) => new Promise((resolve) => {
    if (taskId === 'a') finishA = resolve
    if (taskId === 'b') finishB = resolve
  }))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/projects/:project_id/work/tasks/:task_id', component: View }]
  })
  await router.push('/projects/project/work/tasks/a')
  await router.isReady()
  let instance
  const Component = { ...View, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp(Component)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()

  await router.push('/projects/project/work/tasks/b')
  await settle()
  finishB({ id: 'b', title: '任务 B' })
  await settle()
  finishA({ id: 'a', title: '任务 A' })
  await settle()
  assert.equal(instance.setupState.task.id, 'b')
  assert.equal(instance.setupState.loading, false)
})
