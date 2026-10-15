import assert from 'node:assert/strict'
import { after, before, beforeEach, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, reactive, ssrContextKey } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { routeLocationKey, routerKey } from 'vue-router'
import { createServer } from 'vite'
let vite, Files, Topics, Reports, Overview, dashboardApi, filesApi, api, workApi, useUserStore
before(async () => {
  globalThis.window = { addEventListener() {}, removeEventListener() {}, confirm: () => true }
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: Files } = await vite.ssrLoadModule(
    '/src/components/project/capabilities/ProjectFilesWorkspace.vue'
  ))
  ;({ default: Topics } = await vite.ssrLoadModule(
    '/src/components/project/capabilities/TopicWorkspace.vue'
  ))
  ;({ default: Reports } = await vite.ssrLoadModule(
    '/src/components/project/capabilities/ReportWorkspace.vue'
  ))
  ;({ default: Overview } = await vite.ssrLoadModule(
    '/src/components/project/capabilities/OverviewWorkspace.vue'
  ))
  ;({ projectDashboardApi: dashboardApi } = await vite.ssrLoadModule(
    '/src/apis/project_dashboard_api.js'
  ))
  ;({ projectFilesApi: filesApi } = await vite.ssrLoadModule('/src/apis/project_files_api.js'))
  ;({ governanceBoardApi: api } = await vite.ssrLoadModule('/src/apis/governance_board_api.js'))
  ;({ projectWorkApi: workApi } = await vite.ssrLoadModule('/src/apis/project_work_api.js'))
  ;({ useUserStore } = await vite.ssrLoadModule('/src/stores/user.js'))
})
beforeEach(() => {
  setActivePinia(createPinia())
  useUserStore().uid = 'test-owner'
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
const flush = async () => {
  await nextTick()
  await new Promise((resolve) => setImmediate(resolve))
  await nextTick()
}
const settle = async (predicate) => {
  for (let i = 0; i < 50 && !predicate(); i++) await flush()
  assert.ok(predicate(), '工作区状态未收敛')
}
function mount(t, View, route = { query: {}, hash: '' }, router = { push: async () => {} }, accessLost = () => {}) {
  let instance
  const Captured = {
    ...View,
    render() {
      instance = getCurrentInstance()
      return h('div')
    }
  }
  const app = renderer.createApp({ render: () => h(Captured, { projectId: 'project-a' }) })
  app.provide(ssrContextKey, { modules: new Set() })
  app.provide(routeLocationKey, reactive(route))
  app.provide(routerKey, router)
  app.provide('projectAccessLost', accessLost)
  app.mount({})
  t.after(() => app.unmount())
  return () => instance.setupState
}
test('议题子视图失权后，父级迟到刷新不能恢复数据或草稿', async (t) => {
  const rows = [{ id: 'private-topic', title: '私有议题' }]
  t.mock.method(api, 'listTopics', async () => rows)
  t.mock.method(api, 'listDecisions', async () => [{ id: 'private-decision' }])
  t.mock.method(workApi, 'listTasks', async () => [{ id: 'private-work' }])
  const accessLost = t.mock.fn()
  const state = mount(t, Topics, undefined, undefined, accessLost)
  await settle(() => !state().loading)
  state().open('edit')
  state().discussionDrafts = { 'private-topic': { body: '草稿' } }
  state().achievements = { 'private-topic': true }
  let resolveRead
  t.mock.method(api, 'listTopics', () => new Promise(resolve => { resolveRead = resolve }))
  const pending = state().load()
  state().failure({ status: 403 })
  resolveRead(rows)
  await pending
  assert.deepEqual(state().topics, [])
  assert.deepEqual(state().decisions, [])
  assert.deepEqual(state().works, [])
  assert.deepEqual(state().achievements, {})
  assert.deepEqual(state().discussionDrafts, {})
  assert.deepEqual(state().form, {})
  assert.equal(state().selectedId, '')
  assert.equal(state().composer, null)
  assert.equal(state().loading, false)
  assert.equal(state().busy, false)
  assert.equal(accessLost.mock.callCount(), 1)
})
test('议题刷新中的达成读取失权后，不再恢复旧选中身份', async (t) => {
  t.mock.method(api, 'listTopics', async () => [{ id: 'private-topic', title: '私有议题' }])
  t.mock.method(api, 'listDecisions', async () => [])
  t.mock.method(workApi, 'listTasks', async () => [])
  const accessLost = t.mock.fn()
  const state = mount(t, Topics, { query: { topic_id: 'private-topic' }, hash: '' }, undefined, accessLost)
  await settle(() => !state().loading)
  state().progress = 'achieved'
  t.mock.method(api, 'getTopicFollowup', async () => { throw { status: 403 } })
  await state().load()
  assert.deepEqual(state().topics, [])
  assert.equal(state().selectedId, '')
  assert.equal(state().loading, false)
  assert.equal(accessLost.mock.callCount(), 1)
})
test('资料A目录晚于B返回时不覆盖B的文件或错误', async (t) => {
  const pending = []
  t.mock.method(
    filesApi,
    'list',
    (_, folder, search) =>
      new Promise((resolve, reject) => pending.push({ folder, search, resolve, reject }))
  )
  const state = mount(t, Files)
  await settle(() => pending.length === 1)
  state().folder = '/B'
  const second = state().load()
  pending[1].resolve({ entries: [{ path: '/B/result.md', name: 'result.md' }] })
  await second
  pending[0].resolve({ entries: [{ path: '/A/wrong.md', name: 'wrong.md' }] })
  await flush()
  assert.equal(state().entries[0].path, '/B/result.md')
  assert.equal(state().folder, '/B')
  state().search = 'older'
  const older = state().load()
  state().search = 'newer'
  const newer = state().load()
  pending[3].resolve({ entries: [{ path: '/B/newer.md' }] })
  await newer
  pending[2].reject(new Error('旧搜索失败'))
  await older
  assert.equal(state().entries[0].path, '/B/newer.md')
  assert.equal(state().error, '')
})
test('决定补充与替代草稿按准确来源隔离，恢复不会把入口意图改成旧草案', async (t) => {
  t.mock.method(api, 'listTopics', async () => [
    { id: 'topic-a', title: 'A' },
    { id: 'topic-b', title: 'B' }
  ])
  t.mock.method(api, 'listDecisions', async () => [])
  t.mock.method(workApi, 'listTasks', async () => [])
  const state = mount(t, Topics)
  await settle(() => state().selectedId === 'topic-a')
  state().open('decision')
  state().form.title = '议题A普通草稿'
  await flush()
  state().selectedId = 'topic-b'
  state().open('decision', { id: 'decision-b', topic_id: 'topic-b' }, 'replacement')
  assert.equal(state().form.topic_id, 'topic-b')
  assert.equal(state().form.relation_type, 'replacement')
  assert.equal(state().form.target_decision_id, 'decision-b')
  assert.equal(state().form.title, '')
  state().form.title = 'B替代草稿'
  await flush()
  state().open('decision', { id: 'decision-b', topic_id: 'topic-b' }, 'supplement')
  assert.equal(state().form.title, '')
  assert.equal(state().form.relation_type, 'supplement')
  state().selectedId = 'topic-a'
  state().open('decision')
  assert.equal(state().form.title, '议题A普通草稿')
})
test('督查读取第六条及后续分页工作，汇报保留原结构与来源', async (t) => {
  const report = {
    id: 'report-a',
    title: '报告',
    content: { finding: '核查结论' },
    source_run_id: 'run-a',
    artifact_path: '/reports/review.md'
  }
  t.mock.method(api, 'getProjectBoard', async () => ({
    overview: { work: { items: [] } },
    governance: { reports: [report] }
  }))
  t.mock.method(api, 'getOverviewPage', async (_, section, offset) => ({
    total: section === 'work' ? 101 : 0,
    items:
      section === 'work'
        ? offset === 0
          ? Array.from({ length: 100 }, (_, i) => ({
              id: 'work-' + i,
              status: i === 5 ? 'blocked' : 'todo'
            }))
          : [{ id: 'last-work', status: 'blocked' }]
        : []
  }))
  const state = mount(t, Reports)
  await settle(() => !state().loading)
  assert.deepEqual(
    state().interventions.map((item) => item.id),
    ['work-5', 'last-work']
  )
  assert.deepEqual(state().board.governance.reports, [report])
})

test('督查成功后失权会清空原投影和介入记录', async (t) => {
  let denied = false
  t.mock.method(api, 'getProjectBoard', async () => {
    if (denied) throw Object.assign(new Error('失权'), { status: 403 })
    return {
      governance: { reports: [{ id: 'private-report' }] },
      execution: { blocked_runs: [{ id: 'private-run' }] }
    }
  })
  t.mock.method(api, 'getOverviewPage', async () => ({ total: 0, items: [] }))
  const state = mount(t, Reports)
  await settle(() => !state().loading)
  assert.equal(state().board.governance.reports[0].id, 'private-report')
  denied = true
  await state().load()
  assert.deepEqual(state().board, {})
  assert.deepEqual(state().historical, [])
  assert.deepEqual(state().interventions, [])
})

test('决定单独深链按真实来源选择议题，无来源决定不伪造议题身份', async (t) => {
  t.mock.method(api, 'listTopics', async () => [
    { id: 'topic-a', title: 'A' },
    { id: 'topic-b', title: 'B' }
  ])
  t.mock.method(api, 'listDecisions', async () => [
    { id: 'decision-b', topic_id: 'topic-b' },
    { id: 'independent', topic_id: null }
  ])
  t.mock.method(workApi, 'listTasks', async () => [])
  const route = reactive({ query: { decision_id: 'decision-b' }, hash: '' })
  const state = mount(t, Topics, route)
  await settle(() => state().selectedId === 'topic-b')
  route.query = { decision_id: 'independent' }
  await flush()
  assert.notEqual(state().selectedId, 'independent')
  assert.equal(state().decisions.find((item) => item.id === 'independent').topic_id, null)
})

test('总览更多弹窗拒绝迟到的其他分组及旧分页，业务大屏失权清全部投影', async (t) => {
  t.mock.method(api, 'getProjectBoard', async () => ({ project: { id: 'project-a' } }))
  t.mock.method(api, 'listBlueprints', async () => ({ documents: [] }))
  t.mock.method(api, 'listTopics', async () => [])
  t.mock.method(api, 'recentActivity', async () => ({ items: [] }))
  const state = mount(t, Overview)
  await settle(() => !state().loading)
  const pending = []
  t.mock.method(
    api,
    'getOverviewPage',
    (_, group, offset) => new Promise((resolve) => pending.push({ group, offset, resolve }))
  )
  const old = state().openMore({ key: 'pending', title: '待处理' })
  const newer = state().openMore({ key: 'results', title: '待验收' })
  pending[1].resolve({ items: [{ id: 'accurate-result' }], offset: 0 })
  await newer
  pending[0].resolve({ items: [{ id: 'wrong-pending' }], offset: 0 })
  await old
  assert.equal(state().more.key, 'results')
  assert.equal(state().moreRows.items[0].id, 'accurate-result')
  const firstPage = state().openMore({ key: 'results', title: '待验收' }, 0)
  const secondPage = state().openMore({ key: 'results', title: '待验收' }, 20)
  pending[3].resolve({ items: [{ id: 'page-two' }], offset: 20 })
  await secondPage
  pending[2].resolve({ items: [{ id: 'page-one' }], offset: 0 })
  await firstPage
  assert.equal(state().moreRows.offset, 20)
  t.mock.method(dashboardApi, 'getDashboard', async () => {
    throw Object.assign(new Error('失权'), { status: 403 })
  })
  await state().readBusiness()
  assert.deepEqual(state().board, {})
  assert.equal(state().more, null)
  assert.equal(state().business, null)
})

test('议题目录达成筛选只认原实际确认，拒绝用已决定或旧条件确认代替', async (t) => {
  t.mock.method(api, 'listTopics', async () => [
    { id: 'confirmed', title: '已确认', progress: 'open', expected_outcome: '目标', verification_conditions: '条件' },
    { id: 'decided', title: '已决定', progress: 'decided' },
    { id: 'withdrawn', title: '已撤回', progress: 'open' },
    { id: 'changed', title: '条件已改', progress: 'open', verification_conditions: '新条件' }
  ])
  t.mock.method(api, 'listDecisions', async () => [])
  t.mock.method(workApi, 'listTasks', async () => [])
  t.mock.method(api, 'getTopicFollowup', async (_, id) => ({ confirmations: {
    confirmed: [{ action: 'confirm', expected_outcome: '目标', verification_conditions: '条件' }],
    decided: [], withdrawn: [{ action: 'withdraw' }],
    changed: [{ action: 'confirm', verification_conditions: '旧条件' }]
  }[id] }))
  const state = mount(t, Topics)
  await settle(() => state().topics.length === 4)
  assert.equal(state().detailVisible, false)
  await state().setProgress('achieved')
  assert.deepEqual(state().filtered.map(item => item.id), ['confirmed'])
  await state().setProgress('all')
  assert.equal(state().filtered.length, 4)
})

test('决定内部选择清除旧议题与评论，外部冲突入口明确保留警告', async t => {
  t.mock.method(api, 'listTopics', async () => [{ id: 'a', title: 'A' }, { id: 'b', title: 'B' }])
  t.mock.method(api, 'listDecisions', async () => [{ id: 'db', topic_id: 'b' }])
  t.mock.method(workApi, 'listTasks', async () => [])
  let target
  const state = mount(t, Topics, { query: { topic_id: 'a', decision_id: 'db', comment_id: 'old' } }, { push: async value => { target = value } })
  await settle(() => state().decisions.length === 1)
  assert.equal(state().conflictingSource, true)
  await state().selectDecision('db')
  assert.equal(target.query.topic_id, undefined)
  assert.equal(target.query.comment_id, undefined)
  assert.equal(target.query.decision_id, 'db')
})

test('决定索引按真实议题关联筛选，切换范围不改变原决定或定位',async t=>{
  t.mock.method(api,'listTopics',async()=>[])
  t.mock.method(api,'listDecisions',async()=>[{id:'linked',topic_id:'topic'},{id:'independent',topic_id:null}])
  t.mock.method(workApi,'listTasks',async()=>[])
  const state=mount(t,Topics,{query:{decision_id:'independent'},hash:''})
  await settle(()=>!state().loading)
  assert.equal(state().unlinkedDecisionCount,1)
  assert.deepEqual(state().indexedDecisions.map(row=>row.id),['linked','independent'])
  state().decisionScope='unlinked';await flush()
  assert.deepEqual(state().indexedDecisions.map(row=>row.id),['independent'])
  assert.equal(state().decisions.length,2)
})
