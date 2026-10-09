import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'
import { after, before, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, KeepAlive, nextTick, ssrContextKey } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { createServer } from 'vite'

let vite, View, projectWorkApi, projectAgentApi, projectWorkExecutionApi, governanceBoardApi
before(async () => {
  setActivePinia(createPinia())
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: View } = await vite.ssrLoadModule('/src/views/ProjectWorkTaskView.vue'))
  ;({ projectWorkApi } = await vite.ssrLoadModule('/src/apis/project_work_api.js'))
  ;({ projectAgentApi } = await vite.ssrLoadModule('/src/apis/project_agent_api.js'))
  ;({ governanceBoardApi } = await vite.ssrLoadModule('/src/apis/governance_board_api.js'))
  ;({ projectWorkExecutionApi } = await vite.ssrLoadModule('/src/apis/project_work_execution_api.js'))
})
after(async () => {
  await vite?.close()
  delete globalThis.localStorage
})

const renderer = createRenderer({
  createElement: (tag) => ({ tagName: tag.toUpperCase(), value: '', options: [], getRootNode: () => ({ activeElement: null }), addEventListener() {}, setAttribute() {}, removeAttribute() {} }), createText: () => ({}), createComment: () => ({}),
  insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {},
  parentNode: () => null, nextSibling: () => null
})
const settle = async () => {
  await nextTick()
  await new Promise((resolve) => setImmediate(resolve))
}

test('快速切换任务时迟到的旧任务响应不能覆盖当前详情', async (t) => {
  t.mock.method(projectAgentApi, 'list', async () => ({ agents: [] }))
  t.mock.method(projectWorkExecutionApi, 'listForTask', async () => [])
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

test('离开任务页面后不再用空路由参数请求任务', async (t) => {
  let taskReads = 0
  let executionReads = 0
  let agentReads = 0
  t.mock.method(projectWorkApi, 'getTask', async () => {
    taskReads += 1
    return { id: 'task', status: 'todo', issues: [], comments: [], references: [] }
  })
  t.mock.method(projectAgentApi, 'list', async () => {
    agentReads += 1
    return { agents: [] }
  })
  t.mock.method(projectWorkExecutionApi, 'listForTask', async () => {
    executionReads += 1
    return []
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/projects/:project_id/work/tasks/:task_id', component: View },
      { path: '/inbox', component: { render: () => h('div') } }
    ]
  })
  await router.push('/projects/project/work/tasks/task')
  await router.isReady()
  const Component = { render() { return h(RouterView, null, { default: ({ Component: Current }) => h(KeepAlive, null, { default: () => h(Current) }) }) } }
  const app = renderer.createApp(Component)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()
  await router.push('/inbox')
  await settle()

  assert.deepEqual([taskReads, agentReads, executionReads], [1, 1, 1])
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
  t.mock.method(projectWorkExecutionApi, 'listForTask', async () => [])
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

test('失败尝试展示 Run 与错误并可重新执行', async (t) => {
  const assigned = []
  t.mock.method(projectWorkApi, 'getTask', async () => ({
    id: 'task', status: 'in_progress', primary_owner_agent_slug: null,
    issues: [], comments: [], references: []
  }))
  t.mock.method(projectAgentApi, 'list', async () => ({ agents: [] }))
  t.mock.method(projectWorkExecutionApi, 'listForTask', async () => ([
    { id: 'exec-1', agent_slug: 'agent-a', status: 'failed', error_message: '执行失败', current_run_id: 'run-1', thread_id: 'thread-1' }
  ]))
  t.mock.method(projectWorkExecutionApi, 'assign', async (projectId, taskId, agentSlug) => {
    assigned.push([projectId, taskId, agentSlug])
    return { id: 'exec-2' }
  })
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

  assert.deepEqual(instance.setupState.retryableStatuses, ['failed', 'cancelled'])
  assert.equal(instance.setupState.executions[0].current_run_id, 'run-1')
  await instance.setupState.retryExecution(instance.setupState.executions[0])
  assert.deepEqual(assigned, [['project', 'task', 'agent-a']])
})

test('网页引用提交失败时在表单旁显示错误并保留输入', async (t) => {
  t.mock.method(projectWorkApi, 'getTask', async () => ({
    id: 'task', status: 'todo', primary_owner_agent_slug: null,
    issues: [], comments: [], references: []
  }))
  t.mock.method(projectWorkApi, 'addReference', async () => { throw new Error('引用 URL 无效') })
  t.mock.method(projectWorkApi, 'removeReference', async () => { throw new Error('引用移除失败') })
  t.mock.method(projectAgentApi, 'list', async () => ({ agents: [] }))
  t.mock.method(projectWorkExecutionApi, 'listForTask', async () => [])
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

  instance.setupState.referenceTitle = '资料'
  instance.setupState.referenceUrl = 'bad-url'
  await instance.setupState.addReference()
  assert.equal(instance.setupState.referenceError, '引用 URL 无效')
  assert.equal(instance.setupState.referenceUrl, 'bad-url')
  await instance.setupState.removeReference('reference-one')
  assert.equal(instance.setupState.referenceError, '引用移除失败')
})

test('执行记录与问题单展示可读名称与中文状态', async (t) => {
  t.mock.method(projectWorkApi, 'getTask', async () => ({
    id: 'task', status: 'todo', primary_owner_agent_slug: null,
    issues: [{ id: 'i1', status: 'open', title: '问题' }], comments: [], references: []
  }))
  t.mock.method(projectAgentApi, 'list', async () => ({ agents: [{ slug: 'agent-a', name: '调研员码农' }] }))
  t.mock.method(projectWorkExecutionApi, 'listForTask', async () => [])
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

  assert.equal(instance.setupState.agentName('agent-a'), '调研员码农')
  assert.equal(instance.setupState.agentName('unknown-slug'), 'unknown-slug')
  assert.equal(instance.setupState.issueStatusLabel('open'), '待处理')
  assert.equal(instance.setupState.issueStatusLabel('resolved'), '已解决')
  assert.equal(instance.setupState.issueStatusLabel('closed'), '已关闭')
})

test('附件上传成功后刷新详情，失败时展示错误', async (t) => {
  const uploads = []
  let attachments = []
  t.mock.method(projectWorkApi, 'getTask', async () => ({
    id: 'task', status: 'todo', primary_owner_agent_slug: null,
    issues: [], comments: [], references: [], attachments: [...attachments]
  }))
  t.mock.method(projectAgentApi, 'list', async () => ({ agents: [] }))
  t.mock.method(projectWorkExecutionApi, 'listForTask', async () => [])
  t.mock.method(projectWorkApi, 'uploadAttachment', async (projectId, taskId, file) => {
    uploads.push([projectId, taskId, file.name])
    attachments = [{ id: 'att-1', file_name: file.name, file_size: 5 }]
    return { id: 'att-1' }
  })
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

  const input = { files: [{ name: '设计说明.txt' }], value: 'picked' }
  await instance.setupState.uploadAttachment({ target: input })
  assert.deepEqual(uploads, [['project', 'task', '设计说明.txt']])
  assert.equal(input.value, '')
  assert.equal(instance.setupState.task.attachments.length, 1)
  assert.equal(instance.setupState.formatSize(1536), '1.5 KB')

  t.mock.method(projectWorkApi, 'uploadAttachment', async () => { throw new Error('附件过大，当前仅支持 5 MB 以内的文件') })
  await instance.setupState.uploadAttachment({ target: { files: [{ name: 'big.bin' }], value: 'x' } })
  assert.equal(instance.setupState.attachmentError, '附件过大，当前仅支持 5 MB 以内的文件')
})

test('保存周期巡检发送启用状态与周期，失败时展示错误', async (t) => {
  const updates = []
  t.mock.method(projectWorkApi, 'getTask', async () => ({
    id: 'task', status: 'todo', primary_owner_agent_slug: 'agent-a',
    issues: [], comments: [], references: [], inspection_enabled: false, inspection_interval_minutes: 60
  }))
  t.mock.method(projectAgentApi, 'list', async () => ({ agents: [] }))
  t.mock.method(projectWorkExecutionApi, 'listForTask', async () => [])
  t.mock.method(projectWorkApi, 'updateTask', async (_projectId, taskId, payload) => {
    updates.push(payload)
    return { id: taskId }
  })
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

  instance.setupState.inspectionEnabled = true
  instance.setupState.inspectionInterval = 30
  await instance.setupState.saveInspection()
  assert.deepEqual(updates, [{ inspection_enabled: true, inspection_interval_minutes: 30 }])

  instance.setupState.inspectionEnabled = true
  t.mock.method(projectWorkApi, 'updateTask', async () => { throw new Error('请先设置第一负责人，再启用周期巡检') })
  await instance.setupState.saveInspection()
  assert.equal(instance.setupState.inspectionError, '请先设置第一负责人，再启用周期巡检')
})

async function mountGitCompletionTask(t) {
  t.mock.method(projectWorkApi, 'getTask', async (_project, id) => ({ id, status: 'todo', issues: [], comments: [], references: [] }))
  t.mock.method(projectAgentApi, 'list', async () => ({ agents: [] }))
  t.mock.method(projectWorkExecutionApi, 'listForTask', async () => [])
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:project_id/work/tasks/:task_id', component: View }] })
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
  return { router, state: () => instance.setupState }
}

test('完成任务先提示未处理 Git 成果，人工选择保留后才保存完成状态', async (t) => {
  const update = t.mock.method(projectWorkApi, 'updateTask', async () => ({}))
  t.mock.method(projectWorkApi, 'getGitOutcomes', async () => ({ requires_attention: true, scope_key: 'task:a', resources: [{ worktree_id: 'work', issues: ['uncommitted'], errors: [] }] }))
  const { state } = await mountGitCompletionTask(t)
  state().selectedStatus = 'done'
  await state().updateStatus()
  assert.equal(update.mock.callCount(), 0)
  assert.equal(state().gitCompletionOpen, true)
  assert.deepEqual(state().gitCompletion.resources[0].issues, ['uncommitted'])
  await state().confirmTaskCompletion()
  assert.deepEqual(update.mock.calls[0].arguments, ['project', 'a', { status: 'done', git_outcomes_confirmed: true }])
  assert.equal(state().gitCompletionOpen, false)
})

test('迟到的成果检查不能在另一个任务打开完成提示或保存状态', async (t) => {
  let finish
  t.mock.method(projectWorkApi, 'getGitOutcomes', () => new Promise((resolve) => { finish = resolve }))
  const update = t.mock.method(projectWorkApi, 'updateTask', async () => ({}))
  const { router, state } = await mountGitCompletionTask(t)
  state().selectedStatus = 'done'
  const pending = state().updateStatus()
  await router.push('/projects/project/work/tasks/b')
  await settle()
  finish({ requires_attention: true, resources: [] })
  await pending
  assert.equal(state().gitCompletionOpen, false)
  assert.equal(state().gitCompletion, null)
  assert.equal(state().task.id, 'b')
  assert.equal(update.mock.callCount(), 0)
})

test('无法确认成果状态时保留错误并等待明确完成选择', async (t) => {
  t.mock.method(projectWorkApi, 'getGitOutcomes', async () => { throw new Error('成果服务暂不可用') })
  const update = t.mock.method(projectWorkApi, 'updateTask', async () => ({}))
  const { state } = await mountGitCompletionTask(t)
  state().selectedStatus = 'done'
  await state().updateStatus()
  assert.equal(state().gitCompletionOpen, true)
  assert.deepEqual(state().gitCompletion.errors, ['成果服务暂不可用'])
  assert.equal(update.mock.callCount(), 0)
  await state().confirmTaskCompletion()
  assert.equal(update.mock.callCount(), 1)
})


test('任务知识库保存显式选择，刷新保留未保存草稿', async (t) => {
  let saved = []
  t.mock.method(projectWorkApi, 'getTask', async () => ({
    id: 'task', status: 'todo', knowledge_ids: saved, knowledge_candidates: [{ kb_id: 'linked', name: '项目知识' }]
  }))
  t.mock.method(projectWorkApi, 'updateTask', async (projectId, taskId, payload) => {
    assert.equal(projectId, 'project')
    assert.equal(taskId, 'task')
    saved = payload.knowledge_ids
  })
  t.mock.method(projectAgentApi, 'list', async () => ({ agents: [] }))
  t.mock.method(projectWorkExecutionApi, 'listForTask', async () => [])
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:project_id/work/tasks/:task_id', component: View }] })
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
  assert.deepEqual(instance.setupState.selectedKnowledges, [])
  instance.setupState.selectedKnowledges = ['linked']
  await instance.setupState.load()
  assert.deepEqual(instance.setupState.selectedKnowledges, ['linked'])
  await instance.setupState.saveKnowledges()
  assert.deepEqual(saved, ['linked'])
  assert.deepEqual(instance.setupState.task.knowledge_ids, ['linked'])
})


test('来源调整冲突保留所选来源及预期版本，旧执行定位不改写', async t => {
  const original = { id: 'task', status: 'todo', topic_id: 'topic', source_decision_id: 'old', source_decision_revision: 2 }
  t.mock.method(projectWorkApi, 'getTask', async () => original)
  t.mock.method(projectWorkApi, 'listTopics', async () => [{ id: 'topic', title: '来源议题' }])
  t.mock.method(governanceBoardApi, 'listDecisions', async () => [{ id: 'old', status: 'superseded' }, { id: 'new', status: 'approved' }])
  t.mock.method(projectAgentApi, 'list', async () => ({ agents: [] }))
  t.mock.method(projectWorkExecutionApi, 'listForTask', async () => [{ id: 'attempt', source_decision_id: 'old', source_decision_revision: 2 }])
  const update = t.mock.method(projectWorkApi, 'updateSource', async () => { throw new Error('工作来源已改变') })
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:project_id/work/tasks/:task_id', component: View }] })
  await router.push('/projects/a/work/tasks/task'); await router.isReady()
  let instance
  const Component = { ...View, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp(Component); app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.mount({})
  t.after(() => app.unmount()); await settle()
  const state = instance.setupState
  await state.editSource()
  state.sourceDecision = 'new'
  await state.saveSource()
  assert.equal(state.sourceEditing, true)
  assert.equal(state.sourceDecision, 'new')
  assert.equal(state.sourceError, '工作来源已改变')
  assert.equal(update.mock.calls[0].arguments[2].expected_decision_id, 'old')
  assert.equal(update.mock.calls[0].arguments[2].expected_decision_revision, 2)
  assert.equal(state.executions[0].source_decision_id, 'old')
  assert.equal(state.task.source_decision_id, 'old')
})

test('真实详情模板刷新不卸载结果面板，失败及Git预检查保留同工作草稿', async t => {
  const { readFile } = await import('node:fs/promises')
  const Vue = await import('vue/dist/vue.cjs.js')
  const source = await readFile(new URL('../../src/views/ProjectWorkTaskView.vue', import.meta.url), 'utf8')
  const template = source.slice(source.indexOf('<template>') + 10, source.lastIndexOf('</template>', source.indexOf('<script')))
  const renderTemplate = Vue.compile(template)
  const { default: Panel } = await vite.ssrLoadModule('/src/components/project/WorkResultsPanel.vue')
  let child, mounts = 0, page
  const previousRender = Panel.render
  Panel.render = function () { child = getCurrentInstance(); return h('div') }
  t.after(() => { Panel.render = previousRender })
  const originalSetup = Panel.setup
  t.mock.method(Panel, 'setup', function (...args) { mounts += 1; return originalSetup(...args) })
  let release
  t.mock.method(projectWorkApi, 'getTask', async (_project, id) => ({ id, status: 'todo', criteria_revision: 1, acceptance_criteria: '条件', issues: [], comments: [], references: [], attachments: [], results: [{ id: 'r', status: 'pending' }] }))
  t.mock.method(projectWorkApi, 'listDelegations', async () => ({ delegations: [] }))
  t.mock.method(projectAgentApi, 'list', async () => ({ agents: [] }))
  t.mock.method(projectWorkExecutionApi, 'listForTask', async () => [])
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:project_id/work/tasks/:task_id', component: View }] })
  await router.push('/projects/project/work/tasks/a'); await router.isReady()
  const Component = { ...View, components: { WorkResultsPanel: Panel }, render() { page = getCurrentInstance(); return renderTemplate.call(this, page.setupState, []) } }
  const app = renderer.createApp(Component); app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.mount({})
  t.after(() => app.unmount()); await settle()
  assert.ok(child); assert.equal(mounts, 1)
  child.setupState.summary = '未提交摘要'; child.setupState.criteria = '未保存条件'; child.setupState.comments = { r: '验收意见' }
  t.mock.method(projectWorkApi, 'getTask', () => new Promise(resolve => { release = resolve }))
  const refreshing = page.setupState.load(); await settle()
  assert.equal(mounts, 1); assert.equal(child.setupState.summary, '未提交摘要')
  release({ id: 'a', status: 'todo', criteria_revision: 2, acceptance_criteria: '其他页面条件', issues: [], comments: [], references: [], attachments: [], results: [{ id: 'r', status: 'pending' }] })
  await refreshing; await settle()
  assert.equal(mounts, 1); assert.equal(child.setupState.criteria, '未保存条件'); assert.equal(child.setupState.revision, 1)
  t.mock.method(projectWorkApi, 'getTask', async () => { throw new Error('刷新失败') })
  await page.setupState.load(); await settle()
  assert.equal(mounts, 1); assert.equal(child.setupState.comments.r, '验收意见')
  t.mock.method(projectWorkApi, 'getGitOutcomes', async () => ({ requires_attention: true, resources: [] }))
  await page.setupState.completeWithGitCheck(() => {}); await settle()
  assert.equal(mounts, 1); assert.equal(child.setupState.summary, '未提交摘要')
})
