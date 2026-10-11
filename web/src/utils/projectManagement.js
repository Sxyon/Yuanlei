export const projectStatuses = [['planned', '计划中'], ['in_progress', '进行中'], ['paused', '已暂停'], ['completed', '已完成'], ['cancelled', '已取消']].map(([value, label]) => ({ value, label }))
export const projectPriorities = [['urgent', '紧急'], ['high', '高'], ['medium', '中'], ['low', '低'], ['none', '无优先级']].map(([value, label]) => ({ value, label }))
export const defaultProjectWidths = [320, 140, 120, 160, 180]

/** 对当前可见集合搜索管理信息，并按更新时间与UUID稳定排序。 */
export function searchManagedProjects(projects, query) {
  const keyword = query.trim().toLowerCase()
  return projects.filter(p => [p.name, p.slug, p.description, p.category, ...(p.tags || [])].some(v => String(v || '').toLowerCase().includes(keyword)))
    .sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')) || a.id.localeCompare(b.id))
}
