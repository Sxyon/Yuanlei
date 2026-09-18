import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { createPinia, setActivePinia } from 'pinia'
import { createServer } from 'vite'

const storageValues = new Map()
globalThis.localStorage = {
  getItem: (key) => storageValues.get(key) ?? null,
  setItem: (key, value) => storageValues.set(key, String(value)),
  removeItem: (key) => storageValues.delete(key),
  clear: () => storageValues.clear()
}

async function withServer(run) {
  const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
  try {
    await run(server)
  } finally {
    await server.close()
  }
}

test('智能体列表与详情请求携带项目上下文', async () => {
  await withServer(async (server) => {
    storageValues.set('user_token', 'test-token')
    setActivePinia(createPinia())
    const requests = []
    globalThis.fetch = async (url, options = {}) => {
      requests.push({ url: String(url), method: options.method || 'GET' })
      return new Response(JSON.stringify({ agents: [], agent: { id: 'agent-a' } }), {
        status: 200,
        headers: { 'content-type': 'application/json' }
      })
    }

    const { agentApi } = await server.ssrLoadModule('/src/apis/agent_api.js')

    await agentApi.getAgents({ projectId: 'project-1' })
    await agentApi.getAgentDetail('agent-a', { projectId: 'project-1' })
    await agentApi.getAgents()
    await agentApi.getAgentDetail('agent-a')

    assert.deepEqual(
      requests.map((request) => request.url),
      [
        '/api/agent?project_id=project-1',
        '/api/agent/agent-a?project_id=project-1',
        '/api/agent',
        '/api/agent/agent-a'
      ]
    )
  })
})

test('项目覆盖更新提交变更字段与恢复字段', async () => {
  await withServer(async (server) => {
    storageValues.set('user_token', 'test-token')
    setActivePinia(createPinia())
    const requests = []
    globalThis.fetch = async (url, options = {}) => {
      requests.push({ url: String(url), method: options.method || 'GET', body: options.body })
      return new Response(JSON.stringify({ agent: { id: 'agent-a' } }), {
        status: 200,
        headers: { 'content-type': 'application/json' }
      })
    }

    const { projectAgentApi } = await server.ssrLoadModule('/src/apis/project_agent_api.js')

    await projectAgentApi.updateOverrides(
      'project-1',
      'agent-a',
      { context: { system_prompt: '项目人格' } },
      ['model']
    )

    assert.equal(requests.length, 1)
    assert.equal(requests[0].method, 'PUT')
    assert.equal(requests[0].url, '/api/projects/project-1/agents/agent-a')
    assert.deepEqual(JSON.parse(requests[0].body), {
      config_json: { context: { system_prompt: '项目人格' } },
      reset_fields: ['model']
    })
  })
})

test('项目智能体弹窗正确接线表单事件', () => {
  const panelSource = readFileSync(
    new URL('../../src/components/model-management/ProjectAgentManagePanel.vue', import.meta.url),
    'utf8'
  )
  const formSource = readFileSync(
    new URL('../../src/components/model-management/ProjectAgentConfigForm.vue', import.meta.url),
    'utf8'
  )
  const createSource = readFileSync(
    new URL('../../src/components/model-management/ProjectAgentCreateModal.vue', import.meta.url),
    'utf8'
  )
  const editSource = readFileSync(
    new URL('../../src/components/model-management/ProjectAgentEditModal.vue', import.meta.url),
    'utf8'
  )

  assert.match(formSource, /emit\('update:values'/)
  assert.match(panelSource, /<ProjectAgentCreateModal/)
  assert.match(panelSource, /<ProjectAgentEditModal/)
  assert.match(createSource, /@update:values/)
  assert.match(editSource, /@update:values="handleValuesUpdate"/)
})

test('视图层为项目智能体提供项目徽标', () => {
  const agentViewSource = readFileSync(
    new URL('../../src/views/AgentView.vue', import.meta.url),
    'utf8'
  )
  const agentStoreSource = readFileSync(new URL('../../src/stores/agent.js', import.meta.url), 'utf8')

  assert.match(agentViewSource, /agent\.isProjectAgent/)
  assert.match(agentStoreSource, /projectId/)
})

test('复制草稿填充配置但不触发创建，且不覆盖已输入名称', async () => {
  await withServer(async (server) => {
    const { buildCopiedProjectAgentDraft, DEFAULT_PROJECT_AGENT_NAME } = await server.ssrLoadModule(
      '/src/utils/projectAgentCopy.js'
    )
    const source = {
      name: '网页检索',
      backend_id: 'SubAgentBackend',
      description: '检索描述',
      icon: 'icon-url',
      context: { system_prompt: '项目人格', tools: [] }
    }

    const draft = buildCopiedProjectAgentDraft(source, {
      name: DEFAULT_PROJECT_AGENT_NAME,
      backend_id: 'ChatbotAgent'
    })

    assert.equal(draft.name, '网页检索 副本')
    assert.equal(draft.backend_id, 'SubAgentBackend')
    assert.equal(draft.description, '检索描述')
    assert.equal(draft.icon, 'icon-url')
    assert.deepEqual(draft.configValues, { system_prompt: '项目人格', tools: [] })

    const typed = buildCopiedProjectAgentDraft(source, {
      name: '我的项目助手',
      backend_id: 'ChatbotAgent'
    })
    assert.equal(typed.name, '我的项目助手')

    typed.configValues.system_prompt = 'changed'
    assert.equal(source.context.system_prompt, '项目人格')
  })
})

test('按项目拉取智能体后选中详情使用项目有效配置', async () => {
  await withServer(async (server) => {
    storageValues.set('user_token', 'test-token')
    globalThis.fetch = async () =>
      new Response(JSON.stringify({ agents: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' }
      })
    setActivePinia(createPinia())

    const { useAgentStore } = await server.ssrLoadModule('/src/stores/agent.js')
    const { agentApi } = await server.ssrLoadModule('/src/apis/index.js')
    const store = useAgentStore()

    const fetchedProjects = []
    agentApi.getAgentDetail = async (agentId, { projectId } = {}) => {
      fetchedProjects.push(projectId)
      return {
        agent: {
          id: agentId,
          slug: agentId,
          config_json: { context: {} },
          effective_context: { system_prompt: '项目人格', tools: [] },
          configurable_items: { system_prompt: { type: 'str', kind: 'prompt' } }
        }
      }
    }

    await store.selectAgent('agent-a', { projectId: 'project-1' })

    assert.deepEqual(fetchedProjects, ['project-1'])
    assert.equal(store.agentConfig.system_prompt, '项目人格')
    assert.equal(store.selectedAgentId, 'agent-a')

    await store.selectAgent('agent-a', { projectId: 'project-1' })
    assert.deepEqual(fetchedProjects, ['project-1'])
  })
})
