import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { createRenderer, getCurrentInstance, h, nextTick, ssrContextKey } from 'vue'
import { createPinia } from 'pinia'
import { createServer } from 'vite'
import { message } from 'ant-design-vue'

let vite, View, api, configApi
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: View } = await vite.ssrLoadModule('/src/components/model-management/ModelProviderManagePanel.vue'))
  ;({ modelProviderApi: api, configApi } = await vite.ssrLoadModule('/src/apis/system_api.js'))
})
after(async () => { await vite?.close(); delete globalThis.localStorage })
const renderer = createRenderer({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {},
  parentNode: () => null, nextSibling: () => null
})

test('编辑模型保留默认输出与能力，清空默认明确保存 null', async (t) => {
  t.mock.method(configApi, 'getConfig', async () => ({ default_model: 'test:chat' }))
  t.mock.method(api, 'getProviders', async () => ({ data: [] }))
  let instance
  const Component = { ...View, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp({ setup: () => () => h(Component) })
  app.use(createPinia())
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await nextTick()
  const state = instance.setupState
  state.openModelConfigModal({ id: 'chat', type: 'chat', default_output_tokens: 65536, max_output_tokens: 393216 })
  assert.equal(state.editingModel.default_output_tokens, 65536)
  assert.equal(state.buildModelConfigPayload().max_output_tokens, 393216)
  state.editingModel.default_output_tokens = null
  assert.equal(state.buildModelConfigPayload().default_output_tokens, null)
  state.openModelConfigModal({ id: 'old', type: 'chat' })
  assert.equal(state.editingModel.default_output_tokens, null)
  assert.equal(state.editingModel.max_output_tokens, null)
  t.mock.method(message, 'error', () => {})
})
