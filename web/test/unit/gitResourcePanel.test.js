import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, reactive, ssrContextKey } from 'vue'
import { message } from 'ant-design-vue'
import { createServer } from 'vite'

let vite, ResourcePanel, PullPanel, SettingsModal, WorktreePanel, ActivityPanel, api, gitApi
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: ActivityPanel } = await vite.ssrLoadModule('/src/components/ProjectGitActivityPanel.vue'))
  ;({ default: ResourcePanel } = await vite.ssrLoadModule('/src/components/GitResourcePanel.vue'))
  ;({ default: WorktreePanel } = await vite.ssrLoadModule('/src/components/GitWorktreeArtifactPanel.vue'))
  ;({ default: PullPanel } = await vite.ssrLoadModule('/src/components/GitPullRequestPanel.vue'))
  ;({ default: SettingsModal } = await vite.ssrLoadModule('/src/components/ProjectGitSettingsModal.vue'))
  ;({ gitApi } = await vite.ssrLoadModule('/src/apis/git_api.js'))
  ;({ projectApi: api } = await vite.ssrLoadModule('/src/apis/project_api.js'))
})
after(async () => { await vite?.close(); delete globalThis.localStorage })
const renderer = createRenderer({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {},
  parentNode: () => null, nextSibling: () => null
})
const settle = async () => { await nextTick(); await new Promise((resolve) => setImmediate(resolve)) }
const resource = (id = 'repo') => ({ id, status: 'active', checkout_path: 'backend', configured_base_branch: 'develop', usage_mode: 'worktree', approval_mode: 'protected' })
const mount = (t, View, props) => {
  let instance
  const Component = { ...View, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp({ setup: () => () => h(Component, props) })
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  return () => instance.setupState
}

test('资源轮询保留未保存的草稿，切项目后迟到的审查不能打开弹窗', async (t) => {
  let finish
  t.mock.method(api, 'reviewGitResource', () => new Promise((resolve) => { finish = resolve }))
  const props = reactive({ projectId: 'first', resource: resource() })
  const state = mount(t, ResourcePanel, props)
  state().draft.checkout_path = 'unsaved'
  state().reviewOpen = true
  state().review = { head_sha: 'kept' }
  props.resource = { ...resource() }
  await settle()
  assert.equal(state().draft.checkout_path, 'unsaved')
  assert.equal(state().reviewOpen, true)
  assert.equal(state().review.head_sha, 'kept')
  const pending = state().openReview()
  props.projectId = 'second'
  props.resource = resource('second-repo')
  await settle()
  finish({ head_sha: 'old', tree_sha: 'old-tree', dirty: true })
  await pending
  assert.equal(state().review, null)
  assert.equal(state().reviewOpen, false)
  assert.equal(state().busy, '')
})

test('人工提交固定审查快照，并继续显示提交期间产生的新改动', async (t) => {
  t.mock.method(message, 'success', () => {})
  const commit = t.mock.method(api, 'commitGitResource', async () => ({ head_sha: 'new-head', tree_sha: 'new-tree', dirty: true }))
  const state = mount(t, ResourcePanel, reactive({ projectId: 'project', resource: resource() }))
  state().review = { head_sha: 'reviewed-head', tree_sha: 'reviewed-tree', dirty: true }
  state().commitMessage = '人工批准'
  await state().commit()
  assert.deepEqual(commit.mock.calls[0].arguments, ['project', 'repo', {
    expected_head: 'reviewed-head', expected_tree: 'reviewed-tree', message: '人工批准'
  }])
  assert.equal(state().review.head_sha, 'new-head')
  assert.equal(state().review.dirty, true)
  assert.equal(state().commitMessage, '')
})

test('未完成检出不发提交与推送，已提交资源推送精确 HEAD 和 tree', async (t) => {
  t.mock.method(message, 'success', () => {})
  const commit = t.mock.method(api, 'commitGitResource', async () => ({}))
  const push = t.mock.method(api, 'pushGitResource', async () => ({ head_sha: 'head', tree_sha: 'tree', dirty: false, unpushed: false }))
  const state = mount(t, ResourcePanel, reactive({ projectId: 'project', resource: resource() }))
  state().review = { head_sha: 'head', tree_sha: 'tree', dirty: true, incomplete_checkout: true }
  state().commitMessage = '不能提交'
  await state().commit()
  await state().push()
  assert.equal(commit.mock.callCount(), 0)
  assert.equal(push.mock.callCount(), 0)
  state().review = { head_sha: 'head', tree_sha: 'tree', dirty: false, incomplete_checkout: false }
  await state().push()
  assert.deepEqual(push.mock.calls[0].arguments, ['project', 'repo', { expected_head: 'head', expected_tree: 'tree' }])
  assert.equal(state().review.unpushed, false)
})

test('合并请求确认使用当前请求的源目标 SHA，服务端合并回读才更新状态', async (t) => {
  t.mock.method(message, 'success', () => {})
  const pull = { number: 3, head_sha: 'source', base_sha: 'target', merged: false }
  const merge = t.mock.method(api, 'mergeGitPullRequest', async () => ({ ...pull, merged: true }))
  const state = mount(t, PullPanel, reactive({ projectId: 'project', resource: resource() }))
  state().pulls = [pull]
  await state().merge(pull)
  assert.deepEqual(merge.mock.calls[0].arguments, ['project', 'repo', 3, { expected_head: 'source', expected_base: 'target' }])
  assert.equal(state().pulls[0].merged, true)
})

test('合并请求旧项目响应不会污染新项目的列表或草稿', async (t) => {
  let finish
  t.mock.method(api, 'getGitPullRequests', () => new Promise((resolve) => { finish = resolve }))
  t.mock.method(api, 'getGitWorktrees', async () => [])
  const props = reactive({ projectId: 'first', resource: resource() })
  const state = mount(t, PullPanel, props)
  const pending = state().refresh()
  props.projectId = 'second'
  props.resource = { ...resource('second-repo'), configured_base_branch: 'release' }
  await settle()
  finish([{ number: 1 }])
  await pending
  assert.deepEqual(state().pulls, [])
  assert.equal(state().draft.base_branch, 'release')
  assert.equal(state().busy, false)
})


test('选择连接与仓库读取候选并自动填默认分支，不需要手输归属', async (t) => {
  t.mock.method(gitApi, 'getConnectionRepositories', async () => [{ id: '7', owner: 'team', name: 'repo', default_branch: 'main' }])
  const branches = t.mock.method(gitApi, 'getConnectionBranches', async () => [{ name: 'main' }, { name: 'develop' }])
  const state = mount(t, SettingsModal, reactive({ open: false, project: { id: 'project' } }))
  state().repositoryForm.connection_id = 'connection'
  await settle()
  assert.equal(state().remoteRepositories[0].owner, 'team')
  state().selectedRepositoryId = '7'
  await state().selectRemoteRepository('7')
  assert.equal(state().repositoryForm.repository_owner, 'team')
  assert.equal(state().repositoryForm.repository_name, 'repo')
  assert.equal(state().repositoryForm.alias, 'repo')
  assert.equal(state().repositoryForm.checkout_path, 'repo')
  assert.equal(state().repositoryForm.configured_base_branch, 'main')
  assert.deepEqual(state().remoteBranches.map((value) => value.name), ['main', 'develop'])
  assert.deepEqual(branches.mock.calls[0].arguments, ['connection', 'team', 'repo'])
})

test('切换连接丢弃旧仓库与分支响应，不能携带旧归属继续绑定', async (t) => {
  let finishOld
  t.mock.method(gitApi, 'getConnectionRepositories', (id) => id === 'old'
    ? new Promise((resolve) => { finishOld = resolve })
    : Promise.resolve([{ id: 'new-repo', owner: 'new-team', name: 'new', default_branch: 'main' }]))
  const props = reactive({ open: false, project: { id: 'project' } })
  const state = mount(t, SettingsModal, props)
  state().repositoryForm.connection_id = 'old'
  await settle()
  state().repositoryForm.connection_id = 'new'
  await settle()
  finishOld([{ id: 'old-repo', owner: 'old-team', name: 'old' }])
  await settle()
  assert.equal(state().remoteRepositories[0].id, 'new-repo')
  assert.equal(state().repositoryForm.repository_owner, '')
  assert.equal(state().selectedRepositoryId, '')
  let finishBranches
  t.mock.method(gitApi, 'getConnectionBranches', () => new Promise((resolve) => { finishBranches = resolve }))
  state().selectedRepositoryId = 'new-repo'
  const pending = state().selectRemoteRepository('new-repo')
  props.project = { id: 'other-project' }
  await settle()
  finishBranches([{ name: 'old-result' }])
  await pending
  assert.deepEqual(state().remoteBranches, [])
  assert.equal(state().selectedRepositoryId, '')
  assert.equal(state().loadingRemoteBranches, false)
})


test('分支读取失败保留错误且禁止绑定，不把默认分支草稿当作验证结果', async (t) => {
  t.mock.method(gitApi, 'getConnectionRepositories', async () => [{ id: '7', owner: 'team', name: 'repo', default_branch: 'main' }])
  t.mock.method(gitApi, 'getConnectionBranches', async () => { throw new Error('无分支读取权限') })
  const bind = t.mock.method(api, 'createRepository', async () => ({}))
  const state = mount(t, SettingsModal, reactive({ open: false, project: { id: 'project' } }))
  state().repositoryForm.connection_id = 'connection'
  await settle()
  state().selectedRepositoryId = '7'
  await state().selectRemoteRepository('7')
  assert.equal(state().discoveryError, '无分支读取权限')
  assert.equal(state().canBindRepository, false)
  await state().createRepository()
  assert.equal(bind.mock.callCount(), 0)
})


test('工作树人工操作固定审查快照，切任务后拒绝迟到结果', async (t) => {
  let finish
  const commit = t.mock.method(api, 'commitGitWorktree', async () => ({ head_sha: 'new', tree_sha: 'new-tree', dirty: false }))
  t.mock.method(api, 'reviewGitWorktree', () => new Promise((resolve) => { finish = resolve }))
  const props = reactive({ projectId: 'project', worktree: { id: 'task-one', status: 'ready' } })
  const state = mount(t, WorktreePanel, props)
  state().review = { head_sha: 'head', tree_sha: 'tree', dirty: true }
  state().commitMessage = '人工提交'
  await state().operate('commit')
  assert.deepEqual(commit.mock.calls[0].arguments, ['project', 'task-one', { expected_head: 'head', expected_tree: 'tree', message: '人工提交' }])
  assert.equal(state().review.dirty, false)
  const pending = state().openReview()
  props.worktree = { id: 'task-two', status: 'ready' }
  await settle()
  finish({ head_sha: 'stale', dirty: true })
  await pending
  assert.equal(state().review, null)
  assert.equal(state().open, false)
})

test('审批展示自动规则和执行终态，人工决定只发送当前记录并回读历史', async (t) => {
  const pending = { id: 'pending', repository_id: 'repo', status: 'pending', approval_kind: 'required', approval_reason: '受保护', diff: 'frozen diff' }
  const automatic = { id: 'automatic', repository_id: 'repo', status: 'succeeded', approval_kind: 'automatic', approval_reason: '资源自动授权规则', result: { committed_sha: 'actual-sha' } }
  let history = [pending, automatic]
  t.mock.method(api, 'getGitActions', async () => history)
  const decision = t.mock.method(api, 'decideGitAction', async () => { history = [{ ...pending, status: 'approved', approval_kind: 'human' }, automatic]; return history[0] })
  const state = mount(t, ActivityPanel, reactive({ projectId: 'project', kind: 'history', resources: [{ id: 'repo', alias: '代码' }] }))
  await settle()
  assert.equal(state().rows[1].result.committed_sha, 'actual-sha')
  assert.equal(state().repositoryName('repo'), '代码')
  state().selected = pending
  await state().decide(true)
  assert.deepEqual(decision.mock.calls[0].arguments, ['project', 'pending', true])
  assert.equal(state().selected.status, 'approved')
  assert.equal(state().selected.diff, 'frozen diff')
})

test('占用按当前 owner 和服务端 FIFO 序列展示，运行中的占用保留活动状态', async (t) => {
  t.mock.method(api, 'getGitOccupancies', async () => [
    { id: 'q2', repository_id: 'repo', status: 'queued', queue_position: 2, requested_at: '2026-10-04T02:00:00Z' },
    { id: 'owner', repository_id: 'repo', status: 'owned', active_execution: true, requested_at: '2026-10-04T00:00:00Z' },
    { id: 'q1', repository_id: 'repo', status: 'queued', queue_position: 1, requested_at: '2026-10-04T01:00:00Z' }
  ])
  const state = mount(t, ActivityPanel, reactive({ projectId: 'project', kind: 'occupancies', resources: [] }))
  await settle()
  assert.deepEqual(state().groups[0].rows.map((row) => row.id), ['owner', 'q1', 'q2'])
  assert.equal(state().groups[0].rows[0].active_execution, true)
})

test('旧轮询响应和旧项目响应不能覆盖新历史，失败保留可见错误', async (t) => {
  let resolveOld
  let call = 0
  t.mock.method(api, 'getGitActions', () => ++call === 1 ? new Promise((resolve) => { resolveOld = resolve }) : Promise.resolve([{ id: 'fresh', status: 'succeeded' }]))
  const props = reactive({ projectId: 'old-project', kind: 'history', resources: [] })
  const state = mount(t, ActivityPanel, props)
  await state().load()
  resolveOld([{ id: 'outdated' }])
  await settle()
  assert.equal(state().rows[0].id, 'fresh')
  props.projectId = 'new-project'
  await settle()
  assert.equal(state().selected, null)
  t.mock.method(api, 'getGitActions', async () => { throw new Error('连接失败') })
  await state().load()
  assert.equal(state().error, '连接失败')
  assert.equal(state().loading, false)
})
