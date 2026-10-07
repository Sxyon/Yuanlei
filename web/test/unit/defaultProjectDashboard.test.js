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
  for (const name of ['a-button', 'a-spin', 'a-alert', 'a-pagination'])
    app.component(name, {
      render() {
        return h('span', this.$slots.default?.())
      }
    })
  app.component('a-modal', {
    props: ['open'],
    render() {
      return this.open ? h('section', this.$slots.default?.()) : null
    }
  })
  return renderToString(app)
}

test('默认概览显示项目读视图', async () => {
  const html = await renderDashboard({
    project: { name: '示例项目' },
    governance: {
      pending_topics: [{ id: 't1' }],
      pending_tasks: [],
      topics: [{ id: 't1', title: '范围确认', status: 'proposed' }],
      tasks: [{ id: 'suggestion-1', title: '不应冒充工作', status: 'canonical' }],
      decisions: [{ id: 'd1', title: '确定范围', status: 'approved', conclusion: '先完成闭环' }],
      reports: [{ id: 'r1', title: '本周汇报', summary: '进展正常' }]
    },
    graph: {
      work: {
        total: 1,
        items: [
          {
            id: 'work-1',
            title: '交付一版',
            number: 'W-1',
            status: 'todo',
            url: '/projects/project-1/work/tasks/work-1'
          }
        ]
      }
    },
    overview: {
      results: {
        total: 2,
        work_count: 1,
        items: [
          {
            id: 'result-1',
            title: '交付一版',
            summary: '等待验收',
            number: 'W-1',
            criteria_revision: 3,
            url: '/projects/project-1/work/tasks/work-1#work-result-result-1'
          }
        ]
      }
    },
    execution: { blocked_runs: [], recent_runs: [], run_status_counts: {} }
  })
  for (const text of ['示例项目', '范围确认', '交付一版', '确定范围', '本周汇报'])
    assert.ok(html.includes(text))
  assert.match(html, /2 份结果，1 项工作/)
  assert.match(html, /要求修订 3/)
  assert.match(html, /#work-result-result-1/)
  assert.ok(!html.includes('不应冒充工作'))
})

test('无蓝图和治理记录时显示明确入口与空状态', async () => {
  const html = await renderDashboard({
    project: { name: '空项目' },
    governance: {},
    execution: {}
  })
  assert.match(html, /还没有蓝图内容/)
  assert.match(html, /提出议题、记录决策或创建正式工作后，关系图会在这里展示。/)
  assert.match(html, /暂无执行异常记录/)
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
      decisions: entries(12, 'decision'),
      reports: entries(6, 'report')
    },
    graph: {
      work: {
        total: 12,
        items: entries(12, 'work')
          .reverse()
          .slice(0, 10)
          .map((item) => ({ ...item, url: '/projects/project-1/work/tasks/' + item.id }))
      }
    },
    execution: { blocked_runs: Array.from({ length: 10 }), recent_runs: [] }
  })
  for (const prefix of ['topic', 'work', 'decision', 'report']) {
    assert.ok(html.includes(`${prefix}-${prefix === 'report' ? 5 : 11}`), `缺少最新${prefix}`)
    assert.ok(!html.includes(`${prefix}-0`), `意外包含最旧${prefix}`)
  }
  assert.match(html, /历史执行异常/)
  assert.match(html, /正式工作遗漏 2 条/)
})

test('决策关联的归档或超上限议题仍有维护入口，远端异常标明失败', async () => {
  for (const topics of [[], Array.from({ length: 12 }, (_, i) => ({ id: `t-${i}`, title: `议题${i}` }))]) {
    const html = await renderDashboard({ project: { name: '图外关系' }, governance: {
      topics, decisions: [{ id: 'd', title: '有效决策', status: 'approved', topic_id: 't-0' }]
    }, overview: { exceptions: { total: 1, items: [{ id: 'remote', kind: 'delegation', title: '远端执行', status: 'dispatched', remote_status: 'failed', url: '/projects/project-1/work/tasks/work#work-delegation-remote' }] } } })
    assert.match(html, /执行失败/)
    assert.match(html, /本地已派发/)
    if (!topics.length) {
      assert.match(html, /关联议题（可含归档或图外记录）/)
      assert.match(html, /topic_id=t-0/)
    }
  }
})
