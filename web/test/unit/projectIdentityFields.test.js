import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, reactive, ssrContextKey } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { message } from 'ant-design-vue'
import { createServer } from 'vite'

let vite, View, api, Creation, projectApi
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: View } = await vite.ssrLoadModule('/src/components/ProjectIdentityFields.vue'))
  ;({ userApi: api } = await vite.ssrLoadModule('/src/apis/user_api.js'))
  ;({ default: Creation } = await vite.ssrLoadModule('/src/components/ProjectCreateModal.vue'))
  ;({ projectApi } = await vite.ssrLoadModule('/src/apis/project_api.js'))
})
after(async () => { await vite?.close(); delete globalThis.localStorage })
const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}), insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
const settle = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }
const mount = (t, props, ComponentView = View) => {
  let instance
  const Component = { ...ComponentView, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp({ setup: () => () => h(Component, props) })
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  return { state: () => instance.setupState, unmount: () => app.unmount() }
}
const file = { type: 'image/png', size: 20 }

test('上传成功只产生待保存图标；失败保留原图并解除等待', async t => {
  let finish, fail
  t.mock.method(api, 'uploadImage', () => new Promise((resolve, reject) => { finish = resolve; fail = reject }))
  t.mock.method(message, 'success', () => {})
  t.mock.method(message, 'error', () => {})
  const updates = [], waiting = []
  const { state } = mount(t, reactive({ scopeKey: 'one', icon: '/old.png', 'onUpdate:icon': value => updates.push(value), onUploading: value => waiting.push(value) }))
  assert.equal(state().beforeUpload(file), false)
  assert.equal(state().uploading, true)
  assert.deepEqual(updates, [])
  finish({ image_url: '/new.png' })
  await settle()
  assert.deepEqual(updates, ['/new.png'])
  assert.deepEqual(waiting, [true, false])
  state().beforeUpload(file)
  fail(new Error('失败'))
  await settle()
  assert.deepEqual(updates, ['/new.png'])
  assert.equal(state().uploading, false)
})

test('切换创建意图后的迟到图片不覆盖新项目，卸载后不再发更新', async t => {
  let finish
  t.mock.method(api, 'uploadImage', () => new Promise(resolve => { finish = resolve }))
  t.mock.method(message, 'success', () => {})
  const updates = []
  const props = reactive({ scopeKey: 'one', 'onUpdate:icon': value => updates.push(value) })
  const { state, unmount } = mount(t, props)
  state().beforeUpload(file)
  props.scopeKey = 'two'
  await settle()
  finish({ image_url: '/one.png' })
  await settle()
  assert.deepEqual(updates, [])
  state().beforeUpload(file)
  unmount()
  finish({ image_url: '/two.png' })
  await settle()
  assert.deepEqual(updates, [])
})

test('非图片和超过5MB拒绝上传，不进入等待状态', async t => {
  t.mock.method(api, 'uploadImage', () => { throw new Error('无效文件不应到接口') })
  t.mock.method(message, 'error', () => {})
  const { state } = mount(t, reactive({ scopeKey: 'one' }))
  assert.equal(state().beforeUpload({ type: 'text/plain', size: 1 }), false)
  assert.equal(state().beforeUpload({ type: 'image/png', size: 5 * 1024 * 1024 + 1 }), false)
  assert.equal(state().uploading, false)
})


test('完整新建在上传中不提交，失败后保留草稿并以同一意图重试', async t => {
  setActivePinia(createPinia())
  t.mock.method(message, 'success', () => {})
  const { useUserStore } = await vite.ssrLoadModule('/src/stores/user.js')
  useUserStore().uid = 'creator'
  t.mock.method(projectApi, 'getCreationOptions', async () => ({ members: [{id: 'creator', name: '创建者'}] }))
  const intents = [], created = []
  t.mock.method(projectApi, 'createProject', async intent => {
    intents.push(intent)
    if (intents.length === 1) throw new Error('断线')
    return { id: 'server-project', name: intent.name, icon: intent.icon, slug: intent.slug }
  })
  const { state } = mount(t, reactive({ open: true, initialPath: 'projects/test', onCreated: p => created.push(p) }), Creation)
  await settle()
  state().draft.name = '新项目'
  state().draft.slug = 'A'
  state().draft.icon = '/uploaded.png'
  state().draft.attributes.description = '完整描述'
  state().uploading = true
  await state().create()
  assert.deepEqual(intents, [])
  state().uploading = false
  await state().create()
  assert.deepEqual(created, [])
  assert.equal(state().draft.attributes.description, '完整描述')
  assert.equal(state().error, '断线')
  await state().create()
  assert.equal(intents[0].requestId, intents[1].requestId)
  assert.equal(intents[1].slug, 'A')
  assert.equal(intents[1].icon, '/uploaded.png')
  assert.equal(intents[1].attributes.owner_id, 'creator')
  assert.equal(intents[1].attributes.description, '完整描述')
  assert.deepEqual(created.map(p => p.id), ['server-project'])
})
