import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { createSSRApp, h, isRef } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createServer } from 'vite'

let vite, View, codingSessionApi
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  globalThis.document = {
    documentElement: { classList: { add() {}, remove() {} } },
    getElementsByTagName: () => []
  }
  globalThis.window = { addEventListener() {}, removeEventListener() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: View } = await vite.ssrLoadModule('/src/components/ToolCallingResult/tools/CodingSessionTool.vue'))
  ;({ codingSessionApi } = await vite.ssrLoadModule('/src/apis/coding_session_api.js'))
})
after(async () => {
  await vite?.close()
  delete globalThis.localStorage
  delete globalThis.document
  delete globalThis.window
})

test('编码会话轮次在无摘要时展示已持久化的错误原因', async (t) => {
  t.mock.method(codingSessionApi, 'detail', async () => ({
    status: 'failed',
    turns: [{ seq: 1, status: 'failed', summary: null, error_message: '编码执行超时' }]
  }))
  const detail = await codingSessionApi.detail('session-1')
  const RenderableView = {
    ...View,
    setup(props, context) {
      const state = View.setup(props, context)
      assert.ok(isRef(state.turns))
      state.turns.value = detail.turns
      return state
    }
  }
  const router = createRouter({ history: createMemoryHistory(), routes: [] })
  const app = createSSRApp(() => h(RenderableView, {
    toolCall: {
      id: 'coding-call',
      name: 'coding_session_start',
      tool_call_result: { content: JSON.stringify({ session_id: 'session-1' }) }
    }
  }))
  app.use(createPinia())
  app.use(router)
  const html = await renderToString(app)
  assert.match(html, /编码执行超时/)
  assert.match(html, /（无摘要）/)
})
