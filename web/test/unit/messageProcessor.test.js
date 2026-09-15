import assert from 'node:assert/strict'
import test from 'node:test'

import { MessageProcessor } from '../../src/utils/messageProcessor.js'

const databases = [{ name: '财税库' }, { name: 'DifyKB' }, { name: 'LightGraphKB' }]

test('流式与历史只消费统一展示字段，不解释供应商元数据', () => {
  for (const message of [
    { content: 'OK', reasoning_content: '先检查。' },
    { content: 'OK', reasoning_content: '先检查。', content_blocks: [{ type: 'reasoning', reasoning: '先检查。' }] }
  ]) {
    assert.deepEqual(MessageProcessor.parseAssistantMessageBody(message), { content: 'OK', reasoningContent: '先检查。' })
  }
  assert.deepEqual(MessageProcessor.parseAssistantMessageBody({
    content: 'OK', additional_kwargs: { reasoning_content: '不在页面恢复' },
    content_blocks: [{ type: 'reasoning', reasoning: '不在页面恢复' }]
  }), { content: 'OK', reasoningContent: '' })
  const merged = MessageProcessor.mergeMessageChunk([
    { type: 'ai', content: '', reasoning_content: '先' },
    { type: 'ai', content: '', reasoning_content: '检查。' },
    { type: 'ai', content: 'OK' }
  ])
  assert.deepEqual(MessageProcessor.parseAssistantMessageBody(merged), { content: 'OK', reasoningContent: '先检查。' })
})

test('交付物只归属于调用 present_artifacts 的对话', () => {
  const artifactConversation = {
    messages: [
      {
        type: 'ai',
        tool_calls: [
          {
            name: 'present_artifacts',
            tool_call_result: { content: '已将交付物展示给用户' },
            args: JSON.stringify({
              filepaths: [
                '/home/gem/user-data/outputs/bubble_sort.py',
                '/home/gem/user-data/outputs/bubble_sort.js'
              ]
            })
          },
          {
            function: { name: 'present_artifacts' },
            status: 'success',
            args: { filepaths: ['/home/gem/user-data/outputs/bubble_sort.py'] }
          }
        ]
      }
    ]
  }
  const laterConversation = {
    messages: [{ type: 'human', content: '运行 Python 的' }]
  }

  assert.deepEqual(MessageProcessor.extractArtifactsFromConversation(artifactConversation), [
    '/home/gem/user-data/outputs/bubble_sort.py',
    '/home/gem/user-data/outputs/bubble_sort.js'
  ])
  assert.deepEqual(MessageProcessor.extractArtifactsFromConversation(laterConversation), [])
})

test('知识库来源与历史消息保持独立的归一化语义', () => {
  const conv = {
    messages: [
      {
        type: 'ai',
        tool_calls: [
          {
            name: '财税库',
            tool_call_result: {
              content: JSON.stringify([
                {
                  content: 'A',
                  score: 0.9,
                  metadata: { source: 'doc-a', chunk_id: 'c1', file_id: 'f1', chunk_index: 1 }
                },
                {
                  content: 'A',
                  score: 0.8,
                  metadata: { source: 'doc-a', chunk_id: 'c1', file_id: 'f1', chunk_index: 1 }
                }
              ])
            }
          },
          {
            name: 'LightGraphKB',
            tool_call_result: {
              content: JSON.stringify({
                data: {
                  chunks: [
                    {
                      content: 'B',
                      score: 0.4,
                      metadata: { source: 'doc-b', chunk_id: 'c2', file_id: 'f2', chunk_index: 2 }
                    }
                  ]
                }
              })
            }
          },
          {
            name: 'not_kb_tool',
            tool_call_result: {
              content: JSON.stringify([{ content: 'X', score: 0.99, metadata: { chunk_id: 'cx' } }])
            }
          },
          {
            name: 'DifyKB',
            tool_call_result: { content: 'not-json' }
          }
        ]
      }
    ]
  }

  const chunks = MessageProcessor.extractKnowledgeChunksFromConversation(conv, databases)

  assert.equal(chunks.some((chunk) => chunk.content === 'A' && chunk.kb_name === '财税库'), true)
  assert.equal(
    chunks.some((chunk) => chunk.content === 'B' && chunk.kb_name === 'LightGraphKB'),
    true
  )
  assert.equal(chunks.some((chunk) => chunk.content === 'X'), false)
  assert.equal(chunks.some((chunk) => chunk.kb_name === 'DifyKB'), false)
  assert.equal(chunks.filter((chunk) => chunk.metadata?.chunk_id === 'c1').length, 1)

  const idxA = chunks.findIndex((chunk) => chunk.content === 'A')
  const idxB = chunks.findIndex((chunk) => chunk.content === 'B')
  assert.equal(idxA < idxB, true)

  const conversations = MessageProcessor.convertServerHistoryToMessages([
    { type: 'human', content: '请选择语言' },
    { type: 'ai', content: '请选择输出语言' },
    {
      type: 'human',
      content: '{"language":"python"}',
      extra_metadata: { source: 'ask_user_question_resume' }
    },
    { type: 'ai', content: '这是 Python 版本' }
  ])

  assert.equal(conversations.length, 1)
  assert.equal(conversations[0].messages.length, 3)
  assert.equal(conversations[0].messages.at(-1).content, '这是 Python 版本')
  assert.equal(conversations[0].messages.at(-1).isLast, true)
  assert.equal(conversations[0].status, 'finished')

  assert.deepEqual(
    MessageProcessor.parseAssistantMessageBody({
      type: 'ai',
      content: '<think>推理过程</think>最终答案'
    }),
    { content: '<think>推理过程</think>最终答案', reasoningContent: '' }
  )
})


test('History 按 Run ID 分组，保留零消息 Run、续写和无关联旧消息', () => {
  const runs = [
    { run_id: 'run-a', status: 'completed', timing: { created_at: '2026-09-05T00:00:00Z' } },
    { run_id: 'run-resume', run_type: 'resume', created_by_run_id: 'run-a', status: 'completed', timing: { created_at: '2026-09-05T00:00:01Z' } },
    { run_id: 'run-empty', status: 'failed', timing: { created_at: '2026-09-05T00:00:02Z' } }
  ]
  const history = [
    { id: 'h', type: 'human', run_id: 'run-a', content: '问题' },
    { id: 'resume', type: 'ai', run_id: 'run-resume', content: '续写' },
    { id: 'a', type: 'ai', run_id: 'run-a', content: '首次回答' },
    { id: 'old', type: 'ai', content: '没有 Run 的旧回答', created_at: '2026-09-04T00:00:00Z' }
  ]
  const groups = MessageProcessor.convertServerHistoryToMessages(history, runs)
  assert.deepEqual(groups.map((group) => group.run?.run_id), [undefined, 'run-a', 'run-resume', 'run-empty'])
  assert.deepEqual(groups[1].messages.map((message) => message.id), ['h', 'a'])
  assert.equal(groups[2].messages[0].content, '续写')
  assert.equal(groups[3].messages.length, 0)
  assert.equal(groups[3].run.status, 'failed')
  assert.equal(groups[0].messages[0].id, 'old')
  assert.equal(history[2].isLast, undefined)
})
