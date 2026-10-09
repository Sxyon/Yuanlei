import assert from 'node:assert/strict'
import test from 'node:test'
import { createRenderer, h, nextTick, ref } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { clearReturnScroll, useReturnScroll } from '../../src/utils/pageReturnScroll.js'

const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}), insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
const settle = async () => { await nextTick(); await nextTick() }

test('来源回读后恢复准确路由的滚动；不同查询与登出后的会话不复用', async t => {
  clearReturnScroll()
  let node, loading
  const Source = { setup() { node = { scrollTop: 0 }; loading = ref(true); useReturnScroll(loading, () => node); return () => h('div') } }
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/source', component: Source }, { path: '/result', component: { render: () => h('div') } }
  ] })
  await router.push('/source?filter=one'); await router.isReady()
  const app = renderer.createApp({ render: () => h(RouterView) }); app.use(router); app.mount({}); t.after(() => app.unmount()); await settle()
  loading.value = false; await settle(); node.scrollTop = 480
  await router.push('/result'); await router.push('/source?filter=one'); await settle()
  assert.equal(node.scrollTop, 0)
  loading.value = false; await settle(); assert.equal(node.scrollTop, 480)
  await router.push('/result'); await router.push('/source?filter=two'); await settle()
  loading.value = false; await settle(); assert.equal(node.scrollTop, 0)
  await router.push('/result'); clearReturnScroll(); await router.push('/source?filter=one'); await settle()
  loading.value = false; await settle(); assert.equal(node.scrollTop, 0)
})
