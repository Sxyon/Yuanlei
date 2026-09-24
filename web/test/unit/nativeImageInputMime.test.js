import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const uploadSource = readFileSync(
  new URL('../../src/utils/multimodal_image_upload.js', import.meta.url),
  'utf8'
)
const chatSource = readFileSync(
  new URL('../../src/components/AgentChatComponent.vue', import.meta.url),
  'utf8'
)
const apiSource = readFileSync(new URL('../../src/apis/agent_api.js', import.meta.url), 'utf8')

test('图片上传保留处理后的 MIME 并随 Agent Run 请求传给后端', () => {
  assert.match(uploadSource, /mimeType: result\.mime_type \|\| file\.type/)
  assert.match(chatSource, /const imageMimeType = image\?\.mimeType \|\| null/)
  assert.match(chatSource, /image_mime_type: imageMimeType/)
  assert.match(apiSource, /image_mime_type: data\.image_mime_type \|\| null/)
})
