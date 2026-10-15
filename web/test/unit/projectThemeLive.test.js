import assert from 'node:assert/strict'
import test from 'node:test'
import { createServer } from 'vite'

// 返回状态只验证同账号同项目的捕获值，绝不从返回输入生成自由路由。
test('主题返回只回当前项目，错账号／项目／令牌和损坏记录均拒绝', async () => {
  const { saveThemeReturn, readThemeReturn, themeReturnTarget } = await import('../../src/utils/projectThemeReturn.js')
  const original = globalThis.sessionStorage
  let stored
  globalThis.sessionStorage = { setItem: (_, value) => { stored = value }, getItem: () => stored }
  try {
    const context = { projectId: 'project-a', packageRef: 'version-a', bindingGeneration: 4, pageId: 'read', selectedTopicId: 'topic-a', queries: {}, top: 120 }
    const token = saveThemeReturn('user-a', context)
    assert.deepEqual(readThemeReturn(token, 'user-a', 'project-a'), context)
    assert.deepEqual(themeReturnTarget(token, 'user-a', 'project-a'), { name: 'ProjectThemeDisplay', params: { project_id: 'project-a' }, query: { theme_return: token } })
    for (const args of [[token, 'user-b', 'project-a'], [token, 'user-a', 'project-b'], ['https://external.invalid', 'user-a', 'project-a']]) assert.equal(themeReturnTarget(...args), null)
    stored = 'broken-json'; assert.equal(readThemeReturn(token, 'user-a', 'project-a'), null)
  } finally { globalThis.sessionStorage = original }
})

test('真实适配保留原页状态；读取中改绑定与失权使整上下文失效', async () => {
  const oldStorage = globalThis.localStorage
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  const vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  try {
    const { projectThemeApi, createProjectThemeAdapter } = await vite.ssrLoadModule('/src/apis/project_theme_api.js')
    const { governanceBoardApi } = await vite.ssrLoadModule('/src/apis/governance_board_api.js')
    const originalBinding = projectThemeApi.binding, originalPage = governanceBoardApi.topicsPage
    try {
      let generation = 1
      projectThemeApi.binding = async () => ({ state: 'ready', generation })
      const topic = { id: 'topic-a', project_id: 'project-a', title: '当前', summary: null, expected_outcome: null, admission_status: 'canonical', progress: 'closed' }
      governanceBoardApi.topicsPage = async (_, query) => ({ items: [topic], pagination: { ...query, total: 25 } })
      const adapter = createProjectThemeAdapter('project-a', 1)
      const binding = { kind: 'business', resource: 'topics', scope: 'project' }
      const context = { projectId: 'project-a', bindingGeneration: 1, query: { offset: 20, limit: 20, search: '当前', progress: 'closed' } }
      const result = await adapter.read(binding, context, new AbortController().signal)
      assert.deepEqual(result.value, [topic]); assert.equal(result.pagination.offset, 20); assert.equal(result.pagination.progress, 'closed')
      governanceBoardApi.topicsPage = async () => { generation = 2; return { items: [topic], pagination: { total: 1 } } }
      await assert.rejects(adapter.read(binding, context, new AbortController().signal), error => error.contextInvalid && /选择已变化/.test(error.message))
      projectThemeApi.binding = async () => { throw Object.assign(new Error('无权访问'), { status: 404 }) }
      await assert.rejects(adapter.read(binding, context, new AbortController().signal), error => error.contextInvalid)
      let projectVisible = true
      generation = 1
      projectThemeApi.binding = async () => {
        if (!projectVisible) throw Object.assign(new Error('项目已失权'), { status: 404 })
        return { state: 'ready', generation }
      }
      governanceBoardApi.topicsPage = async () => { projectVisible = false; throw Object.assign(new Error('Project不存在'), { status: 404 }) }
      await assert.rejects(adapter.read(binding, context, new AbortController().signal), error => error.contextInvalid && error.message === '项目已失权')
      generation = 1; projectThemeApi.binding = async () => ({ state: 'ready', generation })
      await assert.rejects(adapter.read(binding, { ...context, projectId: 'project-b' }, new AbortController().signal), error => error.contextInvalid)
    } finally { projectThemeApi.binding = originalBinding; governanceBoardApi.topicsPage = originalPage }
  } finally { await vite.close(); globalThis.localStorage = oldStorage }
})
