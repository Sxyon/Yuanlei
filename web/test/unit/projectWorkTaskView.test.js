import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, ssrContextKey } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createServer } from 'vite'

let vite, View, projectWorkApi, projectAgentApi
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: View } = await vite.ssrLoadModule('/src/views/ProjectWorkTaskView.vue'))
  ;({ projectWorkApi } = await vite.ssrLoadModule('/src/apis/project_work_api.js'))
  ;({ projectAgentApi } = await vite.ssrLoadModule('/src/apis/project_agent_api.js'))
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
  t.mock.method(projectAgentApi, 'list', async () => ({ agents: [] }))
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

test('回读保留未提交负责人草稿，旧 Issue 评论不覆盖新选择', async (t) => {
  const detail = {
    id: 'task', status: 'todo', primary_owner_agent_slug: null,
    issues: [{ id: 'a' }, { id: 'b' }], comments: []
  }
  let finishComment
  t.mock.method(projectWorkApi, 'getTask', async () => detail)
  t.mock.method(projectWorkApi, 'getIssue', async (_projectId, _taskId, issueId) => ({
    id: issueId, status: 'open', comments: []
  }))
  t.mock.method(projectWorkApi, 'updateIssue', async () => ({}))
  t.mock.method(projectWorkApi, 'addIssueComment', () => new Promise((resolve) => { finishComment = resolve }))
  t.mock.method(projectAgentApi, 'list', async () => ({ agents: [] }))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/projects/:project_id/work/tasks/:task_id', component: View }]
  })
  await router.push('/projects/project/work/tasks/task')
  await router.isReady()
  let instance
  const Component = { ...View, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp(Component)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()
  instance.setupState.selectedOwner = 'agent-b'
  await instance.setupState.load()
  assert.equal(instance.setupState.selectedOwner, 'agent-b')

  await instance.setupState.openIssue('a')
  instance.setupState.issueDraft = 'A 的结论'
  instance.setupState.issueStatus = 'resolved'
  await instance.setupState.updateIssue()
  assert.equal(instance.setupState.issueDraft, 'A 的结论')
  const submitted = instance.setupState.addIssueComment()
  await settle()
  await instance.setupState.openIssue('b')
  instance.setupState.issueDraft = 'B 的草稿'
  finishComment()
  await submitted
  assert.equal(instance.setupState.selectedIssue.id, 'b')
  assert.equal(instance.setupState.issueDraft, 'B 的草稿')
})
