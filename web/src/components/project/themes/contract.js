import Ajv2020 from 'ajv/dist/2020.js'
import { toRaw } from 'vue'
import schemas from './contract.schemas.json' with { type: 'json' }

// 只编译平台随版本发布的Schema，主题包不能提供Schema或代码。
const ajv = new Ajv2020({ allErrors: true, useDefaults: true })
ajv.addKeyword('discriminator')
const validators = Object.fromEntries(Object.entries(schemas).map(([name, schema]) => [name, ajv.compile(schema)]))

export class ThemeContractError extends Error {
  constructor(code, message) { super(message); this.code = code }
}

/** 在加载边界用同源Schema校验，返回独立的规范化副本。 */
function validate(name, value) {
  if (!Object.hasOwn(validators, name)) throw new ThemeContractError('unknown_input', '组件输入类型不受支持')
  const copy = structuredClone(toRaw(value))
  if (!validators[name](copy)) {
    const errors = validators[name].errors
    throw new ThemeContractError('invalid_' + name, `${name} 契约不支持：${errors.map(e => `${e.instancePath || '/'} ${e.message}`).slice(0, 4).join('；')}`)
  }
  return copy
}

/** 页引用、资源声明及组件表现共同构成完整定义。 */
export function validateThemePackage(value) {
  const pack = validate('package', value)
  const ids = pack.theme.pages.map(page => page.id)
  const fail = (code, message) => { throw new ThemeContractError(code, message) }
  if (new Set(ids).size !== ids.length) fail('duplicate_page', '页面 ID 重复')
  const paths = Object.values(pack.manifest.assets).map(asset => asset.path)
  if (new Set(paths).size !== paths.length) fail('duplicate_asset', '包内资源成员重复')
  for (const asset of Object.values(pack.manifest.assets)) {
    if (!asset.path.startsWith('assets/') || /[\\:]/.test(asset.path) || asset.path.split('/').some(p => ['', '.', '..'].includes(p))) fail('asset_path', '资源必须是 assets 下的普通相对成员')
  }
  for (const page of pack.theme.pages) {
    const blocks = page.blocks.map(b => b.id)
    if (new Set(blocks).size !== blocks.length) fail('duplicate_block', '页面内组件 ID 重复')
    for (const block of page.blocks) {
      block.action ??= null
      if (block.type === 'records') block.statuses ??= []
      if (block.action && !ids.includes(block.action.pageId)) fail('page_reference', '导航指向未定义页面')
      if (block.type === 'records') {
        const required = { table: 'topics', selector: 'topics', compactSelector: 'topics', conclusions: 'decisions', history: 'decisions', attention: 'workTasks' }[block.variant]
        if (required && block.binding.resource !== required) fail('record_variant', '表现模式与业务对象类型不匹配')
        if (block.binding.resource === 'topics' && block.binding.scope !== 'project') fail('record_scope', '议题目录使用项目范围')
      }
      if (['json', 'image'].includes(block.type)) {
        const { kind, alias } = block.binding
        const media = kind === 'file' ? pack.manifest.files[alias] : pack.manifest.assets[alias]?.mediaType
        if (media !== (block.type === 'json' ? 'application/json' : 'image/png')) fail('resource_reference', '资料 alias 未声明或 MIME 与组件不匹配')
      }
    }
  }
  return pack
}

/** 加载引用由可信来源提供，作者ID及hash均不能替代来源授权。 */
export function validateLoadedPackage(value) {
  const loaded = validate('loadedPackage', value)
  return { ...loaded, ...validateThemePackage({ manifest: loaded.manifest, theme: loaded.theme }) }
}

/** 组件只产生有限导航事件，页面存在性由当前宿主再核实。 */
export function validateNavigation(value) { return validate('navigation', value) }

/** 当前决定与冻结依据分别读取，快照不能引用相邻版本。 */
export function validateSourceRevision(value, task) {
  const snapshot = validate('sourceRevision', value)
  if (snapshot.decision_id !== task.source_decision_id || snapshot.revision_number !== task.source_decision_revision) throw new ThemeContractError('source_revision', '任务历史来源与冻结版本不一致')
  return snapshot
}

/** 原业务DTO的可读投影；项目和讨论归属在接收边界核对。 */
export function validateComponentInput(resource, value, context) {
  const data = validate(resource, value)
  if (resource === 'project') {
    if (data.project.id !== context.projectId) throw new ThemeContractError('project_scope', '摘要不属于当前项目')
  } else {
    for (const item of Array.isArray(data) ? data : [data]) {
      if (resource === 'discussions' ? item.topic_id !== context.selectedTopicId : item.project_id !== context.projectId) throw new ThemeContractError('object_scope', '响应对象不属于当前上下文')
      if (resource === 'selectedTopic' && item.id !== context.selectedTopicId) throw new ThemeContractError('selection_scope', '响应议题与当前选择不一致')
      if (['decisions', 'workTasks'].includes(resource) && context.scope === 'selectedTopic' && item.topic_id !== context.selectedTopicId) throw new ThemeContractError('selection_scope', '关联集合不属于选定议题')
      if (resource === 'workTasks' && (item.source_decision_id === null) !== (item.source_decision_revision === null)) throw new ThemeContractError('task_source', '正式任务的来源决定与版本必须成对')
    }
  }
  return data
}

/** 验证资源元数据与实际字节，错误不能伪装成空资料。 */
export async function validateResource(value, expectedMediaType) {
  const metadata = validate('resource', value.metadata)
  if (metadata.mediaType !== expectedMediaType || !(value.bytes instanceof Uint8Array) || value.bytes.length !== metadata.size || await sha256(value.bytes) !== metadata.sha256) throw new ThemeContractError('resource_bytes', '资料类型、大小或指纹不一致')
  if (expectedMediaType === 'image/png' && ![137, 80, 78, 71, 13, 10, 26, 10].every((b, i) => value.bytes[i] === b)) throw new ThemeContractError('resource_type', '资料不是 PNG 字节')
  return { metadata, bytes: value.bytes }
}

/** 资源和包的字节指纹来自内容，不来自主题ID。 */
export async function sha256(bytes) {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))).map(b => b.toString(16).padStart(2, '0')).join('')
}

/** 每轮请求共享冻结的上下文token；取消也使迟到错误失效。 */
export function createContextGate() {
  let generation = 0
  return {
    next(context) { return Object.freeze({ ...context, generation: ++generation }) },
    isCurrent(token) { return token.generation === generation },
    invalidate() { generation++ }
  }
}
