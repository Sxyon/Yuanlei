import assert from 'node:assert/strict'
import { before, after, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, ssrContextKey } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createServer } from 'vite'
let vite, Dashboard, Graph, api
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: Dashboard } = await vite.ssrLoadModule(
    '/src/components/project/DefaultProjectDashboard.vue'
  ))
  ;({ default: Graph } = await vite.ssrLoadModule(
    '/src/components/project/ProjectGovernanceGraph.vue'
  ))
  ;({ governanceBoardApi: api } = await vite.ssrLoadModule('/src/apis/governance_board_api.js'))
})
after(async () => {
  await vite?.close()
  delete globalThis.localStorage
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
const settle = async () => {
  await nextTick()
  await new Promise((resolve) => setImmediate(resolve))
}
async function mount(Component, props, t) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { render: () => null } },
      {
        path: '/projects/:project_id/inspection',
        name: 'ProjectInspectionBoardComp',
        component: { render: () => null }
      },
      { path: '/projects/:project_id/work/tasks/:task_id', component: { render: () => null } }
    ]
  })
  await router.push('/')
  await router.isReady()
  let instance
  const Observed = {
    ...Component,
    render() {
      instance = getCurrentInstance()
      return h('div')
    }
  }
  const app = renderer.createApp({ render: () => h(Observed, { ...props }) })
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()
  return { state: instance.setupState, router }
}
test('分页错误可重试，关闭和切换项目后迟到列表不能覆盖', async (t) => {
  const pending = []
  t.mock.method(
    api,
    'getOverviewPage',
    (project, section, offset) =>
      new Promise((resolve, reject) => pending.push({ project, section, offset, resolve, reject }))
  )
  const props = (await import('vue')).reactive({ projectId: 'p', board: {} })
  const { state } = await mount(Dashboard, props, t)
  assert.match(
    state.detailLabel({ status: 'dispatched', remote_status: 'failed' }),
    /执行失败.*本地已派发/
  )
  state.openList('results', '待验收')
  await settle()
  assert.equal(pending[0].section, 'results')
  assert.equal(pending[0].offset, 0)
  pending[0].reject(new Error('读取失败'))
  await settle()
  assert.equal(state.listError, '读取失败')
  state.loadList(20)
  await settle()
  pending[1].resolve({ total: 23, items: [{ id: 'new' }] })
  await settle()
  assert.equal(state.listOffset, 20)
  assert.equal(state.listPage.total, 23)
  state.loadList(0)
  await settle()
  state.closeList()
  pending[2].resolve({ total: 100, items: [{ id: 'late' }] })
  await settle()
  assert.equal(state.listPage.total, 23)
  state.openList('work', '工作')
  await settle()
  props.projectId = 'other'
  await settle()
  pending[3].resolve({ total: 99, items: [{ id: 'old-project' }] })
  await settle()
  assert.equal(state.listOpen, false)
  assert.equal(state.listPage.total, 23)
})
test('图只画当前正式工作来源，冻结旧来源及图外节点保留定位', async (t) => {
  const { state, router } = await mount(
    Graph,
    {
      projectId: 'p',
      governance: {
        topics: [
          { id: 'current', title: '当前议题' },
          { id: 'old', title: '历史议题' }
        ],
        tasks: [{ id: 'suggestion', topic_id: 'old', title: '建议' }],
        decisions: [{ id: 'old-decision', title: '旧依据', status: 'superseded', topic_id: 'outside-topic' }]
      },
      graph: {
        work: {
          total: 12,
          items: [
            {
              id: 'work',
              title: '正式工作',
              topic_id: 'current',
              source_decision_id: 'outside',
              source_decision_revision: 2,
              url: '/projects/p/work/tasks/work'
            },
            { id: 'independent', title: '独立工作', url: '/projects/p/work/tasks/independent' }
          ]
        },
        results: {
          total: 1,
          items: [
            {
              id: 'result',
              task_id: 'work',
              summary: '结果摘要',
              title: '工作标题',
              frozen_decision_id: 'old-decision',
              frozen_decision_revision: 1,
              url: '/projects/p/work/tasks/work#work-result-result',
              history_url: '/projects/p/work/tasks/work#work-execution-old'
            }
          ]
        },
        feedback: [{ id: 'feedback', result_id: 'result', topic_id: 'old', topic_revision: 2 }]
      }
    },
    t
  )
  assert.equal(
    state.nodes.some((node) => node.item.id === 'suggestion'),
    false
  )
  assert.ok(state.edges.some((edge) => edge.from === 'topic:current' && edge.to === 'work:work'))
  assert.ok(
    !state.edges.some((edge) => edge.from === 'decision:old-decision' && edge.to === 'work:work')
  )
  assert.ok(!state.edges.some((edge) => edge.from === 'decision:outside'))
  assert.ok(state.edges.some((edge) => edge.from === 'result:result' && edge.label === '反馈'))
  assert.ok(state.omittedSummary.includes('正式工作遗漏 10 条'))
  state.selectedKey = 'decision:old-decision'
  await settle()
  assert.equal(state.recordLink({ topic_id: state.selectedNode.item.topic_id }).query.topic_id, 'outside-topic')
  state.selectedKey = 'result:result'
  await settle()
  assert.equal(state.nodeTitle(state.selectedNode), '结果摘要')
  assert.equal(state.selectedNode.item.frozen_decision_revision, 1)
  state.openSelectedInWorkbench()
  await settle()
  assert.equal(router.currentRoute.value.hash, '#work-result-result')
})
