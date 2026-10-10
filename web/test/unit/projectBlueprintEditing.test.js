import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, ssrContextKey } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createServer } from 'vite'
import { message, Modal } from 'ant-design-vue'
import { createPinia, setActivePinia } from 'pinia'

let vite, View, api, agentApi, workApi
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: View } = await vite.ssrLoadModule('/src/views/ProjectInspectionBoardView.vue'))
  ;({ governanceBoardApi: api } = await vite.ssrLoadModule('/src/apis/governance_board_api.js'))
  ;({ projectWorkApi: workApi } = await vite.ssrLoadModule('/src/apis/project_work_api.js'))
  ;({ projectAgentApi: agentApi } = await vite.ssrLoadModule('/src/apis/project_agent_api.js'))
})
after(async () => {
  await vite?.close()
  delete globalThis.localStorage
  delete globalThis.document
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
async function mountWorkbench(t, url = '/projects/p/inspection', topics = [], preserve = false) {
  globalThis.document ||= { getElementById: () => null }
  const pinia = createPinia()
  setActivePinia(pinia)
  const { useUserStore } = await vite.ssrLoadModule('/src/stores/user.js')
  const { clearGovernanceDrafts } = await vite.ssrLoadModule('/src/utils/governanceDrafts.js')
  if (!preserve) clearGovernanceDrafts()
  useUserStore().uid = 'draft-test'

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
  t.mock.method(api, 'listTopics', async () => topics)
  t.mock.method(workApi, 'listTasks', async () => [])
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
  await router.push(url)
  let instance
  const app = renderer.createApp({
    ...View,
    render() {
      instance = getCurrentInstance()
      return h('div')
    }
  })
  app.use(pinia)
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
  const state = await mountWorkbench(t)
  useUserStore().token = 'test-token'
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

test('议题保存冲突在编辑区提示并保留标题正文和原因', async t => {
  const state = await mountWorkbench(t)
  state.topicRows = [{ id: 'topic', title: '原标题', summary: '原正文', revision_number: 1 }]
  state.selectedTopicId = 'topic'
  state.beginEditTopic()
  state.editingTopicTitle = '我的标题'
  state.editingTopicSummary = '我的未保存正文'
  state.editingTopicReason = '我的修改原因'
  t.mock.method(api, 'updateTopic', async () => {
    throw { response: { data: { detail: { code: 'revision_conflict', message: '议题已被修改，请重新读取后保存' } } } }
  })
  await state.saveTopicEdit()
  assert.equal(state.editingTopic, true)
  assert.equal(state.editingTopicTitle, '我的标题')
  assert.equal(state.editingTopicSummary, '我的未保存正文')
  assert.equal(state.editingTopicReason, '我的修改原因')
  assert.match(state.topicEditError, /草稿已保留.*复制正文/)
})


test('新建按项目类型推荐模板，模板可编辑且不覆盖已有正文', async (t) => {
  const state = await mountWorkbench(t)
  t.mock.method(api, 'listBlueprints', async () => ({ documents: [{ name: 'plan.md' }], project_type: 'ongoing', shared_workdir: true }))
  await state.load()
  state.openCreateBlueprint()
  assert.equal(state.newBlueprintTemplate, 'ongoing')
  for (const heading of ['预期结果', '衡量方式', '时间与复盘', '约束', '当前重点']) assert.match(state.newBlueprintContent, new RegExp(heading))
  assert.equal(state.blueprintContent, '磁盘正文')
  assert.equal(state.sharedBlueprintDirectory, true)
  state.newBlueprintContent += '我自己的补充'
  let confirmation
  t.mock.method(Modal, 'confirm', options => { confirmation = options })
  state.changeBlueprintTemplate('delivery')
  assert.equal(state.newBlueprintTemplate, 'ongoing')
  assert.match(state.newBlueprintContent, /我自己的补充/)
  state.createBlueprintOpen = false
  state.openCreateBlueprint()
  assert.match(state.newBlueprintContent, /我自己的补充/)
  confirmation.onOk()
  assert.equal(state.newBlueprintTemplate, 'delivery')
  assert.match(state.newBlueprintContent, /计划交付时间/)
  assert.equal(state.blueprintContent, '磁盘正文')
})

test('新建取消不写文件，同名失败保留输入与旧蓝图，成功采用回读正文', async (t) => {
  const state = await mountWorkbench(t)
  const create = t.mock.method(api, 'createBlueprint', async () => { throw new Error('同名蓝图已存在') })
  state.openCreateBlueprint()
  state.newBlueprintName = 'plan'
  state.newBlueprintContent = '新的可复制草稿'
  state.createBlueprintOpen = false
  assert.equal(create.mock.callCount(), 0)
  state.openCreateBlueprint()
  await state.createBlueprint()
  assert.equal(state.newBlueprintName, 'plan')
  assert.equal(state.newBlueprintContent, '新的可复制草稿')
  assert.equal(state.createBlueprintOpen, true)
  assert.match(state.createBlueprintError, /同名/)
  assert.equal(state.blueprintContent, '磁盘正文')
  state.newBlueprintName = '新蓝图'
  create.mock.mockImplementation(async (_id, name, content) => ({ name, content }))
  t.mock.method(api, 'listBlueprints', async () => ({ documents: [{ name: 'plan.md' }, { name: '新蓝图.md' }] }))
  t.mock.method(api, 'getBlueprint', async () => ({ name: '新蓝图.md', content: '新的可复制草稿' }))
  await state.createBlueprint()
  assert.deepEqual(create.mock.calls[1].arguments, ['p', '新蓝图.md', '新的可复制草稿'])
  assert.equal(state.createBlueprintOpen, false)
  assert.equal(state.loadedBlueprintName, '新蓝图.md')
  assert.equal(state.savedBlueprintContent, '新的可复制草稿')
})

test('旧蓝图未保存编辑阻止新建，模板不清空旧编辑草稿', async t => {
  const state = await mountWorkbench(t)
  state.blueprintContent = '旧文档未保存内容'
  state.openCreateBlueprint()
  assert.equal(state.createBlueprintOpen, false)
  assert.equal(state.blueprintContent, '旧文档未保存内容')
  assert.match(state.blueprintActionError, /先保存/)
})


for (const failed of [false, true]) {
  test(`新建蓝图${failed ? '失败' : '成功'}响应迟到时不污染另一项目草稿`, async t => {
    const state = await mountWorkbench(t)
    let finish, fail
    t.mock.method(api, 'createBlueprint', () => new Promise((resolve, reject) => { finish = resolve; fail = reject }))
    state.openCreateBlueprint()
    state.newBlueprintName = '原项目新蓝图'
    state.newBlueprintContent = '原项目请求'
    const creating = state.createBlueprint()
    await state.router.push('/projects/second/inspection')
    await settle()
    state.openCreateBlueprint()
    state.newBlueprintName = '新项目草稿'
    state.newBlueprintContent = '新项目正文'
    if (failed) fail(new Error('原项目创建失败'))
    else finish({ name: '原项目新蓝图.md', content: '原项目正文' })
    await creating
    assert.equal(state.newBlueprintName, '新项目草稿')
    assert.equal(state.newBlueprintContent, '新项目正文')
    assert.equal(state.createBlueprintError, '')
    assert.equal(state.createBlueprintOpen, true)
    assert.notEqual(state.blueprintContent, '原项目正文')
  })
}

test('关闭或切项目后旧模板确认不清空草稿', async t => {
  const state = await mountWorkbench(t)
  let confirmation
  t.mock.method(Modal, 'confirm', options => { confirmation = options })
  state.openCreateBlueprint()
  state.newBlueprintContent = '保留草稿'
  state.changeBlueprintTemplate('delivery')
  state.createBlueprintOpen = false
  confirmation.onOk()
  assert.equal(state.newBlueprintContent, '保留草稿')
  state.openCreateBlueprint()
  state.changeBlueprintTemplate('ongoing')
  await state.router.push('/projects/second/inspection')
  await settle()
  state.openCreateBlueprint()
  state.newBlueprintContent = '另一项目草稿'
  confirmation.onOk()
  assert.equal(state.newBlueprintContent, '另一项目草稿')
})


test('切换议题清理旧评论与修订定位，同议题刷新保留；切换决策清理旧版本', async t => {
  globalThis.document = { getElementById: () => null }
  t.after(() => { delete globalThis.document })
  const state = await mountWorkbench(t, '/projects/p/inspection?topic_id=a&comment_id=old&revision=4&decision_id=d1&decision_revision=3', [{ id: 'a' }, { id: 'b' }])
  state.setTopicRoute('a'); await settle(); await settle()
  assert.equal(state.route.query.comment_id, 'old')
  assert.equal(state.route.query.revision, '4')
  assert.equal(state.route.query.decision_revision, undefined)
  state.selectTopic({ id: 'b' }); await settle(); await settle()
  assert.equal(state.route.query.topic_id, 'b')
  assert.equal(state.route.query.comment_id, undefined)
  assert.equal(state.route.query.revision, undefined)
  await state.router.replace({ query: { topic_id: 'b', decision_id: 'd1', decision_revision: '3' } })
  state.selectDecision('d2'); await settle(); await settle()
  assert.equal(state.route.query.decision_id, 'd2')
  assert.equal(state.route.query.decision_revision, undefined)
})


test('蓝图默认阅读，刷新和重新进入保留未保存正文与原基线', async t => {
  const first = await mountWorkbench(t)
  assert.equal(first.blueprintEditing, false)
  first.blueprintEditing = true
  first.blueprintContent = '跨页独有草稿'
  await first.load()
  assert.equal(first.blueprintContent, '跨页独有草稿')
  const restored = await mountWorkbench(t, '/projects/p/inspection', [], true)
  assert.equal(restored.blueprintContent, '跨页独有草稿')
  assert.equal(restored.savedBlueprintContent, '磁盘正文')
  assert.equal(restored.blueprintEditing, true)
})
test('迟到正文不覆盖请求期间输入，保存失败保留正文', async t => {
  const state = await mountWorkbench(t)
  let resolveRead
  t.mock.method(api, 'getBlueprint', () => new Promise(resolve => { resolveRead = resolve }))
  const pending = state.readBlueprint()
  state.blueprintContent = '读取期间新输入'
  resolveRead({ name: 'plan.md', content: '迟到旧正文' })
  await pending
  assert.equal(state.blueprintContent, '读取期间新输入')
  t.mock.method(api, 'putBlueprint', async () => { throw new Error('写入失败') })
  await state.saveBlueprint()
  assert.equal(state.blueprintContent, '读取期间新输入')
  assert.match(state.blueprintActionError, /写入失败/)
})
test('原议题移除后不会将其编辑草稿转移到另一议题', async t => {
  const topic = { id: 'original', title: '原议题', admission_status: 'proposed', revision_number: 2 }
  const state = await mountWorkbench(t, '/projects/p/inspection?topic_id=original', [topic])
  state.beginEditTopic()
  state.editingTopicSummary = '准确原对象草稿'
  t.mock.method(api, 'listTopics', async () => [{ ...topic, id: 'another', title: '另一议题' }])
  await state.load()
  assert.equal(state.selectedTopicId, '')
  assert.equal(state.editingTopic, false)
  assert.equal(state.editingTopicSummary, '准确原对象草稿')
  assert.match(state.topicCommentError, /不会把原草稿提交到另一议题/)
})
test('无权回读清除当前项目草稿，并阻止重新进入泄漏', async t => {
  const state = await mountWorkbench(t)
  state.blueprintContent = '私有草稿'
  t.mock.method(api, 'getProjectBoard', async () => { throw Object.assign(new Error('无权'), { status: 403 }) })
  await state.load()
  assert.equal(state.blueprintContent, '')
  const { getGovernanceDraft } = await vite.ssrLoadModule('/src/utils/governanceDrafts.js')
  assert.equal(getGovernanceDraft('draft-test', 'p', 'workbench'), null)
})


test('从另一个可见议题深链返回时，A 的编辑草稿不会写到 B', async t => {
  const topics = ['a', 'b'].map(id => ({ id, title: id, summary: id + '正文', revision_number: 1, admission_status: 'canonical' }))
  const a = await mountWorkbench(t, '/projects/p/inspection?topic_id=a', topics)
  a.beginEditTopic(); a.editingTopicSummary = 'A 独有草稿'; a.editingTopicReason = '修改A'
  const b = await mountWorkbench(t, '/projects/p/inspection?topic_id=b', topics, true)
  assert.equal(b.selectedTopicId, 'b')
  assert.equal(b.activeSection, 'topics')
  assert.equal(b.editingTopic, false)
  const writes = t.mock.method(api, 'updateTopic', async () => ({}))
  await b.saveTopicEdit()
  assert.equal(writes.mock.callCount(), 0)
  b.beginEditTopic()
  assert.equal(b.editingTopicId, 'b')
  assert.equal(b.editingTopicSummary, 'b正文')
  const { getGovernanceDraft } = await vite.ssrLoadModule('/src/utils/governanceDrafts.js')
  assert.equal(getGovernanceDraft('draft-test', 'p', 'topic-edit:a').editingTopicSummary, 'A 独有草稿')
})
test('写入失权清除工作台全部活草稿，409冲突仍保留', async t => {
  const state = await mountWorkbench(t)
  state.blueprintContent = '私有编辑'; state.decisionTitle = '私有决策'; state.taskTitle = '私有建议'
  t.mock.method(api, 'putBlueprint', async () => { throw Object.assign(new Error('权限已撤销'), { status: 403 }) })
  await state.saveBlueprint()
  assert.equal(state.blueprintContent, '')
  assert.equal(state.decisionTitle, '')
  assert.equal(state.taskTitle, '')
  const { getGovernanceDraft } = await vite.ssrLoadModule('/src/utils/governanceDrafts.js')
  assert.equal(getGovernanceDraft('draft-test', 'p', 'workbench'), null)
})
test('单对象404且项目仍可见时保留全部草稿，项目404才清理', async t => {
  const state = await mountWorkbench(t)
  state.blueprintContent = '蓝图草稿'; state.decisionTitle = '决策草稿'
  const absent = Object.assign(new Error('单对象不可见'), { status: 404 })
  await state.visibilityLost(absent)
  assert.equal(state.blueprintContent, '蓝图草稿')
  assert.equal(state.decisionTitle, '决策草稿')
  assert.equal(state.errorMessage, '')
  t.mock.method(api, 'getProjectBoard', async () => { throw Object.assign(new Error('项目不可见'), { status: 404 }) })
  await state.visibilityLost(absent)
  assert.equal(state.blueprintContent, '')
  assert.equal(state.decisionTitle, '')
})
