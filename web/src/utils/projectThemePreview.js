/** 临时预览意图只携准确引用；返回与应用始终由宿主生成固定平台路由。 */
export const themePreviewKeys = ['theme_preview_version', 'theme_preview_source', 'theme_preview_revision']

/** 解析互斥的准确版本或候选修订引用。 */
export function readThemePreview(query) {
  if (!themePreviewKeys.some(key => query[key] !== undefined)) return null
  const version = query.theme_preview_version, source = query.theme_preview_source, revision = query.theme_preview_revision
  if (typeof version === 'string' && version && source === undefined && revision === undefined) return { versionId: version }
  if (typeof source === 'string' && source && version === undefined && typeof revision === 'string' && /^[1-9]\d*$/.test(revision) && Number.isSafeInteger(Number(revision))) return { sourceId: source, revision: Number(revision) }
  throw new Error('预览引用不完整或冲突，请返回主题管理重新选择准确版本。')
}

/** 生成不参与持久绑定的临时查询。 */
export function themePreviewQuery(intent) {
  return intent.versionId ? { theme_preview_version: intent.versionId } : { theme_preview_source: intent.sourceId, theme_preview_revision: String(intent.revision) }
}

/** 固定进入目标项目总览，不接受任意返回地址。 */
export function themePreviewTarget(projectId, intent) {
  return { name: 'ProjectDashboardComp', params: { project_id: projectId }, query: themePreviewQuery(intent) }
}

/** 完整能力页复用真实宿主，区块包沿原预览。 */
export function supportsWorkspacePreview(pack) {
  return pack?.theme.baseVersion === 1 && pack.theme.pages.every(page => page.capability)
}
