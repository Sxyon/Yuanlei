import assert from 'node:assert/strict'
import test from 'node:test'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia } from 'pinia'
import { createServer } from 'vite'

globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
globalThis.document = {
  documentElement: { classList: { add() {}, remove() {} } },
  getElementsByTagName: () => []
}
globalThis.window = { addEventListener() {}, removeEventListener() {} }
const vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
const { default: DefaultProjectDashboard } = await vite.ssrLoadModule(
  '/src/components/project/DefaultProjectDashboard.vue'
)

test.after(async () => {
  await vite.close()
  delete globalThis.localStorage
  delete globalThis.document
  delete globalThis.window
})

async function renderDashboard(board, blueprintContent = '') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { render: () => null } },
      {
        path: '/projects/:project_id/inspection',
        name: 'ProjectInspectionBoardComp',
        component: { render: () => null }
      }
    ]
  })
  await router.push('/')
  await router.isReady()
  const app = createSSRApp(() =>
    h(DefaultProjectDashboard, {
      projectId: 'project-1',
      board,
      blueprints: blueprintContent ? [{ name: 'plan.md' }] : [],
      selectedBlueprint: blueprintContent ? 'plan.md' : '',
      blueprintContent
    })
  )
  app.use(router)
  app.use(createPinia())
  app.component('a-tag', {
    render() {
      return h('span', this.$slots.default?.())
    }
  })
  return renderToString(app)
}

test('默认概览显示项目读视图', async () => {
  const html = await renderDashboard(
    {
      project: { name: '示例项目' },
      governance: {
        pending_topics: [{ id: 't1' }],
        pending_tasks: [],
        topics: [{ id: 't1', title: '范围确认', status: 'proposed' }],
        tasks: [{ id: 'task-1', title: '交付一版', status: 'canonical' }],
        decisions: [{ id: 'd1', title: '确定范围', conclusion: '先完成闭环' }],
        reports: [{ id: 'r1', title: '本周汇报', summary: '进展正常' }]
      },
      execution: { blocked_runs: [], recent_runs: [], run_status_counts: {} }
    }
  )
  for (const text of ['示例项目', '范围确认', '交付一版', '确定范围', '本周汇报'])
    assert.ok(html.includes(text))
})

test('无蓝图和治理记录时显示明确入口与空状态', async () => {
  const html = await renderDashboard({
    project: { name: '空项目' },
    governance: {},
    execution: {}
  })
  assert.match(html, /还没有蓝图内容/)
  assert.match(html, /提出议题、记录决策或创建任务后，关系图会在这里展示。/)
  assert.match(html, /暂无执行记录/)
  assert.match(html, /ProjectInspectionBoardComp|\/inspection/)
})

test('列表超过展示上限时优先显示最新治理记录', async () => {
  const entries = (count, prefix) =>
    Array.from({ length: count }, (_, index) => ({
      id: `${prefix}-${index}`,
      title: `${prefix}-${index}`,
      status: 'canonical',
      conclusion: '已决定',
      summary: '已汇报'
    }))
  const html = await renderDashboard({
    project: { name: '大量记录' },
    governance: {
      topics: entries(12, 'topic'),
      tasks: entries(12, 'task'),
      decisions: entries(12, 'decision'),
      reports: entries(6, 'report')
    },
    execution: { blocked_runs: Array.from({ length: 10 }), recent_runs: [] }
  })
  for (const prefix of ['topic', 'task', 'decision', 'report']) {
    assert.ok(html.includes(`${prefix}-${prefix === 'report' ? 5 : 11}`))
    assert.ok(!html.includes(`${prefix}-0`))
  }
  assert.match(html, /近期阻塞记录/)
})
