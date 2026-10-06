import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { createRenderer, getCurrentInstance, h, nextTick, ssrContextKey } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createServer } from 'vite'

let vite, Selection, Navigation, useProjectsStore
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: Selection } = await vite.ssrLoadModule('/src/components/ProjectSelectionSection.vue'))
  ;({ default: Navigation } = await vite.ssrLoadModule('/src/components/ConversationNavSection.vue'))
  ;({ useProjectsStore } = await vite.ssrLoadModule('/src/stores/projects.js'))
})
after(async () => { await vite?.close(); delete globalThis.localStorage })
const renderer = createRenderer({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {},
  parentNode: () => null, nextSibling: () => null
})
const projects = [
  { id: 'legacy', name: '旧项目', status: 'active', selection_status: 'selectable' },
  { id: 'ongoing', name: '经营', status: 'active', selection_status: 'selectable', project_type: 'ongoing', category: '运营', tags: ['收入'] }
]
async function mount(t, Component, props, pinia) {
  let instance
  const app = renderer.createApp({ ...Component, render() { instance = getCurrentInstance(); return h('div') } }, props)
  if (pinia) app.use(pinia)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await nextTick()
  return instance.setupState
}

test('项目选择筛选隐藏当前项目时保留名称与选择，清除恢复旧项目', async t => {
  const pinia = createPinia()
  setActivePinia(pinia)
  useProjectsStore().projects = projects
  const selectionEvents = []
  const state = await mount(t, Selection, { modelValue: 'legacy', 'onUpdate:modelValue': id => selectionEvents.push(id) }, pinia)
  state.projectFilters = { type: 'ongoing', category: '运营', tag: '收入' }
  assert.deepEqual(state.filteredProjects.map(p => p.id), ['ongoing'])
  assert.equal(state.currentProject.id, 'legacy')
  assert.equal(state.currentProjectLabel, '旧项目')
  assert.deepEqual(selectionEvents, [])
  state.projectFilters = { type: 'delivery' }
  assert.deepEqual(state.filteredProjects, [])
  state.projectFilters = {}
  assert.deepEqual(state.filteredProjects.map(p => p.id), ['legacy', 'ongoing'])
  assert.deepEqual(selectionEvents, [])
})

test('侧栏筛选只隐藏分组，当前对话仍归原项目且不进入最近对话', async t => {
  const chat = { id: 'chat', project_id: 'legacy', created_at: '2026-10-01' }
  const state = await mount(t, Navigation, { projects, chatsList: [chat], currentChatId: 'chat' })
  state.projectFilters = { type: 'ongoing' }
  assert.deepEqual(state.filteredProjectGroups.map(g => g.project.id), ['ongoing'])
  assert.equal(state.filteredCurrentProject.id, 'legacy')
  assert.deepEqual(state.otherConversations, [])
  assert.equal(state.projectGroups.find(g => g.project.id === 'legacy').conversations[0].id, 'chat')
  state.projectFilters = {}
  assert.equal(state.filteredCurrentProject, undefined)
  assert.equal(state.filteredProjectGroups.length, 2)
})


test('重命名摘要替换 store 后仍符合类型分类标签筛选', async t => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useProjectsStore()
  store.projects = projects
  const state = await mount(t, Selection, { modelValue: 'ongoing' }, pinia)
  state.projectFilters = { type: 'ongoing', category: '运营', tag: '收入' }
  store.replaceProject({ ...projects[1], name: '经营更名' })
  assert.equal(state.filteredProjects[0].name, '经营更名')
  assert.equal(state.currentProjectLabel, '经营更名')
  assert.deepEqual(state.currentProject.tags, ['收入'])
})
