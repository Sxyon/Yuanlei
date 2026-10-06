import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, ssrContextKey } from 'vue'
import { createServer } from 'vite'
let vite, Panel, api, workApi
before(async () => {
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: Panel } = await vite.ssrLoadModule(
    '/src/components/project/WorkDelegationsPanel.vue'
  ))
  ;({ governanceBoardApi: api } = await vite.ssrLoadModule('/src/apis/governance_board_api.js'))
  ;({ projectWorkApi: workApi } = await vite.ssrLoadModule('/src/apis/project_work_api.js'))
})
after(async () => {
  await vite?.close()
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
async function mount(t) {
  let instance
  const app = renderer.createApp(
    {
      ...Panel,
      render() {
        instance = getCurrentInstance()
        return h('div')
      }
    },
    {
      projectId: 'project',
      taskId: 'work',
      title: '工作标题',
      description: '执行内容',
      agents: [{ slug: 'agent', config_json: { coding: { executors: ['codex'] } } }]
    }
  )
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()
  return instance.setupState
}
test('编码委派从正式工作发起，失败保留数字员工选择', async (t) => {
  t.mock.method(workApi, 'listDelegations', async () => [
    { operation_id: 'old', work_task_id: null },
    { operation_id: 'own', work_task_id: 'work' }
  ])
  let sent
  t.mock.method(workApi, 'delegateTask', async (...args) => {
    sent = args
    throw new Error('执行器未就绪')
  })
  const state = await mount(t)
  assert.deepEqual(
    state.items.map((i) => i.operation_id),
    ['own']
  )
  state.agentSlug = 'agent'
  state.executor = 'codex'
  await state.dispatch()
  assert.deepEqual(sent, ['project', 'work', { executor_key: 'codex', agent_slug: 'agent' }])
  assert.equal(state.agentSlug, 'agent')
  assert.match(state.error, /未就绪/)
  assert.equal(state.busy, false)
})
test('外部委派与终态回收沿用正式工作归属并回读结果', async (t) => {
  let completed = false,
    sent
  t.mock.method(workApi, 'listDelegations', async () => [
    {
      operation_id: 'own',
      work_task_id: 'work',
      result: completed ? { summary: '最终结果' } : null
    }
  ])
  t.mock.method(api, 'createDelegation', async (...args) => {
    sent = args
  })
  t.mock.method(api, 'collectDelegation', async (_project, id) => {
    assert.equal(id, 'own')
    completed = true
  })
  const state = await mount(t)
  state.executor = 'multica'
  await state.dispatch()
  assert.deepEqual(sent, [
    'project',
    { executor_key: 'multica', work_task_id: 'work', task: '工作标题\n\n执行内容' }
  ])
  await state.collect(state.items[0])
  assert.equal(state.items[0].result.summary, '最终结果')
})
