import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, ssrContextKey } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createServer } from 'vite'
import { message } from 'ant-design-vue'
import { createPinia, setActivePinia } from 'pinia'

let vite, View, api, agentApi
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: View } = await vite.ssrLoadModule('/src/views/ProjectInspectionBoardView.vue'))
  ;({ governanceBoardApi: api } = await vite.ssrLoadModule('/src/apis/governance_board_api.js'))
  ;({ projectAgentApi: agentApi } = await vite.ssrLoadModule('/src/apis/project_agent_api.js'))
})
after(async () => {
  await vite?.close()
  delete globalThis.localStorage
})
const renderer = createRenderer({
  createElement: () => ({}),
  createText: () => ({}),
  createComment: () => ({}),
  insert() {},
  remove() {},
  setText() {},
  setElementText() {},
  patchProp() {},
  parentNode: () => null,
  nextSibling: () => null
})
const settle = async () => {
  await nextTick()
  await new Promise((resolve) => setImmediate(resolve))
}

/** 挂载真实页面 setup 并提供受控项目事实。 */
async function mountWorkbench(t) {
  t.mock.method(message, 'success', () => {})
  t.mock.method(api, 'getProjectBoard', async () => ({
    project: { id: 'p' },
    governance: {},
    execution: {}
  }))
  t.mock.method(api, 'listBlueprints', async () => ({ documents: [{ name: 'plan.md' }] }))
  t.mock.method(api, 'listBlueprintArchives', async () => ({ documents: [] }))
  t.mock.method(api, 'getBlueprint', async () => ({ name: 'plan.md', content: '磁盘正文' }))
  t.mock.method(api, 'listDelegations', async () => [])
  t.mock.method(api, 'listTopics', async () => [])
  t.mock.method(agentApi, 'list', async () => ({ agents: [] }))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/projects/:project_id/inspection',
        name: 'ProjectInspectionBoardComp',
        component: View
      }
    ]
  })
  await router.push('/projects/p/inspection')
  let instance
  const app = renderer.createApp({
    ...View,
    render() {
      instance = getCurrentInstance()
      return h('div')
    }
  })
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await settle()
  return instance.setupState
}

test('重命名保留未保存正文与保存基线，同名失败保留原选择和草稿', async (t) => {
  const state = await mountWorkbench(t)
  state.blueprintContent = '尚未保存的编辑'
  state.renameBlueprintDraft = 'API设计（第二版）'
  state.renameBlueprintOpen = true
  const rename = t.mock.method(api, 'renameBlueprint', async () => ({
    name: 'API设计（第二版）.md'
  }))
  await state.renameBlueprint()
  assert.equal(state.loadedBlueprintName, 'API设计（第二版）.md')
  assert.equal(state.blueprintName, 'API设计（第二版）.md')
  assert.equal(state.blueprintContent, '尚未保存的编辑')
  assert.equal(state.savedBlueprintContent, '磁盘正文')
  assert.deepEqual(
    state.blueprints.map((doc) => doc.name),
    ['API设计（第二版）.md']
  )
  assert.equal(state.renameBlueprintOpen, false)
  state.renameBlueprintOpen = true
  rename.mock.mockImplementation(async () => {
    throw new Error('同名蓝图已存在')
  })
  await state.renameBlueprint()
  assert.equal(state.blueprintName, 'API设计（第二版）.md')
  assert.equal(state.blueprintContent, '尚未保存的编辑')
  assert.equal(state.renameBlueprintOpen, true)
  assert.match(state.renameBlueprintError, /同名/)
})

test('删除失败保留未保存正文，成功丢弃草稿并回读空列表', async (t) => {
  const state = await mountWorkbench(t)
  state.blueprintContent = '待丢弃编辑'
  state.openBlueprintDelete(false)
  const remove = t.mock.method(api, 'deleteBlueprint', async () => {
    throw new Error('删除失败')
  })
  await state.deleteBlueprint()
  assert.equal(state.blueprintContent, '待丢弃编辑')
  assert.equal(state.deleteBlueprintOpen, true)
  remove.mock.mockImplementation(async () => {})
  t.mock.method(api, 'listBlueprints', async () => ({ documents: [] }))
  await state.deleteBlueprint()
  assert.equal(state.blueprintContent, '')
  assert.equal(state.savedBlueprintContent, '')
  assert.equal(state.blueprintName, '')
  assert.deepEqual(state.blueprints, [])
  assert.equal(state.deleteBlueprintOpen, false)
})


test('删除收到真实 204 空 Response 后关闭弹窗并回读列表', async (t) => {
  setActivePinia(createPinia())
  const { useUserStore } = await vite.ssrLoadModule('/src/stores/user.js')
  useUserStore().token = 'test-token'
  const state = await mountWorkbench(t)
  state.openBlueprintDelete(false)
  t.mock.method(globalThis, 'fetch', async () =>
    new Response(null, { status: 204, headers: { 'content-type': 'application/json' } })
  )
  t.mock.method(api, 'listBlueprints', async () => ({ documents: [] }))

  await state.deleteBlueprint()

  assert.equal(state.deleteBlueprintError, '')
  assert.equal(state.deleteBlueprintOpen, false)
  assert.equal(state.blueprintName, '')
  assert.deepEqual(state.blueprints, [])
})

 test('归档议题读取失败仍加载蓝图，并明确展示局部错误', async (t) => {
  const state = await mountWorkbench(t)
  t.mock.method(api, 'listTopics', async () => { throw new Error('议题列表读取失败') })
  await state.load()
  assert.equal(state.savedBlueprintContent, '磁盘正文')
  assert.match(state.actionError, /议题列表读取失败/)
})
