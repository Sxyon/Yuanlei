import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { createPinia, setActivePinia } from 'pinia'
import { createServer } from 'vite'

import {
  describeBoardError,
  governanceStatusLabel,
  runStatusEntries,
  runStatusLabel,
  sourceChannelLabel
} from '../../src/utils/governanceBoard.js'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

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

test('runStatusEntries 仅展示非零计数并按数量倒序', () => {
  assert.deepEqual(runStatusEntries({ running: 2, failed: 3, completed: 0 }), [
    { status: 'failed', label: '失败', count: 3 },
    { status: 'running', label: '运行中', count: 2 }
  ])
  assert.deepEqual(runStatusEntries(null), [])
  assert.deepEqual(runStatusEntries({}), [])
  assert.deepEqual(runStatusEntries({ mystery: 1 }), [
    { status: 'mystery', label: 'mystery', count: 1 }
  ])
})

test('状态与来源文案对未知值回退为原始值', () => {
  assert.equal(runStatusLabel('running'), '运行中')
  assert.equal(governanceStatusLabel('proposed'), '待审核')
  assert.equal(governanceStatusLabel('implemented'), '已实施')
  assert.equal(sourceChannelLabel('github'), 'GitHub')
  assert.equal(runStatusLabel('mystery'), 'mystery')
  assert.equal(governanceStatusLabel('mystery'), 'mystery')
  assert.equal(sourceChannelLabel('mystery'), 'mystery')
})

test('describeBoardError 提取后端可展示文案并回退', () => {
  assert.equal(
    describeBoardError({ response: { data: { detail: 'Project 不存在' } } }),
    'Project 不存在'
  )
  assert.equal(
    describeBoardError({ response: { data: { detail: { message: '参数错误' } } } }),
    '参数错误'
  )
  assert.equal(describeBoardError(new Error('网络错误')), '网络错误')
  assert.equal(describeBoardError({}), '督查板加载失败')
})

test('督查板视图消费只读 board 端点，不写任何治理或 Run 状态', async () => {
  await withServer(async (server) => {
    storageValues.set('user_token', 'test-token')
    setActivePinia(createPinia())
    const requests = []
    globalThis.fetch = async (url, options = {}) => {
      requests.push({ url: String(url), method: options.method || 'GET' })
      return new Response(JSON.stringify({ projects: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' }
      })
    }

    const { governanceBoardApi } = await server.ssrLoadModule('/src/apis/governance_board_api.js')

    await governanceBoardApi.getCrossProjectBoard()
    await governanceBoardApi.getProjectBoard('project-1')

    assert.deepEqual(
      requests.map((request) => [request.method, request.url]),
      [
        ['GET', '/api/governance/board'],
        ['GET', '/api/projects/project-1/governance/board']
      ]
    )
  })
})

test('展示面只消费读视图给出的 pending/blocked 字段，前端不自行筛选状态', () => {
  const panelSource = readSource('../../src/components/inspection/GovernanceBoardPanel.vue')
  const crossViewSource = readSource('../../src/views/InspectionBoardView.vue')
  const projectViewSource = readSource('../../src/views/ProjectInspectionBoardView.vue')
  const routerSource = readSource('../../src/router/index.js')
  const layoutSource = readSource('../../src/layouts/AppLayout.vue')

  assert.match(panelSource, /pending_topics/)
  assert.match(panelSource, /pending_tasks/)
  assert.match(panelSource, /pending_decisions/)
  assert.match(panelSource, /blocked_runs/)
  assert.equal(panelSource.includes("=== 'proposed'"), false)
  assert.equal(panelSource.includes("=== 'failed'"), false)
  assert.equal(panelSource.includes("=== 'interrupted'"), false)

  assert.match(crossViewSource, /governanceBoardApi\.getCrossProjectBoard\(\)/)
  assert.match(projectViewSource, /governanceBoardApi\.getProjectBoard\(projectId\.value\)/)

  assert.match(routerSource, /name: 'InspectionBoardComp'/)
  assert.match(routerSource, /name: 'ProjectInspectionBoardComp'/)
  assert.match(routerSource, /path: '\/projects\/:project_id\/inspection'/)
  assert.match(layoutSource, /name: '督查板'/)
  assert.match(layoutSource, /path: '\/inspection'/)
})
