import assert from 'node:assert/strict'
import { before, after, test } from 'node:test'
import { setImmediate } from 'node:timers'
import { createRenderer, getCurrentInstance, h, nextTick, reactive, computed, ssrContextKey } from 'vue'
import { createServer } from 'vite'

let vite, Discussion, Outcome, api, utils
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: Discussion } = await vite.ssrLoadModule('/src/components/project/TopicDiscussionCard.vue'))
  ;({ default: Outcome } = await vite.ssrLoadModule('/src/components/project/TopicOutcomePanel.vue'))
  ;({ governanceBoardApi: api } = await vite.ssrLoadModule('/src/apis/governance_board_api.js'))
  utils = await vite.ssrLoadModule('/src/utils/topicFollowup.js')
})
after(async () => { await vite?.close(); delete globalThis.localStorage })
const renderer = createRenderer({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {},
  parentNode: () => null, nextSibling: () => null
})
const settle = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }
function mount(t, component, props) {
  let instance
  const events = []
  const Comp = { ...component, render() { instance = getCurrentInstance(); return h('div') } }
  const app = renderer.createApp({ render: () => h(Comp, { ...props, onUpdated: () => events.push('updated') }) })
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  return { state: instance.setupState, app, events }
}
const comment = () => reactive({ id: 'comment', content: '原评论', dispositions: [], replies: [] })
const topic = () => reactive({ id: 'topic', revision_number: 2, expected_outcome: '目标', verification_conditions: '条件' })

test('同一意图重试沿用请求标识，编辑后生成新标识；引用键含准确版本', () => {
  const draft = {}
  const first = utils.stableIntent(draft, { explanation: '采纳', expected_version: 0 })
  const retry = utils.stableIntent(draft, { explanation: '采纳', expected_version: 0 })
  assert.equal(first.operation_id, retry.operation_id)
  assert.notEqual(first.operation_id, utils.stableIntent(draft, { explanation: '修正', expected_version: 0 }).operation_id)
  assert.notEqual(utils.candidateKey({ kind: 'decision', id: 'a', version: 1 }), utils.candidateKey({ kind: 'decision', id: 'a', version: 2 }))
  assert.match(utils.candidateTitle({ title: '决定', version: 2, status: 'superseded' }), /已替代/)
})

test('目标条件变更提示旧确认，纯正文修订不冒充目标改变', () => {
  const current = topic()
  const record = { expected_outcome: '目标', verification_conditions: '条件', revision_number: 1 }
  assert.equal(utils.confirmationConditionsChanged(current, record), false)
  current.verification_conditions = '新条件'
  assert.equal(utils.confirmationConditionsChanged(current, record), true)
})

test('回复失败保留草稿，相同内容重试幂等，迟到成功不清空离开后的草稿', async t => {
  let finish
  const requests = []
  t.mock.method(api, 'createTopicComment', (...args) => {
    requests.push(args)
    if (requests.length === 1) return Promise.reject(new Error('发送失败'))
    return new Promise(resolve => { finish = resolve })
  })
  const draft = reactive({})
  const { state, app } = mount(t, Discussion, { projectId: 'project', topicId: 'topic', comment: comment(), candidates: [], draft })
  draft.replies.comment.content = '未发送回复'
  await state.postReply()
  assert.equal(draft.replies.comment.content, '未发送回复')
  assert.match(state.error, /发送失败/)
  const retry = state.postReply()
  assert.equal(requests[0][4].operation_id, requests[1][4].operation_id)
  app.unmount()
  finish({ id: 'reply' })
  await retry
  assert.equal(draft.replies.comment.content, '未发送回复')
})

test('处置表单固定打开时版本，冲突保留正文和引用', async t => {
  const original = comment()
  original.dispositions = [{ version: 1, disposition: 'partial' }]
  let request
  t.mock.method(api, 'recordTopicDisposition', async (...args) => { request = args[3]; throw new Error('处置版本冲突') })
  const draft = reactive({})
  const { state } = mount(t, Discussion, { projectId: 'project', topicId: 'topic', comment: original, candidates: [], draft })
  state.openDisposition()
  draft.dispositions.comment.explanation = '我新的判断'
  original.dispositions = [{ version: 2, disposition: 'adopted' }]
  await settle()
  await state.saveDisposition()
  assert.equal(request.expected_version, 1)
  assert.equal(draft.dispositions.comment.explanation, '我新的判断')
  assert.match(state.error, /冲突/)
  assert.equal(original.content, '原评论')
})

test('实际确认固定当次修订和确认版本，冲突保留依据；更正不调用任务或Run接口', async t => {
  const current = topic(), draft = reactive({}), confirmations = reactive([{ version: 1 }])
  let request
  t.mock.method(api, 'recordTopicConfirmation', async (...args) => { request = args[2]; throw new Error('条件已变更') })
  const { state } = mount(t, Outcome, { projectId: 'project', topic: current, candidates: [], confirmations, draft })
  state.openForm('correct')
  draft.outcome.explanation = '更正范围'
  draft.outcome.evidenceValue = 'https://example.com/check'
  current.revision_number = 3
  confirmations[0] = { version: 2 }
  await settle()
  await state.save()
  assert.equal(request.expected_revision, 2)
  assert.equal(request.expected_version, 1)
  assert.equal(request.action, 'correct')
  assert.equal(draft.outcome.explanation, '更正范围')
  assert.equal(draft.outcome.evidenceValue, 'https://example.com/check')
  assert.match(state.error, /条件已变更/)
})


test('回复成功后同文再次发布使用新标识，不吞掉新的独立回复', async t => {
  const ids = []
  t.mock.method(api, 'createTopicComment', async (...args) => { ids.push(args[4].operation_id); return { id: String(ids.length) } })
  const draft = reactive({})
  const { state } = mount(t, Discussion, { projectId: 'project', topicId: 'topic', comment: comment(), candidates: [], draft })
  draft.replies.comment.content = '同文'
  await state.postReply()
  assert.equal(draft.replies.comment.content, '')
  draft.replies.comment.content = '同文'
  await state.postReply()
  assert.equal(ids.length, 2)
  assert.notEqual(ids[0], ids[1])
})


test('候选版本刷新后仍携带原选择，后端冲突保留依据', async t => {
  const original = comment(), draft = reactive({})
  let request
  t.mock.method(api, 'recordTopicDisposition', async (...args) => { request = args[3]; throw new Error('引用已变化') })
  const { state } = mount(t, Discussion, { projectId: 'project', topicId: 'topic', comment: original, candidates: [], draft })
  state.openDisposition()
  draft.dispositions.comment.explanation = '保留旧选择'
  draft.dispositions.comment.referenceKey = utils.candidateKey({ kind: 'result', id: 'old', version: 1 })
  await state.saveDisposition()
  assert.deepEqual(request.reference, { kind: 'result', id: 'old', version: 1 })
  assert.equal(draft.dispositions.comment.explanation, '保留旧选择')
})


test('首次初始化的普通草稿输入后能更新发布与保存状态', async t => {
  const draft = {}
  const { state } = mount(t, Discussion, { projectId: 'project', topicId: 'topic', comment: comment(), candidates: [], draft })
  const canPublish = computed(() => Boolean(state.replyDraft.content.trim()))
  assert.equal(canPublish.value, false)
  state.replyDraft.content = '首次输入'
  await settle()
  assert.equal(canPublish.value, true)
  const outcome = mount(t, Outcome, { projectId: 'project', topic: topic(), candidates: [], confirmations: [], draft: {} })
  const hasExplanation = computed(() => Boolean(outcome.state.outcomeDraft.explanation.trim()))
  assert.equal(hasExplanation.value, false)
  outcome.state.outcomeDraft.explanation = '首次确认'
  await settle()
  assert.equal(hasExplanation.value, true)
})
test('恢复现实确认草稿保留原议题和确认版本，清弃后才采用当前依据', t => {
  const draft = reactive({ outcome: { action: 'confirm', explanation: '旧依据说明', evidenceKind: 'url', evidenceValue: 'https://example.invalid/evidence', expectedRevision: 2, expectedVersion: 1 } })
  const current = topic(); current.revision_number = 3
  const { state } = mount(t, Outcome, { projectId: 'project', topic: current, candidates: [], confirmations: [{ version: 2 }], draft })
  state.openForm('confirm')
  assert.equal(draft.outcome.expectedRevision, 2)
  assert.equal(draft.outcome.expectedVersion, 1)
  assert.match(state.error, /原操作与依据/)
  state.discardDraft()
  assert.equal(draft.outcome.expectedRevision, 3)
  assert.equal(draft.outcome.expectedVersion, 2)
  assert.equal(draft.outcome.explanation, '')
})
test('恢复处置草稿保留准确原版本，清弃后才采用当前记录', t => {
  const draft = reactive({ dispositions: { comment: { disposition: 'adopted', explanation: '旧处理解释', expectedVersion: 1 } } })
  const current = comment(); current.dispositions = [{ version: 2 }]
  const { state } = mount(t, Discussion, { projectId: 'project', topicId: 'topic', comment: current, candidates: [], draft })
  state.openDisposition()
  assert.equal(draft.dispositions.comment.expectedVersion, 1)
  assert.match(state.error, /原处置版本/)
  state.discardDisposition()
  assert.equal(draft.dispositions.comment.expectedVersion, 2)
  assert.equal(draft.dispositions.comment.explanation, '')
})


test('确认提交途中改选引用，迟到成功保留新引用与正文', async t => {
  let finish
  t.mock.method(api, 'recordTopicConfirmation', () => new Promise(resolve => { finish = resolve }))
  const candidates = [{ kind: 'decision', id: 'a', version: 1 }, { kind: 'decision', id: 'b', version: 1 }]
  const draft = reactive({})
  const { state } = mount(t, Outcome, { projectId: 'project', topic: topic(), candidates, confirmations: [], draft })
  state.openForm('confirm')
  state.outcomeDraft.explanation = '核对依据'
  state.outcomeDraft.referenceKey = utils.candidateKey(candidates[0])
  const pending = state.save()
  state.outcomeDraft.referenceKey = utils.candidateKey(candidates[1])
  finish({})
  await pending
  assert.equal(state.outcomeDraft.referenceKey, utils.candidateKey(candidates[1]))
  assert.equal(state.outcomeDraft.explanation, '核对依据')
})
