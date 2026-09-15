import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('../../src/components/AgentChatComponent.vue', import.meta.url),
  'utf8'
)

test('模型选择按当前选择、Conversation、智能体默认的顺序解析', () => {
  const modelBlock = source.slice(
    source.indexOf('const currentModelSpec = computed'),
    source.indexOf('const handleModelSelect')
  )

  for (const expression of [
    'selectedModelByThread',
    'currentThread.value?.metadata?.model_spec',
    'agentDefaultModel.value'
  ]) assert.ok(modelBlock.includes(expression), expression)

  assert.ok(
    modelBlock.indexOf('selectedModelByThread') <
      modelBlock.indexOf('currentThread.value?.metadata?.model_spec')
  )
  assert.ok(
    modelBlock.indexOf('currentThread.value?.metadata?.model_spec') <
      modelBlock.indexOf('agentDefaultModel.value')
  )
})

test('发送当前展示模型并在请求被接受后同步 Conversation metadata', () => {
  const sendBlock = source.slice(
    source.indexOf('const handleSendMessage'),
    source.indexOf('const handleDirectSteer')
  )

  assert.match(sendBlock, /const modelSpec = currentModelSpec\.value \|\| null/)
  assert.match(sendBlock, /model_spec: modelSpec/)
  assert.match(sendBlock, /status !== 'rejected' && modelSpec/)
  assert.match(sendBlock, /thread\.metadata = \{ \.\.\.\(thread\.metadata \|\| \{\}\), model_spec: modelSpec \}/)
})

test('路由选择即使已预写当前线程也会加载消息', () => {
  const routeSelectionBlock = source.slice(
    source.indexOf('const selectThreadFromRoute'),
    source.indexOf('const handleQuestionSubmit')
  )

  assert.doesNotMatch(
    routeSelectionBlock,
    /if \(currentThreadId\.value === threadId\) \{\s*return true\s*\}/
  )
  assert.match(routeSelectionBlock, /await selectChat\(threadId\)/)
})
