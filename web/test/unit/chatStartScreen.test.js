import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as Vue from 'vue'
import { renderToString } from 'vue/server-renderer'

const source = readFileSync(
  new URL('../../src/components/AgentChatComponent.vue', import.meta.url),
  'utf8'
)
const view = readFileSync(new URL('../../src/views/AgentView.vue', import.meta.url), 'utf8')
const dock = source.slice(
  source.indexOf('<div\n            ref="messageInputDockRef"'),
  source.indexOf('              <section\n                v-if="currentQueuedRequests.length"')
)
const render = Vue.compile(`${dock}</div></div>`)

test('路由决定新建布局，已有线程的加载和空消息不显示居中输入框或欢迎语', async () => {
  assert.ok(view.includes(':is-new-conversation="!getRouteThreadId()"'), '新建布局由路由传入')
  for (const isNewConversation of [false, true]) {
    for (const isLoadingMessages of [false, true]) {
      for (const conversations of [[], [{ id: 'history' }]]) {
        const html = await renderToString(
          Vue.createSSRApp({
            data: () => ({
              isNewConversation,
              isLoadingMessages,
              conversations,
              randomGreeting: '欢迎测试'
            }),
            render
          })
        )
        assert.equal(html.includes('start-screen'), isNewConversation)
        assert.equal(html.includes('欢迎测试'), isNewConversation)
        assert.equal(html.includes('正在加载消息'), isLoadingMessages)
      }
    }
  }
})
