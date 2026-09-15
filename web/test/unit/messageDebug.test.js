import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  bindMessageRequestRun,
  buildMessageDebugTraceSpans,
  buildMessageDebugEntries,
  constrainMessageDebugInspectorHeight,
  constrainMessageDebugInspectorWidth,
  extractMessageToolNames,
  formatAuditDuration,
  formatMessageDebugContent,
  getMessageRequestId,
  getMessageRunId,
  groupMessageDebugEntries,
  getMessageDebugEntryTimeRange,
  isMessageDebugEntryInTimeRange,
  isMessageDebugTimelineMarkSelected,
  mergeMessageDebugAudits,
  mergeMessageDebugMessages,
  mergeMessageDebugRunGroups,
  resolveLangfuseRunUrl
} from '../../src/utils/messageDebug.js'

test('时间概览只高亮当前选中记录，选中 Run 时高亮其全部时间条', () => {
  assert.equal(isMessageDebugTimelineMarkSelected('run:run-a-0', 'run-a-0'), true)
  assert.equal(isMessageDebugTimelineMarkSelected('run:run-a-0', 'run-a-0', 'model-a'), true)
  assert.equal(isMessageDebugTimelineMarkSelected('run:run-a-0', 'run-b-1', 'model-b'), false)

  assert.equal(isMessageDebugTimelineMarkSelected('item:run-a-0:model-a', 'run-a-0'), false)
  assert.equal(
    isMessageDebugTimelineMarkSelected('item:run-a-0:model-a', 'run-a-0', 'model-a'),
    true
  )
  assert.equal(
    isMessageDebugTimelineMarkSelected('item:run-a-0:model-a', 'run-a-0', 'tool-a'),
    false
  )
  assert.equal(isMessageDebugTimelineMarkSelected('', 'run-a-0', 'model-a'), false)
})

test('调试概览忠实显示字符串和结构化消息正文', () => {
  assert.equal(formatMessageDebugContent('第一行\n第二行'), '第一行\n第二行')
  assert.equal(
    formatMessageDebugContent([{ type: 'text', text: '内容' }]),
    '[\n  {\n    "type": "text",\n    "text": "内容"\n  }\n]'
  )
  assert.equal(formatMessageDebugContent(null), '')
})

test('详情面板拖动保留记录区并约束异常高度', () => {
  assert.equal(constrainMessageDebugInspectorHeight(600, 260), 260)
  assert.equal(constrainMessageDebugInspectorHeight(600, -50), 180)
  assert.equal(constrainMessageDebugInspectorHeight(600, 900), 476)
  assert.equal(constrainMessageDebugInspectorHeight(200, 180), 76)
  assert.equal(constrainMessageDebugInspectorHeight(0, 100), null)
})

test('宽屏详情面板拖动保留记录区并约束异常宽度', () => {
  assert.equal(constrainMessageDebugInspectorWidth(1200, 504), 504)
  assert.equal(constrainMessageDebugInspectorWidth(1200, -50), 260)
  assert.equal(constrainMessageDebugInspectorWidth(1200, 900), 896)
  assert.equal(constrainMessageDebugInspectorWidth(700, 500), 396)
  assert.equal(constrainMessageDebugInspectorWidth(600, 252), 260)
  assert.equal(constrainMessageDebugInspectorWidth(0, 100), null)
})

test('消息身份按 metadata 优先，并显式控制 human id fallback', () => {
  const message = {
    id: 'human-1',
    type: 'human',
    request_id: 'request-direct',
    run_id: 'run-direct',
    extra_metadata: {
      request_id: 'request-meta',
      run_id: 'run-meta'
    }
  }

  assert.equal(getMessageRequestId(message), 'request-meta')
  assert.equal(getMessageRunId(message), 'run-meta')
  assert.equal(getMessageRequestId({ id: 'human-2', type: 'human' }), null)
  assert.equal(
    getMessageRequestId({ id: 'human-2', type: 'human' }, { allowMessageIdFallback: true }),
    'human-2'
  )
})

test('消息调试条目保持后端数组顺序并保留独立工具消息', () => {
  const history = [
    { id: 1, type: 'human', content: '请查询' },
    {
      id: 2,
      type: 'ai',
      content: '开始查询',
      tool_calls: [{ name: 'search_kb' }, { function: { name: 'read_file' } }]
    },
    { id: 3, type: 'tool', name: 'search_kb', content: '查询结果' },
    { id: 4, type: 'system', content: '系统提示' }
  ]

  const entries = buildMessageDebugEntries(history)

  assert.deepEqual(
    entries.map((entry) => entry.id),
    ['1', '2', '3', '4']
  )
  assert.deepEqual(
    entries.map((entry) => entry.role),
    ['human', 'ai', 'tool', 'system']
  )
  assert.equal(entries[1].summary, '开始查询 | 工具: search_kb、read_file')
  assert.equal(entries[2].summary, '工具: search_kb | 查询结果')
})

test('消息调试按连续 Run 分组且不猜测无 run_id 消息的归属', () => {
  const entries = buildMessageDebugEntries([
    { id: 'user-a', type: 'human', run_id: 'run-a', content: '问题 A' },
    { id: 'ai-a', type: 'ai', extra_metadata: { run_id: 'run-a' }, content: '回答 A' },
    { id: 'system', type: 'system', content: '未关联消息' },
    { id: 'user-b', type: 'human', run_id: 'run-b', content: '问题 B' }
  ])

  const groups = groupMessageDebugEntries(entries)

  assert.deepEqual(
    groups.map((group) => group.runId),
    ['run-a', null, 'run-b']
  )
  assert.deepEqual(
    groups.map((group) => group.items.map((entry) => entry.id)),
    [['user-a', 'ai-a'], ['system'], ['user-b']]
  )
})

test('AgentRun 投影为零消息取消 Run 补齐可检查分组', () => {
  const entries = buildMessageDebugEntries([
    { id: 'user-a', type: 'human', run_id: 'run-a', content: '问题 A' }
  ])
  const groups = mergeMessageDebugRunGroups(entries, [
    { run_id: 'run-a', status: 'completed' },
    { run_id: 'run-cancelled', status: 'cancelled' },
    { run_id: 'run-cancelled', status: 'cancelled' }
  ])

  assert.deepEqual(
    groups.map((group) => ({ runId: group.runId, items: group.items.length })),
    [
      { runId: 'run-a', items: 1 },
      { runId: 'run-cancelled', items: 0 }
    ]
  )
})

test('AgentRun 投影补组时不重排未关联或重复 Run 的事实顺序', () => {
  const entries = buildMessageDebugEntries([
    { id: 'run-a-first', type: 'human', run_id: 'run-a', content: '问题 A' },
    { id: 'unassigned', type: 'system', content: '未关联事实' },
    { id: 'run-a-second', type: 'ai', run_id: 'run-a', content: '回答 A' },
    { id: 'run-b', type: 'human', run_id: 'run-b', content: '问题 B' }
  ])
  const groups = mergeMessageDebugRunGroups(entries, [
    { run_id: 'run-a', status: 'completed' },
    { run_id: 'run-missing', status: 'cancelled' },
    { run_id: 'run-b', status: 'completed' }
  ])

  assert.deepEqual(
    groups.map((group) => ({ runId: group.runId, ids: group.items.map((item) => item.id) })),
    [
      { runId: 'run-a', ids: ['run-a-first'] },
      { runId: null, ids: ['unassigned'] },
      { runId: 'run-a', ids: ['run-a-second'] },
      { runId: 'run-missing', ids: [] },
      { runId: 'run-b', ids: ['run-b'] }
    ]
  )
})

test('模型调试条目只保留模型自身时间，Run 由独立列表分组', () => {
  const [entry] = buildMessageDebugEntries([
    {
      id: 'ai-a', type: 'ai', run_id: 'run-a',
      started_at: '2026-09-05T00:00:01Z', duration_ms: 800
    }
  ])
  assert.equal(entry.durationMs, 800)
  assert.equal('runTiming' in entry, false)
  assert.equal(entry.runId, 'run-a')
})

test('Langfuse Run 地址仅接受后端确认的 HTTP(S) URL', () => {
  assert.equal(
    resolveLangfuseRunUrl({
      available: true,
      url: 'https://langfuse.example/project/project-1/traces/trace-1'
    }),
    'https://langfuse.example/project/project-1/traces/trace-1'
  )
  assert.equal(resolveLangfuseRunUrl({ available: true, url: 'javascript:alert(1)' }), null)
  assert.equal(
    resolveLangfuseRunUrl({ available: false, url: 'https://langfuse.example/trace-1' }),
    null
  )
})

test('Run 详情保留按稳定 run_id 打开 Langfuse Trace 的入口', () => {
  const source = readFileSync(
    new URL('../../src/components/MessageDebugPanel.vue', import.meta.url),
    'utf8'
  )

  assert.match(source, /打开 Langfuse Trace/)
  assert.match(source, /openRunInLangfuse\(selectedTarget\.group\.runId\)/)
  assert.match(source, /agentApi\.getAgentRunLangfuseLink\(runId\)/)
  assert.match(source, /resolveLangfuseRunUrl\(result\)/)
})

test('Run 行只读取审计接口返回的 AgentRun 状态而不从消息终态猜测', () => {
  const source = readFileSync(
    new URL('../../src/components/MessageDebugPanel.vue', import.meta.url),
    'utf8'
  )

  assert.match(source, /runTraces\.value = Array\.isArray\(result\?\.runs\)/)
  const persistedStatusRead = source.indexOf(
    'if (group.runTrace?.status) return group.runTrace.status'
  )
  const liveFallbackRead = source.indexOf('if (props.runActive && props.activeRunId')
  assert.ok(persistedStatusRead >= 0)
  assert.ok(liveFallbackRead > persistedStatusRead)
  assert.doesNotMatch(source, /terminalModel/)
})

test('没有稳定身份时不按 AI 位置替换实时投影', () => {
  const history = [
    { id: 'user-1', type: 'human', request_id: 'request-1' },
    { id: 'ai-db', type: 'ai', run_id: 'run-1', content: '中间投影' },
    { id: 'tool-1', type: 'tool', run_id: 'run-1', content: '工具结果' }
  ]
  const ongoing = [{ id: 'ai-live', type: 'ai', run_id: 'run-1', content: '流式投影' }]

  const merged = mergeMessageDebugMessages(history, ongoing)

  assert.deepEqual(
    merged.map((message) => message.id),
    ['user-1', 'ai-db', 'tool-1', 'ai-live']
  )
})

test('active run 没有流式 AI 时保留持久化 AI', () => {
  const history = [
    { id: 'user-1', type: 'human' },
    { id: 'ai-db', type: 'ai', run_id: 'run-1', content: '持久化内容' }
  ]

  const merged = mergeMessageDebugMessages(history, [])

  assert.deepEqual(
    merged.map((message) => message.id),
    ['user-1', 'ai-db']
  )
})

test('同 request_id 的实时 User 将 Run 关联补入旧持久快照', () => {
  const history = [
    {
      id: 41,
      type: 'human',
      request_id: 'request-1',
      content: '快排',
      extra_metadata: { request_id: 'request-1' }
    }
  ]
  const ongoing = [
    {
      id: 'request-1',
      type: 'human',
      run_id: 'run-1',
      content: '快排',
      extra_metadata: { request_id: 'request-1', run_id: 'run-1' }
    }
  ]

  const merged = mergeMessageDebugMessages(history, ongoing)

  assert.equal(merged.length, 1)
  assert.equal(merged[0].id, 41)
  assert.equal(merged[0].run_id, 'run-1')
  assert.equal(merged[0].extra_metadata.run_id, 'run-1')
})

test('active run 尚无持久化 AI 时保持流式 Human 到 AI 的顺序', () => {
  const ongoing = [
    { id: 'user-live', type: 'human', request_id: 'request-live' },
    { id: 'ai-live', type: 'ai', run_id: 'run-live' }
  ]

  const merged = mergeMessageDebugMessages([], ongoing)

  assert.deepEqual(
    merged.map((message) => message.id),
    ['user-live', 'ai-live']
  )
})

test('Model 审计按稳定 operation 合并并按 sequence 插入隐藏调用', () => {
  const messages = [
    { id: 'user-1', type: 'human', run_id: 'run-1', content: '开始' },
    { id: 21, type: 'ai', run_id: 'run-1', content: '流式工具调用' },
    { id: 23, type: 'ai', run_id: 'run-1', content: '最终回答' }
  ]
  const audits = [
    {
      id: 21,
      type: 'ai',
      run_id: 'run-1',
      operation_id: 'operation-1',
      sequence: 3,
      content: '持久化工具调用',
      execution_status: 'completed'
    },
    {
      id: 22,
      type: 'ai',
      run_id: 'run-1',
      operation_id: 'operation-2',
      sequence: 7,
      content: '隐藏的中间调用',
      execution_status: 'completed'
    },
    {
      id: 23,
      type: 'ai',
      run_id: 'run-1',
      operation_id: 'operation-3',
      sequence: 10,
      content: '最终回答',
      execution_status: 'completed'
    }
  ]

  const merged = mergeMessageDebugAudits(messages, audits)

  assert.deepEqual(
    merged.map((message) => message.operation_id || message.id),
    ['user-1', 'operation-1', 'operation-2', 'operation-3']
  )
  assert.equal(merged[1].content, '流式工具调用')
})

test('审计快照落后于 SSE 时仍按已知 sequence 放置持久操作', () => {
  const messages = mergeMessageDebugMessages(
    [{ id: 21, type: 'ai', run_id: 'run-1', content: 'operation 1' }],
    [{ id: 'operation-3', type: 'ai', run_id: 'run-1', content: 'operation 3 live' }]
  )
  const audits = [
    {
      id: 21,
      type: 'ai',
      run_id: 'run-1',
      operation_id: 'operation-1',
      sequence: 3,
      content: 'operation 1'
    },
    {
      id: 22,
      type: 'ai',
      run_id: 'run-1',
      operation_id: 'operation-2',
      sequence: 7,
      content: 'operation 2'
    }
  ]

  const merged = mergeMessageDebugAudits(messages, audits)

  assert.deepEqual(
    merged.map((message) => message.operation_id || message.id),
    ['operation-1', 'operation-2', 'operation-3']
  )
})

test('同一 Model 的历史行和实时投影按稳定 operation 合并为一条', () => {
  const messages = [
    { id: 42, type: 'ai', run_id: 'run-1', content: '持久化内容' },
    { id: 'operation-1', type: 'ai', run_id: 'run-1', content: '更完整的实时内容' }
  ]
  const audits = [
    {
      id: 42,
      type: 'ai',
      run_id: 'run-1',
      operation_id: 'operation-1',
      content: '',
      execution_status: 'running'
    }
  ]

  const merged = mergeMessageDebugAudits(messages, audits)

  assert.equal(merged.length, 1)
  assert.equal(merged[0].operation_id, 'operation-1')
  assert.equal(merged[0].content, '更完整的实时内容')
})

test('实时 Model 投影只按同一 Run 的 operation id 合并', () => {
  const messages = [
    { id: 'shared-operation', type: 'ai', run_id: 'run-other', content: '其它 Run' },
    { id: 'shared-operation', type: 'ai', run_id: 'run-target', content: '实时内容' }
  ]
  const audits = [
    {
      id: 42,
      type: 'ai',
      run_id: 'run-target',
      operation_id: 'shared-operation',
      content: '',
      duration_ms: 0,
      execution_status: 'running'
    }
  ]

  const merged = mergeMessageDebugAudits(messages, audits)

  assert.equal(merged[0].operation_id, undefined)
  assert.equal(merged[1].operation_id, 'shared-operation')
  assert.equal(merged[1].content, '实时内容')
  const entry = buildMessageDebugEntries([merged[1]])[0]
  assert.equal(entry.id, 'run-target:assistant:shared-operation')
  assert.equal(entry.roleLabel, 'Model')
  assert.equal(entry.durationMs, 0)
  assert.equal(entry.executionStatus, 'running')
})

test('同 Run 同 operation id 的 Model 与 Tool 审计保持独立', () => {
  const messages = [
    {
      id: 'shared-operation',
      type: 'ai',
      run_id: 'run-1',
      content: '实时模型输出'
    }
  ]
  const audits = [
    {
      id: 10,
      type: 'ai',
      run_id: 'run-1',
      operation_id: 'shared-operation',
      sequence: 3,
      content: '模型输出'
    },
    {
      id: 11,
      type: 'tool',
      run_id: 'run-1',
      operation_id: 'shared-operation',
      sequence: 6,
      content: '工具输出'
    }
  ]

  const merged = mergeMessageDebugAudits(messages, audits)
  const entries = buildMessageDebugEntries(merged)

  assert.equal(merged.length, 2)
  assert.equal(merged[0].content, '实时模型输出')
  assert.equal(merged[0].type, 'ai')
  assert.equal(merged[1].content, '工具输出')
  assert.equal(merged[1].type, 'tool')
  assert.deepEqual(
    entries.map((entry) => entry.id),
    ['run-1:assistant:shared-operation', 'run-1:tool:shared-operation']
  )
})

test('Model 与 Tool 审计按 sequence 形成交错时间线并展示真实工具事实', () => {
  const messages = [{ id: 'user-1', type: 'human', run_id: 'run-1', content: '查询' }]
  const audits = [
    {
      id: 10,
      type: 'ai',
      run_id: 'run-1',
      operation_id: 'model-1',
      sequence: 3,
      execution_status: 'completed'
    },
    {
      id: 11,
      type: 'tool',
      run_id: 'run-1',
      operation_id: 'call-1',
      tool_name: 'search',
      tool_input: { q: 'Yuxi' },
      content: '查询结果',
      sequence: 6,
      duration_ms: 125,
      execution_status: 'completed'
    },
    {
      id: 12,
      type: 'ai',
      run_id: 'run-1',
      operation_id: 'model-2',
      sequence: 9,
      execution_status: 'running'
    }
  ]

  const merged = mergeMessageDebugAudits(messages, audits)
  const entries = buildMessageDebugEntries(merged)

  assert.deepEqual(
    entries.map((entry) => entry.operationId || entry.id),
    ['user-1', 'model-1', 'call-1', 'model-2']
  )
  assert.equal(entries[2].role, 'tool')
  assert.equal(entries[2].roleLabel, 'Tool · search')
  assert.equal(entries[2].summary, '输出: 查询结果')
  assert.equal(entries[2].durationMs, 125)
  assert.equal(entries[2].executionStatus, 'completed')
})

test('失败 Tool 审计展示错误而不把 running wall-clock 推算成耗时', () => {
  const [entry] = buildMessageDebugEntries([
    {
      id: 11,
      type: 'tool',
      run_id: 'run-1',
      operation_id: 'call-error',
      tool_name: 'search',
      tool_input: { q: 'Yuxi' },
      error_message: 'provider unavailable',
      execution_status: 'failed'
    }
  ])

  assert.equal(entry.summary, '错误: provider unavailable')
  assert.equal(entry.durationMs, null)
})

test('Model/Tool monotonic 耗时在分钟边界正确进位', () => {
  assert.equal(formatAuditDuration(675), '675 ms')
  assert.equal(formatAuditDuration(1120), '1.12 s')
  assert.equal(formatAuditDuration(60_000), '1m 0s')
  assert.equal(formatAuditDuration(119_600), '2m 0s')
  assert.equal(formatAuditDuration(null), '')
})

test('大量未匹配审计按 sequence 一次合并', () => {
  const auditCount = 2000
  const audits = Array.from({ length: auditCount }, (_, index) => ({
    id: index + 1,
    type: 'ai',
    run_id: 'run-large',
    operation_id: `operation-${index + 1}`,
    sequence: index + 1
  }))
  const messages = [
    { id: 'user-large', type: 'human', run_id: 'run-large' },
    {
      id: 'operation-live',
      type: 'ai',
      run_id: 'run-large',
      content: '实时输出'
    }
  ]

  const merged = mergeMessageDebugAudits(messages, audits)

  assert.equal(merged.length, auditCount + 2)
  assert.equal(merged[0].id, 'user-large')
  assert.equal(merged[1].operation_id, 'operation-1')
  assert.equal(merged[auditCount].operation_id, `operation-${auditCount}`)
  assert.equal(merged.at(-1).id, 'operation-live')
})

test('工具名称按多种消息字段解析并去重', () => {
  const names = extractMessageToolNames({
    tool_calls: [
      { name: 'search' },
      { tool_name: 'search' },
      { function: { name: 'read_file' } },
      {}
    ]
  })

  assert.deepEqual(names, ['search', 'read_file'])
})

test('Trace 记录位置只使用持久绝对时间，不从 monotonic 耗时推算', () => {
  const entries = buildMessageDebugEntries([
    {
      id: 'user-1',
      type: 'human',
      created_at: '2026-09-04T08:00:01Z',
      run_id: 'run-1'
    },
    {
      id: 'model-1',
      type: 'ai',
      run_id: 'run-1',
      operation_id: 'model-1',
      started_at: '2026-09-04T08:00:02Z',
      finished_at: '2026-09-04T08:00:06Z',
      duration_ms: 3998
    },
    {
      id: 'tool-without-time',
      type: 'tool',
      run_id: 'run-1',
      duration_ms: 800
    }
  ])
  const runWindow = {
    startMs: Date.parse('2026-09-04T08:00:00Z'),
    endMs: Date.parse('2026-09-04T08:00:08Z'),
    durationMs: 8000
  }

  assert.deepEqual(getMessageDebugEntryTimeRange(entries[0]), {
    startMs: Date.parse('2026-09-04T08:00:01Z'),
    endMs: Date.parse('2026-09-04T08:00:01Z')
  })
  assert.equal(getMessageDebugEntryTimeRange(entries[2]), null)
  assert.deepEqual(
    buildMessageDebugTraceSpans(entries, runWindow).map(({ key, startOffsetMs, endOffsetMs }) => ({
      key,
      startOffsetMs,
      endOffsetMs
    })),
    [
      { key: 'user-1', startOffsetMs: 1000, endOffsetMs: 1000 },
      { key: 'run-1:assistant:model-1', startOffsetMs: 2000, endOffsetMs: 6000 },
      { key: 'tool-without-time', startOffsetMs: 0, endOffsetMs: 8000 }
    ]
  )
  const fallbackSpan = buildMessageDebugTraceSpans(entries, runWindow).at(-1)
  assert.equal(fallbackSpan.timingFallback, true)
  assert.equal(
    isMessageDebugTimelineMarkSelected(
      `item:run-1-0:${fallbackSpan.key}`,
      'run-1-0',
      fallbackSpan.key
    ),
    true
  )
})

test('调试投影把后端无时区数据库时间明确解释为 UTC', () => {
  const [entry] = buildMessageDebugEntries([
    {
      id: 'user-1',
      type: 'human',
      created_at: '2026-09-04T11:09:41.123456',
      run_id: 'run-1'
    }
  ])

  assert.equal(entry.createdAt, '2026-09-04T11:09:41.123456Z')
  assert.equal(
    getMessageDebugEntryTimeRange(entry).startMs,
    Date.parse('2026-09-04T11:09:41.123456Z')
  )
})

test('范围筛选把 Run 内记录映射到拼接后的累计执行时间', () => {
  const runWindow = {
    startMs: Date.parse('2026-09-04T08:00:00Z'),
    durationMs: 10_000
  }
  const outside = { createdAt: '2026-09-04T08:00:01Z' }
  const inside = { startedAt: '2026-09-04T08:00:05Z', finishedAt: '2026-09-04T08:00:06Z' }
  const context = { durationMs: 750 }

  assert.equal(isMessageDebugEntryInTimeRange(outside, runWindow, 10_000, 30_000, 0.45, 0.6), false)
  assert.equal(isMessageDebugEntryInTimeRange(inside, runWindow, 10_000, 30_000, 0.45, 0.6), true)
  assert.equal(isMessageDebugEntryInTimeRange(context, runWindow, 10_000, 30_000, 0.45, 0.6), true)
})

test('会话范围筛选按 Run 拼接位置处理无时间记录', () => {
  const earlyRunWindow = {
    startMs: Date.parse('2026-09-04T08:00:00Z'),
    endMs: Date.parse('2026-09-04T08:00:04Z'),
    durationMs: 4000
  }
  const lateRunWindow = {
    startMs: Date.parse('2026-09-04T08:00:12Z'),
    endMs: Date.parse('2026-09-04T08:00:16Z'),
    durationMs: 4000
  }

  assert.equal(isMessageDebugEntryInTimeRange({}, earlyRunWindow, 0, 8000, 0.625, 1), false)
  assert.equal(isMessageDebugEntryInTimeRange({}, lateRunWindow, 4000, 8000, 0.625, 1), true)
})

test('待运行请求独立分组，Run 到达后保持分组和用户记录标识', () => {
  const messages = [
    {
      id: 'req-a',
      type: 'human',
      request_id: 'req-a',
      created_at: '2026-09-05T06:32:00Z',
      content: 'A'
    },
    { id: 'req-b', type: 'human', request_id: 'req-b', delivery_status: 'queued', content: 'B' }
  ]
  const before = groupMessageDebugEntries(buildMessageDebugEntries(messages))
  assert.equal(before.length, 2)
  assert.equal(before[0].requestId, 'req-a')
  assert.equal(before[1].requestId, 'req-b')
  const after = groupMessageDebugEntries(
    buildMessageDebugEntries([
      { ...messages[0], id: 101, run_id: 'run-a' },
      { id: 102, type: 'ai', run_id: 'run-a', content: '回答 A' },
      messages[1]
    ])
  )
  assert.equal(after[0].key, before[0].key)
  assert.equal(after[0].items[0].id, before[0].items[0].id)
  assert.equal(after[0].items.length, 2)
  assert.equal(after[1].runId, null)
  assert.equal(after[1].key, before[1].key)
})

test('明确接入关联只更新对应用户消息，保留已有运行事实', () => {
  const messages = [
    { type: 'human', request_id: 'req-a', created_at: '2026-09-05T06:32:00Z' },
    { type: 'human', request_id: 'req-b' },
    { type: 'ai', request_id: 'req-a' },
    { type: 'human', request_id: 'req-a', run_id: 'existing-run' }
  ]
  bindMessageRequestRun(messages, 'req-a', 'run-a')
  assert.equal(getMessageRunId(messages[0]), 'run-a')
  assert.equal(messages[0].created_at, '2026-09-05T06:32:00Z')
  assert.equal(getMessageRunId(messages[1]), null)
  assert.equal(getMessageRunId(messages[2]), null)
  assert.equal(getMessageRunId(messages[3]), 'existing-run')
  bindMessageRequestRun(messages, 'req-b', null)
  assert.equal(getMessageRunId(messages[1]), null)
})

test('活跃 Run 中的新请求通过队列投影独立展示且不重复已有消息', () => {
  const requests = [
    {
      request_id: 'req-b',
      status: 'queued',
      content: '排队消息',
      created_at: '2026-09-05T06:32:00Z'
    }
  ]
  const history = [
    { id: 1, type: 'human', request_id: 'req-a', run_id: 'run-a', content: '运行中' }
  ]
  const projected = mergeMessageDebugMessages(history, [], requests)
  assert.equal(projected.length, 2)
  assert.equal(projected[1].created_at, requests[0].created_at)
  assert.equal(projected[1].delivery_status, 'queued')
  const groups = groupMessageDebugEntries(buildMessageDebugEntries(projected))
  assert.equal(groups.length, 2)
  assert.equal(groups[1].requestId, 'req-b')
  assert.equal(groups[1].runId, null)
  const ongoing = [{ ...projected[1], run_id: 'run-b' }]
  const merged = mergeMessageDebugMessages(history, ongoing, requests)
  assert.equal(merged.length, 2)
  assert.equal(getMessageRunId(merged[1]), 'run-b')
  assert.equal(mergeMessageDebugMessages(projected, ongoing, requests).length, 2)
})

test('非连续同请求分段具有独立 key，不抢占其他分段的选择', () => {
  const groups = groupMessageDebugEntries(
    buildMessageDebugEntries([
      { id: 1, type: 'human', request_id: 'req-a', run_id: 'run-a' },
      { id: 2, type: 'human', request_id: 'req-b' },
      { id: 3, type: 'ai', request_id: 'req-a', run_id: 'run-a' }
    ])
  )
  assert.equal(groups.length, 3)
  assert.equal(new Set(groups.map((group) => group.key)).size, 3)
})
