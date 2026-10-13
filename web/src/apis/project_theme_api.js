import { apiGet, apiPost, apiPut, apiRequest, buildQuery } from './base'
import { governanceBoardApi } from './governance_board_api'
import { projectWorkApi } from './project_work_api'

const query = (projectId, extra = {}) => buildQuery({ project_id: projectId || undefined, ...extra })
const sourcePath = (id, action, projectId, extra) => `/api/theme-sources/${encodeURIComponent(id)}/${action}?${query(projectId, extra)}`

export const projectThemeApi = {
  catalog: projectId => apiGet(`/api/theme-sources?${query(projectId)}`, { cache: 'no-store' }),
  create: body => apiPost('/api/theme-sources', body),
  candidate: (id, projectId) => apiGet(sourcePath(id, 'candidate', projectId), { cache: 'no-store' }),
  upload: (id, projectId, revision, file) => apiRequest(sourcePath(id, 'candidate', projectId, { expected_revision: revision }), { method: 'PUT', body: file, headers: { 'Content-Type': 'application/zip' } }),
  edit: (id, projectId, body) => apiPut(sourcePath(id, 'definition', projectId), body),
  publish: (id, projectId, revision) => apiPost(sourcePath(id, 'publish', projectId), { expected_revision: revision }),
  status: (id, projectId, status, reason) => apiPut(sourcePath(id, 'status', projectId), { status, reason }),
  audit: (id, projectId) => apiGet(sourcePath(id, 'audit', projectId)),
  cleanup: (id, projectId) => apiPost(sourcePath(id, 'cleanup', projectId), {}),
  version: (id, projectId, signal) => apiGet(`/api/theme-versions/${encodeURIComponent(id)}?${query(projectId)}`, { signal, cache: 'no-store' }),
  binding: (projectId, signal) => apiGet(`/api/projects/${encodeURIComponent(projectId)}/theme`, { signal, cache: 'no-store' }),
  select: (projectId, body) => apiPut(`/api/projects/${encodeURIComponent(projectId)}/theme`, body),
  async file(projectId, generation, alias, signal) {
    const response = await apiGet(`/api/projects/${encodeURIComponent(projectId)}/theme/files?${buildQuery({ expected_generation: generation, alias })}`, { signal, cache: 'no-store' }, true, 'blob')
    return resourceResponse(response)
  },
  async asset({ versionId, sourceId, revision, projectId, generation, alias, signal }) {
    const path = generation
      ? `/api/projects/${encodeURIComponent(projectId)}/theme/assets?${buildQuery({ expected_generation: generation, alias })}`
      : versionId
        ? `/api/theme-versions/${encodeURIComponent(versionId)}/assets?${query(projectId, { alias })}`
        : sourcePath(sourceId, 'candidate/assets', projectId, { expected_revision: revision, alias })
    const response = await apiGet(path, { signal, cache: 'no-store' }, true, 'blob')
    return resourceResponse(response)
  }
}

/** 同一加载接口从数据库准确绑定消费真实版本；不以样例ID分支。 */
export function createProjectThemeLoader(projectId) {
  return {
    async load({ signal }) {
      const result = await projectThemeApi.binding(projectId, signal)
      if (result.state !== 'ready') {
        const error = new Error(result.error?.message || '项目尚未选择主题')
        error.selection = result
        throw error
      }
      return { ...result.package, selection: result }
    }
  }
}

/** 响应元数据取服务端同一字节声明，宿主独立校验指纹与长度。 */
async function resourceResponse(response) {
  const bytes = new Uint8Array(await response.arrayBuffer())
  const mediaType = response.headers.get('Content-Type')?.split(';')[0].trim()
  return { state: 'ready', bytes, metadata: { mediaType, size: Number(response.headers.get('X-Theme-Size')), sha256: response.headers.get('X-Theme-Sha256') } }
}

/** 固定逻辑绑定消费原业务API，每轮重查当前绑定，不持久缓存业务事实。 */
export function createProjectThemeAdapter(projectId, generation) {
  const checks = new WeakMap()
  async function checkSelection(signal) {
    try {
      const selection = await projectThemeApi.binding(projectId, signal)
      if (selection.state !== 'ready' || selection.generation !== generation) throw new Error(selection.error?.message || '项目主题选择已变化，请重新读取')
    } catch (error) {
      if (error.name !== 'AbortError') error.contextInvalid = true
      throw error
    }
  }
  async function authorize(signal) {
    if (!checks.has(signal)) checks.set(signal, checkSelection(signal))
    return checks.get(signal)
  }
  async function guarded(signal, action) {
    try { await authorize(signal); const result = await action(); await checkSelection(signal); return result }
    catch (error) {
      if (error.status === 404 && !error.contextInvalid) await checkSelection(signal)
      if ([401, 403].includes(error.status) || error.contextInvalid || error.response?.data?.detail?.code === 'project_denied' || error.response?.data?.detail?.code === 'binding_conflict') {
        error.contextInvalid = true
        throw error
      }
      const code = error.response?.data?.detail?.code
      if (code === 'file_unbound') return { state: 'unbound', message: error.message }
      if (error.status === 404) return { state: 'missing', message: error.message }
      return { state: 'error', message: error.message }
    }
  }
  return {
    read(binding, context, signal) {
      return guarded(signal, async () => {
        if (context.projectId !== projectId || context.bindingGeneration !== generation) throw Object.assign(new Error('项目主题上下文已变化'), { contextInvalid: true })
        if (binding.kind === 'asset') return projectThemeApi.asset({ projectId, generation, alias: binding.alias, signal })
        if (binding.kind === 'file') return projectThemeApi.file(projectId, generation, binding.alias, signal)
        const { offset = 0, limit = 20, search = '', progress = '', statuses = [] } = context.query || {}
        const topicId = context.selectedTopicId
        if ((binding.scope === 'selectedTopic' || ['selectedTopic', 'discussions'].includes(binding.resource)) && !topicId) return { state: 'unbound', message: '请先选择当前议题' }
        if (binding.resource === 'project') return { state: 'ready', value: await governanceBoardApi.businessSummary(projectId, signal) }
        if (binding.resource === 'selectedTopic') return { state: 'ready', value: await governanceBoardApi.topic(projectId, topicId, signal) }
        let result
        if (binding.resource === 'topics') result = await governanceBoardApi.topicsPage(projectId, { offset, limit, search, progress, statuses }, signal)
        else if (binding.resource === 'decisions') result = await governanceBoardApi.decisionsPage(projectId, { offset, limit, statuses, topic_id: binding.scope === 'selectedTopic' ? topicId : undefined }, signal)
        else if (binding.resource === 'workTasks') result = await projectWorkApi.tasksPage(projectId, { offset, limit, statuses, topic_id: binding.scope === 'selectedTopic' ? topicId : undefined }, signal)
        else if (binding.resource === 'discussions') result = await governanceBoardApi.commentsPage(projectId, topicId, { offset, limit }, signal)
        else throw new Error('未知业务绑定')
        return { state: result.items.length ? 'ready' : 'empty', value: result.items, pagination: result.pagination, contextTopic: result.contextTopic, relatedCounts: result.relatedCounts }
      })
    },
    readObject(event, context, signal) {
      return guarded(signal, async () => {
        let value
        if (event.objectType === 'topic') value = await governanceBoardApi.topic(projectId, event.id, signal)
        else if (event.objectType === 'decision') value = await governanceBoardApi.getDecision(projectId, event.id)
        else if (event.objectType === 'workTask') value = await projectWorkApi.getTask(projectId, event.id)
        else throw new Error('未知业务对象')
        let sourceRevision = null
        if (value.source_decision_id && value.source?.decision?.snapshot) sourceRevision = { ...value.source.decision.snapshot, decision_id: value.source_decision_id, revision_number: value.source_decision_revision }
        return { state: 'ready', value, related: {}, sourceRevision }
      })
    }
  }
}
