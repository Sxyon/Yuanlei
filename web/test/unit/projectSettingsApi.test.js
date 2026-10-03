import assert from 'node:assert/strict'
import test from 'node:test'
import { createServer } from 'vite'
import { createPinia, setActivePinia } from 'pinia'

/** 用真实 API 封装验证设置和弱关联使用独立请求，不附带权限字段。 */
test('项目设置与知识库关联保存保持独立的完整请求', async () => {
  const previousFetch = globalThis.fetch
  const previousStorage = globalThis.localStorage
  globalThis.localStorage = { getItem: () => 'test-token', setItem() {}, removeItem() {} }
  setActivePinia(createPinia())
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  try {
    const requests = []
    globalThis.fetch = async (url, options = {}) => {
      requests.push({ url: String(url), method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null })
      return new Response(JSON.stringify({ project: { id: 'p1', name: '服务端名称' }, knowledge_links: [] }), { status: 200, headers: { 'content-type': 'application/json' } })
    }
    const { projectApi } = await server.ssrLoadModule('/src/apis/project_api.js')
    const values = { name: '项目名称', description: '描述', work_status: 'paused', priority: 'none', owner_type: 'member', owner_id: 'u2', start_date: null, due_date: '2026-10-03' }
    const saved = await projectApi.saveSettings('p1', values)
    assert.equal(saved.project.name, '服务端名称')
    await projectApi.saveKnowledgeLinks('p1', ['kb1'])
    assert.deepEqual(requests, [
      { url: '/api/projects/p1/settings', method: 'PUT', body: values },
      { url: '/api/projects/p1/knowledge-links', method: 'PUT', body: { kb_ids: ['kb1'] } }
    ])
  } finally {
    globalThis.fetch = previousFetch
    globalThis.localStorage = previousStorage
    await server.close()
  }
})
