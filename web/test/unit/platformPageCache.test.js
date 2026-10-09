import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRenderer, defineComponent, getCurrentInstance, h, nextTick, onUnmounted, reactive, ref } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { compile } from 'vue/dist/vue.cjs.js'

const source = readFileSync(new URL('../../src/layouts/AppLayout.vue', import.meta.url), 'utf8')
const template = source.slice(source.indexOf('<ProjectLayout id="app-router-view"'), source.indexOf('</ProjectLayout>') + 16)
const render = compile(template)
const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}), insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
const settle = async () => { await nextTick(); await nextTick() }

test('实际宿主缓存模板：聊天经过非缓存项目页保持草稿，换账户销毁旧缓存', async t => {
  let chat, mounts = 0, unmounts = 0
  const Chat = defineComponent({ name: 'ChatTestComp', setup() { mounts += 1; chat = getCurrentInstance(); const draft = ref(''); onUnmounted(() => { unmounts += 1 }); return { draft } }, render: () => h('div') })
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/agent', name: 'chat', component: Chat, meta: { keepAlive: true } },
    { path: '/work', name: 'work', component: { name: 'WorkTestComp', render: () => h('p') }, meta: { keepAlive: true } },
    { path: '/projects/:project_id/dashboard', name: 'dashboard', component: { render: () => h('div') }, meta: { keepAlive: false } }
  ] })
  await router.push('/agent'); await router.isReady()
  const userStore = reactive({ uid: 'u1' })
  const Shell = defineComponent({ render() { return h('section', this.$slots.default?.()) } })
  const app = renderer.createApp({ components: { RouterView, ProjectLayout: Shell }, setup: () => ({ userStore, route: router.currentRoute }), render })
  app.use(router); app.mount({}); t.after(() => app.unmount()); await settle()
  chat.setupState.draft = '合成未发送草稿'
  await router.push('/work'); await settle();
  await router.push('/agent'); await settle(); assert.equal(chat.setupState.draft, '合成未发送草稿')
  await router.push('/projects/p/dashboard'); await settle(); assert.equal(unmounts, 0)
  await router.push('/agent'); await settle(); assert.equal(mounts, 1); assert.equal(chat.setupState.draft, '合成未发送草稿')
  userStore.uid = 'u2'; await settle(); assert.equal(unmounts, 1); assert.equal(mounts, 2); assert.equal(chat.setupState.draft, '')
})
