import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createServer } from 'vite'
let vite, Fields
before(async () => {
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: Fields } = await vite.ssrLoadModule('/src/components/project/WorkSourceFields.vue'))
})
after(async () => { await vite?.close() })
test('批准、替代、撤销候选效力明确，需复核补充展示确认入口', async () => {
  const app = createSSRApp(Fields, { decisionId: 'supplement', decisions: [
    { id: 'supplement', title: '补充方案', status: 'approved', requires_review: true },
    { id: 'old', title: '旧方案', status: 'superseded' }, { id: 'revoked', title: '撤销方案', status: 'revoked' }
  ] })
  for (const name of ['a-select', 'a-select-option', 'a-checkbox', 'a-alert']) app.component(name, {
    setup: (_, { attrs, slots }) => () => h(name === 'a-select-option' ? 'option' : 'div', attrs, slots.default?.())
  })
  const html = await renderToString(app)
  assert.match(html, /补充方案 · 已批准 · 需复核/)
  assert.match(html, /<option[^>]*disabled[^>]*>旧方案 · 已被替代/)
  assert.match(html, /<option[^>]*disabled[^>]*>撤销方案 · 已撤销/)
  assert.match(html, /我已复核此补充/)
  assert.match(html, /补充决策原依据已变化/)
})
