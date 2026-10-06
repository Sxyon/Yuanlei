import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, reactive, ssrContextKey } from 'vue'
import { message } from 'ant-design-vue'
import { createServer } from 'vite'

let vite, View, api
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: View } = await vite.ssrLoadModule('/src/components/ProjectSettingsModal.vue'))
  ;({ projectApi: api } = await vite.ssrLoadModule('/src/apis/project_api.js'))
})
after(async () => { await vite?.close(); delete globalThis.localStorage })

const renderer = createRenderer({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {},
  parentNode: () => null, nextSibling: () => null
})
const settle = async () => { await nextTick(); await new Promise((resolve) => setImmediate(resolve)) }
const result = (id) => ({
  project: { id, name: id },
  settings: { work_status: 'planned', priority: 'none', owner_type: 'member', owner_id: 'creator', description: '', start_date: null, due_date: null },
  members: [{ id: 'creator', name: '创建者' }], agents: [], knowledge_candidates: [], knowledge_links: []
})
const mount = (t, props) => {
  let instance
  const Component = { ...View, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp({ setup: () => () => h(Component, props) })
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  return () => instance.setupState
}

test('切换项目后迟到的设置响应不能覆盖新项目', async (t) => {
  let finishFirst
  t.mock.method(api, 'getSettings', (id) => id === 'first' ? new Promise((resolve) => { finishFirst = resolve }) : Promise.resolve(result(id)))
  const props = reactive({ open: true, project: { id: 'first' } })
  const state = mount(t, props)
  await settle()
  props.project = { id: 'second' }
  await settle()
  assert.equal(state().draft.name, 'second')
  finishFirst(result('first'))
  await settle()
  assert.equal(state().draft.name, 'second')
  assert.equal(state().loading, false)
})

test('关联保存不覆盖未保存的名称描述，日期错误不发保存请求', async (t) => {
  t.mock.method(api, 'getSettings', async (id) => result(id))
  t.mock.method(api, 'saveKnowledgeLinks', async () => ({ ...result('first'), knowledge_links: [{ kb_id: 'kb', accessible: true, name: '知识库' }] }))
  const save = t.mock.method(api, 'saveSettings', async () => result('first'))
  t.mock.method(message, 'success', () => {})
  const state = mount(t, reactive({ open: true, project: { id: 'first' } }))
  await settle()
  state().draft.name = '未保存名称'
  state().draft.description = '未保存描述'
  state().selectedKnowledge = ['kb']
  await state().saveLinks()
  assert.equal(state().draft.name, '未保存名称')
  assert.equal(state().draft.description, '未保存描述')
  assert.equal(state().data.knowledge_links[0].kb_id, 'kb')
  state().draft.start_date = '2026-10-04'
  state().draft.due_date = '2026-10-03'
  await state().save()
  assert.equal(save.mock.callCount(), 0)
  assert.equal(state().error, '截止日期不得早于开始日期')
})

test('负责人缺失阻止保存，无负责人允许保存并采用服务端回读', async (t) => {
  t.mock.method(api, 'getSettings', async (id) => result(id))
  const save = t.mock.method(api, 'saveSettings', async () => ({ ...result('first'), project: { id: 'first', name: '服务端名称' } }))
  t.mock.method(message, 'success', () => {})
  const saved = []
  const state = mount(t, reactive({ open: true, project: { id: 'first' }, onSaved: (project) => saved.push(project) }))
  await settle()
  state().draft.owner_type = 'agent'
  state().draft.owner_id = null
  await state().save()
  assert.equal(save.mock.callCount(), 0)
  assert.equal(state().error, '请选择负责人')
  state().draft.owner_type = 'none'
  await state().save()
  assert.equal(save.mock.calls[0].arguments[1].owner_id, null)
  assert.equal(saved[0].name, '服务端名称')
  assert.equal(state().data.project.name, '服务端名称')
})

test('负责人单一选择框区分同名成员与智能体，并允许解除责任', async (t) => {
  t.mock.method(api, 'getSettings', async () => ({
    ...result('first'), members: [{ id: 'shared', name: '同名负责人', avatar: 'https://example.com/member.png' }],
    agents: [{ id: 'shared', name: '同名负责人', icon: 'https://example.com/agent.png' }]
  }))
  const state = mount(t, reactive({ open: true, project: { id: 'first' } }))
  await settle()
  const groups = state().ownerOptions
  assert.deepEqual(groups.slice(1).map((group) => group.label), ['成员', '智能体'])
  state().ownerSelection = groups[1].options[0].value
  assert.equal(state().draft.owner_type, 'member')
  assert.equal(state().draft.owner_id, 'shared')
  assert.equal(state().selectedOwner.avatar, 'https://example.com/member.png')
  assert.equal(groups[1].options[0].avatar, 'https://example.com/member.png')
  state().ownerSelection = groups[2].options[0].value
  assert.equal(state().draft.owner_type, 'agent')
  assert.equal(state().draft.owner_id, 'shared')
  assert.equal(state().selectedOwner.icon, 'https://example.com/agent.png')
  assert.equal(groups[2].options[0].avatar, 'https://example.com/agent.png')
  state().ownerSelection = groups[0].value
  assert.equal(state().draft.owner_type, 'none')
  assert.equal(state().draft.owner_id, null)
})


test('长期项目无日期可保存属性，失败保留类型分类标签与原资源草稿', async (t) => {
  t.mock.method(api, 'getSettings', async id => ({ ...result(id), settings: { ...result(id).settings, project_type: 'unspecified', category: null, tags: [] } }))
  const save = t.mock.method(api, 'saveSettings', async () => { throw new Error('保存失败') })
  const state = mount(t, reactive({ open: true, project: { id: 'first' } }))
  await settle()
  Object.assign(state().draft, { project_type: 'ongoing', category: '经营', tags: ['收入'], description: '原描述' })
  state().selectedKnowledge = ['原资源']
  await state().save()
  assert.equal(save.mock.calls[0].arguments[1].start_date, null)
  assert.equal(save.mock.calls[0].arguments[1].due_date, null)
  assert.equal(save.mock.calls[0].arguments[1].owner_id, 'creator')
  assert.equal(state().draft.project_type, 'ongoing')
  assert.equal(state().draft.category, '经营')
  assert.deepEqual(state().draft.tags, ['收入'])
  assert.deepEqual(state().selectedKnowledge, ['原资源'])
  assert.match(state().error, /保存失败/)
})
