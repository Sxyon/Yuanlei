import { apiGet, apiPost, apiPut, apiRequest, buildQuery } from './base'
import { sha256 } from '@/components/project/themes/contract'

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
  async asset({ versionId, sourceId, revision, projectId, generation, alias, signal }) {
    const path = generation
      ? `/api/projects/${encodeURIComponent(projectId)}/theme/assets?${buildQuery({ expected_generation: generation, alias })}`
      : versionId
        ? `/api/theme-versions/${encodeURIComponent(versionId)}/assets?${query(projectId, { alias })}`
        : sourcePath(sourceId, 'candidate/assets', projectId, { expected_revision: revision, alias })
    const response = await apiGet(path, { signal, cache: 'no-store' }, true, 'blob')
    const bytes = new Uint8Array(await response.arrayBuffer())
    const mediaType = response.headers.get('Content-Type')?.split(';')[0].trim()
    return { state: 'ready', bytes, metadata: { mediaType, size: bytes.length, sha256: await sha256(bytes) } }
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

/** 正式S04页面只读包内资源，业务和指定文件内容留S05。 */
export function createS04Adapter(projectId, generation) {
  return {
    read(binding, context, signal) {
      if (binding.kind === 'asset') return projectThemeApi.asset({ projectId, generation, alias: binding.alias, signal })
      return Promise.resolve({ state: 'unbound', message: binding.kind === 'file' ? '文件映射已保存；项目文件内容待 S05 接通' : '真实业务数据待 S05 接通' })
    },
    readObject() { return Promise.resolve({ state: 'error', message: '真实业务对象待 S05 接通，请使用项目工作台' }) }
  }
}
