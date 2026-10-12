import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { createContextGate, sha256, validateComponentInput, validateLoadedPackage, validateNavigation, validateResource, validateSourceRevision, validateThemePackage } from '../../src/components/project/themes/contract.js'
import { createSyntheticAdapter } from '../../src/components/project/themes/syntheticAdapter.js'

async function sample(id) {
  const folder = new URL(`../../src/components/project/themes/packages/${id}/`, import.meta.url)
  return { manifest: JSON.parse(await readFile(new URL('manifest.json', folder))), theme: JSON.parse(await readFile(new URL('theme.json', folder))) }
}

test('两份独立正式定义加载；显示别名与原业务绑定分别保留', async () => {
  const first = validateThemePackage(await sample('default')), second = validateThemePackage(await sample('research'))
  assert.deepEqual(first.theme.pages.map(p => p.id), ['dashboard', 'workbench', 'topics'])
  assert.deepEqual(second.theme.pages.map(p => p.id), ['context', 'evidence', 'conclusions'])
  second.theme.topicLabel = '战略规划'
  assert.equal(validateThemePackage(second).theme.pages[0].blocks[0].binding.resource, 'topics')
  const loaded = { ...first, reference: 'host-version-uuid', digest: 'a'.repeat(64) }
  assert.equal(validateLoadedPackage(loaded).reference, 'host-version-uuid')
  assert.notEqual(validateLoadedPackage(loaded).reference, first.theme.id)
  assert.throws(() => validateLoadedPackage({ ...first, digest: 'a'.repeat(64) }), /契约不支持/)
  assert.throws(() => validateLoadedPackage({ ...loaded, digest: 'not-a-digest' }), /契约不支持/)
})

test('结构与跨引用负例按正确原因拒绝，不跳过坏块', async () => {
  const valid = await sample('research')
  const cases = [
    ['invalid_package', p => { p.manifest.componentAbi = 2 }],
    ['invalid_package', p => { p.manifest.formatVersion = '1' }],
    ['invalid_package', p => { p.theme.script = 'alert(1)' }],
    ['invalid_package', p => { p.theme.pages[0].blocks[0].type = 'iframe' }],
    ['invalid_package', p => { p.theme.pages[0].blocks[0].binding.resource = 'tasks' }],
    ['duplicate_page', p => p.theme.pages.push(p.theme.pages[0])],
    ['duplicate_block', p => p.theme.pages[0].blocks.push(p.theme.pages[0].blocks[0])],
    ['record_variant', p => { p.theme.pages[0].blocks[0].binding.resource = 'workTasks' }],
    ['record_scope', p => { p.theme.pages[0].blocks[0].binding.scope = 'selectedTopic' }],
    ['resource_reference', p => { p.theme.pages[1].blocks[1].binding.alias = 'absent' }],
    ['resource_reference', p => { p.manifest.files.survey = 'image/png' }],
    ['page_reference', p => { p.theme.pages[0].blocks[3].action.pageId = 'absent' }],
    ['asset_path', p => { p.manifest.assets.distribution.path = 'assets/../outside.png' }],
    ['asset_path', p => { p.manifest.assets.distribution.path = 'https://example.com/a.png' }],
    ['duplicate_asset', p => { p.manifest.assets.other = p.manifest.assets.distribution }],
    ['invalid_package', p => { p.theme.pages[1].blocks[1].binding.url = 'https://example.com' }]
  ]
  for (const [reason, mutate] of cases) {
    const data = structuredClone(valid); mutate(data)
    assert.throws(() => validateThemePackage(data), cause => cause.code === reason, reason)
  }
})

test('导航只接受类型和引用，不接受执行动作或任意返回URL', () => {
  assert.deepEqual(validateNavigation({ kind: 'object', objectType: 'workTask', id: 'work-a' }), { kind: 'object', objectType: 'workTask', id: 'work-a' })
  for (const event of [{ kind: 'approve', id: 'a' }, { kind: 'object', objectType: 'task', id: 'a' }, { kind: 'page', pageId: 'home', returnUrl: 'https://example.com' }, { kind: 'selectTopic', id: 'a', project_id: 'other' }]) assert.throws(() => validateNavigation(event), /契约不支持/)
})

test('组件输入保留原字段并核对项目、讨论和冻结来源版本', () => {
  const context = { projectId: 'project-a', selectedTopicId: 'topic-a' }
  const task = { id: 'work-a', project_id: 'project-a', title: '工作', topic_id: null, source_decision_id: 'decision-a', source_decision_revision: 1, number: 'DEMO-GEN-000001', description: null, status: 'in_progress', acceptance_criteria: '验收说明' }
  assert.equal(validateComponentInput('workTasks', [task], context)[0].acceptance_criteria, '验收说明')
  assert.throws(() => validateComponentInput('workTasks', [{ ...task, project_id: 'other' }], context), /不属于/)
  assert.throws(() => validateComponentInput('workTasks', [{ ...task, source_decision_revision: null }], context), /必须成对/)
  assert.throws(() => validateComponentInput('discussions', [{ id: 'c', topic_id: 'other-topic', content: '意见', author_name: '作者', created_at: '2026-10-12' }], context), /不属于/)
  assert.throws(() => validateComponentInput('topics', [task], context), /契约不支持/)
  assert.throws(() => validateComponentInput('__proto__', {}, context), /类型不受支持/)
  assert.throws(() => validateComponentInput('selectedTopic', { id: 'other-topic', project_id: 'project-a', title: '其他议题', summary: null, expected_outcome: null, admission_status: 'canonical', progress: 'open' }, context), /当前选择/)
  assert.throws(() => validateComponentInput('workTasks', [task], { ...context, scope: 'selectedTopic' }), /不属于选定议题/)
  const snapshot = { decision_id: 'decision-a', revision_number: 1, conclusion: '当次依据', snapshot: { title: '历史标题' } }
  assert.equal(validateSourceRevision(snapshot, task).snapshot.title, '历史标题')
  assert.throws(() => validateSourceRevision({ ...snapshot, revision_number: 2 }, task), /冻结版本/)
  assert.throws(() => validateSourceRevision({ ...snapshot, conclusion: {} }, task), /契约不支持/)
})

test('资源验证实际字节、类型与指纹；JSON资料不当主题定义执行', async () => {
  const bytes = new TextEncoder().encode('{"title":"资料","script":"文字"}')
  const metadata = { mediaType: 'application/json', size: bytes.length, sha256: await sha256(bytes) }
  assert.equal((await validateResource({ bytes, metadata }, 'application/json')).bytes, bytes)
  await assert.rejects(validateResource({ bytes, metadata: { ...metadata, size: bytes.length + 1 } }, 'application/json'), /不一致/)
  await assert.rejects(validateResource({ bytes, metadata: { ...metadata, sha256: '0'.repeat(64) } }, 'application/json'), /不一致/)
  await assert.rejects(validateResource({ bytes, metadata }, 'image/png'), /不一致/)
  await assert.rejects(validateResource({ bytes, metadata: { ...metadata, mediaType: 'image/png' } }, 'image/png'), /不是 PNG/)
})

test('上下文gate拒绝旧结果和取消后的错误，最新请求仍能提交', async () => {
  const gate = createContextGate(), commits = []
  let resolveOld, rejectOld
  const first = gate.next({ projectId: 'first' })
  const old = new Promise(resolve => { resolveOld = resolve }).then(value => { if (gate.isCurrent(first)) commits.push(value) })
  const failed = new Promise((_, reject) => { rejectOld = reject }).catch(() => { if (gate.isCurrent(first)) commits.push('old-error') })
  const next = gate.next({ projectId: 'second' })
  resolveOld('old-data'); rejectOld(new Error('old'))
  await Promise.all([old, failed])
  assert.deepEqual(commits, [])
  assert.equal(gate.isCurrent(next), true)
  gate.invalidate(); assert.equal(gate.isCurrent(next), false)
})

test('合成适配只提供原对象DTO和逻辑文件；详情核对当前项目', async () => {
  const adapter = createSyntheticAdapter({})
  const context = { projectId: 'preview-market', selectedTopicId: 'preview-market-topic-entry' }
  const records = await adapter.read({ kind: 'business', resource: 'workTasks', scope: 'project' }, context)
  assert.equal(records.value[0].source_decision_revision, 1)
  const detail = await adapter.readObject({ objectType: 'workTask', id: records.value[0].id }, context)
  assert.equal(detail.value.id, records.value[0].id)
  assert.equal(detail.sourceRevision.revision_number, records.value[0].source_decision_revision)
  assert.equal((await adapter.readObject({ objectType: 'workTask', id: records.value[0].id }, { ...context, projectId: 'preview-service' })).state, 'missing')
  assert.equal((await adapter.read({ kind: 'business', resource: 'discussions' }, { ...context, selectedTopicId: '' })).state, 'unbound')
  const resource = await adapter.read({ kind: 'file', alias: 'survey' }, context)
  await validateResource(resource, 'application/json')
  assert.equal((await adapter.read({ kind: 'file', alias: 'not-provided' }, context)).state, 'unbound')
})
