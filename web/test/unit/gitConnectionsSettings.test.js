import assert from 'node:assert/strict'
import { after, before, beforeEach, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, reactive, ssrContextKey } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createServer } from 'vite'
let vite, View, api, useUserStore
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: View } = await vite.ssrLoadModule('/src/components/GitConnectionsSettingsCard.vue'))
  ;({ gitApi: api } = await vite.ssrLoadModule('/src/apis/git_api.js'))
  ;({ useUserStore } = await vite.ssrLoadModule('/src/stores/user.js'))
})
beforeEach(() => { setActivePinia(createPinia()); useUserStore().uid = 'owner-a' })
after(async () => { await vite?.close(); delete globalThis.localStorage })
const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}), insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
const flush = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)); await nextTick() }
function mount(t, props = reactive({ active: true })) {
  let instance
  const app = renderer.createApp({ setup: () => () => h({ ...View, render() { instance = getCurrentInstance(); return h('div') } }, props) })
  app.provide(ssrContextKey, { modules: new Set() }); app.mount({}); t.after(() => app.unmount())
  return () => instance.setupState
}
test('用户切换后迟到的连接读取不能恢复原用户连接', async t => {
  let finish
  t.mock.method(api, 'getConnections', () => useUserStore().uid === 'owner-a' ? new Promise(resolve => { finish = resolve }) : Promise.resolve([{ id: 'new-owner' }]))
  const state = mount(t)
  await flush(); state().form.api_token = 'fixture-not-a-real-token'; state().credentialToken = 'fixture-token'
  useUserStore().uid = 'owner-b'; await flush()
  finish([{ id: 'old-owner' }]); await flush()
  assert.deepEqual(state().connections.map(item => item.id), ['new-owner'])
  assert.equal(state().form.api_token, ''); assert.equal(state().credentialToken, '')
})
test('Token更新拒绝保留错误并清空秘密，不把失败记成成功', async t => {
  t.mock.method(api, 'getConnections', async () => [{ id: 'connection-a' }])
  const update = t.mock.method(api, 'updateCredential', async () => { throw new Error('更新被拒绝') })
  const state = mount(t); await flush()
  state().beginEdit({ id: 'connection-a' }); state().credentialToken = 'fixture-token'
  await state().update({ id: 'connection-a' })
  assert.deepEqual(update.mock.calls[0].arguments, ['connection-a', 'fixture-token'])
  assert.equal(state().credentialToken, ''); assert.equal(state().success, ''); assert.equal(state().error, '更新被拒绝')
})
test('连接创建使用原用户API且成功后回读，切离设置页清空未提交Token', async t => {
  let rows = []
  t.mock.method(api, 'getConnections', async () => rows)
  const create = t.mock.method(api, 'createConnection', async () => { rows = [{ id: 'created', name: '测试服务' }] })
  const props = reactive({ active: true }), state = mount(t, props); await flush()
  Object.assign(state().form, { name: '测试服务', api_origin: 'https://git.example.test', ssh_host: 'git.example.test', ssh_known_host_key: 'fixture-host-key', api_token: 'fixture-token' })
  await state().create()
  assert.equal(create.mock.calls[0].arguments[0].provider, 'gitea')
  assert.equal(create.mock.calls[0].arguments[0].project_id, undefined)
  assert.equal(state().connections[0].id, 'created'); assert.equal(state().form.api_token, '')
  state().form.api_token = 'unsent-fixture'; props.active = false; await flush()
  assert.equal(state().form.api_token, '')
})
