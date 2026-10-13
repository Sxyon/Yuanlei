import assert from 'node:assert/strict'
import test from 'node:test'
import { createRenderer, getCurrentInstance, h, nextTick, reactive, ssrContextKey } from 'vue'
import { createServer } from 'vite'
import { setImmediate } from 'node:timers'

const flush = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)); await nextTick() }
const waitFor = async predicate => { for (let i = 0; i < 50; i++) { if (predicate()) return; await flush() } assert.ok(predicate(), '组件状态未收敛') }

test('第三份独立定义复用同宿主；旧选择/项目数据与错误不提交，类型和返回准确', async () => {
  const vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  let app
  try {
    const { default: Host } = await vite.ssrLoadModule('/src/components/project/themes/ThemeHost.vue')
    const definition = { manifest: { formatVersion: 1, componentAbi: 1, theme: 'theme.json', source: '独立测试消费者', files: {}, assets: {} }, theme: { id: 'third-consumer', version: '1.0', name: '第三个独立消费者', topicLabel: '战略规划', pages: [{ id: 'read', title: '自定义阅读页', description: '证明宿主不识别两个主题ID', layout: 'reading', blocks: [{ id: 'selector', title: '选择', type: 'records', region: 'aside', variant: 'selector', binding: { kind: 'business', resource: 'topics', scope: 'project' } }, { id: 'topic', title: '问题', type: 'topic', region: 'main', binding: { kind: 'business', resource: 'selectedTopic' } }] }, { id: 'other', title: '另一页', description: '有限导航', layout: 'full', blocks: [{ id: 'topics', title: '目录', type: 'records', region: 'main', variant: 'list', binding: { kind: 'business', resource: 'topics', scope: 'project' } }] }] }, reference: 'fixture-third', digest: 'a'.repeat(64) }
    const topic = (project, suffix) => ({ id: `${project}-${suffix}`, project_id: project, title: `${project} ${suffix}`, summary: '摘要', expected_outcome: '预期', admission_status: 'canonical', progress: 'open' })
    let visibleTopics = null
    const pending = []
    let defer = true
    const adapter = {
      read(binding, context) {
        if (binding.resource === 'topics') return Promise.resolve({ state: 'ready', value: visibleTopics || [topic(context.projectId, 'first'), topic(context.projectId, 'second')] })
        if (!context.selectedTopicId) return Promise.resolve({ state: 'unbound', message: '请先选择' })
        if (!defer) return Promise.resolve({ state: 'ready', value: topic(context.projectId, context.selectedTopicId.endsWith('first') ? 'first' : 'second') })
        return new Promise((resolve, reject) => pending.push({ context, resolve, reject }))
      },
      readObject(event, context) { return Promise.resolve({ state: 'ready', value: topic(context.projectId, event.id.endsWith('first') ? 'first' : 'second'), related: {} }) }
    }
    const props = reactive({ projectId: 'project-a', userId: 'user-a' })
    let instance
    const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}), insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
    const CapturedHost = { ...Host, render() { instance = getCurrentInstance(); return h('div') } }
    app = renderer.createApp({ render: () => h(CapturedHost, { ...props, themePackage: definition, adapter }) })
    app.provide(ssrContextKey, { modules: new Set() }); app.mount({})
    const state = () => instance.setupState
    await waitFor(() => state().selectedTopicId === 'project-a-first' && pending.length)
    const old = pending.at(-1)
    await state().navigate({ kind: 'selectTopic', id: 'project-a-second' })
    await waitFor(() => pending.at(-1).context.selectedTopicId === 'project-a-second')
    pending.at(-1).resolve({ state: 'ready', value: topic('project-a', 'second') })
    await waitFor(() => state().results.topic?.value?.id === 'project-a-second')
    old.reject(new Error('旧议题错误'))
    await flush(); assert.equal(state().results.topic.value.id, 'project-a-second')
    await state().navigate({ kind: 'selectTopic', id: 'project-a-first' })
    await waitFor(() => pending.at(-1).context.selectedTopicId === 'project-a-first')
    const oldProject = pending.at(-1)
    props.projectId = 'project-b'
    await waitFor(() => pending.at(-1).context.projectId === 'project-b')
    pending.at(-1).resolve({ state: 'ready', value: topic('project-b', 'first') })
    await waitFor(() => state().results.topic?.value?.project_id === 'project-b')
    oldProject.resolve({ state: 'ready', value: topic('project-a', 'first') })
    await flush(); assert.equal(state().results.topic.value.project_id, 'project-b')
    await state().navigate({ kind: 'selectTopic', id: 'foreign-topic' }); assert.match(state().navigationError, /不在当前/)
    await state().navigate({ kind: 'page', pageId: 'unknown' }); assert.match(state().navigationError, /没有此页面/)
    state().content = { scrollTop: 120, querySelector: () => null, querySelectorAll: () => [] }
    void state().loadPage()
    await waitFor(() => state().results.topic?.state === 'loading')
    await state().navigate({ kind: 'object', objectType: 'topic', id: 'project-b-first' })
    assert.equal(state().detail.value.id, 'project-b-first')
    defer = false
    await state().returnToPage()
    assert.equal(state().selectedTopicId, 'project-b-first'); assert.equal(state().pageId, 'read'); assert.equal(state().content.scrollTop, 120)
    assert.equal(state().results.topic.state, 'ready', '返回后重读被详情导航取消的原页面请求')
    await state().navigate({ kind: 'object', objectType: 'topic', id: 'project-b-absent' })
    assert.match(state().detail.message, /身份不一致/)
    await state().returnToPage()
    adapter.readObject = async () => ({ state: 'ready', value: { id: 'work-a', project_id: 'project-b', title: '工作', topic_id: null, source_decision_id: 'decision-a', source_decision_revision: 1, number: 'DEMO-GEN-000001', description: null, status: 'in_progress' }, sourceRevision: { decision_id: 'other-decision', revision_number: 1, conclusion: '错误来源' } })
    await state().navigate({ kind: 'object', objectType: 'workTask', id: 'work-a' })
    assert.match(state().detail.message, /历史来源/)
    await state().returnToPage()
    adapter.readObject = async () => ({ state: 'ready', value: { ...topic('project-b', 'first'), topic_id: 'project-b-second', conclusion: '决定', rationale: null, status: 'approved', revision_number: 1 }, related: { topics: [topic('project-b', 'first')] } })
    await state().navigate({ kind: 'object', objectType: 'decision', id: 'project-b-first' })
    assert.match(state().detail.message, /关联对象与来源引用/)
    await state().returnToPage()
    const objects = []
    adapter.readObject = (event, context) => new Promise((resolve, reject) => objects.push({ event, context, resolve, reject }))
    for (const staleError of [false, true]) {
      const first = state().navigate({ kind: 'object', objectType: 'topic', id: 'project-b-first' })
      await waitFor(() => objects.at(-1)?.event.id === 'project-b-first')
      const stale = objects.at(-1)
      const second = state().navigate({ kind: 'object', objectType: 'topic', id: 'project-b-second' })
      await waitFor(() => objects.at(-1)?.event.id === 'project-b-second')
      objects.at(-1).resolve({ state: 'ready', value: topic('project-b', 'second'), related: {} })
      await second
      if (staleError) stale.reject(new Error('旧对象错误'))
      else stale.resolve({ state: 'ready', value: topic('project-b', 'first'), related: {} })
      await first; await flush()
      assert.equal(state().detail.value.id, 'project-b-second', `旧对象${staleError ? '错误' : 'DTO'}不得覆盖新对象`)
      await state().returnToPage()
      const leaving = state().navigate({ kind: 'object', objectType: 'topic', id: 'project-b-first' })
      await waitFor(() => state().detail?.state === 'loading')
      const abandoned = objects.at(-1)
      await state().returnToPage()
      if (staleError) abandoned.reject(new Error('已返回对象错误'))
      else abandoned.resolve({ state: 'ready', value: topic('project-b', 'first'), related: {} })
      await leaving; await flush()
      assert.equal(state().detailEvent, null)
      assert.equal(state().detail, null, '返回后的旧对象响应不得重新打开详情')
      assert.equal(state().pageId, 'read'); assert.equal(state().selectedTopicId, 'project-b-first')
      assert.equal(state().results.topic.state, 'ready')
    }
    defer = false
    visibleTopics = [topic('project-b', 'third')]
    state().queries = { '["read","selector"]': { offset: 20, limit: 20 } }
    await state().loadPage()
    assert.equal(state().selectedTopicId, 'project-b-first', '目录分页没有当前议题时仍保留准确选择')
    assert.equal(state().results.topic.value.id, 'project-b-first', '讨论/详情继续绑定原议题，不从当前页推断选择')
    await state().navigate({ kind: 'page', pageId: 'other' })
    await waitFor(() => state().results.topics?.state === 'ready')
    assert.equal(state().selectedTopicId, 'project-b-first', '切到另一目录页不重置准确选择')
    await state().navigate({ kind: 'page', pageId: 'other' }); assert.equal(state().pageId, 'other')
  } finally { app?.unmount(); await vite.close() }
})
