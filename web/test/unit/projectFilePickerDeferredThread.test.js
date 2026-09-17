import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

// 源级 tripwire：AgentChatComponent 挂载依赖过重，此处直接断言函数体顺序；
// 若未来重构改变创建线程/引用落库的时机，本测试应随装配变化同步重写，而不是被静默跳过。
const source = readFileSync(
  new URL('../../src/components/AgentChatComponent.vue', import.meta.url),
  'utf8'
)

const functionBody = (name) =>
  source.match(new RegExp(`const ${name} = (?:async )?\\([^)]*\\) => \\{[\\s\\S]*?\\n\\}`))?.[0]

test('打开选择器与确认引用都不创建线程，首次发送前仅缓存待引用文件', () => {
  const openPicker = functionBody('handleProjectFileSelect')
  const confirmFiles = functionBody('handleProjectFilesSelected')
  assert.ok(openPicker, '应存在 handleProjectFileSelect')
  assert.ok(confirmFiles, '应存在 handleProjectFilesSelected')

  assert.doesNotMatch(
    openPicker,
    /ensureAttachmentThread|ensureActiveThread/,
    '打开选择器不得创建线程，否则智能体入口会被锁定'
  )
  assert.match(openPicker, /projectFilePickerOpen\.value = true/)

  // 无线程分支只写前端缓存，不创建线程、不调用引用接口。
  const cacheIndex = confirmFiles.indexOf('pendingWorkspaceReferences.value = [')
  assert.ok(cacheIndex >= 0, '无线程确认应写入前端缓存')
  const cacheBranch = confirmFiles.slice(cacheIndex, confirmFiles.indexOf('return', cacheIndex))
  assert.doesNotMatch(
    cacheBranch,
    /ensureAttachmentThread|ensureActiveThread|referenceThreadAttachments/,
    '首次发送前缓存分支不得创建线程或引用落库'
  )

  // 已有线程分支保持立即引用。
  assert.match(confirmFiles, /referenceThreadAttachments/)
  assert.match(confirmFiles, /source: file\.source \|\| 'workspace'/)
})

test('首条消息发送时才把缓存引用落库到真实线程', () => {
  const sendMessage = functionBody('handleSendMessage')
  assert.ok(sendMessage, '应存在 handleSendMessage')

  const materializeIndex = sendMessage.indexOf('pendingWorkspaceReferences.value.length')
  assert.ok(materializeIndex >= 0, '发送链路应物化待引用文件')
  const materialize = sendMessage.slice(
    materializeIndex,
    sendMessage.indexOf('const modelSpec', materializeIndex)
  )
  assert.match(materialize, /referenceThreadAttachments\(threadId, payload\)/)
  assert.match(materialize, /source: 'workspace'/)
  assert.match(materialize, /pendingWorkspaceReferences\.value = \[\]/)
  assert.match(materialize, /fetchThreadAttachments\(threadId\)/)

  const createIndex = sendMessage.indexOf('ensureActiveThread(text)')
  assert.ok(
    createIndex >= 0 && createIndex < materializeIndex,
    '线程必须先创建，缓存引用才能落库'
  )
})

test('选择器模板不再注入 thread-id，浏览不依赖线程', () => {
  const pickerBlock = source.match(/<ProjectFilePickerModal[\s\S]*?\/>/)?.[0]
  assert.ok(pickerBlock, '应存在 ProjectFilePickerModal 模板块')
  assert.doesNotMatch(pickerBlock, /:thread-id/, '选择器不应接收 thread-id')
  assert.match(pickerBlock, /@select="handleProjectFilesSelected"/)
})
