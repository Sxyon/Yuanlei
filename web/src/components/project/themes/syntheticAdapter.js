import { sha256 } from './contract.js'

export const syntheticProjects = [
  { id: 'preview-market', name: '市场进入研究', description: '研究区域 A 的进入条件，以证据形成决定，跟踪试点验证。' },
  { id: 'preview-service', name: '服务体验改进', description: '评估支持流程，以观察资料讨论服务改进方案。' }
]

/** 合成对象保留原DTO语义，fixture仅由独立预览消费。 */
export function syntheticProjectData(projectId) {
  const project = syntheticProjects.find(item => item.id === projectId)
  if (!project) throw new Error('合成项目不存在')
  const id = suffix => `${projectId}-${suffix}`
  const numberPrefix = projectId === 'preview-market' ? 'DEMO-RES' : 'DEMO-SVC'
  const topics = [
    { id: id('topic-entry'), project_id: projectId, title: projectId === 'preview-market' ? '是否进入区域 A 市场' : '是否增加异步服务支持', summary: '核对需求强度、服务成本与进入条件，形成小规模试点建议。', expected_outcome: '给出试点或延后建议，并明确可证伪条件。', admission_status: 'canonical', progress: 'decided' },
    { id: id('topic-pricing'), project_id: projectId, title: '试点定价与服务边界', summary: '明确试点服务包含哪些工作，避免交付范围与长期承诺混淆。', expected_outcome: '比较两个方案，列明尚未核实的假设。', admission_status: 'canonical', progress: 'open' },
    { id: id('topic-channel'), project_id: projectId, title: '渠道合作的长期职责、证据归属与跨区域服务交付条件应如何界定', summary: '长标题边界案例；仍在讨论，尚未形成正式决定。', expected_outcome: '明确各方职责与退出条件。', admission_status: 'proposed', progress: 'open' }
  ]
  const decisions = [
    { id: id('decision-pilot'), project_id: projectId, topic_id: id('topic-entry'), title: '批准开展限定范围试点', conclusion: '先验证小规模需求，试点通过后再讨论扩大范围。', rationale: '样本仍有限；以回访资料检验投入与收益。', status: 'approved', revision_number: 2 },
    { id: id('decision-old'), project_id: projectId, topic_id: id('topic-entry'), title: '初步方案：直接扩大投入', conclusion: '该方案已被后续决定替代。', rationale: '历史依据保留供对照。', status: 'superseded', revision_number: 1 },
    { id: id('decision-independent'), project_id: projectId, topic_id: null, title: '保持研究资料可追溯', conclusion: '统一记录资料来源与局限，便于复核。', rationale: '项目级决定，无来源议题。', status: 'approved', revision_number: 1 }
  ]
  const workTasks = [
    { id: id('work-interviews'), project_id: projectId, topic_id: id('topic-entry'), source_decision_id: id('decision-pilot'), source_decision_revision: 1, number: `${numberPrefix}-000001`, title: '完成试点客户回访与验证报告', description: '核对样本偏差，提交可回读的验证资料。', status: 'in_progress' },
    { id: id('work-cost'), project_id: projectId, topic_id: id('topic-pricing'), source_decision_id: null, source_decision_revision: null, number: `${numberPrefix}-000002`, title: '核对试点服务成本', description: '服务时长估计缺少依据，等待补充。', status: 'blocked' }
  ]
  const discussions = topics.flatMap(topic => [
    { id: `${topic.id}-comment-1`, topic_id: topic.id, content: topic.id.endsWith('entry') ? '目前证据支持有限试点，样本不足以支持全面进入。' : '先补充成本资料，再判断价格与职责是否合理。', author_name: '合成研究者', created_at: '2026-10-10T08:00:00Z' },
    { id: `${topic.id}-comment-2`, topic_id: topic.id, content: '需要补充不同服务规模下的成本边界。', author_name: '合成评审者', created_at: '2026-10-12T08:00:00Z' }
  ])
  return { project, topics, decisions, workTasks, discussions }
}

/** 预览适配遵守窄read/readObject协议；故障与延迟属于明确测试控制。 */
export function createSyntheticAdapter(loader, getOptions = () => ({})) {
  const settle = async (result, options, signal) => {
    if (options.delayMs) await new Promise((resolve, reject) => {
      const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve() }, options.delayMs)
      function abort() { clearTimeout(timer); reject(new DOMException('请求取消', 'AbortError')) }
      if (!options.ignoreAbort) {
        if (signal?.aborted) abort()
        else signal?.addEventListener('abort', abort, { once: true })
      }
    })
    if (options.scenario === 'error') throw new Error('合成读取失败；未提交业务修改')
    if (options.scenario === 'denied') return { state: 'denied', message: '合成权限拒绝，当前内容已清空' }
    return result
  }
  return {
    async read(binding, context, signal) {
      const options = { ...getOptions() }
      const data = syntheticProjectData(context.projectId)
      if (options.scenario === 'empty') { data.topics = []; data.decisions = []; data.workTasks = []; data.discussions = [] }
      if (binding.kind === 'asset') {
        const result = await loader.readAsset({ reference: context.packageRef, digest: context.digest, alias: binding.alias, signal })
        return settle(result, options, signal)
      }
      if (binding.kind === 'file') {
        if (['unbound', 'missing'].includes(options.scenario)) return settle({ state: options.scenario, message: options.scenario === 'unbound' ? '指定项目文件尚未绑定' : '指定项目文件不存在' }, options, signal)
        if (binding.alias !== 'survey') return settle({ state: 'unbound', message: '合成适配器未提供该指定文件' }, options, signal)
        const bytes = new TextEncoder().encode(JSON.stringify({ '资料来源': `合成访谈 · ${data.project.name}`, '访谈样本': context.projectId === 'preview-market' ? 24 : 12, '愿意进入试点': context.projectId === 'preview-market' ? 15 : 9, '资料局限': ['样本有限', '未核实付费意愿'] }))
        return settle({ state: 'ready', bytes, metadata: { mediaType: 'application/json', size: bytes.length, sha256: await sha256(bytes) } }, options, signal)
      }
      const resource = binding.resource
      let value
      if (resource === 'project') value = { project: data.project, counts: { topics: data.topics.length, workTasks: data.workTasks.length, approvedDecisions: data.decisions.filter(d => d.status === 'approved').length, blockedTasks: data.workTasks.filter(t => t.status === 'blocked').length } }
      else if (resource === 'selectedTopic') value = data.topics.find(topic => topic.id === context.selectedTopicId)
      else if (resource === 'discussions') value = data.discussions.filter(item => item.topic_id === context.selectedTopicId)
      else value = binding.scope === 'selectedTopic' ? data[resource].filter(item => item.topic_id === context.selectedTopicId) : data[resource]
      const result = value === undefined || (binding.scope === 'selectedTopic' || resource === 'discussions') && !context.selectedTopicId
        ? { state: 'unbound', message: '请先选择当前议题' }
        : { state: Array.isArray(value) && !value.length ? 'empty' : 'ready', value, contextTopic: resource === 'discussions' ? data.topics.find(topic => topic.id === context.selectedTopicId) : undefined, related: resource === 'topics' ? { decisions: data.decisions, workTasks: data.workTasks } : undefined }
      return settle(result, options, signal)
    },
    async readObject(event, context, signal) {
      const options = { ...getOptions() }
      const data = syntheticProjectData(context.projectId)
      const collection = { topic: data.topics, decision: data.decisions, workTask: data.workTasks }[event.objectType]
      const object = collection?.find(item => item.id === event.id)
      if (!object) return settle({ state: 'missing', message: '对象不属于当前合成项目' }, options, signal)
      const topic = data.topics.find(item => item.id === object.topic_id)
      const decision = data.decisions.find(item => item.id === object.source_decision_id)
      return settle({ state: 'ready', value: object, related: { topics: topic ? [topic] : [], decisions: decision ? [decision] : [] }, sourceRevision: decision ? { decision_id: decision.id, revision_number: object.source_decision_revision, conclusion: '限定访谈验证范围，先提交验证资料再讨论扩大投入。', synthetic: true } : null }, options, signal)
    }
  }
}
